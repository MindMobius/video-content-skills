from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from video_content import wechat_adapter


def _write_package(root: Path) -> None:
    assets = root / "assets"
    assets.mkdir(parents=True)
    (assets / "01-cover.jpg").write_bytes(b"cover bytes")
    body = (
        '<section><p data-local-image-slot="assets/01-cover.jpg">'
        "<span>assets/01-cover.jpg</span></p><p>正文 &amp; 结尾</p></section>"
    )
    (root / "article.html").write_text(body, encoding="utf-8")


def test_clipboard_builder_replaces_markers_only_in_memory(tmp_path: Path) -> None:
    _write_package(tmp_path)
    source_before = (tmp_path / "article.html").read_bytes()
    transport = wechat_adapter.build_clipboard_html(tmp_path, tmp_path / "article.html")
    report = wechat_adapter.prepare_wechat_clipboard(tmp_path, copy=False)
    assert 'src="data:image/jpeg;base64,' in transport["html"]
    assert "data-local-image-slot" not in transport["html"]
    assert "base64" not in transport["assets"][0]
    assert "html" not in report
    assert report["payload_persisted"] is False
    assert report["previous_clipboard_read"] is False
    assert (tmp_path / "article.html").read_bytes() == source_before


def test_cf_html_offsets_address_utf8_fragment() -> None:
    fragment = "<p>中文</p>"
    payload = wechat_adapter._cf_html_bytes(fragment)
    header = payload.split(b"<html>", 1)[0].decode("ascii")
    offsets = {
        key: int(value)
        for key, value in (
            line.split(":", 1) for line in header.splitlines() if ":" in line
        )
        if key != "Version"
    }
    assert payload[offsets["StartHTML"] :].startswith(b"<html>")
    assert (
        payload[offsets["StartFragment"] : offsets["EndFragment"]].decode("utf-8")
        == fragment
    )


def test_appmsgid_parser_never_returns_url_tokens() -> None:
    value = "https://mp.weixin.qq.com/cgi-bin/appmsg?action=edit&appmsgid=100000721&token=secret"
    assert wechat_adapter.parse_appmsgid(value) == "100000721"
    assert wechat_adapter.parse_appmsgid("not-an-id") is None


def test_browser_snapshot_contract_records_visible_ai_creation_source() -> None:
    schema = json.loads(
        Path("schemas/wechat-browser-snapshot.schema.json").read_text(encoding="utf-8")
    )
    snapshot = {
        "schema_version": "video-content/wechat-browser-snapshot-v1",
        "adapter": {
            "id": "video-content/wechat-browser-adapter",
            "version": wechat_adapter.WECHAT_BROWSER_ADAPTER_VERSION,
        },
        "ready": True,
        "appmsgid": "100000721",
        "body_images": {
            "intended": 0,
            "items": [],
            "local_path_markers_remaining": 0,
        },
        "fields": {
            "title": {"value": "测试标题", "visible_candidates": 1},
            "summary": {"value": "测试摘要", "visible_candidates": 1},
            "author": {"value": "", "visible_candidates": 1},
        },
        "creation_source": {
            "type": "ai_generated",
            "declared": True,
            "visible_candidates": 1,
            "selected_candidates": 1,
        },
    }

    assert wechat_adapter.WECHAT_BROWSER_ADAPTER_VERSION == "3"
    assert (
        wechat_adapter.OBSERVATION_VERSION
        == "video-content/wechat-editor-observation-v3"
    )
    jsonschema.validate(snapshot, schema)
