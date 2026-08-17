"""Automation-specific content-project initialization and audit recording."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .automation_job import get_automation_job, transition_automation_job
from .automation_paths import resolve_job_artifact_path
from .automation_profile import read_automation_profile
from .canonical import require_usable_canonical_subtitle
from .content import initialize_content_project
from .util import read_json, utc_now, write_json_atomic


def initialize_automated_content_project(
    *,
    manifest_path: Path,
    profile_path: Path,
    job_path: Path,
) -> dict[str, Any]:
    job = get_automation_job(job_path)
    if job["status"] != "canonical_ready":
        raise ValueError("Automated content requires a canonical_ready job")
    canonical = require_usable_canonical_subtitle(manifest_path)
    profile = read_automation_profile(profile_path)
    if (
        job["profile_id"] != profile["profile_id"]
        or job["profile_version"] != profile["version"]
    ):
        raise ValueError("Automation job and profile version do not match")
    content = profile["content"]
    project = initialize_content_project(
        manifest_path,
        objective=str(content["objective"]),
        audience=str(content.get("audience") or ""),
        output_language=str(content["output_language"]),
    )
    job_path = Path(job["job_path"])
    project_path = Path(project["project_path"])
    binding_path = job_path.parent / "automation-content-binding.json"
    try:
        relative_project = project_path.relative_to(job_path.parent).as_posix()
    except ValueError as error:
        raise ValueError(
            "Automated content project must stay under its job directory"
        ) from error
    binding = {
        "schema_version": "video-automation/content-binding-v1",
        "job_id": job["job_id"],
        "profile_id": profile["profile_id"],
        "profile_version": profile["version"],
        "canonical_id": canonical["canonical_id"],
        "project_id": project["project_id"],
        "project_path": relative_project,
        "project_sha256": _sha256_file(project_path),
        "created_at": utc_now(),
    }
    write_json_atomic(binding_path, binding)
    transition_automation_job(
        job_path,
        status="content_generating",
        artifact_kind="content_binding",
        artifact_path=str(binding_path),
        artifact_sha256=_sha256_file(binding_path),
    )
    return {
        **project,
        "automation": {
            "job_id": job["job_id"],
            "profile_id": profile["profile_id"],
            "profile_version": profile["version"],
            "canonical_id": canonical["canonical_id"],
            "selected_medium": "article",
            "selection_authority": "user_selected",
            "style": content["style"],
            "image_policy": content["image_policy"],
            "binding_path": str(binding_path),
        },
    }


def record_automation_audit(*, job_path: Path, project_path: Path) -> dict[str, Any]:
    project_path = resolve_job_artifact_path(
        job_path,
        project_path,
        must_exist=True,
        label="Content project",
    )
    project = read_json(project_path)
    current_id = project.get("current", {}).get("fidelity_audit_id")
    audit = next(
        (
            item
            for item in project.get("artifacts", {}).get("fidelity_audits", [])
            if item.get("artifact_id") == current_id
        ),
        None,
    )
    if audit is None:
        raise ValueError("Automated content project has no current fidelity audit")
    status = str(audit.get("audit_status") or "")
    if status in {"pass", "pass_with_warnings"}:
        return transition_automation_job(
            job_path,
            status="rendering",
            artifact_kind="fidelity_audit",
            artifact_path=str(Path(project_path).parent / str(audit["path"])),
            artifact_sha256=str(audit["sha256"]),
            artifact_status=status,
        )
    from .automation_job import record_content_repair

    return record_content_repair(job_path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
