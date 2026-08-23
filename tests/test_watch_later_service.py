from __future__ import annotations

import json
from pathlib import Path

import pytest

from video_content.automation import save_watch_later_profile, watch_later_scan
from video_content.jobs import update_job
from video_content.store import Store

ROOT = Path(__file__).resolve().parent


class FixtureSource:
    def __init__(self, name: str) -> None:
        self.name = name

    def list_entries(self, *, limit=None):
        rows = json.loads(
            (ROOT / "fixtures" / "bilibili-watch-later" / self.name).read_text(
                encoding="utf-8-sig"
            )
        )
        return rows[:limit] if limit else rows


class RowsSource:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def list_entries(self, *, limit=None):
        return self.rows[:limit] if limit else self.rows


def test_scan_creates_jobs_only_for_new_stable_identities(tmp_path: Path) -> None:
    store = Store(tmp_path)
    save_watch_later_profile(
        store,
        profile_id="daily",
        account_profile_alias="j6g376bb",
    )
    first = watch_later_scan(
        store, profile_id="daily", source=FixtureSource("first.json")
    )
    repeat = watch_later_scan(
        store, profile_id="daily", source=FixtureSource("first.json")
    )
    changed = watch_later_scan(
        store,
        profile_id="daily",
        source=FixtureSource("reordered-with-new.json"),
    )
    assert first["new_entry_count"] == 2
    assert len(first["created_jobs"]) == 2
    assert repeat["new_entry_count"] == 0
    assert changed["new_entry_count"] == 1
    assert len(changed["created_jobs"]) == 1
    assert len(store.list_jobs()) == 3
    new_job = store.get_job(changed["created_jobs"][0])
    assert new_job["source"]["bvid"] == "BV1new"
    assert new_job["source"]["page"] == 2
    assert changed["detection_mode"] == "timestamp_watermark"
    assert changed["ignored_unseen_entry_count"] == 0


def test_scan_does_not_backfill_older_unseen_rows_when_window_expands(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path)
    save_watch_later_profile(
        store,
        profile_id="daily",
        account_profile_alias="j6g376bb",
    )
    watch_later_scan(store, profile_id="daily", source=FixtureSource("first.json"))
    expanded = watch_later_scan(
        store,
        profile_id="daily",
        source=RowsSource(
            [
                {
                    "bvid": "BV1new",
                    "page": 1,
                    "title": "New",
                    "position": 1,
                    "addedAt": "2026-08-16T00:00:00.000Z",
                },
                {
                    "bvid": "BV1beta",
                    "page": 1,
                    "title": "Beta",
                    "position": 2,
                    "addedAt": "2026-08-15T01:00:00.000Z",
                },
                {
                    "bvid": "BV1alpha",
                    "page": 1,
                    "title": "Alpha",
                    "position": 3,
                    "addedAt": "2026-08-15T00:00:00.000Z",
                },
                {
                    "bvid": "BV1older",
                    "page": 1,
                    "title": "Historical tail",
                    "position": 4,
                    "addedAt": "2026-08-14T00:00:00.000Z",
                },
            ]
        ),
    )
    assert expanded["new_entry_count"] == 1
    assert expanded["ignored_unseen_entry_count"] == 1
    assert expanded["detection_mode"] == "timestamp_watermark"
    assert len(store.list_jobs()) == 3
    created = store.get_job(expanded["created_jobs"][0])
    assert created["source"]["bvid"] == "BV1new"
    assert "BV1older:p1" in store.get_profile("daily")["baseline"]["seen"]


def test_empty_profile_can_initialize_baseline_without_backfill(tmp_path: Path) -> None:
    store = Store(tmp_path)
    save_watch_later_profile(
        store, profile_id="daily", account_profile_alias="j6g376bb"
    )
    result = watch_later_scan(
        store,
        profile_id="daily",
        source=FixtureSource("first.json"),
        baseline_if_empty=True,
    )
    assert result["baseline_initialized"] is True
    assert result["created_jobs"] == []
    assert len(store.get_profile("daily")["baseline"]["seen"]) == 2


def test_profile_enforces_no_publish_and_serial_gpu(tmp_path: Path) -> None:
    store = Store(tmp_path)
    profile = save_watch_later_profile(
        store,
        profile_id="daily",
        account_profile_alias="j6g376bb",
    )
    assert profile["settings"] == {
        "max_retries": 3,
        "gpu_parallelism": 1,
        "publish": False,
        "adaptation_mode": "source_faithful_full",
        "visual_policy": "source_frames_at_material_transitions",
        "minimum_source_frames": 3,
        "wechat_creation_source": "ai_generated",
    }
    with pytest.raises(ValueError, match="never publish"):
        save_watch_later_profile(
            store,
            profile_id="daily",
            account_profile_alias="j6g376bb",
            settings={"publish": True},
        )
    with pytest.raises(ValueError, match="serially"):
        save_watch_later_profile(
            store,
            profile_id="daily",
            account_profile_alias="j6g376bb",
            settings={"gpu_parallelism": 2},
        )


def test_technical_failure_retry_physical_limit_and_auth_pause_use_job_status(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path)
    job, _ = store.create_job(
        source={"platform": "bilibili"}, idempotency_key="fixture"
    )
    retry = update_job(
        store,
        job["job_id"],
        stage="evidence",
        status="retryable",
        error={"code": "TIMEOUT", "message": "download timeout"},
        increment_attempts=True,
    )
    assert retry["attempts"] == 1
    # Separate jobs demonstrate terminal and authentication outcomes without batch wrappers.
    physical, _ = store.create_job(
        source={"platform": "bilibili"}, idempotency_key="physical"
    )
    assert (
        update_job(
            store,
            physical["job_id"],
            stage="evidence",
            status="unprocessable",
            error={"code": "NO_EVIDENCE", "message": "physical source insufficient"},
        )["status"]
        == "unprocessable"
    )
    auth, _ = store.create_job(source={"platform": "bilibili"}, idempotency_key="auth")
    assert (
        update_job(
            store,
            auth["job_id"],
            stage="inspecting",
            status="paused_auth",
        )["status"]
        == "paused_auth"
    )
