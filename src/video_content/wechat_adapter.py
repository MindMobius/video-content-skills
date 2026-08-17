"""Deterministic helpers for transient WeChat editor handoff mechanics."""

from __future__ import annotations

import ctypes
import hashlib
import html
import mimetypes
import os
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .wechat_renderer import safe_asset_path

WECHAT_BROWSER_ADAPTER_ID = "video-content/wechat-browser-adapter"
WECHAT_BROWSER_ADAPTER_VERSION = "1"
OBSERVATION_VERSION = "video-content/wechat-editor-observation-v1"
VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
PROHIBITED_KEY_RE = re.compile(
    r"(?i)(cookie|password|qr.?login|storage|url_token|access_token|refresh_token|sessdata)"
)
PROHIBITED_VALUE_RE = re.compile(
    r"(?i)(data:image/[^;]+;base64,|(?:^|[?&])token=|SESSDATA=|document\.cookie|localStorage)"
)


class ClipboardHTMLBuilder(HTMLParser):
    """Replace validated local-image marker elements while preserving other HTML."""

    def __init__(self, package_dir: Path) -> None:
        super().__init__(convert_charrefs=False)
        self.package_dir = package_dir
        self.parts: list[str] = []
        self.assets: list[dict[str, Any]] = []
        self._seen: set[str] = set()
        self._suppressed_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._suppressed_depth:
            if tag not in VOID_TAGS:
                self._suppressed_depth += 1
            return
        attributes = dict(attrs)
        raw_path = attributes.get("data-local-image-slot")
        if raw_path is None:
            self.parts.append(self.get_starttag_text())
            return
        if tag in VOID_TAGS:
            raise ValueError("Local-image marker must be a container element")
        asset = self._asset(raw_path)
        self.assets.append(asset)
        path = html.escape(asset["path"], quote=True)
        data_url = f"data:{asset['mime_type']};base64,{asset['base64']}"
        self.parts.append(
            f'<img src="{data_url}" alt="{path}" data-local-image-source="{path}" '
            'style="display:block;width:100%;height:auto;margin:30px auto;">'
        )
        self._suppressed_depth = 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._suppressed_depth:
            return
        if dict(attrs).get("data-local-image-slot") is not None:
            raise ValueError("Local-image marker must not be self-closing")
        self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag: str) -> None:
        if self._suppressed_depth:
            self._suppressed_depth -= 1
            return
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self._suppressed_depth:
            self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        if not self._suppressed_depth:
            self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self._suppressed_depth:
            self.parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        if not self._suppressed_depth:
            self.parts.append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        if not self._suppressed_depth:
            self.parts.append(f"<!{decl}>")

    def close(self) -> None:
        super().close()
        if self._suppressed_depth:
            raise ValueError("Local-image marker HTML is unbalanced")

    def _asset(self, raw_path: str) -> dict[str, Any]:
        relative_path = safe_asset_path(raw_path.strip())
        if relative_path in self._seen:
            raise ValueError(f"Duplicate local-image marker: {relative_path}")
        self._seen.add(relative_path)
        candidate = (self.package_dir / relative_path).resolve()
        if self.package_dir != candidate and self.package_dir not in candidate.parents:
            raise ValueError("Local-image asset escapes the article package")
        if not candidate.is_file():
            raise FileNotFoundError(
                f"Local-image asset does not exist: {relative_path}"
            )
        mime_type = mimetypes.guess_type(candidate.name)[0]
        if not mime_type or not mime_type.startswith("image/"):
            raise ValueError(f"Cannot determine image MIME type: {relative_path}")
        payload = candidate.read_bytes()
        import base64

        return {
            "path": relative_path,
            "mime_type": mime_type,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "base64": base64.b64encode(payload).decode("ascii"),
        }


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if value := data.strip():
            self.parts.append(value)


def build_clipboard_html(package_dir: Path, clean_html: Path) -> dict[str, Any]:
    """Build a transient rich clipboard payload without persisting image bytes."""
    package_dir = package_dir.expanduser().resolve()
    clean_html = clean_html.expanduser().resolve()
    if package_dir != clean_html and package_dir not in clean_html.parents:
        raise ValueError("Clean HTML must stay inside the article package")
    source = clean_html.read_text(encoding="utf-8")
    builder = ClipboardHTMLBuilder(package_dir)
    builder.feed(source)
    builder.close()
    if not builder.assets:
        raise ValueError("Clean HTML has no local-image markers")
    payload = "".join(builder.parts)
    plain = _PlainTextParser()
    plain.feed(payload)
    plain.close()
    assets = [
        {key: value for key, value in item.items() if key != "base64"}
        for item in builder.assets
    ]
    return {
        "html": payload,
        "plain_text": "\n".join(plain.parts),
        "assets": assets,
        "payload_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "payload_chars": len(payload),
    }


def copy_html_to_windows_clipboard(html_payload: str, plain_text: str) -> None:
    """Write CF_HTML and Unicode text without reading the previous clipboard."""
    if os.name != "nt":
        raise OSError(
            "Rich clipboard transport is currently implemented for Windows only"
        )
    html_bytes = _cf_html_bytes(html_payload)
    text_bytes = plain_text.encode("utf-16-le") + b"\x00\x00"
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    html_format = user32.RegisterClipboardFormatW("HTML Format")
    if not html_format:
        raise OSError("Could not register the Windows HTML clipboard format")
    opened = False
    for _ in range(8):
        if user32.OpenClipboard(None):
            opened = True
            break
        time.sleep(0.05)
    if not opened:
        raise OSError("Could not open the Windows clipboard")
    try:
        if not user32.EmptyClipboard():
            raise OSError("Could not clear the Windows clipboard")
        _set_clipboard_bytes(kernel32, user32, html_format, html_bytes)
        _set_clipboard_bytes(kernel32, user32, 13, text_bytes)
    finally:
        user32.CloseClipboard()


def prepare_wechat_clipboard(
    package_dir: Path,
    *,
    clean_html: Path | None = None,
    copy: bool = False,
) -> dict[str, Any]:
    package_dir = package_dir.expanduser().resolve()
    clean_path = (clean_html or package_dir / "article.html").expanduser().resolve()
    transport = build_clipboard_html(package_dir, clean_path)
    if copy:
        copy_html_to_windows_clipboard(transport["html"], transport["plain_text"])
    return {
        "schema_version": "video-content/wechat-clipboard-transport-v1",
        "ok": True,
        "copied": copy,
        "marker_count": len(transport["assets"]),
        "assets": transport["assets"],
        "payload_sha256": transport["payload_sha256"],
        "payload_chars": transport["payload_chars"],
        "payload_persisted": False,
        "previous_clipboard_read": False,
    }


def parse_appmsgid(value: str) -> str | None:
    """Return only a stable numeric article ID, never the surrounding URL token."""
    parsed = urlparse(value)
    query = parse_qs(parsed.query or value.lstrip("?"), keep_blank_values=False)
    candidates = query.get("appmsgid", [])
    if not candidates and re.fullmatch(r"[0-9]+", value.strip()):
        candidates = [value.strip()]
    return (
        candidates[0] if candidates and re.fullmatch(r"[0-9]+", candidates[0]) else None
    )


def _cf_html_bytes(fragment: str) -> bytes:
    prefix = "<html><body><!--StartFragment-->"
    suffix = "<!--EndFragment--></body></html>"
    body = (prefix + fragment + suffix).encode("utf-8")
    header_template = (
        "Version:0.9\r\n"
        "StartHTML:{start_html:010d}\r\n"
        "EndHTML:{end_html:010d}\r\n"
        "StartFragment:{start_fragment:010d}\r\n"
        "EndFragment:{end_fragment:010d}\r\n"
    )
    placeholder = header_template.format(
        start_html=0, end_html=0, start_fragment=0, end_fragment=0
    ).encode("ascii")
    start_html = len(placeholder)
    start_fragment = start_html + len(prefix.encode("utf-8"))
    end_fragment = start_fragment + len(fragment.encode("utf-8"))
    end_html = start_html + len(body)
    header = header_template.format(
        start_html=start_html,
        end_html=end_html,
        start_fragment=start_fragment,
        end_fragment=end_fragment,
    ).encode("ascii")
    return header + body + b"\x00"


def _set_clipboard_bytes(
    kernel32: Any, user32: Any, format_id: int, value: bytes
) -> None:
    handle = kernel32.GlobalAlloc(0x0002, len(value))
    if not handle:
        raise OSError("Could not allocate clipboard memory")
    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        kernel32.GlobalFree(handle)
        raise OSError("Could not lock clipboard memory")
    try:
        ctypes.memmove(pointer, value, len(value))
    finally:
        kernel32.GlobalUnlock(handle)
    if not user32.SetClipboardData(format_id, handle):
        kernel32.GlobalFree(handle)
        raise OSError("Could not set clipboard data")
