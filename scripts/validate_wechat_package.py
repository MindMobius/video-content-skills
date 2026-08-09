"""Validate a portable WeChat article package without platform access."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any

IMAGE_SUFFIXES = frozenset({".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"})
CHECKLIST_PATH_RE = re.compile(r"`([^`\r\n]+)`")
WINDOWS_ABSOLUTE_RE = re.compile(r"(?i)(?<![a-z0-9])(?:[a-z]:[\\/]|\\\\)")
POSIX_ABSOLUTE_RE = re.compile(
    r"(?i)(?<![a-z0-9:])/(?:home|mnt|opt|private|root|tmp|users|var)/"
)
UNDERLINE_STYLE_RE = re.compile(
    r"(?i)(?:text-decoration(?:-line)?\s*:[^;]*\bunderline\b)"
)
MANUAL_IMAGE_WARNING_RE = re.compile(
    r"本地图片.{0,80}(?:仍需|需要|需).{0,40}(?:手动)?(?:插入|导入)",
    re.DOTALL,
)
STOCK_SHELL_PATTERNS = (
    re.compile(r"点赞\s*(?:[/|｜·、]\s*)?在看(?:\s*[/|｜·、]\s*转发)?"),
    re.compile(r"长按.{0,12}(?:识别|二维码)", re.DOTALL),
    re.compile(r"扫码.{0,12}(?:关注|二维码)", re.DOTALL),
    re.compile(r"(?:欢迎|记得|点击).{0,8}关注(?:我们|本公众号|公众号)", re.DOTALL),
)
STOCK_IDENTIFIER_TOKENS = (
    "author-card",
    "engagement-cta",
    "follow-card",
    "qr-code",
    "qrcode",
    "signature",
    "stock-cta",
)


@dataclass(frozen=True)
class Marker:
    path: str
    visible_text: str
    tag: str


@dataclass
class _OpenMarker:
    path: str
    tag: str
    same_tag_depth: int
    text_parts: list[str]


class ArticleHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.markers: list[Marker] = []
        self.images: list[dict[str, str]] = []
        self.tags: set[str] = set()
        self.styles: list[str] = []
        self.identifiers: list[str] = []
        self.visible_text_parts: list[str] = []
        self.has_doctype = False
        self._open_markers: list[_OpenMarker] = []
        self._suppressed_depth = 0

    @property
    def unclosed_marker_count(self) -> int:
        return len(self._open_markers)

    @property
    def visible_text(self) -> str:
        return _collapse_whitespace(" ".join(self.visible_text_parts))

    def handle_decl(self, decl: str) -> None:
        if decl.lower().startswith("doctype"):
            self.has_doctype = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr_map = {name.lower(): value or "" for name, value in attrs}

        for marker in self._open_markers:
            if marker.tag == tag:
                marker.same_tag_depth += 1

        self._record_element(tag, attr_map)
        marker_path = attr_map.get("data-local-image-slot")
        if marker_path is not None:
            self._open_markers.append(
                _OpenMarker(
                    path=marker_path.strip(),
                    tag=tag,
                    same_tag_depth=1,
                    text_parts=[],
                )
            )

        if tag in {"script", "style"}:
            self._suppressed_depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr_map = {name.lower(): value or "" for name, value in attrs}
        self._record_element(tag, attr_map)
        marker_path = attr_map.get("data-local-image-slot")
        if marker_path is not None:
            self.markers.append(Marker(marker_path.strip(), "", tag))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style"} and self._suppressed_depth:
            self._suppressed_depth -= 1

        for index in range(len(self._open_markers) - 1, -1, -1):
            marker = self._open_markers[index]
            if marker.tag != tag:
                continue
            marker.same_tag_depth -= 1
            if marker.same_tag_depth == 0:
                self.markers.append(
                    Marker(
                        path=marker.path,
                        visible_text=_collapse_whitespace(" ".join(marker.text_parts)),
                        tag=marker.tag,
                    )
                )
                self._open_markers.pop(index)

    def handle_data(self, data: str) -> None:
        if not self._suppressed_depth:
            self.visible_text_parts.append(data)
        for marker in self._open_markers:
            marker.text_parts.append(data)

    def _record_element(self, tag: str, attrs: dict[str, str]) -> None:
        self.tags.add(tag)
        if tag == "img":
            self.images.append(
                {
                    "src": attrs.get("src", ""),
                    "srcset": attrs.get("srcset", ""),
                }
            )
        if style := attrs.get("style"):
            self.styles.append(style)
        for attribute in ("class", "id"):
            if value := attrs.get(attribute):
                self.identifiers.append(value.lower())


def _collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


def _finding(code: str, message: str, path: str | None = None) -> dict[str, str]:
    finding = {"code": code, "message": message}
    if path is not None:
        finding["path"] = path
    return finding


def _is_image_path(value: str) -> bool:
    return PurePosixPath(value).suffix.lower() in IMAGE_SUFFIXES


def _path_problem(value: str) -> str | None:
    if not value:
        return "path is empty"
    if "\\" in value:
        return "path must use forward slashes"
    if value.startswith("/") or re.match(r"(?i)^[a-z]:[\\/]", value):
        return "path must be relative"
    if value.startswith(("file:", "data:", "blob:")) or "://" in value:
        return "path must not use a URI scheme"
    path = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in path.parts):
        return "path must not contain empty, dot, or parent segments"
    if not _is_image_path(value):
        return "path must use a supported image extension"
    return None


def _inspect_html(text: str) -> ArticleHTMLParser:
    parser = ArticleHTMLParser()
    parser.feed(text)
    parser.close()
    return parser


def _read_utf8(path: Path, errors: list[dict[str, str]], code: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        errors.append(_finding(code, str(error), path.name))
        return ""


def _resolve_member(
    root: Path,
    value: str | Path,
    errors: list[dict[str, str]],
    code: str,
) -> Path | None:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve()
    except OSError as error:
        errors.append(_finding(code, str(error), str(value)))
        return None
    if resolved != root and root not in resolved.parents:
        errors.append(_finding(code, "file must stay inside the package", str(value)))
        return None
    if not resolved.is_file():
        errors.append(_finding(code, "file does not exist", str(value)))
        return None
    return resolved


def _looks_like_preview(path: Path, text: str) -> bool:
    lowered_name = path.name.lower()
    return (
        "preview" in lowered_name
        or "预览" in path.name
        or ("复制排版正文" in text and "<html" in text.lower())
    )


def _discover_html_files(
    root: Path,
    clean_html: str | Path | None,
    preview_html: str | Path | None,
    errors: list[dict[str, str]],
) -> tuple[Path | None, Path | None]:
    if clean_html is not None:
        clean_path = _resolve_member(root, clean_html, errors, "clean_html_missing")
    else:
        clean_path = None
    if preview_html is not None:
        preview_path = _resolve_member(
            root, preview_html, errors, "preview_html_missing"
        )
    else:
        preview_path = None

    if clean_path is not None and preview_path is not None:
        return clean_path, preview_path

    candidates: list[tuple[Path, str]] = []
    for candidate in sorted(root.glob("*.html")):
        candidates.append(
            (candidate, _read_utf8(candidate, errors, "html_read_failed"))
        )
    previews = [item for item in candidates if _looks_like_preview(*item)]
    cleans = [item for item in candidates if item not in previews]

    if clean_path is None:
        if len(cleans) == 1:
            clean_path = cleans[0][0]
        else:
            errors.append(
                _finding(
                    "clean_html_ambiguous",
                    f"expected one clean HTML fragment, found {len(cleans)}",
                )
            )
    if preview_path is None:
        if len(previews) == 1:
            preview_path = previews[0][0]
        else:
            errors.append(
                _finding(
                    "preview_html_ambiguous",
                    f"expected one preview HTML file, found {len(previews)}",
                )
            )
    return clean_path, preview_path


def _relative_name(root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    return path.relative_to(root).as_posix()


def _check_persisted_sources(
    name: str,
    text: str,
    inspection: ArticleHTMLParser,
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> None:
    lowered = text.lower()
    if "data:image" in lowered:
        errors.append(
            _finding(
                "persisted_base64_image", "Base64 image data must stay transient", name
            )
        )
    for scheme in ("file:", "blob:"):
        if scheme in lowered:
            errors.append(
                _finding(
                    "persisted_local_scheme",
                    f"persisted HTML contains {scheme}",
                    name,
                )
            )
    if WINDOWS_ABSOLUTE_RE.search(text) or POSIX_ABSOLUTE_RE.search(text):
        errors.append(
            _finding(
                "absolute_local_path",
                "persisted HTML contains an absolute local path",
                name,
            )
        )

    for image_index, image in enumerate(inspection.images, start=1):
        sources = [image["src"]]
        if image["srcset"]:
            for part in image["srcset"].split(","):
                if tokens := part.strip().split():
                    sources.append(tokens[0])
        for source in sources:
            source = source.strip()
            if not source:
                errors.append(
                    _finding(
                        "empty_image_source",
                        f"image {image_index} has an empty source",
                        name,
                    )
                )
                continue
            lowered_source = source.lower()
            if lowered_source.startswith(("data:", "file:", "blob:")):
                errors.append(
                    _finding(
                        "nonportable_image_source",
                        f"image {image_index} uses {source[:32]}",
                        name,
                    )
                )
            elif source.startswith("/") or re.match(r"(?i)^[a-z]:[\\/]", source):
                errors.append(
                    _finding(
                        "absolute_image_source",
                        f"image {image_index} uses an absolute local path",
                        name,
                    )
                )
            elif "://" not in source:
                errors.append(
                    _finding(
                        "relative_image_source",
                        f"image {image_index} uses non-transferable relative source {source}",
                        name,
                    )
                )
            elif not lowered_source.startswith(("https://", "http://")):
                warnings.append(
                    _finding(
                        "unusual_remote_image_source",
                        f"image {image_index} uses an unusual remote source",
                        name,
                    )
                )


def _check_marker_contract(
    root: Path,
    clean_name: str,
    inspection: ArticleHTMLParser,
    checklist_entries: list[str],
    errors: list[dict[str, str]],
) -> list[str]:
    marker_paths = [marker.path for marker in inspection.markers]
    for marker in inspection.markers:
        if problem := _path_problem(marker.path):
            errors.append(_finding("invalid_marker_path", problem, marker.path))
        if marker.visible_text != marker.path:
            errors.append(
                _finding(
                    "marker_text_mismatch",
                    "visible marker text must contain only its relative path",
                    marker.path or clean_name,
                )
            )

    duplicates = sorted(
        path for path, count in Counter(marker_paths).items() if count > 1
    )
    for duplicate in duplicates:
        errors.append(
            _finding("duplicate_marker_path", "marker path must be unique", duplicate)
        )

    if inspection.unclosed_marker_count:
        errors.append(
            _finding(
                "unclosed_marker",
                f"{inspection.unclosed_marker_count} image marker elements were not closed",
                clean_name,
            )
        )

    if marker_paths != checklist_entries:
        errors.append(
            _finding(
                "checklist_order_mismatch",
                "marker paths and checklist image paths must match one-to-one in order",
                clean_name,
            )
        )

    for marker_path in marker_paths:
        if _path_problem(marker_path):
            continue
        candidate = (root / PurePosixPath(marker_path)).resolve()
        if candidate != root and root not in candidate.parents:
            errors.append(
                _finding(
                    "asset_outside_package",
                    "image asset resolves outside the package",
                    marker_path,
                )
            )
        elif not candidate.is_file():
            errors.append(
                _finding(
                    "missing_image_asset", "image asset does not exist", marker_path
                )
            )
    return marker_paths


def _check_clean_policy(
    name: str,
    inspection: ArticleHTMLParser,
    errors: list[dict[str, str]],
    allow_stock_shell: bool,
) -> None:
    if inspection.has_doctype or inspection.tags.intersection({"html", "head", "body"}):
        errors.append(
            _finding(
                "clean_html_has_preview_shell",
                "clean HTML must be a body fragment, not a document wrapper",
                name,
            )
        )
    if "u" in inspection.tags or any(
        UNDERLINE_STYLE_RE.search(style) for style in inspection.styles
    ):
        errors.append(
            _finding(
                "underline_emphasis",
                "clean HTML contains underline emphasis",
                name,
            )
        )

    if allow_stock_shell:
        return
    for pattern in STOCK_SHELL_PATTERNS:
        if pattern.search(inspection.visible_text):
            errors.append(
                _finding(
                    "stock_engagement_shell",
                    "clean HTML contains a stock engagement or QR-code prompt",
                    name,
                )
            )
            break
    for identifier in inspection.identifiers:
        if any(token in identifier for token in STOCK_IDENTIFIER_TOKENS):
            errors.append(
                _finding(
                    "stock_signature_component",
                    "clean HTML contains a stock signature or CTA component",
                    name,
                )
            )
            break


def _extract_checklist_entries(text: str) -> list[str]:
    return [
        value.strip()
        for value in CHECKLIST_PATH_RE.findall(text)
        if _is_image_path(value.strip())
    ]


def validate_package(
    package_dir: str | Path,
    *,
    clean_html: str | Path | None = None,
    preview_html: str | Path | None = None,
    checklist: str | Path = "image-import-checklist.md",
    allow_stock_shell: bool = False,
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    root = Path(package_dir).expanduser().resolve()

    if not root.is_dir():
        errors.append(
            _finding(
                "package_missing",
                "package directory does not exist",
                str(package_dir),
            )
        )
        return _report(root, None, None, None, [], [], errors, warnings)

    article_path = root / "article.md"
    if not article_path.is_file():
        errors.append(
            _finding("article_markdown_missing", "article.md is required", "article.md")
        )

    checklist_path = _resolve_member(
        root,
        checklist,
        errors,
        "checklist_missing",
    )
    clean_path, preview_path = _discover_html_files(
        root,
        clean_html,
        preview_html,
        errors,
    )

    checklist_entries: list[str] = []
    if checklist_path is not None:
        checklist_text = _read_utf8(
            checklist_path,
            errors,
            "checklist_read_failed",
        )
        checklist_entries = _extract_checklist_entries(checklist_text)
        for entry in checklist_entries:
            if problem := _path_problem(entry):
                errors.append(_finding("invalid_checklist_path", problem, entry))
        for duplicate in sorted(
            path for path, count in Counter(checklist_entries).items() if count > 1
        ):
            errors.append(
                _finding(
                    "duplicate_checklist_path",
                    "checklist image path must be unique",
                    duplicate,
                )
            )

    marker_paths: list[str] = []
    clean_inspection: ArticleHTMLParser | None = None
    if clean_path is not None:
        clean_name = _relative_name(root, clean_path) or clean_path.name
        clean_text = _read_utf8(clean_path, errors, "clean_html_read_failed")
        clean_inspection = _inspect_html(clean_text)
        marker_paths = _check_marker_contract(
            root,
            clean_name,
            clean_inspection,
            checklist_entries,
            errors,
        )
        _check_persisted_sources(
            clean_name,
            clean_text,
            clean_inspection,
            errors,
            warnings,
        )
        _check_clean_policy(
            clean_name,
            clean_inspection,
            errors,
            allow_stock_shell,
        )

    if preview_path is not None:
        preview_name = _relative_name(root, preview_path) or preview_path.name
        preview_text = _read_utf8(preview_path, errors, "preview_html_read_failed")
        preview_inspection = _inspect_html(preview_text)
        preview_paths = [marker.path for marker in preview_inspection.markers]
        if preview_paths != marker_paths:
            errors.append(
                _finding(
                    "preview_marker_mismatch",
                    "preview image markers must match the clean HTML in order",
                    preview_name,
                )
            )
        _check_persisted_sources(
            preview_name,
            preview_text,
            preview_inspection,
            errors,
            warnings,
        )
        if "复制排版正文" not in preview_text:
            errors.append(
                _finding(
                    "preview_copy_label",
                    "preview must use the qualified label 复制排版正文",
                    preview_name,
                )
            )
        if marker_paths and not MANUAL_IMAGE_WARNING_RE.search(preview_text):
            errors.append(
                _finding(
                    "preview_image_warning",
                    "preview must state that local images still require insertion",
                    preview_name,
                )
            )
        for misleading_phrase in ("复制到公众号", "可直接粘贴", "直接粘贴到公众号"):
            if misleading_phrase in preview_text:
                errors.append(
                    _finding(
                        "misleading_preview_copy",
                        f"preview contains misleading wording: {misleading_phrase}",
                        preview_name,
                    )
                )

    return _report(
        root,
        clean_path,
        preview_path,
        checklist_path,
        marker_paths,
        checklist_entries,
        errors,
        warnings,
        clean_image_count=len(clean_inspection.images) if clean_inspection else 0,
    )


def _report(
    root: Path,
    clean_path: Path | None,
    preview_path: Path | None,
    checklist_path: Path | None,
    marker_paths: list[str],
    checklist_entries: list[str],
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
    *,
    clean_image_count: int = 0,
) -> dict[str, Any]:
    return {
        "schema_version": "video-content/wechat-package-validation-v1",
        "valid": not errors,
        "package": root.name,
        "files": {
            "clean_html": _relative_name(root, clean_path),
            "preview_html": _relative_name(root, preview_path),
            "checklist": _relative_name(root, checklist_path),
        },
        "counts": {
            "markers": len(marker_paths),
            "checklist_entries": len(checklist_entries),
            "clean_img_elements": clean_image_count,
        },
        "errors": errors,
        "warnings": warnings,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_dir", help="WeChat article package directory")
    parser.add_argument("--html", dest="clean_html", help="Clean HTML path in package")
    parser.add_argument(
        "--preview", dest="preview_html", help="Preview HTML path in package"
    )
    parser.add_argument(
        "--checklist",
        default="image-import-checklist.md",
        help="Image checklist path in package",
    )
    parser.add_argument(
        "--allow-stock-shell",
        action="store_true",
        help="Allow an explicitly authorized signature or engagement shell",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = validate_package(
        args.package_dir,
        clean_html=args.clean_html,
        preview_html=args.preview_html,
        checklist=args.checklist,
        allow_stock_shell=args.allow_stock_shell,
    )
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
