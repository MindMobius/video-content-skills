from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

from video_subtitle.core.handoff import validate_wechat_draft_receipt

ROOT = Path(__file__).parents[2]


def _receipt() -> dict:
    return {
        "schema_version": "video-content/wechat-draft-receipt-v1",
        "project_id": "content_0123456789abcdef",
        "deliverable_id": "dlv-001",
        "fidelity_audit_id": "audit-001",
        "platform": "wechat_official_account",
        "status": "saved_as_draft",
        "started_at": "2026-08-10T04:00:00+00:00",
        "saved_at": "2026-08-10T04:20:00+00:00",
        "title": "Test article",
        "appmsgid": "100000845",
        "body_images": {
            "intended": 5,
            "visible_loaded": 5,
            "wechat_hosted": 5,
            "non_wechat_hosted": 0,
            "local_path_markers_remaining": 0,
        },
        "cover": {
            "source": "first body image",
            "asset": "assets/01-original-cover.jpg",
            "selected": True,
            "crop_confirmed": True,
            "wechat_hosted_preview": True,
        },
        "summary": {"filled": True, "text": "A concise audited summary."},
        "author": {"value": "", "left_blank": True},
        "originality": {"declared": False, "visible_state": "not declared"},
        "content_checks": {
            "source_disclosure_present": True,
            "ending_present": True,
            "underline_count": 0,
            "stock_cta_present": False,
            "speaker_identity_preserved": True,
        },
        "save": {
            "saved": True,
            "channel": "web",
            "mode": "manual save",
            "history_record": "08-10 12:20 / web / manual save",
            "history_record_persisted": True,
            "saved_page_read_back": True,
        },
        "published": False,
        "publish_actions_performed": [],
    }


def _write_receipt(tmp_path: Path, value: dict) -> Path:
    path = tmp_path / "wechat-draft-receipt.json"
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def test_wechat_receipt_schema_and_validator_accept_durable_draft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _receipt()
    schema = json.loads(
        (ROOT / "schemas" / "wechat-draft-receipt.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(receipt, schema)
    receipt_path = _write_receipt(tmp_path, receipt)
    monkeypatch.setattr(
        "video_subtitle.core.handoff.get_content_project",
        lambda path: {
            "project_id": receipt["project_id"],
            "current": {
                "deliverable_id": receipt["deliverable_id"],
                "fidelity_audit_id": receipt["fidelity_audit_id"],
            },
            "integrity": {"ready_for_delivery": True, "warnings": []},
        },
    )

    result = validate_wechat_draft_receipt(
        receipt_path,
        project_path=tmp_path / "project.json",
    )

    assert result["valid"] is True
    assert result["project_checked"] is True
    assert result["errors"] == []


def test_wechat_receipt_rejects_partial_images_and_publish_state(
    tmp_path: Path,
) -> None:
    receipt = _receipt()
    receipt["body_images"]["visible_loaded"] = 4
    receipt["body_images"]["non_wechat_hosted"] = 1
    receipt["published"] = True
    receipt["publish_actions_performed"] = ["publish"]

    result = validate_wechat_draft_receipt(_write_receipt(tmp_path, receipt))
    codes = {item["code"] for item in result["errors"]}

    assert result["valid"] is False
    assert {
        "BODY_IMAGE_COUNT_MISMATCH",
        "BODY_IMAGE_IMPORT_INCOMPLETE",
        "PUBLISHED_STATE_FORBIDDEN",
        "PUBLISH_ACTIONS_FORBIDDEN",
    } <= codes


def test_wechat_receipt_rejects_stale_project_artifact_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _receipt()
    receipt_path = _write_receipt(tmp_path, receipt)
    monkeypatch.setattr(
        "video_subtitle.core.handoff.get_content_project",
        lambda path: {
            "project_id": receipt["project_id"],
            "current": {
                "deliverable_id": "dlv-002",
                "fidelity_audit_id": "audit-002",
            },
            "integrity": {"ready_for_delivery": True, "warnings": []},
        },
    )

    result = validate_wechat_draft_receipt(
        receipt_path,
        project_path=tmp_path / "project.json",
    )
    codes = {item["code"] for item in result["errors"]}

    assert {"DELIVERABLE_ID_MISMATCH", "FIDELITY_AUDIT_ID_MISMATCH"} <= codes


def test_wechat_receipt_validator_cli_returns_json(tmp_path: Path) -> None:
    receipt_path = _write_receipt(tmp_path, _receipt())

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "validate_wechat_draft_receipt.py"),
            str(receipt_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0
    result = json.loads(completed.stdout)
    assert result["valid"] is True
    assert result["project_checked"] is False
    assert result["warnings"][0]["code"] == "PROJECT_NOT_CHECKED"
