from __future__ import annotations

from pathlib import Path

import pytest

from video_subtitle.core.automation_job import (
    automation_idempotency_key,
    get_automation_job,
    initialize_automation_job,
    list_automation_jobs,
    transition_automation_job,
)


def _profile() -> dict:
    return {
        "profile_id": "profile-watch-later",
        "version": 1,
        "retry_policy": {
            "max_technical_attempts": 2,
            "max_content_repairs": 1,
            "backoff_seconds": 1,
        },
    }


def _source() -> dict:
    return {
        "platform": "bilibili",
        "bvid": "BV1fixture",
        "page": 1,
        "title": "fixture",
        "url": "https://www.bilibili.com/video/BV1fixture/",
    }


def test_job_identity_and_initialization_are_idempotent(tmp_path: Path) -> None:
    first = initialize_automation_job(tmp_path, _source(), _profile())
    second = initialize_automation_job(tmp_path, _source(), _profile())
    assert first["job_id"] == second["job_id"]
    assert first["idempotency_key"] == automation_idempotency_key(
        "bilibili", "BV1fixture", 1, "profile-watch-later", 1
    )
    assert len(list_automation_jobs(tmp_path)["jobs"]) == 1


def test_job_enforces_transitions_and_terminal_states(tmp_path: Path) -> None:
    job = initialize_automation_job(tmp_path, _source(), _profile())
    path = Path(job["job_path"])
    transition_automation_job(path, status="queued")
    transition_automation_job(path, status="evidence_running")
    with pytest.raises(ValueError, match="canonical"):
        transition_automation_job(path, status="canonical_ready")
    transition_automation_job(path, status="unprocessable", error={"code": "NO_TEXT"})
    with pytest.raises(ValueError, match="terminal"):
        transition_automation_job(path, status="queued")


def test_job_retry_is_bounded(tmp_path: Path) -> None:
    job = initialize_automation_job(tmp_path, _source(), _profile())
    path = Path(job["job_path"])
    transition_automation_job(path, status="queued")
    transition_automation_job(path, status="evidence_running")
    transition_automation_job(
        path,
        status="retry_wait",
        error={"code": "TIMEOUT"},
        next_retry_at="2026-08-16T00:01:00Z",
    )
    transition_automation_job(path, status="evidence_running")
    transition_automation_job(
        path,
        status="retry_wait",
        error={"code": "TIMEOUT"},
        next_retry_at="2026-08-16T00:02:00Z",
    )
    transition_automation_job(path, status="evidence_running")
    result = transition_automation_job(
        path,
        status="retry_wait",
        error={"code": "TIMEOUT"},
        next_retry_at="2026-08-16T00:03:00Z",
    )
    assert result["status"] == "failed_retry_exhausted"
    assert get_automation_job(path)["termination"]["code"] == "RETRY_EXHAUSTED"
