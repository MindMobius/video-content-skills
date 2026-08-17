from __future__ import annotations

from pathlib import Path

import pytest

from video_subtitle.core.automation_job import (
    get_automation_job,
    initialize_automation_job,
    transition_automation_job,
)


def _profile() -> dict:
    return {
        "profile_id": "profile-paths",
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
        "bvid": "BV1paths",
        "page": 1,
        "title": "Paths",
        "url": "https://www.bilibili.com/video/BV1paths/",
    }


def test_workspace_relative_artifact_is_stored_relative_to_job_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    job = initialize_automation_job(Path("runtime"), _source(), _profile())
    job_path = Path(job["job_path"])
    artifact = job_path.parent / "evidence" / "manifest.json"
    artifact.parent.mkdir()
    artifact.write_text("{}", encoding="utf-8")

    workspace_relative = artifact.relative_to(tmp_path)
    transition_automation_job(job_path, status="queued")
    result = transition_automation_job(
        job_path,
        status="evidence_running",
        artifact_kind="subtitle_manifest",
        artifact_path=str(workspace_relative),
    )

    assert result["artifacts"]["subtitle_manifest"]["path"] == "evidence/manifest.json"


def test_short_relative_artifact_is_resolved_from_job_root(tmp_path: Path) -> None:
    job = initialize_automation_job(tmp_path, _source(), _profile())
    job_path = Path(job["job_path"])
    artifact = job_path.parent / "manifest.json"
    artifact.write_text("{}", encoding="utf-8")

    transition_automation_job(job_path, status="queued")
    result = transition_automation_job(
        job_path,
        status="evidence_running",
        artifact_kind="subtitle_manifest",
        artifact_path="manifest.json",
    )

    assert result["artifacts"]["subtitle_manifest"]["path"] == "manifest.json"


def test_artifact_outside_job_root_is_rejected(tmp_path: Path) -> None:
    job = initialize_automation_job(tmp_path / "store", _source(), _profile())
    job_path = Path(job["job_path"])
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")

    transition_automation_job(job_path, status="queued")
    with pytest.raises(ValueError, match="job directory"):
        transition_automation_job(
            job_path,
            status="evidence_running",
            artifact_kind="subtitle_manifest",
            artifact_path=str(outside),
        )

    assert "subtitle_manifest" not in get_automation_job(job_path)["artifacts"]
