from __future__ import annotations

from pathlib import Path

import pytest

from video_subtitle.core.automation_profile import save_automation_profile
from video_subtitle.core.automation_scan import scan_watch_later


class FakeWatchLaterSource:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def list_entries(self, *, limit: int | None = None) -> list[dict]:
        return self.rows[:limit] if limit is not None else list(self.rows)


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


def _rows() -> list[dict]:
    return [
        {
            "bvid": "BV1alpha",
            "page": 1,
            "title": "Alpha",
            "url": "https://www.bilibili.com/video/BV1alpha/",
            "position": 1,
            "addedAt": "2026-08-15T00:00:00Z",
        }
    ]


def test_scan_is_idempotent_and_enqueues_only_new_items(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.json"
    save_automation_profile(profile_path, _profile())
    source = FakeWatchLaterSource(_rows())
    first = scan_watch_later(profile_path=profile_path, source=source, store=tmp_path)
    second = scan_watch_later(profile_path=profile_path, source=source, store=tmp_path)
    assert first["new_entry_count"] == 1
    assert len(first["created_jobs"]) == 1
    assert second["new_entry_count"] == 0
    assert second["created_jobs"] == []


def test_scan_adds_one_new_identity_and_does_not_cancel_removed_item(
    tmp_path: Path,
) -> None:
    profile_path = tmp_path / "profile.json"
    save_automation_profile(profile_path, _profile())
    first = FakeWatchLaterSource(_rows())
    scan_watch_later(profile_path=profile_path, source=first, store=tmp_path)
    changed = FakeWatchLaterSource(
        [
            {
                "bvid": "BV1new",
                "page": 2,
                "title": "New",
                "url": "https://www.bilibili.com/video/BV1new/",
                "position": 1,
                "addedAt": "2026-08-16T00:00:00Z",
            }
        ]
    )
    result = scan_watch_later(profile_path=profile_path, source=changed, store=tmp_path)
    assert result["new_entry_count"] == 1
    assert len(result["created_jobs"]) == 1
    assert result["job_count"] == 2


def test_malformed_scan_creates_no_partial_jobs(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.json"
    save_automation_profile(profile_path, _profile())
    malformed = FakeWatchLaterSource([{**_rows()[0], "bvid": ""}])
    with pytest.raises(ValueError):
        scan_watch_later(profile_path=profile_path, source=malformed, store=tmp_path)
    assert not (tmp_path / "jobs").exists()
