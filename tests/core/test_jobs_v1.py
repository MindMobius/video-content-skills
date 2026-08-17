from __future__ import annotations

from pathlib import Path

import pytest

from video_content.jobs import resume_job, update_job
from video_content.store import Store


def test_job_follows_forward_only_state_machine(tmp_path: Path) -> None:
    store = Store(tmp_path)
    job, _ = store.create_job(source={"kind": "fixture"}, idempotency_key="fixture_1")
    current = update_job(store, job["job_id"], stage="inspecting", status="running")
    current = update_job(store, current["job_id"], stage="evidence", status="running")
    with pytest.raises(ValueError, match="backwards"):
        update_job(store, current["job_id"], stage="inspecting")
    current = update_job(store, current["job_id"], stage="transcript")
    current = update_job(store, current["job_id"], stage="content")
    current = update_job(store, current["job_id"], stage="handoff")
    current = update_job(
        store, current["job_id"], stage="completed", status="completed"
    )
    assert current["completed_at"]
    with pytest.raises(ValueError, match="Terminal"):
        update_job(store, current["job_id"], status="queued")


def test_retry_and_auth_pause_are_explicit(tmp_path: Path) -> None:
    store = Store(tmp_path)
    job, _ = store.create_job(source={"kind": "fixture"}, idempotency_key="fixture_2")
    failed = update_job(
        store,
        job["job_id"],
        stage="evidence",
        status="retryable",
        error={"code": "DOWNLOAD_TIMEOUT", "message": "retry"},
        increment_attempts=True,
    )
    assert failed["attempts"] == 1
    resumed = resume_job(store, job["job_id"])
    assert resumed["status"] == "queued"
    paused = update_job(store, job["job_id"], stage="handoff", status="paused_auth")
    assert resume_job(store, paused["job_id"])["status"] == "queued"


def test_physical_evidence_limit_is_terminal(tmp_path: Path) -> None:
    store = Store(tmp_path)
    job, _ = store.create_job(source={"kind": "fixture"}, idempotency_key="fixture_3")
    result = update_job(
        store,
        job["job_id"],
        stage="evidence",
        status="unprocessable",
        error={"code": "INSUFFICIENT_EVIDENCE", "message": "no audio or readable text"},
    )
    assert result["status"] == "unprocessable"
