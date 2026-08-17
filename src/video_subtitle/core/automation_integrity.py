"""Integrity auditing for durable Watch Later automation stores."""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path
from typing import Any

from .automation_job import TERMINAL, get_automation_job, list_automation_jobs
from .automation_paths import automation_job_root, resolve_job_artifact_path
from .locking import exclusive_file_lock
from .util import read_json, write_json_atomic

JOB_AUDIT_SCHEMA_VERSION = "video-automation/job-integrity-v1"
STORE_AUDIT_SCHEMA_VERSION = "video-automation/store-integrity-v1"


def audit_automation_job(
    job_path: Path,
    *,
    repair_paths: bool = False,
) -> dict[str, Any]:
    """Audit one job ledger, its artifacts, and any completed draft receipt."""
    repairs = _repair_artifact_paths(job_path) if repair_paths else []
    job = get_automation_job(job_path)
    artifact_reports = [
        _audit_artifact(job, kind, metadata)
        for kind, metadata in sorted(job.get("artifacts", {}).items())
    ]
    errors: list[str] = []
    warnings: list[str] = []
    for artifact in artifact_reports:
        kind = artifact["kind"]
        if artifact["path_status"] == "outside_job":
            errors.append(f"ARTIFACT_OUTSIDE_JOB:{kind}")
        elif artifact["exists"] is False:
            errors.append(f"ARTIFACT_MISSING:{kind}")
        if artifact["hash_status"] == "mismatch":
            errors.append(f"ARTIFACT_HASH_MISMATCH:{kind}")
        elif artifact["hash_status"] == "not_recorded":
            warnings.append(f"ARTIFACT_HASH_NOT_RECORDED:{kind}")
        if artifact["noncanonical"]:
            errors.append(f"ARTIFACT_PATH_NONCANONICAL:{kind}")

    draft = None
    if job["status"] == "completed":
        if not isinstance(job.get("artifacts", {}).get("handoff_binding"), dict):
            errors.append("COMPLETED_WITHOUT_HANDOFF_BINDING")
        else:
            draft, handoff_errors = _audit_completed_handoff(job)
            errors.extend(handoff_errors)

    return {
        "schema_version": JOB_AUDIT_SCHEMA_VERSION,
        "job_id": job["job_id"],
        "job_path": job["job_path"],
        "source": job["source"],
        "status": job["status"],
        "terminal": job["status"] in TERMINAL,
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "artifacts": artifact_reports,
        "draft": draft,
        "repairs": repairs,
    }


def audit_automation_store(
    store: Path,
    *,
    repair_paths: bool = False,
) -> dict[str, Any]:
    """Audit every job and summarize terminal outcomes and saved draft identity."""
    jobs = list_automation_jobs(store)["jobs"]
    reports = [
        audit_automation_job(Path(job["job_path"]), repair_paths=repair_paths)
        for job in jobs
    ]
    drafts = [report["draft"] for report in reports if report.get("draft")]
    counts = Counter(str(job["status"]) for job in jobs)
    appmsgid_counts = Counter(str(item["appmsgid"]) for item in drafts)
    duplicate_appmsgids = sorted(
        appmsgid for appmsgid, count in appmsgid_counts.items() if count > 1
    )
    active_jobs = [job for job in jobs if job["status"] not in TERMINAL]
    valid = all(report["valid"] for report in reports) and not duplicate_appmsgids
    return {
        "schema_version": STORE_AUDIT_SCHEMA_VERSION,
        "store": str(Path(store).expanduser().resolve()),
        "valid": valid,
        "all_jobs_terminal": not active_jobs,
        "complete": valid and not active_jobs,
        "summary": {
            "job_count": len(jobs),
            "by_status": dict(sorted(counts.items())),
            "valid_jobs": sum(1 for report in reports if report["valid"]),
            "invalid_jobs": sum(1 for report in reports if not report["valid"]),
            "draft_count": len(drafts),
        },
        "duplicate_appmsgids": duplicate_appmsgids,
        "drafts": drafts,
        "jobs": reports,
        "repairs": [
            {"job_id": report["job_id"], **repair}
            for report in reports
            for repair in report["repairs"]
        ],
    }


def _audit_artifact(job: dict[str, Any], kind: str, metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {
            "kind": kind,
            "path": None,
            "resolved_path": None,
            "path_status": "invalid_metadata",
            "exists": False,
            "sha256": None,
            "expected_sha256": None,
            "hash_status": "missing",
            "noncanonical": False,
            "repairable": False,
            "canonical_path": None,
        }
    raw_path = str(metadata.get("path") or "")
    expected_sha256 = str(metadata.get("sha256") or "") or None
    try:
        path = resolve_job_artifact_path(
            Path(job["job_path"]),
            raw_path,
            must_exist=False,
            label=f"Automation artifact {kind}",
        )
        path_status = "inside_job"
    except ValueError:
        path = None
        path_status = "outside_job"
    exists = path is not None and path.is_file()
    actual_sha256 = _sha256_file(path) if exists and path is not None else None
    if not exists:
        hash_status = "missing"
    elif expected_sha256 is None:
        hash_status = "not_recorded"
    elif actual_sha256 == expected_sha256:
        hash_status = "match"
    elif _is_historical_manifest_pin(job, kind, expected_sha256, path):
        hash_status = "historical_pin"
    else:
        hash_status = "mismatch"
    canonical = _legacy_canonical_candidate(job, raw_path, expected_sha256)
    noncanonical = canonical is not None
    return {
        "kind": kind,
        "path": raw_path,
        "resolved_path": str(path) if path is not None else None,
        "path_status": path_status,
        "exists": exists,
        "sha256": actual_sha256,
        "expected_sha256": expected_sha256,
        "hash_status": hash_status,
        "noncanonical": noncanonical,
        "repairable": noncanonical,
        "canonical_path": (
            canonical.relative_to(automation_job_root(Path(job["job_path"]))).as_posix()
            if canonical is not None
            else None
        ),
    }


def _audit_completed_handoff(
    job: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    metadata = job["artifacts"]["handoff_binding"]
    try:
        binding_path = resolve_job_artifact_path(
            Path(job["job_path"]),
            str(metadata.get("path") or ""),
            must_exist=True,
            label="Handoff binding",
        )
    except (ValueError, FileNotFoundError):
        return None, ["HANDOFF_BINDING_MISSING"]
    binding = read_json(binding_path)
    if binding.get("schema_version") != "video-automation/handoff-binding-v1":
        errors.append("HANDOFF_BINDING_SCHEMA_INVALID")
    if binding.get("job_id") != job["job_id"]:
        errors.append("HANDOFF_BINDING_JOB_MISMATCH")
    appmsgid = str(binding.get("appmsgid") or "").strip()
    if not appmsgid.isdigit():
        errors.append("HANDOFF_APPMSGID_INVALID")
    try:
        receipt_path = resolve_job_artifact_path(
            Path(job["job_path"]),
            str(binding.get("receipt_path") or ""),
            must_exist=True,
            label="Draft receipt",
        )
    except (ValueError, FileNotFoundError):
        errors.append("HANDOFF_RECEIPT_MISSING")
        return None, errors
    receipt_sha256 = _sha256_file(receipt_path)
    if receipt_sha256 != str(binding.get("receipt_sha256") or ""):
        errors.append("HANDOFF_RECEIPT_HASH_MISMATCH")
    receipt = read_json(receipt_path)
    if receipt.get("published") is not False:
        errors.append("HANDOFF_RECEIPT_PUBLISHED")
    if receipt.get("publish_actions_performed") != []:
        errors.append("HANDOFF_RECEIPT_PUBLISH_ACTIONS")
    if str(receipt.get("appmsgid") or "") != appmsgid:
        errors.append("HANDOFF_RECEIPT_APPMSGID_MISMATCH")
    if errors:
        return None, errors
    return (
        {
            "job_id": job["job_id"],
            "bvid": job["source"]["bvid"],
            "page": job["source"]["page"],
            "title": job["source"]["title"],
            "appmsgid": appmsgid,
            "binding_path": str(binding_path),
            "receipt_path": str(receipt_path),
            "published": False,
        },
        [],
    )


def _repair_artifact_paths(job_path: Path) -> list[dict[str, str]]:
    job_path = Path(job_path).expanduser().resolve()
    repairs: list[dict[str, str]] = []
    with exclusive_file_lock(job_path):
        document = read_json(job_path)
        for kind, metadata in sorted(document.get("artifacts", {}).items()):
            if not isinstance(metadata, dict):
                continue
            old_path = str(metadata.get("path") or "")
            expected_sha256 = str(metadata.get("sha256") or "") or None
            candidate = _legacy_canonical_candidate(
                {**document, "job_path": str(job_path)},
                old_path,
                expected_sha256,
            )
            if candidate is None:
                continue
            new_path = candidate.relative_to(job_path.parent).as_posix()
            metadata["path"] = new_path
            repairs.append(
                {
                    "kind": kind,
                    "old_path": old_path,
                    "new_path": new_path,
                }
            )
        if repairs:
            write_json_atomic(job_path, document)
    return repairs


def _legacy_canonical_candidate(
    job: dict[str, Any], raw_path: str, expected_sha256: str | None
) -> Path | None:
    if not raw_path or expected_sha256 is None:
        return None
    parts = list(Path(raw_path).parts)
    indices = [index for index, part in enumerate(parts) if part == job["job_id"]]
    if not indices:
        return None
    suffix = parts[indices[-1] + 1 :]
    if not suffix:
        return None
    root = automation_job_root(Path(job["job_path"]))
    candidate = (root / Path(*suffix)).resolve()
    if not candidate.is_file() or _sha256_file(candidate) != expected_sha256:
        return None
    canonical_path = candidate.relative_to(root).as_posix()
    if canonical_path == Path(raw_path).as_posix():
        return None
    return candidate


def _is_historical_manifest_pin(
    job: dict[str, Any],
    kind: str,
    expected_sha256: str,
    manifest_path: Path | None,
) -> bool:
    if kind != "subtitle_manifest" or manifest_path is None:
        return False
    canonical_metadata = job.get("artifacts", {}).get("canonical_subtitle")
    if not isinstance(canonical_metadata, dict):
        return False
    try:
        report_path = resolve_job_artifact_path(
            Path(job["job_path"]),
            str(canonical_metadata.get("path") or ""),
            must_exist=True,
            label="Canonical subtitle report",
        )
    except (ValueError, FileNotFoundError):
        return False
    report = read_json(report_path)
    if report.get("manifest_sha256") != expected_sha256:
        return False
    manifest = read_json(manifest_path)
    current = manifest.get("canonical_subtitle") or {}
    return current.get("canonical_id") == report.get("canonical_id") and current.get(
        "report_sha256"
    ) == _sha256_file(report_path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
