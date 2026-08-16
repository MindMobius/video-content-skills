from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _schema(name: str) -> dict:
    return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))


def _examples() -> dict[str, dict]:
    sha = "a" * 64
    profile = {
        "schema_version": "video-automation/profile-v1",
        "profile_id": "profile-watch-later",
        "version": 1,
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
            "max_technical_attempts": 3,
            "max_content_repairs": 2,
            "backoff_seconds": 60,
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
    job = {
        "schema_version": "video-automation/job-v1",
        "job_id": "auto_0123456789abcdef",
        "idempotency_key": sha,
        "profile_id": profile["profile_id"],
        "profile_version": 1,
        "source": {
            "platform": "bilibili",
            "bvid": "BV1fixture",
            "page": 1,
            "title": "fixture",
            "url": "https://www.bilibili.com/video/BV1fixture/",
        },
        "status": "queued",
        "stage": "queued",
        "attempts": {"technical": 0, "content_repairs": 0},
        "artifacts": {},
        "retry": {"resume_status": None, "next_retry_at": None},
        "termination": None,
        "timestamps": {
            "created_at": "2026-08-16T00:00:00Z",
            "updated_at": "2026-08-16T00:00:00Z",
            "finished_at": None,
        },
    }
    snapshot = {
        "schema_version": "video-automation/watch-later-snapshot-v1",
        "snapshot_id": "snapshot_0123456789abcdef",
        "captured_at": "2026-08-16T00:00:00Z",
        "profile_id": profile["profile_id"],
        "account_profile_alias": "bilibili-main",
        "entries": [
            {
                "bvid": "BV1fixture",
                "page": 1,
                "title": "fixture",
                "url": "https://www.bilibili.com/video/BV1fixture/",
                "position": 1,
                "added_at": None,
            }
        ],
        "new_entries": [],
        "source_digest": sha,
    }
    canonical = {
        "schema_version": "video-subtitle/canonical-v1",
        "canonical_id": "canonical_0123456789abcdef",
        "manifest_sha256": sha,
        "status": "usable",
        "evidence": [
            {
                "evidence_id": "platform-bilibili",
                "sha256": sha,
                "role": "primary",
            }
        ],
        "cues": [
            {
                "cue_id": "canonical-cue-00001",
                "start_ms": 0,
                "end_ms": 1000,
                "text": "测试字幕",
                "evidence_refs": ["platform-bilibili-cue-00001"],
            }
        ],
        "decisions": [],
        "unresolved": [],
        "artifacts": {
            "srt": "subtitle.canonical.srt",
            "json": "subtitle.canonical.json",
            "report": "subtitle.canonical.report.json",
        },
        "termination": None,
        "created_at": "2026-08-16T00:00:00Z",
    }
    authorization = {
        "schema_version": "video-automation/draft-authorization-v1",
        "authorization_id": "auth-watch-later",
        "status": "active",
        "profile_ids": [profile["profile_id"]],
        "browser_profile_alias": "wechat-main",
        "allowed_actions": ["save_wechat_draft"],
        "prohibited_actions": profile["prohibited_actions"],
        "created_at": "2026-08-16T00:00:00Z",
        "expires_at": None,
        "revoked_at": None,
    }
    binding = {
        "schema_version": "video-automation/handoff-binding-v1",
        "binding_id": "binding_0123456789abcdef",
        "job_id": job["job_id"],
        "authorization_id": authorization["authorization_id"],
        "project_id": "content_0123456789abcdef",
        "deliverable_id": "dlv-001",
        "fidelity_audit_id": "audit-001",
        "receipt_path": "wechat/wechat-draft-receipt.json",
        "receipt_sha256": sha,
        "appmsgid": "123456789",
        "created_at": "2026-08-16T00:00:00Z",
    }
    return {
        "automation-profile.schema.json": profile,
        "automation-job.schema.json": job,
        "watch-later-snapshot.schema.json": snapshot,
        "canonical-subtitle.schema.json": canonical,
        "draft-authorization.schema.json": authorization,
        "automation-handoff-binding.schema.json": binding,
    }


def test_automation_examples_are_schema_valid() -> None:
    for name, document in _examples().items():
        jsonschema.validate(document, _schema(name))


def test_draft_authorization_rejects_publish_action() -> None:
    document = _examples()["draft-authorization.schema.json"]
    document["allowed_actions"] = ["save_wechat_draft", "publish"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(document, _schema("draft-authorization.schema.json"))


def test_usable_canonical_requires_cues() -> None:
    document = _examples()["canonical-subtitle.schema.json"]
    document["cues"] = []
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(document, _schema("canonical-subtitle.schema.json"))
