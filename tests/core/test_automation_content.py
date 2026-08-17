from __future__ import annotations

from pathlib import Path

import pytest

from video_subtitle.core.automation_content import (
    initialize_automated_content_project,
    record_automation_audit,
)
from video_subtitle.core.automation_job import (
    initialize_automation_job,
    transition_automation_job,
)
from video_subtitle.core.automation_profile import save_automation_profile
from video_subtitle.core.canonical import save_canonical_subtitle
from video_subtitle.core.evidence import list_subtitle_evidence_for_manifest
from video_subtitle.core.srt import Cue, write_srt
from video_subtitle.core.util import write_json_atomic


def _profile() -> dict:
    return {
        "enabled": True,
        "source": {
            "kind": "bilibili_watch_later",
            "account_profile_alias": "bilibili-main",
            "poll_interval_seconds": 900,
        },
        "content": {
            "medium": "wechat_article",
            "objective": "faithful_information_transfer",
            "audience": "公众号读者",
            "output_language": "zh-CN",
            "style": "restrained-editorial",
            "image_policy": "source_video_only",
        },
        "evidence_policy": {
            "require_hard_subtitle_assessment": True,
            "allow_platform_subtitle": True,
            "allow_hard_ocr": True,
            "allow_audio_asr": True,
        },
        "retry_policy": {
            "max_technical_attempts": 2,
            "max_content_repairs": 1,
            "backoff_seconds": 1,
        },
        "draft_authorization_id": "auth-watch-later",
        "prohibited_actions": [
            "publish",
            "mass_send",
            "schedule",
            "originality",
            "account_management",
        ],
    }


def _job_with_manifest(tmp_path: Path) -> tuple[Path, Path, Path]:
    profile_path = tmp_path / "profile.json"
    profile = save_automation_profile(profile_path, _profile())
    job = initialize_automation_job(
        tmp_path,
        {
            "platform": "bilibili",
            "bvid": "BV1auto",
            "page": 1,
            "title": "Auto",
            "url": "https://www.bilibili.com/video/BV1auto/",
        },
        profile,
    )
    job_path = Path(job["job_path"])
    subtitle_dir = job_path.parent / "subtitle"
    subtitle_dir.mkdir()
    srt = subtitle_dir / "subtitle.platform.srt"
    write_srt(srt, [Cue(0, 1000, "自动化字幕")])
    manifest = subtitle_dir / "manifest.json"
    write_json_atomic(
        manifest,
        {
            "schema_version": "video-subtitle/v1",
            "job_id": "sub_auto",
            "status": "completed",
            "video": {"bvid": "BV1auto", "duration_seconds": 1},
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
                    "path": str(srt),
                    "owned_by_job": True,
                    "selected": True,
                    "cue_count": 1,
                }
            ],
        },
    )
    return profile_path, job_path, manifest


def _make_canonical(manifest: Path) -> dict:
    import hashlib

    evidence = list_subtitle_evidence_for_manifest(manifest)["evidence"][0]
    document = {
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "status": "usable",
        "evidence": [
            {
                "evidence_id": evidence["evidence_id"],
                "sha256": hashlib.sha256(
                    Path(evidence["path"]).read_bytes()
                ).hexdigest(),
                "role": "primary",
            }
        ],
        "cues": [
            {
                "start_ms": 0,
                "end_ms": 1000,
                "text": "自动化字幕",
                "evidence_refs": ["ev-0001-cue-00001"],
            }
        ],
        "decisions": [],
        "unresolved": [],
        "termination": None,
    }
    return save_canonical_subtitle(manifest, document=document)


def test_automated_content_requires_usable_canonical(tmp_path: Path) -> None:
    profile_path, job_path, manifest = _job_with_manifest(tmp_path)
    transition_automation_job(job_path, status="queued")
    transition_automation_job(job_path, status="evidence_running")
    transition_automation_job(job_path, status="evidence_ready")
    transition_automation_job(job_path, status="canonicalizing")
    with pytest.raises(ValueError, match="canonical"):
        initialize_automated_content_project(
            manifest_path=manifest,
            profile_path=profile_path,
            job_path=job_path,
        )


def test_automated_content_uses_profile_and_canonical_evidence(tmp_path: Path) -> None:
    profile_path, job_path, manifest = _job_with_manifest(tmp_path)
    transition_automation_job(job_path, status="queued")
    transition_automation_job(job_path, status="evidence_running")
    transition_automation_job(job_path, status="evidence_ready")
    transition_automation_job(job_path, status="canonicalizing")
    canonical = _make_canonical(manifest)
    transition_automation_job(
        job_path,
        status="canonical_ready",
        artifact_kind="canonical_subtitle",
        artifact_path=canonical["artifacts"]["report"],
        artifact_status="usable",
    )
    result = initialize_automated_content_project(
        manifest_path=manifest,
        profile_path=profile_path,
        job_path=job_path,
    )
    assert result["intent"]["audience"] == "公众号读者"
    assert result["automation"]["selected_medium"] == "article"
    assert result["automation"]["selection_authority"] == "user_selected"
    assert any(
        item["source_kind"] == "canonical_subtitle"
        for item in result["source"]["evidence"]
    )


def test_record_audit_resolves_workspace_relative_project_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    project_dir = workspace / "jobs" / "auto_fixture" / "content"
    audit_dir = project_dir / "audits"
    audit_dir.mkdir(parents=True)
    audit_path = audit_dir / "audit.json"
    audit_path.write_text("{}", encoding="utf-8")
    project_path = project_dir / "project.json"
    write_json_atomic(
        project_path,
        {
            "current": {"fidelity_audit_id": "audit-001"},
            "artifacts": {
                "fidelity_audits": [
                    {
                        "artifact_id": "audit-001",
                        "audit_status": "pass",
                        "path": "audits/audit.json",
                        "sha256": "a" * 64,
                    }
                ]
            },
        },
    )
    monkeypatch.chdir(workspace)
    captured: dict = {}

    def fake_transition(_job_path: Path, **kwargs: object) -> dict:
        captured.update(kwargs)
        return captured

    monkeypatch.setattr(
        "video_subtitle.core.automation_content.transition_automation_job",
        fake_transition,
    )

    record_automation_audit(
        job_path=Path("jobs/auto_fixture/job.json"),
        project_path=project_path.relative_to(workspace),
    )

    assert Path(str(captured["artifact_path"])).is_absolute()
    assert Path(str(captured["artifact_path"])) == audit_path.resolve()
