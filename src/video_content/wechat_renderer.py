"""Deterministic restrained WeChat article package renderer."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
from pathlib import Path, PurePosixPath
from typing import Any

from . import __version__
from .util import utc_now

MANUSCRIPT_VERSION = "video-content/wechat-manuscript-v1"
RENDER_MANIFEST_VERSION = "video-content/wechat-render-manifest-v1"
RENDERER_ID = "video-content/restrained-editorial"
RENDERER_VERSION = "1"
DEFAULT_DISCLAIMER = (
    "本文由上述视频内容转写、压缩并按图文载体重新组织，可能存在偏差，"
    "请以原视频为准；本文不代表原作者认可这一改编版本。"
)
IMAGE_SUFFIXES = frozenset({".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"})


def render_wechat_package(
    manuscript_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Render one Agent-authored manuscript without changing its semantics."""
    manuscript_path = manuscript_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    manuscript = json.loads(manuscript_path.read_text(encoding="utf-8"))
    _validate_manuscript(manuscript, manuscript_path)
    input_sha256 = _sha256(manuscript_path)

    existing_manifest = output_dir / "render-manifest.json"
    if existing_manifest.is_file():
        existing = json.loads(existing_manifest.read_text(encoding="utf-8"))
        if (
            existing.get("input_sha256") == input_sha256
            and existing.get("renderer", {}).get("version") == RENDERER_VERSION
        ):
            invalid_files = _invalid_render_files(output_dir, existing.get("files"))
            if invalid_files:
                raise ValueError(
                    "Existing render failed its recorded file integrity check: "
                    + ", ".join(invalid_files)
                )
            return {
                "schema_version": "video-content/wechat-render-result-v1",
                "ok": True,
                "reused": True,
                "output_dir": str(output_dir),
                "manifest": str(existing_manifest),
                "files": existing["files"],
            }
        raise ValueError(
            "Output directory contains a render for a different manuscript"
        )
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("Output directory must be absent or empty")

    output_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = output_dir / "assets"
    assets_dir.mkdir()
    rendered_blocks: list[str] = []
    markdown_blocks: list[str] = []
    assets: list[dict[str, Any]] = []
    image_index = 0
    for block in manuscript["blocks"]:
        if block["type"] == "image":
            image_index += 1
            asset = _copy_image_asset(
                block,
                image_index=image_index,
                manuscript_path=manuscript_path,
                assets_dir=assets_dir,
            )
            assets.append(asset)
            rendered_blocks.append(_image_marker(asset))
            markdown_blocks.append(_markdown_image(asset))
        else:
            rendered_blocks.append(_render_block(block))
            markdown_blocks.append(_markdown_block(block))

    body = "\n".join(
        [
            _source_block(manuscript["source"]),
            *rendered_blocks,
        ]
    )
    article_markdown = _article_markdown(manuscript, markdown_blocks)
    checklist = _image_checklist(assets)
    preview = _preview_document(manuscript["title"], body, bool(assets))
    metadata = {
        "schema_version": "video-content/wechat-metadata-v1",
        "title": manuscript["title"],
        "summary": manuscript["summary"],
        "source": manuscript["source"],
        "cover_asset": next(
            (
                asset["path"]
                for asset in assets
                if asset["source_kind"] == "video_cover"
            ),
            None,
        ),
    }

    outputs = {
        "article.md": article_markdown,
        "article.html": body + "\n",
        "article-preview.html": preview,
        "image-import-checklist.md": checklist,
        "metadata.json": json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
    }
    for name, content in outputs.items():
        (output_dir / name).write_text(content, encoding="utf-8")

    file_records = [_file_record(output_dir, output_dir / name) for name in outputs]
    file_records.extend(
        _file_record(output_dir, output_dir / asset["path"]) for asset in assets
    )
    render_manifest = {
        "schema_version": RENDER_MANIFEST_VERSION,
        "created_at": utc_now(),
        "input_sha256": input_sha256,
        "renderer": {
            "id": RENDERER_ID,
            "version": RENDERER_VERSION,
            "package_version": __version__,
            "theme": "restrained-editorial",
        },
        "policy": {
            "underlines": 0,
            "stock_cta": False,
            "stock_signature": False,
            "image_sources": ["video_cover", "video_frame"],
            "image_handoff": "single_relative_path_marker",
        },
        "assets": assets,
        "files": sorted(file_records, key=lambda item: item["path"]),
    }
    _write_json(existing_manifest, render_manifest)
    return {
        "schema_version": "video-content/wechat-render-result-v1",
        "ok": True,
        "reused": False,
        "output_dir": str(output_dir),
        "manifest": str(existing_manifest),
        "files": render_manifest["files"],
    }


def _validate_manuscript(document: Any, manuscript_path: Path) -> None:
    if not isinstance(document, dict):
        raise TypeError("WeChat manuscript must be a JSON object")
    if document.get("schema_version") != MANUSCRIPT_VERSION:
        raise ValueError("Unsupported WeChat manuscript schema")
    for field in ("title", "summary"):
        if not isinstance(document.get(field), str) or not document[field].strip():
            raise ValueError(f"{field} must be non-empty text")
    if len(document["title"]) > 64 or len(document["summary"]) > 240:
        raise ValueError("Title or summary exceeds the WeChat manuscript limit")
    source = document.get("source")
    if not isinstance(source, dict):
        raise TypeError("source must be an object")
    for field in ("title", "creator", "canonical_url"):
        if not isinstance(source.get(field), str) or not source[field].strip():
            raise ValueError(f"source.{field} must be non-empty text")
    if not source["canonical_url"].startswith(("https://", "http://")):
        raise ValueError("source.canonical_url must be an HTTP(S) URL")
    blocks = document.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("blocks must be a non-empty array")
    image_blocks = [block for block in blocks if block.get("type") == "image"]
    if not any(block.get("source_kind") == "video_cover" for block in image_blocks):
        raise ValueError(
            "A video-derived WeChat article requires the original video cover"
        )
    for index, block in enumerate(blocks):
        _validate_block(block, index, manuscript_path)


def _validate_block(block: Any, index: int, manuscript_path: Path) -> None:
    if not isinstance(block, dict):
        raise TypeError(f"blocks[{index}] must be an object")
    block_type = block.get("type")
    allowed = {
        "heading",
        "paragraph",
        "lead",
        "key_point",
        "quote",
        "list",
        "image",
        "separator",
    }
    if block_type not in allowed:
        raise ValueError(f"blocks[{index}].type is unsupported")
    if block_type in {"heading", "paragraph", "lead", "key_point", "quote"}:
        if not isinstance(block.get("text"), str) or not block["text"].strip():
            raise ValueError(f"blocks[{index}].text must be non-empty")
    elif block_type == "list":
        items = block.get("items")
        if (
            not isinstance(items, list)
            or not items
            or not all(isinstance(item, str) and item.strip() for item in items)
        ):
            raise ValueError(f"blocks[{index}].items must contain non-empty text")
    elif block_type == "image":
        if block.get("source_kind") not in {"video_cover", "video_frame"}:
            raise ValueError(f"blocks[{index}].source_kind is unsupported")
        source_path = _source_image_path(block, manuscript_path)
        if not source_path.is_file():
            raise FileNotFoundError(f"Image asset does not exist: {source_path}")
        if source_path.suffix.lower() not in IMAGE_SUFFIXES:
            raise ValueError(f"Unsupported image extension: {source_path.suffix}")
        if block["source_kind"] == "video_frame" and not isinstance(
            block.get("timestamp_ms"), int
        ):
            raise ValueError(
                f"blocks[{index}].timestamp_ms is required for a video frame"
            )


def _copy_image_asset(
    block: dict[str, Any],
    *,
    image_index: int,
    manuscript_path: Path,
    assets_dir: Path,
) -> dict[str, Any]:
    source = _source_image_path(block, manuscript_path)
    safe_stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", source.stem).strip("-") or "image"
    name = f"{image_index:02d}-{safe_stem[:48]}{source.suffix.lower()}"
    destination = assets_dir / name
    shutil.copyfile(source, destination)
    return {
        "path": f"assets/{name}",
        "source_kind": block["source_kind"],
        "timestamp_ms": block.get("timestamp_ms"),
        "caption": str(block.get("caption") or "").strip(),
        "bytes": destination.stat().st_size,
        "sha256": _sha256(destination),
        "source_name": source.name,
    }


def _source_image_path(block: dict[str, Any], manuscript_path: Path) -> Path:
    value = Path(str(block.get("path") or "")).expanduser()
    if not value.is_absolute():
        value = manuscript_path.parent / value
    return value.resolve()


def _source_block(source: dict[str, Any]) -> str:
    title = html.escape(source["title"])
    creator = html.escape(source["creator"])
    url = html.escape(source["canonical_url"], quote=True)
    disclaimer = html.escape(source.get("disclaimer") or DEFAULT_DISCLAIMER)
    return (
        '<section data-source-disclosure="true" style="margin:0 0 30px;padding:0 0 0 14px;'
        'border-left:3px solid #2f6f5e;color:#60666d;font-size:13px;line-height:1.75;">'
        '<p style="margin:0 0 5px;color:#2f6f5e;font-weight:700;">原始内容</p>'
        f'<p style="margin:0 0 4px;color:#24282d;font-weight:700;">{title}</p>'
        f'<p style="margin:0 0 4px;">创作者：{creator}</p>'
        f'<p style="margin:0 0 8px;"><a href="{url}" style="color:#2f6f5e;">{url}</a></p>'
        f'<p style="margin:0;">{disclaimer}</p></section>'
    )


def _render_block(block: dict[str, Any]) -> str:
    block_type = block["type"]
    if block_type == "separator":
        return '<p style="margin:34px 0;text-align:center;color:#a7adb2;">· · ·</p>'
    if block_type == "list":
        tag = "ol" if block.get("ordered") else "ul"
        items = "".join(
            f'<li style="margin:0 0 8px;">{_text(item)}</li>' for item in block["items"]
        )
        return (
            f'<{tag} style="margin:16px 0 22px;padding-left:1.4em;color:#30353a;'
            f'font-size:16px;line-height:1.85;">{items}</{tag}>'
        )
    text = _text(block["text"])
    if block_type == "heading":
        return (
            '<h2 style="margin:38px 0 16px;color:#202428;font-size:20px;line-height:1.45;'
            f'font-weight:750;letter-spacing:0;">{text}</h2>'
        )
    if block_type == "lead":
        return (
            '<p style="margin:0 0 24px;color:#30353a;font-size:18px;line-height:1.85;'
            f'font-weight:500;">{text}</p>'
        )
    if block_type == "key_point":
        return (
            '<p style="margin:28px 0;color:#1f4f43;font-size:19px;line-height:1.7;'
            f'font-weight:750;">{text}</p>'
        )
    if block_type == "quote":
        attribution = html.escape(str(block.get("attribution") or "").strip())
        suffix = (
            f'<p style="margin:10px 0 0;color:#747a80;font-size:13px;">{attribution}</p>'
            if attribution
            else ""
        )
        return (
            '<blockquote style="margin:26px 0;padding:2px 0 2px 16px;border-left:2px solid '
            '#9aa5a1;color:#50565c;font-size:16px;line-height:1.85;">'
            f'<p style="margin:0;">{text}</p>{suffix}</blockquote>'
        )
    return (
        '<p style="margin:0 0 20px;color:#30353a;font-size:16px;line-height:1.9;'
        f'text-align:justify;">{text}</p>'
    )


def _image_marker(asset: dict[str, Any]) -> str:
    path = html.escape(asset["path"])
    caption = html.escape(asset["caption"])
    caption_html = (
        f'<p style="margin:-20px 0 28px;color:#8a9095;font-size:12px;text-align:center;">{caption}</p>'
        if caption
        else ""
    )
    return (
        f'<p data-local-image-slot="{path}" style="margin:30px 0;color:#9a9fa4;'
        f'font-size:12px;line-height:1.6;text-align:center;">{path}</p>{caption_html}'
    )


def _markdown_block(block: dict[str, Any]) -> str:
    block_type = block["type"]
    if block_type == "heading":
        return f"## {block['text'].strip()}"
    if block_type in {"paragraph", "lead", "key_point"}:
        return block["text"].strip()
    if block_type == "quote":
        value = f"> {block['text'].strip()}"
        if block.get("attribution"):
            value += f"\n>\n> {block['attribution'].strip()}"
        return value
    if block_type == "list":
        return "\n".join(
            f"{index}. {item.strip()}" if block.get("ordered") else f"- {item.strip()}"
            for index, item in enumerate(block["items"], start=1)
        )
    if block_type == "separator":
        return "* * *"
    raise ValueError(f"Unsupported markdown block: {block_type}")


def _markdown_image(asset: dict[str, Any]) -> str:
    result = asset["path"]
    if asset["caption"]:
        result += f"\n\n{asset['caption']}"
    return result


def _article_markdown(manuscript: dict[str, Any], blocks: list[str]) -> str:
    source = manuscript["source"]
    disclaimer = source.get("disclaimer") or DEFAULT_DISCLAIMER
    return (
        "\n\n".join(
            [
                f"# {manuscript['title'].strip()}",
                (
                    f"原始内容：{source['title'].strip()}\n\n"
                    f"创作者：{source['creator'].strip()}\n\n"
                    f"原视频：{source['canonical_url'].strip()}\n\n"
                    f"{disclaimer.strip()}"
                ),
                *blocks,
            ]
        )
        + "\n"
    )


def _image_checklist(assets: list[dict[str, Any]]) -> str:
    lines = ["# 图片导入清单", ""]
    for index, asset in enumerate(assets, start=1):
        provenance = (
            "原视频封面"
            if asset["source_kind"] == "video_cover"
            else (f"原视频截帧，{asset['timestamp_ms']} ms")
        )
        lines.append(f"{index}. `{asset['path']}` - {provenance}")
    return "\n".join(lines) + "\n"


def _preview_document(title: str, body: str, has_assets: bool) -> str:
    warning = (
        "本地图片仍需按正文中的路径手动插入。" if has_assets else "正文没有本地图片。"
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} - 预览</title>
<style>
body {{ margin: 0; background: #eef0ef; color: #24282d; font-family: system-ui, sans-serif; letter-spacing: 0; }}
.toolbar {{ position: sticky; top: 0; padding: 12px 16px; background: #202428; color: #fff; z-index: 2; }}
.toolbar button {{ border: 0; border-radius: 4px; padding: 8px 14px; background: #f4f5f4; color: #202428; cursor: pointer; }}
.toolbar span {{ margin-left: 12px; color: #c9cdca; font-size: 13px; }}
.paper {{ box-sizing: border-box; max-width: 677px; min-height: 100vh; margin: 20px auto; padding: 42px 34px; background: #fff; }}
@media (max-width: 720px) {{ .paper {{ margin: 0; padding: 32px 22px; }} .toolbar span {{ display: block; margin: 8px 0 0; }} }}
</style>
</head>
<body>
<div class="toolbar"><button id="copy-body" type="button">复制排版正文</button><span>{warning}</span></div>
<main id="article-body" class="paper">{body}</main>
<script>
document.getElementById('copy-body').addEventListener('click', async () => {{
  const body = document.getElementById('article-body').innerHTML;
  await navigator.clipboard.write([new ClipboardItem({{'text/html': new Blob([body], {{type: 'text/html'}})}})]);
}});
</script>
</body>
</html>
"""


def _text(value: str) -> str:
    return html.escape(value.strip()).replace("\n", "<br>")


def _file_record(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _invalid_render_files(root: Path, records: Any) -> list[str]:
    if not isinstance(records, list) or not records:
        return ["render-manifest.json:files"]
    invalid: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            invalid.append("invalid-record")
            continue
        raw_path = record.get("path")
        if not isinstance(raw_path, str):
            invalid.append("missing-path")
            continue
        path = PurePosixPath(raw_path)
        if (
            "\\" in raw_path
            or raw_path.startswith("/")
            or ":" in raw_path
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            invalid.append(raw_path)
            continue
        candidate = (root / Path(*path.parts)).resolve()
        if root != candidate and root not in candidate.parents:
            invalid.append(raw_path)
            continue
        expected_bytes = record.get("bytes")
        expected_sha256 = record.get("sha256")
        if (
            not candidate.is_file()
            or not isinstance(expected_bytes, int)
            or isinstance(expected_bytes, bool)
            or candidate.stat().st_size != expected_bytes
            or not isinstance(expected_sha256, str)
            or _sha256(candidate) != expected_sha256
        ):
            invalid.append(raw_path)
    return invalid


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def safe_asset_path(value: str) -> str:
    """Validate a portable image path used by clipboard and package adapters."""
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or value.startswith("/")
        or ":" in value
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.suffix.lower() not in IMAGE_SUFFIXES
    ):
        raise ValueError(f"Unsafe or unsupported asset path: {value!r}")
    return path.as_posix()
