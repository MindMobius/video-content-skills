from __future__ import annotations

import json
from pathlib import Path

import pytest

from video_subtitle.core.automation_handoff import (
    bind_automation_handoff_receipt,
    get_existing_handoff_binding,
    prepare_automation_handoff,
)
from video_subtitle.core.automation_job import (
    get_automation_job,
    initialize_automation_job,
    transition_automation_job,
)
from video_subtitle.core.automation_profile import (
    save_automation_profile,
    save_draft_authorization,
)
from video_subtitle.core.util import write_json_atomic


def _profile_document() -> dict:
    return {
        "enabled": True,
        "source": {
            "kind": "bilibili_watch_later",
            "account_profile_alias": "bilibili-main",
            "poll_interval_seconds": 900,
        },
        "content": {
            "medium": "wechat_article",
            "objective": "faithful_information_transfer",
            "audience": "公众号读者",
            "output_language": "zh-CN",
            "style": "restrained-editorial",
            "image_policy": "source_video_only",
        },
        "evidence_policy": {
            "require_hard_subtitle_assessment": True,
            "allow_platform_subtitle": True,
            "allow_hard_ocr": True,
            "allow_audio_asr": True,
        },
        "retry_policy": {
            "max_technical_attempts": 2,
            "max_content_repairs": 1,
            "backoff_seconds": 1,
        },
        "draft_authorization_id": "auth-watch-later",
        "prohibited_actions": [
            "publish",
            "mass_send",
            "schedule",
            "originality",
            "account_management",
        ],
    }


def _receipt() -> dict:
    return {
        "schema_version": "video-content/wechat-draft-receipt-v1",
        "project_id": "content_0123456789abcdef",
        "deliverable_id": "dlv-001",
        "fidelity_audit_id": "audit-001",
        "platform": "wechat_official_account",
        "status": "saved_as_draft",
        "started_at": "2026-08-16T00:00:00Z",
        "saved_at": "2026-08-16T00:10:00Z",
        "title": "Draft",
        "appmsgid": "123456789",
        "body_images": {
            "intended": 1,
            "visible_loaded": 1,
            "wechat_hosted": 1,
            "non_wechat_hosted": 0,
            "local_path_markers_remaining": 0,
        },
        "cover": {
            "source": "first body image",
            "asset": "assets/cover.jpg",
            "selected": True,
            "crop_confirmed": True,
            "wechat_hosted_preview": True,
        },
        "summary": {"filled": True, "text": "Summary"},
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
            "history_record": "08-16 08:10 / web / manual save",
            "history_record_persisted": True,
            "saved_page_read_back": True,
        },
        "published": False,
        "publish_actions_performed": [],
    }


def _ready_job(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    profile_path = tmp_path / "profile.json"
    profile = save_automation_profile(profile_path, _profile_document())
    authorization_path = tmp_path / "authorization.json"
    save_draft_authorization(
        authorization_path,
        {
            "authorization_id": "auth-watch-later",
            "status": "active",
            "profile_ids": [profile["profile_id"]],
            "browser_profile_alias": "wechat-main",
            "allowed_actions": ["save_wechat_draft"],
            "prohibited_actions": profile["prohibited_actions"],
            "expires_at": None,
            "revoked_at": None,
        },
    )
    job = initialize_automation_job(
        tmp_path,
        {
            "platform": "bilibili",
            "bvid": "BV1handoff",
            "page": 1,
            "title": "Handoff",
            "url": "https://www.bilibili.com/video/BV1handoff/",
        },
        profile,
    )
    job_path = Path(job["job_path"])
    root = job_path.parent
    canonical = root / "canonical.json"
    canonical.write_text("{}", encoding="utf-8")
    content_dir = root / "content"
    content_dir.mkdir()
    project_path = content_dir / "project.json"
    write_json_atomic(project_path, {"project_id": "content_0123456789abcdef"})
    content_binding = root / "automation-content-binding.json"
    write_json_atomic(
        content_binding,
        {
            "project_id": "content_0123456789abcdef",
            "project_path": "content/project.json",
        },
    )
    audit = root / "audit.json"
    audit.write_text("{}", encoding="utf-8")
    transition_automation_job(job_path, status="queued")
    transition_automation_job(job_path, status="evidence_running")
    transition_automation_job(job_path, status="evidence_ready")
    transition_automation_job(job_path, status="canonicalizing")
    transition_automation_job(
        job_path,
        status="canonical_ready",
        artifact_kind="canonical_subtitle",
        artifact_path=str(canonical),
        artifact_status="usable",
    )
    transition_automation_job(
        job_path,
        status="content_generating",
        artifact_kind="content_binding",
        artifact_path=str(content_binding),
    )
    transition_automation_job(job_path, status="content_auditing")
    transition_automation_job(
        job_path,
        status="rendering",
        artifact_kind="fidelity_audit",
        artifact_path=str(audit),
        artifact_status="pass",
    )
    transition_automation_job(job_path, status="handoff_running")
    return profile_path, authorization_path, job_path, project_path


def test_binding_completes_job_and_prevents_duplicate_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_path, authorization_path, job_path, _project_path = _ready_job(tmp_path)
    receipt_path = job_path.parent / "wechat-draft-receipt.json"
    write_json_atomic(receipt_path, _receipt())
    monkeypatch.setattr(
        "video_subtitle.core.automation_handoff.validate_wechat_draft_receipt",
        lambda *args, **kwargs: {"valid": True, "errors": []},
    )
    prepared = prepare_automation_handoff(
        job_path=job_path,
        profile_path=profile_path,
        authorization_path=authorization_path,
    )
    assert prepared["already_completed"] is False
    result = bind_automation_handoff_receipt(
        job_path=job_path,
        authorization_path=authorization_path,
        receipt_path=receipt_path,
    )
    assert result["appmsgid"] == "123456789"
    assert (job_path.parent / "handoff-binding.json").is_file()
    assert (
        get_automation_job(job_path)["artifacts"]["handoff_binding"]["path"]
        == "handoff-binding.json"
    )
    assert get_automation_job(job_path)["status"] == "completed"
    assert get_existing_handoff_binding(job_path)["binding_id"] == result["binding_id"]
    assert (
        prepare_automation_handoff(
            job_path=job_path,
            profile_path=profile_path,
            authorization_path=authorization_path,
        )["already_completed"]
        is True
    )


def test_binding_rejects_revoked_authorization_and_publish_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_path, authorization_path, job_path, _project_path = _ready_job(tmp_path)
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    authorization["status"] = "revoked"
    authorization["revoked_at"] = "2026-08-16T00:00:00Z"
    write_json_atomic(authorization_path, authorization)
    with pytest.raises(ValueError, match="active"):
        prepare_automation_handoff(
            job_path=job_path,
            profile_path=profile_path,
            authorization_path=authorization_path,
        )

    active = authorization
    active["status"] = "active"
    active["revoked_at"] = None
    write_json_atomic(authorization_path, active)
    receipt = _receipt()
    receipt["published"] = True
    receipt["publish_actions_performed"] = ["publish"]
    receipt_path = job_path.parent / "wechat-draft-receipt.json"
    write_json_atomic(receipt_path, receipt)
    monkeypatch.setattr(
        "video_subtitle.core.automation_handoff.validate_wechat_draft_receipt",
        lambda *args, **kwargs: {"valid": True, "errors": []},
    )
    with pytest.raises(ValueError, match="publish"):
        bind_automation_handoff_receipt(
            job_path=job_path,
            authorization_path=authorization_path,
            receipt_path=receipt_path,
            output_path=job_path.parent / "binding.json",
        )
