from __future__ import annotations

from pathlib import Path

import pytest

from video_subtitle.core.automation_profile import (
    read_automation_profile,
    require_active_draft_authorization,
    save_automation_profile,
    save_draft_authorization,
)


def _profile() -> dict:
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


def _authorization(profile_id: str) -> dict:
    return {
        "authorization_id": "auth-watch-later",
        "status": "active",
        "profile_ids": [profile_id],
        "browser_profile_alias": "wechat-main",
        "allowed_actions": ["save_wechat_draft"],
        "prohibited_actions": [
            "publish",
            "mass_send",
            "schedule",
            "originality",
            "account_management",
        ],
        "expires_at": None,
        "revoked_at": None,
    }


def test_profile_identity_is_deterministic(tmp_path: Path) -> None:
    first = save_automation_profile(tmp_path / "first.json", _profile())
    second = save_automation_profile(tmp_path / "second.json", _profile())
    assert first["profile_id"] == second["profile_id"]
    assert first["version"] == 1
    assert (
        read_automation_profile(tmp_path / "first.json")["profile_id"]
        == first["profile_id"]
    )


def test_authorization_allows_only_draft_save(tmp_path: Path) -> None:
    profile = save_automation_profile(tmp_path / "profile.json", _profile())
    authorization = save_draft_authorization(
        tmp_path / "authorization.json", _authorization(profile["profile_id"])
    )
    require_active_draft_authorization(profile, authorization)
    assert authorization["allowed_actions"] == ["save_wechat_draft"]


def test_authorization_rejects_publish_and_secret_fields(tmp_path: Path) -> None:
    profile = save_automation_profile(tmp_path / "profile.json", _profile())
    publish = _authorization(profile["profile_id"])
    publish["allowed_actions"] = ["save_wechat_draft", "publish"]
    with pytest.raises(ValueError, match="draft"):
        save_draft_authorization(tmp_path / "publish.json", publish)

    secret = _authorization(profile["profile_id"])
    secret["browser"] = {"cookie": "secret"}
    with pytest.raises(ValueError, match="secret"):
        save_draft_authorization(tmp_path / "secret.json", secret)


def test_revoked_or_wrong_profile_authorization_is_rejected(tmp_path: Path) -> None:
    profile = save_automation_profile(tmp_path / "profile.json", _profile())
    revoked = _authorization(profile["profile_id"])
    revoked["status"] = "revoked"
    revoked["revoked_at"] = "2026-08-16T00:00:00Z"
    authorization = save_draft_authorization(tmp_path / "revoked.json", revoked)
    with pytest.raises(ValueError, match="active"):
        require_active_draft_authorization(profile, authorization)

    wrong = save_draft_authorization(
        tmp_path / "wrong.json", _authorization("profile-other")
    )
    with pytest.raises(ValueError, match="profile"):
        require_active_draft_authorization(profile, wrong)
