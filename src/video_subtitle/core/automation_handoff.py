"""Idempotent binding between automation jobs and verified WeChat drafts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .automation_job import get_automation_job, transition_automation_job
from .automation_profile import (
    read_automation_profile,
    read_draft_authorization,
    require_active_draft_authorization,
)
from .handoff import validate_wechat_draft_receipt
from .util import read_json, utc_now, write_json_atomic

SCHEMA_VERSION = "video-automation/handoff-binding-v1"


def prepare_automation_handoff(
    *, job_path: Path, profile_path: Path, authorization_path: Path
) -> dict[str, Any]:
    job = get_automation_job(job_path)
    existing = get_existing_handoff_binding(job_path)
    if existing is not None:
        return {
            "schema_version": "video-automation/handoff-preparation-v1",
            "job_id": job["job_id"],
            "already_completed": True,
            "binding": existing,
        }
    if job["status"] not in {"rendering", "handoff_running"}:
        raise ValueError(
            "Automation handoff requires a rendering or handoff_running job"
        )
    profile = read_automation_profile(profile_path)
    authorization = read_draft_authorization(authorization_path)
    if (
        job["profile_id"] != profile["profile_id"]
        or job["profile_version"] != profile["version"]
    ):
        raise ValueError("Automation job and profile version do not match")
    require_active_draft_authorization(profile, authorization)
    return {
        "schema_version": "video-automation/handoff-preparation-v1",
        "job_id": job["job_id"],
        "already_completed": False,
        "authorization_id": authorization["authorization_id"],
        "browser_profile_alias": authorization["browser_profile_alias"],
        "allowed_actions": ["save_wechat_draft"],
        "prohibited_actions": authorization["prohibited_actions"],
    }


def bind_automation_handoff_receipt(
    *,
    job_path: Path,
    authorization_path: Path,
    receipt_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    job = get_automation_job(job_path)
    existing = get_existing_handoff_binding(job_path)
    if existing is not None:
        return existing
    if job["status"] != "handoff_running":
        raise ValueError("Automation receipt binding requires a handoff_running job")
    authorization = read_draft_authorization(authorization_path)
    if authorization["status"] != "active":
        raise ValueError("Draft authorization is not active")
    if job["profile_id"] not in authorization["profile_ids"]:
        raise ValueError("Draft authorization does not cover this automation profile")
    if authorization["allowed_actions"] != ["save_wechat_draft"]:
        raise ValueError("Automation authorization may only save a draft")

    job_path = Path(job["job_path"])
    receipt_path = _require_within_file(job_path.parent, receipt_path, "Draft receipt")
    receipt = read_json(receipt_path)
    if receipt.get("published") is not False:
        raise ValueError("Automation draft receipt contains a forbidden publish state")
    if receipt.get("publish_actions_performed") != []:
        raise ValueError("Automation draft receipt contains forbidden publish actions")
    appmsgid = str(receipt.get("appmsgid") or "").strip()
    if not appmsgid.isdigit():
        raise ValueError("Automation draft receipt requires a stable numeric appmsgid")

    content_binding = _job_artifact(job_path, job, "content_binding")
    content = read_json(content_binding)
    project_path = _require_within_file(
        job_path.parent,
        job_path.parent / str(content.get("project_path") or ""),
        "Content project",
    )
    validation = validate_wechat_draft_receipt(
        receipt_path,
        project_path=project_path,
    )
    if validation.get("valid") is not True:
        errors = validation.get("errors") or []
        raise ValueError(f"WeChat draft receipt is invalid: {errors}")
    project_id = str(content.get("project_id") or "")
    if receipt.get("project_id") != project_id:
        raise ValueError("Draft receipt targets a different content project")

    output_path = output_path.expanduser()
    if not output_path.is_absolute():
        output_path = job_path.parent / output_path
    output_path = output_path.resolve()
    try:
        output_path.relative_to(job_path.parent)
    except ValueError as error:
        raise ValueError(
            "Automation handoff binding must stay under the job directory"
        ) from error
    receipt_sha256 = _sha256_file(receipt_path)
    identity = {
        "job_id": job["job_id"],
        "authorization_id": authorization["authorization_id"],
        "receipt_sha256": receipt_sha256,
        "appmsgid": appmsgid,
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    binding = {
        "schema_version": SCHEMA_VERSION,
        "binding_id": f"binding_{digest[:16]}",
        "job_id": job["job_id"],
        "authorization_id": authorization["authorization_id"],
        "project_id": project_id,
        "deliverable_id": str(receipt.get("deliverable_id") or ""),
        "fidelity_audit_id": str(receipt.get("fidelity_audit_id") or ""),
        "receipt_path": receipt_path.relative_to(job_path.parent).as_posix(),
        "receipt_sha256": receipt_sha256,
        "appmsgid": appmsgid,
        "created_at": utc_now(),
    }
    write_json_atomic(output_path, binding)
    transition_automation_job(
        job_path,
        status="completed",
        artifact_kind="handoff_binding",
        artifact_path=str(output_path),
        artifact_sha256=_sha256_file(output_path),
        artifact_status="valid",
    )
    return binding


def get_existing_handoff_binding(job_path: Path) -> dict[str, Any] | None:
    job = get_automation_job(job_path)
    metadata = job.get("artifacts", {}).get("handoff_binding")
    if not isinstance(metadata, dict):
        return None
    path = Path(job["job_path"]).parent / str(metadata.get("path") or "")
    path = _require_within_file(Path(job["job_path"]).parent, path, "Handoff binding")
    expected = metadata.get("sha256")
    if expected and _sha256_file(path) != expected:
        raise ValueError("Automation handoff binding hash changed")
    binding = read_json(path)
    if binding.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported automation handoff binding schema")
    if binding.get("job_id") != job["job_id"]:
        raise ValueError("Automation handoff binding targets a different job")
    return binding


def _job_artifact(job_path: Path, job: dict[str, Any], kind: str) -> Path:
    metadata = job.get("artifacts", {}).get(kind)
    if not isinstance(metadata, dict):
        raise TypeError(f"Automation job artifact {kind} must be an object")
    return _require_within_file(
        job_path.parent,
        job_path.parent / str(metadata.get("path") or ""),
        kind,
    )


def _require_within_file(root: Path, value: Path, label: str) -> Path:
    root = root.resolve()
    value = value.expanduser().resolve()
    try:
        value.relative_to(root)
    except ValueError as error:
        raise ValueError(
            f"{label} must stay under the automation job directory"
        ) from error
    if not value.is_file():
        raise FileNotFoundError(f"{label} does not exist: {value}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
