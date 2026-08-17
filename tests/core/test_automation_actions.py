from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from video_subtitle.core.automation_actions import (
    begin_automation_evidence,
    complete_automation_evidence,
    save_automation_canonical_subtitle,
)
from video_subtitle.core.automation_job import (
    get_automation_job,
    initialize_automation_job,
    transition_automation_job,
)
from video_subtitle.core.evidence import list_subtitle_evidence_for_manifest
from video_subtitle.core.srt import Cue, write_srt
from video_subtitle.core.util import write_json_atomic


def _profile() -> dict:
    return {
        "profile_id": "profile-actions",
        "version": 1,
        "retry_policy": {
            "max_technical_attempts": 2,
            "max_content_repairs": 1,
            "backoff_seconds": 1,
        },
    }


def _source(*, bvid: str = "BV1actions", page: int = 1) -> dict:
    return {
        "platform": "bilibili",
        "bvid": bvid,
        "page": page,
        "title": "Actions",
        "url": f"https://www.bilibili.com/video/{bvid}/",
    }


def _job_with_manifest(tmp_path: Path) -> tuple[Path, Path, Path]:
    job = initialize_automation_job(tmp_path, _source(), _profile())
    job_path = Path(job["job_path"])
    transition_automation_job(job_path, status="queued")
    evidence_dir = job_path.parent / "evidence"
    evidence_dir.mkdir()
    subtitle = evidence_dir / "subtitle.platform.srt"
    write_srt(subtitle, [Cue(0, 1000, "自动化字幕")])
    manifest = evidence_dir / "manifest.json"
    write_json_atomic(
        manifest,
        {
            "schema_version": "video-subtitle/v1",
            "job_id": "sub_actions",
            "status": "completed",
            "request": {
                "url": "https://www.bilibili.com/video/BV1actions/",
                "page": 1,
            },
            "video": {
                "bvid": "BV1actions",
                "page": 1,
                "duration_seconds": 1,
            },
            "selected_source": {"kind": "platform_subtitle"},
            "sources": [
                {
                    "kind": "platform_subtitle",
                    "artifact_source": "platform_subtitle:bilibili",
                    "cue_count": 1,
                }
            ],
            "review": None,
            "artifacts": [
                {
                    "kind": "subtitle_srt",
                    "source": "platform_subtitle:bilibili",
                    "path": str(subtitle),
                    "owned_by_job": True,
                    "selected": True,
                    "cue_count": 1,
                }
            ],
        },
    )
    return job_path, manifest, subtitle


def _canonical_document(manifest: Path, *, status: str = "usable") -> dict:
    evidence = list_subtitle_evidence_for_manifest(manifest)["evidence"][0]
    document = {
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "status": status,
        "evidence": [
            {
                "evidence_id": evidence["evidence_id"],
                "sha256": hashlib.sha256(
                    Path(str(evidence["path"])).read_bytes()
                ).hexdigest(),
                "role": "primary",
            }
        ],
        "cues": [],
        "decisions": [],
        "unresolved": [],
        "termination": None,
    }
    if status == "usable":
        document["cues"] = [
            {
                "start_ms": 0,
                "end_ms": 1000,
                "text": "自动化字幕",
                "evidence_refs": [f"{evidence['evidence_id']}-cue-00001"],
            }
        ]
    else:
        document["termination"] = {
            "code": "EVIDENCE_INSUFFICIENT",
            "message": "证据无法形成可靠字幕",
        }
    return document


def test_evidence_actions_validate_and_bind_completed_manifest(tmp_path: Path) -> None:
    job_path, manifest, _subtitle = _job_with_manifest(tmp_path)

    started = begin_automation_evidence(job_path)
    assert started["status"] == "evidence_running"
    assert begin_automation_evidence(job_path)["status"] == "evidence_running"

    completed = complete_automation_evidence(job_path, manifest)
    assert completed["status"] == "evidence_ready"
    assert (
        completed["artifacts"]["subtitle_manifest"]["path"] == "evidence/manifest.json"
    )
    assert (
        completed["artifacts"]["subtitle_manifest"]["sha256"]
        == hashlib.sha256(manifest.read_bytes()).hexdigest()
    )


def test_evidence_completion_rejects_mismatched_video(tmp_path: Path) -> None:
    job_path, manifest, _subtitle = _job_with_manifest(tmp_path)
    document = __import__("json").loads(manifest.read_text(encoding="utf-8"))
    document["video"]["bvid"] = "BV1different"
    write_json_atomic(manifest, document)
    begin_automation_evidence(job_path)

    with pytest.raises(ValueError, match="BVID"):
        complete_automation_evidence(job_path, manifest)

    assert get_automation_job(job_path)["status"] == "evidence_running"


def test_usable_canonical_action_closes_state_transition(tmp_path: Path) -> None:
    job_path, manifest, _subtitle = _job_with_manifest(tmp_path)
    begin_automation_evidence(job_path)
    complete_automation_evidence(job_path, manifest)

    result = save_automation_canonical_subtitle(
        job_path,
        manifest,
        _canonical_document(manifest),
    )

    assert result["job"]["status"] == "canonical_ready"
    assert result["canonical"]["status"] == "usable"
    assert result["job"]["artifacts"]["canonical_subtitle"]["path"] == (
        "evidence/subtitle.canonical.report.json"
    )
    assert (
        save_automation_canonical_subtitle(
            job_path,
            manifest,
            _canonical_document(manifest),
        )["reused_existing_stage"]
        is True
    )


def test_unusable_canonical_action_terminates_without_content(tmp_path: Path) -> None:
    job_path, manifest, _subtitle = _job_with_manifest(tmp_path)
    begin_automation_evidence(job_path)
    complete_automation_evidence(job_path, manifest)

    result = save_automation_canonical_subtitle(
        job_path,
        manifest,
        _canonical_document(manifest, status="unusable"),
    )

    assert result["job"]["status"] == "unprocessable"
    assert result["job"]["termination"]["code"] == "EVIDENCE_INSUFFICIENT"
    assert result["job"]["artifacts"]["canonical_subtitle"]["status"] == "unusable"
