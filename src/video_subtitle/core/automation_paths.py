"""Canonical path handling for durable automation job artifacts."""

from __future__ import annotations

from pathlib import Path


def automation_job_root(job_path: Path) -> Path:
    """Return the resolved directory that owns one automation job ledger."""
    path = Path(job_path).expanduser()
    if path.is_dir():
        path = path / "job.json"
    return path.resolve().parent


def resolve_job_artifact_path(
    job_path: Path,
    value: str | Path,
    *,
    must_exist: bool,
    label: str,
) -> Path:
    """Resolve absolute, workspace-relative, or job-relative artifact paths.

    Workspace-relative paths are accepted only when they already resolve inside the
    job directory. All other relative paths are interpreted from the job root.
    """
    root = automation_job_root(job_path)
    raw = Path(value).expanduser()
    if raw.is_absolute():
        candidate = raw.resolve()
    else:
        workspace_candidate = raw.resolve()
        if _is_within(workspace_candidate, root):
            candidate = workspace_candidate
        else:
            candidate = (root / raw).resolve()
    if not _is_within(candidate, root):
        raise ValueError(f"{label} must stay under the automation job directory")
    if must_exist and not candidate.is_file():
        raise FileNotFoundError(f"{label} does not exist: {candidate}")
    return candidate


def job_relative_artifact_path(
    job_path: Path,
    value: str | Path,
    *,
    must_exist: bool,
    label: str,
) -> str:
    """Return the canonical job-relative POSIX path for one artifact."""
    root = automation_job_root(job_path)
    path = resolve_job_artifact_path(
        job_path,
        value,
        must_exist=must_exist,
        label=label,
    )
    return path.relative_to(root).as_posix()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
