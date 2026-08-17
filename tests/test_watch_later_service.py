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
