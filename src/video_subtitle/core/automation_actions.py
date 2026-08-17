"""High-level deterministic actions for Watch Later automation jobs."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .automation_job import get_automation_job, transition_automation_job
from .automation_paths import resolve_job_artifact_path
from .canonical import (
    get_canonical_subtitle,
    save_canonical_subtitle,
)
from .util import read_json


def begin_automation_evidence(job_path: Path) -> dict[str, Any]:
    """Start evidence collection, idempotently preserving an active stage."""
    job = get_automation_job(job_path)
    if job["status"] == "evidence_running":
        return {**job, "reused_existing_stage": True}
    if job["status"] != "queued":
        raise ValueError("Automation evidence can begin only from queued")
    result = transition_automation_job(Path(job["job_path"]), status="evidence_running")
    return {**result, "reused_existing_stage": False}


def complete_automation_evidence(
    job_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    """Validate and bind one completed subtitle manifest to its automation job."""
    job = get_automation_job(job_path)
    manifest_path = resolve_job_artifact_path(
        Path(job["job_path"]),
        manifest_path,
        must_exist=True,
        label="Subtitle manifest",
    )
    manifest = _validate_manifest_for_job(job, manifest_path)
    manifest_sha256 = _sha256_file(manifest_path)
    if job["status"] == "evidence_ready":
        existing = job.get("artifacts", {}).get("subtitle_manifest") or {}
        if (
            existing.get("path")
            != manifest_path.relative_to(Path(job["job_path"]).parent).as_posix()
            or existing.get("sha256") != manifest_sha256
        ):
            raise ValueError("Automation evidence is already bound to another manifest")
        return {**job, "reused_existing_stage": True}
    if job["status"] != "evidence_running":
        raise ValueError(
            "Automation evidence completion requires an evidence_running job"
        )
    result = transition_automation_job(
        Path(job["job_path"]),
        status="evidence_ready",
        artifact_kind="subtitle_manifest",
        artifact_path=str(manifest_path),
        artifact_sha256=manifest_sha256,
        artifact_status=str(manifest["status"]),
    )
    return {**result, "reused_existing_stage": False}


def save_automation_canonical_subtitle(
    job_path: Path,
    manifest_path: Path,
    document: dict[str, Any],
) -> dict[str, Any]:
    """Save the Agent-authored canonical subtitle and close its state transition."""
    job = get_automation_job(job_path)
    manifest_path = resolve_job_artifact_path(
        Path(job["job_path"]),
        manifest_path,
        must_exist=True,
        label="Subtitle manifest",
    )
    metadata = _require_bound_manifest_path(job, manifest_path)
    if job["status"] == "canonical_ready":
        canonical = get_canonical_subtitle(manifest_path)
        expected_hash = str(metadata.get("sha256") or "")
        if expected_hash and canonical.get("manifest_sha256") != expected_hash:
            raise ValueError("Canonical subtitle is not pinned to the bound manifest")
        return {
            "job": job,
            "canonical": canonical,
            "reused_existing_stage": True,
        }
    _require_bound_manifest_hash(metadata, manifest_path)
    if job["status"] == "evidence_ready":
        job = transition_automation_job(Path(job["job_path"]), status="canonicalizing")
    elif job["status"] != "canonicalizing":
        raise ValueError(
            "Automation canonical subtitle requires evidence_ready or canonicalizing"
        )

    canonical = save_canonical_subtitle(manifest_path, document=document)
    report_path = Path(str(canonical.get("artifacts", {}).get("report") or ""))
    report_sha256 = _sha256_file(report_path)
    if canonical["status"] == "usable":
        updated = transition_automation_job(
            Path(job["job_path"]),
            status="canonical_ready",
            artifact_kind="canonical_subtitle",
            artifact_path=str(report_path),
            artifact_sha256=report_sha256,
            artifact_status="usable",
        )
    else:
        termination = canonical.get("termination") or {}
        updated = transition_automation_job(
            Path(job["job_path"]),
            status="unprocessable",
            artifact_kind="canonical_subtitle",
            artifact_path=str(report_path),
            artifact_sha256=report_sha256,
            artifact_status="unusable",
            error={
                "code": str(termination.get("code") or "CANONICAL_UNUSABLE"),
                "message": str(
                    termination.get("message")
                    or "Canonical subtitle evidence is not usable."
                ),
            },
        )
    return {
        "job": updated,
        "canonical": canonical,
        "reused_existing_stage": False,
    }


def _validate_manifest_for_job(
    job: dict[str, Any], manifest_path: Path
) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    if manifest.get("schema_version") != "video-subtitle/v1":
        raise ValueError("Unsupported subtitle manifest schema")
    if manifest.get("status") != "completed":
        raise ValueError("Automation evidence requires a completed subtitle manifest")
    video = manifest.get("video") or {}
    request = manifest.get("request") or {}
    expected = job["source"]
    actual_bvid = str(video.get("bvid") or "").strip()
    if actual_bvid != expected["bvid"]:
        raise ValueError("Subtitle manifest BVID does not match the automation job")
    raw_page = video.get("page", request.get("page", 1))
    try:
        actual_page = int(raw_page)
    except (TypeError, ValueError) as error:
        raise ValueError("Subtitle manifest page is invalid") from error
    if actual_page != int(expected["page"]):
        raise ValueError("Subtitle manifest page does not match the automation job")
    return manifest


def _require_bound_manifest_path(
    job: dict[str, Any], manifest_path: Path
) -> dict[str, Any]:
    metadata = job.get("artifacts", {}).get("subtitle_manifest")
    if not isinstance(metadata, dict):
        raise TypeError("Automation job has no bound subtitle manifest")
    expected_path = resolve_job_artifact_path(
        Path(job["job_path"]),
        str(metadata.get("path") or ""),
        must_exist=True,
        label="Bound subtitle manifest",
    )
    if expected_path != manifest_path:
        raise ValueError("Canonical subtitle targets a different subtitle manifest")
    return metadata


def _require_bound_manifest_hash(metadata: dict[str, Any], manifest_path: Path) -> None:
    expected_hash = str(metadata.get("sha256") or "")
    if expected_hash and _sha256_file(manifest_path) != expected_hash:
        raise ValueError("Bound subtitle manifest changed before canonicalization")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
