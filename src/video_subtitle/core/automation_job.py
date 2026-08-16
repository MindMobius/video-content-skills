"""Durable idempotent state machine for Watch Later automation jobs."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .locking import exclusive_file_lock
from .util import read_json, utc_now, write_json_atomic

SCHEMA_VERSION = "video-automation/job-v1"
TERMINAL = {"completed", "unprocessable", "failed_retry_exhausted", "cancelled"}
ALLOWED: dict[str, set[str]] = {
    "discovered": {"queued", "cancelled"},
    "queued": {"evidence_running", "cancelled"},
    "evidence_running": {"evidence_ready", "retry_wait", "unprocessable"},
    "evidence_ready": {"canonicalizing", "retry_wait", "unprocessable"},
    "canonicalizing": {"canonical_ready", "retry_wait", "unprocessable"},
    "canonical_ready": {"content_generating", "cancelled"},
    "content_generating": {"content_auditing", "retry_wait", "unprocessable"},
    "content_auditing": {"content_generating", "rendering", "unprocessable"},
    "rendering": {"handoff_running", "retry_wait", "unprocessable"},
    "handoff_running": {"completed", "retry_wait", "paused_auth"},
    "paused_auth": {"handoff_running", "cancelled"},
}
TOKEN_RE = re.compile(r"(?i)(?:[?&](?:token|cookie|sessdata|password)=)")


def automation_idempotency_key(
    platform: str,
    bvid: str,
    page: int,
    profile_id: str,
    profile_version: int,
) -> str:
    identity = {
        "platform": platform.strip().lower(),
        "bvid": bvid.strip(),
        "page": int(page),
        "profile_id": profile_id.strip(),
        "profile_version": int(profile_version),
    }
    return hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def initialize_automation_job(
    store: Path, source: dict[str, Any], profile: dict[str, Any]
) -> dict[str, Any]:
    store = store.expanduser().resolve()
    normalized_source = _normalize_source(source)
    profile_id = str(profile.get("profile_id") or "").strip()
    profile_version = int(profile.get("version") or 0)
    if not re.fullmatch(r"profile[-_][A-Za-z0-9_-]+", profile_id):
        raise ValueError("Automation profile_id is invalid")
    if profile_version < 1:
        raise ValueError("Automation profile version is invalid")
    retry_policy = profile.get("retry_policy")
    if not isinstance(retry_policy, dict):
        raise TypeError("Automation profile retry policy must be an object")
    limits = {
        "max_technical_attempts": _nonnegative_int(
            retry_policy.get("max_technical_attempts"), "max_technical_attempts"
        ),
        "max_content_repairs": _nonnegative_int(
            retry_policy.get("max_content_repairs"), "max_content_repairs"
        ),
        "backoff_seconds": _nonnegative_int(
            retry_policy.get("backoff_seconds"), "backoff_seconds"
        ),
    }
    key = automation_idempotency_key(
        normalized_source["platform"],
        normalized_source["bvid"],
        normalized_source["page"],
        profile_id,
        profile_version,
    )
    job_id = f"auto_{key[:16]}"
    job_path = store / "jobs" / job_id / "job.json"
    if job_path.is_file():
        result = get_automation_job(job_path)
        result["reused_existing_job"] = True
        return result
    now = utc_now()
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "job_id": job_id,
        "idempotency_key": key,
        "profile_id": profile_id,
        "profile_version": profile_version,
        "source": normalized_source,
        "status": "discovered",
        "stage": "discovered",
        "attempts": {"technical": 0, "content_repairs": 0},
        "limits": limits,
        "artifacts": {},
        "retry": {"resume_status": None, "next_retry_at": None},
        "termination": None,
        "timestamps": {
            "created_at": now,
            "updated_at": now,
            "finished_at": None,
        },
    }
    job_path.parent.mkdir(parents=True, exist_ok=False)
    write_json_atomic(job_path, document)
    result = get_automation_job(job_path)
    result["reused_existing_job"] = False
    return result


def get_automation_job(path: Path) -> dict[str, Any]:
    path = _require_job(path)
    document = read_json(path)
    _validate_job(document)
    return {**document, "job_path": str(path)}


def list_automation_jobs(store: Path, *, status: str | None = None) -> dict[str, Any]:
    store = store.expanduser().resolve()
    jobs = []
    for path in sorted((store / "jobs").glob("auto_*/job.json")):
        job = get_automation_job(path)
        if status is None or job["status"] == status:
            jobs.append(job)
    by_status: dict[str, int] = {}
    for job in jobs:
        by_status[job["status"]] = by_status.get(job["status"], 0) + 1
    return {"store": str(store), "jobs": jobs, "summary": {"by_status": by_status}}


def transition_automation_job(
    path: Path,
    *,
    status: str,
    stage: str | None = None,
    artifact_kind: str | None = None,
    artifact_path: str | None = None,
    artifact_sha256: str | None = None,
    artifact_status: str | None = None,
    error: dict[str, Any] | None = None,
    next_retry_at: str | None = None,
) -> dict[str, Any]:
    path = _require_job(path)
    with exclusive_file_lock(path):
        document = read_json(path)
        _validate_job(document)
        previous = str(document["status"])
        requested = status.strip()
        if previous in TERMINAL:
            raise ValueError(f"Automation job is already terminal as {previous}")
        if previous == "retry_wait":
            resume = document["retry"].get("resume_status")
            if requested != resume:
                raise ValueError(f"Retry job must resume {resume!r}, not {requested!r}")
        elif requested not in ALLOWED.get(previous, set()):
            if requested == "canonical_ready":
                raise ValueError(
                    "Canonical readiness requires evidence_ready and canonicalizing"
                )
            raise ValueError(
                f"Cannot transition automation job from {previous} to {requested}"
            )

        now = utc_now()
        document = copy.deepcopy(document)
        if requested == "retry_wait":
            if not error or not next_retry_at:
                raise ValueError("Retry transition requires error and next_retry_at")
            technical = int(document["attempts"]["technical"]) + 1
            document["attempts"]["technical"] = technical
            if technical > int(document["limits"]["max_technical_attempts"]):
                requested = "failed_retry_exhausted"
                document["termination"] = {
                    "code": "RETRY_EXHAUSTED",
                    "message": _safe_error_message(error),
                }
                document["retry"] = {"resume_status": None, "next_retry_at": None}
            else:
                document["retry"] = {
                    "resume_status": previous,
                    "next_retry_at": str(next_retry_at),
                }
                document["termination"] = None
        elif previous == "retry_wait":
            document["retry"] = {"resume_status": None, "next_retry_at": None}
        if requested in {"unprocessable", "cancelled"}:
            if not error:
                raise ValueError(f"{requested} transition requires an error reason")
            document["termination"] = {
                "code": str(error.get("code") or requested.upper()),
                "message": _safe_error_message(error),
            }
            document["retry"] = {"resume_status": None, "next_retry_at": None}
        if artifact_kind or artifact_path:
            if not artifact_kind or not artifact_path:
                raise ValueError("Artifact kind and path must be supplied together")
            document["artifacts"][artifact_kind] = _artifact(
                path,
                artifact_path,
                sha256=artifact_sha256,
                status=artifact_status,
            )
        if requested == "completed":
            binding = document["artifacts"].get("handoff_binding")
            if not binding:
                raise ValueError("Completed automation job requires a handoff binding")
        if requested == "canonical_ready":
            canonical = document["artifacts"].get("canonical_subtitle")
            if not canonical or canonical.get("status") != "usable":
                raise ValueError(
                    "Canonical readiness requires a usable canonical artifact"
                )
        if requested == "rendering":
            audit = document["artifacts"].get("fidelity_audit")
            if not audit or audit.get("status") not in {"pass", "pass_with_warnings"}:
                raise ValueError("Rendering requires a passing fidelity audit")
        document["status"] = requested
        document["stage"] = stage.strip() if stage else requested
        document["timestamps"]["updated_at"] = now
        if requested in TERMINAL:
            document["timestamps"]["finished_at"] = now
        write_json_atomic(path, document)
    return get_automation_job(path)


def record_content_repair(path: Path) -> dict[str, Any]:
    path = _require_job(path)
    with exclusive_file_lock(path):
        document = read_json(path)
        _validate_job(document)
        repairs = int(document["attempts"]["content_repairs"]) + 1
        document["attempts"]["content_repairs"] = repairs
        if repairs > int(document["limits"]["max_content_repairs"]):
            document["status"] = "unprocessable"
            document["stage"] = "unprocessable"
            document["termination"] = {
                "code": "CONTENT_REPAIR_EXHAUSTED",
                "message": "Article could not pass fidelity audit within the repair limit.",
            }
            document["timestamps"]["finished_at"] = utc_now()
        else:
            if document["status"] != "content_auditing":
                raise ValueError("Content repair requires a content_auditing job")
            document["status"] = "content_generating"
            document["stage"] = "content_generating"
        document["timestamps"]["updated_at"] = utc_now()
        write_json_atomic(path, document)
    return get_automation_job(path)


def _normalize_source(source: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(source, dict):
        raise TypeError("Automation source must be a JSON object")
    platform = str(source.get("platform") or "").strip().lower()
    bvid = str(source.get("bvid") or "").strip()
    title = str(source.get("title") or "").strip()
    url = str(source.get("url") or "").strip()
    page = source.get("page", 1)
    if platform != "bilibili":
        raise ValueError("Automation currently supports only Bilibili")
    if not bvid:
        raise ValueError("Automation source BVID cannot be empty")
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        raise ValueError("Automation source page is invalid")
    if TOKEN_RE.search(url):
        raise ValueError("Automation source URL must not contain credentials")
    expected_prefix = "https://www.bilibili.com/video/"
    if not url.startswith(expected_prefix) or "?" in url:
        raise ValueError("Automation source URL must be a canonical Bilibili video URL")
    return {
        "platform": platform,
        "bvid": bvid,
        "page": page,
        "title": title,
        "url": url,
    }


def _artifact(
    job_path: Path,
    value: str,
    *,
    sha256: str | None,
    status: str | None,
) -> dict[str, Any]:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = job_path.parent / candidate
    candidate = candidate.resolve()
    try:
        relative = candidate.relative_to(job_path.parent).as_posix()
    except ValueError as error:
        raise ValueError(
            "Automation artifacts must stay under the job directory"
        ) from error
    result: dict[str, Any] = {"path": relative}
    if sha256 is not None:
        if not re.fullmatch(r"[a-f0-9]{64}", sha256):
            raise ValueError("Automation artifact SHA-256 is invalid")
        result["sha256"] = sha256
    if status is not None:
        result["status"] = status
    return result


def _safe_error_message(error: dict[str, Any]) -> str:
    message = str(
        error.get("message") or error.get("code") or "Automation error"
    ).strip()
    if len(message) > 2000:
        raise ValueError("Automation error exceeds 2000 characters")
    if TOKEN_RE.search(message):
        raise ValueError("Automation error must not contain credentials")
    return message


def _validate_job(document: Any) -> None:
    if not isinstance(document, dict):
        raise TypeError("Automation job must be a JSON object")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported automation job schema")
    if not re.fullmatch(r"auto_[a-f0-9]{16}", str(document.get("job_id") or "")):
        raise ValueError("Automation job_id is invalid")
    if document.get("status") in TERMINAL and not document.get("timestamps", {}).get(
        "finished_at"
    ):
        raise ValueError("Terminal automation job requires finished_at")
    if not isinstance(document.get("artifacts"), dict):
        raise TypeError("Automation job artifacts must be an object")


def _nonnegative_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"Automation {label} must be a non-negative integer")
    return value


def _require_job(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.is_dir():
        path = path / "job.json"
    if not path.is_file():
        raise FileNotFoundError(f"Automation job does not exist: {path}")
    return path
