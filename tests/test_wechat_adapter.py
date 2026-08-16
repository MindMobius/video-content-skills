from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import jsonschema

from video_subtitle import wechat_adapter

ROOT = Path(__file__).resolve().parents[1]


def _write_package(root: Path) -> None:
    assets = root / "assets"
    assets.mkdir(parents=True)
    (assets / "01-cover.jpg").write_bytes(b"cover bytes")
    (root / "article.md").write_text("# Article\n", encoding="utf-8")
    (root / "image-import-checklist.md").write_text(
        "# Images\n\n1. `assets/01-cover.jpg`\n", encoding="utf-8"
    )
    body = (
        '<section><p data-local-image-slot="assets/01-cover.jpg">'
        "<span>assets/01-cover.jpg</span></p><p>正文 &amp; 结尾</p></section>"
    )
    (root / "article.html").write_text(body, encoding="utf-8")
    (root / "article-preview.html").write_text(
        "<!doctype html><html><body><p>复制排版正文；本地图片仍需手动插入</p>"
        + body
        + "</body></html>",
        encoding="utf-8",
    )


def _observation() -> dict:
    return {
        "schema_version": "video-content/wechat-editor-observation-v1",
        "started_at": "2026-08-16T08:00:00Z",
        "saved_at": "2026-08-16T08:02:00Z",
        "title": "测试文章",
        "appmsgid": "100000721",
        "body_images": {
            "intended": 1,
            "items": [
                {
                    "visible": True,
                    "complete": True,
                    "natural_width": 1280,
                    "width": 640,
                    "height": 360,
                    "host_class": "wechat",
                },
                {
                    "visible": False,
                    "complete": True,
                    "natural_width": 200,
                    "width": 0,
                    "height": 0,
                    "host_class": "other",
                },
            ],
            "local_path_markers_remaining": 0,
        },
        "cover": {
            "source": "body_image_1",
            "asset": "assets/01-cover.jpg",
            "selected": True,
            "crop_confirmed": True,
            "wechat_hosted_preview": True,
        },
        "summary": {"filled": True, "text": "测试摘要"},
        "author": {"value": "", "left_blank": True},
        "originality": {"declared": False, "visible_state": "未声明"},
        "content_checks": {
            "source_disclosure_present": True,
            "ending_present": True,
            "underline_count": 0,
            "stock_cta_present": False,
            "speaker_identity_preserved": True,
        },
        "save": {
            "saved": True,
            "channel": "manual_save",
            "mode": "draft",
            "history_record": "08:02 手动保存",
            "history_record_persisted": True,
            "saved_page_read_back": True,
        },
    }


def test_clipboard_builder_replaces_markers_only_in_memory(tmp_path: Path) -> None:
    _write_package(tmp_path)
    source_before = (tmp_path / "article.html").read_bytes()

    transport = wechat_adapter.build_clipboard_html(tmp_path, tmp_path / "article.html")
    report = wechat_adapter.prepare_wechat_clipboard(tmp_path, copy=False)

    assert 'src="data:image/jpeg;base64,' in transport["html"]
    assert "data-local-image-slot" not in transport["html"]
    assert transport["assets"][0]["path"] == "assets/01-cover.jpg"
    assert "base64" not in transport["assets"][0]
    assert "html" not in report
    assert report["payload_persisted"] is False
    assert report["previous_clipboard_read"] is False
    assert (tmp_path / "article.html").read_bytes() == source_before
    assert not list(tmp_path.rglob("*.base64"))


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


def test_appmsgid_parser_never_returns_the_url_token() -> None:
    value = (
        "https://mp.weixin.qq.com/cgi-bin/appmsg?action=edit&"
        "appmsgid=100000721&token=secret-value&lang=zh_CN"
    )

    assert wechat_adapter.parse_appmsgid(value) == "100000721"
    assert wechat_adapter.parse_appmsgid("not-an-id") is None


def test_receipt_builder_counts_only_visible_loaded_wechat_images(monkeypatch) -> None:
    monkeypatch.setattr(
        wechat_adapter,
        "get_content_project",
        lambda _path: {
            "project_id": "content_0123456789abcdef",
            "current": {
                "deliverable_id": "dlv-001",
                "fidelity_audit_id": "audit-001",
            },
        },
    )
    observation = _observation()

    receipt = wechat_adapter.build_wechat_draft_receipt(
        Path("project.json"), observation
    )

    assert receipt["body_images"] == {
        "intended": 1,
        "visible_loaded": 1,
        "wechat_hosted": 1,
        "non_wechat_hosted": 0,
        "local_path_markers_remaining": 0,
    }
    assert receipt["adapter"]["version"] == "1"
    assert receipt["published"] is False
    assert receipt["publish_actions_performed"] == []
    schema = json.loads(
        (ROOT / "schemas" / "wechat-draft-receipt.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(receipt, schema)


def test_observation_schema_and_secret_guard() -> None:
    observation = _observation()
    schema = json.loads(
        (ROOT / "schemas" / "wechat-editor-observation.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(observation, schema)

    observation["url_token"] = "forbidden"
    try:
        wechat_adapter._validate_observation(observation)
    except ValueError as error:
        assert "Secret-bearing field" in str(error)
    else:  # pragma: no cover
        raise AssertionError("browser tokens must be rejected")


def test_browser_snapshot_schema_excludes_raw_image_sources() -> None:
    snapshot = {
        "schema_version": "video-content/wechat-browser-snapshot-v1",
        "adapter": {
            "id": "video-subtitle/wechat-browser-adapter",
            "version": "1",
        },
        "ready": True,
        "appmsgid": "100000721",
        "body_images": {
            "intended": 1,
            "items": [
                {
                    "visible": True,
                    "complete": True,
                    "natural_width": 1280,
                    "width": 640,
                    "height": 360,
                    "host_class": "wechat",
                }
            ],
            "local_path_markers_remaining": 0,
        },
        "fields": {
            "title": {"value": "测试文章", "visible_candidates": 1},
            "summary": {"value": "测试摘要", "visible_candidates": 1},
            "author": {"value": "", "visible_candidates": 1},
        },
    }
    schema = json.loads(
        (ROOT / "schemas" / "wechat-browser-snapshot.schema.json").read_text(
            encoding="utf-8"
        )
    )

    jsonschema.validate(snapshot, schema)
    snapshot["body_images"]["items"][0]["source"] = "https://mmbiz.qpic.cn/secret.jpg"
    try:
        jsonschema.validate(snapshot, schema)
    except jsonschema.ValidationError:
        pass
    else:  # pragma: no cover
        raise AssertionError("browser snapshot must not persist raw image URLs")


def test_browser_snapshot_schema_keeps_ready_and_ambiguous_states_exclusive() -> None:
    schema = json.loads(
        (ROOT / "schemas" / "wechat-browser-snapshot.schema.json").read_text(
            encoding="utf-8"
        )
    )
    ambiguous = {
        "schema_version": "video-content/wechat-browser-snapshot-v1",
        "adapter": {
            "id": "video-subtitle/wechat-browser-adapter",
            "version": "1",
        },
        "ready": False,
        "appmsgid": None,
        "ambiguity": {"body_candidates": 2},
    }

    jsonschema.validate(ambiguous, schema)
    ambiguous["body_images"] = {
        "intended": 0,
        "items": [],
        "local_path_markers_remaining": 0,
    }
    try:
        jsonschema.validate(ambiguous, schema)
    except jsonschema.ValidationError:
        pass
    else:  # pragma: no cover
        raise AssertionError("an ambiguous snapshot must not claim ready body evidence")


def test_clipboard_script_dry_run_emits_no_payload(tmp_path: Path) -> None:
    _write_package(tmp_path)
    completed = subprocess.run(
        [
            sys.executable,
            str(
                ROOT
                / ".agents"
                / "skills"
                / "wechat-draft-handoff"
                / "scripts"
                / "prepare_clipboard.py"
            ),
            str(tmp_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["ok"] is True
    assert report["copied"] is False
    assert "data:image" not in completed.stdout
    assert "secret-value" not in completed.stdout


def test_invalid_draft_receipt_is_not_committed(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        wechat_adapter,
        "get_content_project",
        lambda _path: {
            "project_id": "content_0123456789abcdef",
            "current": {
                "deliverable_id": "dlv-001",
                "fidelity_audit_id": "audit-001",
            },
        },
    )
    monkeypatch.setattr(
        wechat_adapter,
        "validate_wechat_draft_receipt",
        lambda *_args, **_kwargs: {"valid": False, "errors": ["fixture"]},
    )
    observation = tmp_path / "observation.json"
    observation.write_text(
        json.dumps(_observation(), ensure_ascii=False), encoding="utf-8"
    )
    output = tmp_path / "wechat-draft-receipt.json"
    previous = b'{"valid":"previous receipt"}\n'
    output.write_bytes(previous)

    result = wechat_adapter.write_and_validate_wechat_draft_receipt(
        tmp_path / "project.json", observation, output
    )

    assert result["ok"] is False
    assert result["persisted"] is False
    assert output.read_bytes() == previous
    assert not list(tmp_path.glob(".*.tmp"))
