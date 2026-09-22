from __future__ import annotations

from typing import Any

from .models import JOB_STAGES, JOB_STATUSES, TERMINAL_STATUSES
from .store import Store
from .util import utc_now

_STAGE_ORDER = {
    "queued": 0,
    "inspecting": 1,
    "evidence": 2,
    "transcript": 3,
    "content": 4,
    "handoff": 5,
    "completed": 6,
}


def update_job(
    store: Store,
    job_id: str,
    *,
    stage: str | None = None,
    status: str | None = None,
    error: dict[str, Any] | None = None,
    retry_at: str | None = None,
    increment_attempts: bool = False,
) -> dict[str, Any]:
    job = store.get_job(job_id)
    old_stage = str(job["stage"])
    old_status = str(job["status"])
    if old_status in TERMINAL_STATUSES:
        requested_stage = stage or old_stage
        requested_status = status or old_status
        if requested_stage != old_stage or requested_status != old_status:
            raise ValueError(f"Terminal job cannot transition: {old_status}")
        return job
    next_stage = stage or old_stage
    next_status = status or old_status
    if next_stage not in JOB_STAGES:
        raise ValueError(f"Unknown job stage: {next_stage}")
    if next_status not in JOB_STATUSES:
        raise ValueError(f"Unknown job status: {next_status}")
    if _STAGE_ORDER[next_stage] < _STAGE_ORDER[old_stage]:
        raise ValueError(
            f"Job stage cannot move backwards: {old_stage} -> {next_stage}"
        )
    if next_status == "completed" and next_stage != "completed":
        raise ValueError("Completed status requires completed stage")
    if next_stage == "completed" and next_status != "completed":
        raise ValueError("Completed stage requires completed status")
    if next_status == "completed":
        wechat_required = old_stage == "handoff"
        if job.get("profile_id"):
            wechat_required = (
                wechat_required
                or store.get_profile(job["profile_id"]).get("carrier")
                == "wechat_article"
            )
        if wechat_required:
            # Local import avoids the service dependency cycle; completion is
            # checked after wechat_bind has persisted its validated Receipt.
            from .wechat import validate_draft_receipt

            receipts = store.list_artifacts(job_id, kind="draft_receipt")
            if not any(
                validate_draft_receipt(
                    store,
                    job_id=job_id,
                    receipt_id=str(ref.get("metadata", {}).get("receipt_id") or ""),
                )["valid"]
                for ref in receipts
            ):
                raise ValueError(
                    "WeChat completion requires a validated Draft Receipt; use wechat_bind"
                )
    if next_status == "retryable" and not error:
        raise ValueError("Retryable job requires an error")
    if next_status == "paused_auth" and next_stage not in {
        "inspecting",
        "evidence",
        "handoff",
    }:
        raise ValueError("paused_auth requires an authenticated platform stage")
    if next_status == "unprocessable" and not error:
        raise ValueError("unprocessable job requires a physical limitation")
    job["stage"] = next_stage
    job["status"] = next_status
    if increment_attempts:
        job["attempts"] = int(job.get("attempts", 0)) + 1
    job["last_error"] = error
    job["retry_at"] = retry_at
    if next_status == "completed":
        job["completed_at"] = utc_now()
    saved = store.write_job(job)
    store.append_event(
        job_id,
        {
            "type": "job.transitioned",
            "from": {"stage": old_stage, "status": old_status},
            "to": {"stage": next_stage, "status": next_status},
            "error": error,
            "retry_at": retry_at,
        },
    )
    return saved


def resume_job(store: Store, job_id: str) -> dict[str, Any]:
    job = store.get_job(job_id)
    if job["status"] not in {"retryable", "paused_auth"}:
        raise ValueError(f"Job is not resumable: {job['status']}")
    return update_job(store, job_id, status="queued", error=None, retry_at=None)
