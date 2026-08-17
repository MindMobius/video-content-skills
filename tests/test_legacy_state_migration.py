from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.migrate_legacy_state import (
    apply_migration,
    plan_migration,
    verify_migration,
)
from video_content.automation import watch_later_scan
from video_content.store import Store

ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _build_source(root: Path, *, published: bool = False) -> list[dict[str, Any]]:
    root.mkdir(parents=True)
    runtime = root / "runtimes" / "tool.exe"
    runtime.parent.mkdir(parents=True)
    runtime.write_bytes(b"tool")
    model = root / "runtimes" / "model"
    model.mkdir()
    cache = root / "subtitle-home" / "cache" / "media"
    cache_media = cache / "bilibili" / "fixture" / "video.mp4"
    cache_media.parent.mkdir(parents=True)
    cache_media.write_bytes(b"authorized cached video")
    _write_json(
        cache_media.parent / "download-cache.json",
        {
            "cache_key": "fixture",
            "media_file": cache_media.name,
            "actual_bytes": cache_media.stat().st_size,
        },
    )
    (root / "preserved" / "notes.srt").parent.mkdir(parents=True)
    (root / "preserved" / "notes.srt").write_text("evidence\n", encoding="utf-8")
    _write_json(
        root / "config.json",
        {
            "schema_version": "video-" + "subtitle/config-v1",
            "values": {
                "home": str(root / "subtitle-home"),
                "download_cache": str(cache),
                "videocr": str(runtime),
                "qwen_asr_model": str(model),
                "opencli_profile": "fixture-browser",
                "download_retries": 2,
                "download_retry_backoff": 2.0,
                "media_execution": "serial",
            },
        },
    )
    entries = [
        {
            "bvid": "BV1fixtureA",
            "page": 1,
            "title": "Fixture A",
            "url": "https://www.bilibili.com/video/BV1fixtureA/",
            "position": 1,
        },
        {
            "bvid": "BV1fixtureB",
            "page": 2,
            "title": "Fixture B",
            "url": "https://www.bilibili.com/video/BV1fixtureB/",
            "position": 2,
        },
    ]
    _write_json(
        root
        / "automation-backfill"
        / "automation"
        / "profile"
        / "watch-later-latest.json",
        {
            "schema_version": "video-" + "automation/watch-later-snapshot-v1",
            "profile_id": "old-profile",
            "account_profile_alias": "fixture-browser",
            "captured_at": "2026-08-16T12:00:00Z",
            "entries": entries,
            "new_entries": entries,
        },
    )
    for index, entry in enumerate(entries, start=1):
        job_dir = root / "automation-backfill" / "jobs" / f"old-job-{index}"
        project = job_dir / "evidence" / "content" / "project.json"
        project.parent.mkdir(parents=True)
        project.write_text(f"project {index}\n", encoding="utf-8")
        receipt = job_dir / "evidence" / "content" / "wechat" / "receipt.json"
        _write_json(
            receipt,
            {
                "schema_version": "video-content/wechat-draft-receipt-v1",
                "appmsgid": str(100000000 + index),
                "published": published,
                "publish_actions_performed": [],
                "status": "draft_created",
                "body_images": {
                    "intended": index + 1,
                    "visible_loaded": index + 1,
                    "wechat_hosted": index + 1,
                    "non_wechat_hosted": 0,
                    "local_path_markers_remaining": 0,
                },
                "save": {"saved": True, "saved_page_read_back": True},
            },
        )
        content_binding = job_dir / "automation-content-binding.json"
        _write_json(
            content_binding,
            {
                "project_path": project.relative_to(job_dir).as_posix(),
                "project_sha256": _sha256(project),
            },
        )
        handoff_binding = job_dir / "handoff-binding.json"
        _write_json(
            handoff_binding,
            {
                "receipt_path": receipt.relative_to(job_dir).as_posix(),
                "receipt_sha256": _sha256(receipt),
                "appmsgid": str(100000000 + index),
            },
        )
        _write_json(
            job_dir / "job.json",
            {
                "schema_version": "video-" + "automation/job-v1",
                "job_id": f"old-job-{index}",
                "profile_id": "old-profile",
                "idempotency_key": f"old-{index}",
                "source": {"platform": "bilibili", **entry},
                "stage": "completed",
                "status": "completed",
                "timestamps": {
                    "created_at": f"2026-08-16T12:0{index}:00Z",
                    "updated_at": f"2026-08-16T13:0{index}:00Z",
                    "finished_at": f"2026-08-16T13:0{index}:00Z",
                },
                "artifacts": {
                    "content_binding": {
                        "path": content_binding.relative_to(job_dir).as_posix(),
                        "sha256": _sha256(content_binding),
                    },
                    "handoff_binding": {
                        "path": handoff_binding.relative_to(job_dir).as_posix(),
                        "sha256": _sha256(handoff_binding),
                    },
                },
            },
        )
    return entries


class _WatchLaterFixture:
    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self.entries = entries

    def list_entries(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        return self.entries[:limit] if limit else self.entries


def test_plan_is_a_non_mutating_integrity_check(tmp_path: Path) -> None:
    source = tmp_path / "source-state"
    archive = tmp_path / "archive" / "state-2026-08-17"
    target = tmp_path / "new-state"
    _build_source(source)

    plan = plan_migration(source, archive, target, expected_completed=2)

    assert plan["schema_version"] == "video-content/state-migration-plan-v1"
    assert plan["ready"] is True
    assert plan["source_inventory"]["files"] >= 12
    assert plan["validated"] == {
        "completed_jobs": 2,
        "draft_receipts": 2,
        "published_false": 2,
        "unique_appmsgids": 2,
        "wechat_hosted_images": 5,
    }
    assert plan["profile"]["account_profile_alias"] == "fixture-browser"
    assert len(plan["sources"]) == 2
    assert source.is_dir()
    assert not archive.exists()
    assert not target.exists()


def test_plan_reports_stale_noncritical_references_without_losing_data(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source-state"
    archive = tmp_path / "archive"
    target = tmp_path / "target"
    _build_source(source)
    for job_path in source.rglob("job.json"):
        job = json.loads(job_path.read_text(encoding="utf-8"))
        manifest = job_path.parent / "evidence" / "manifest.json"
        manifest.write_text("post-processed manifest\n", encoding="utf-8")
        job["artifacts"]["subtitle_manifest"] = {
            "path": manifest.relative_to(job_path.parent).as_posix(),
            "sha256": "0" * 64,
        }
        _write_json(job_path, job)

    plan = plan_migration(source, archive, target, expected_completed=2)

    assert plan["ready"] is True
    assert plan["validated"]["noncritical_reference_warnings"] == 2
    assert len(plan["warnings"]) == 2
    assert {item["kind"] for item in plan["warnings"]} == {"subtitle_manifest"}


def test_apply_moves_archive_builds_store_and_prevents_duplicate_jobs(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source-state"
    archive = tmp_path / "archive" / "state-2026-08-17"
    target = tmp_path / "new-state"
    entries = _build_source(source)

    receipt = apply_migration(
        source,
        archive,
        target,
        expected_completed=2,
        protect_archive=False,
    )

    assert receipt["schema_version"] == "video-content/state-migration-v1"
    assert receipt["published"] is False
    assert not source.exists()
    assert archive.is_dir()
    assert target.is_dir()
    assert (archive / "archive-manifest.json").is_file()
    assert (target / "migration-receipt.json").is_file()
    assert (
        target / "cache" / "media" / "bilibili" / "fixture" / "video.mp4"
    ).read_bytes() == b"authorized cached video"

    config = json.loads((target / "config.json").read_text(encoding="utf-8"))
    assert config["schema_version"] == "video-content/config-v1"
    assert config["values"]["home"] == str(target.resolve())
    assert config["values"]["download_cache"] == str(
        (target / "cache" / "media").resolve()
    )
    assert config["values"]["videocr"] == str(
        (archive / "runtimes" / "tool.exe").resolve()
    )
    assert config["values"]["download_retries"] == "2"

    store = Store(target)
    profiles = store.list_profiles()
    jobs = store.list_jobs(profile_id="watch-later-main")
    assert len(profiles) == 1
    assert profiles[0]["baseline"]["seen"] == ["BV1fixtureA:p1", "BV1fixtureB:p2"]
    assert len(jobs) == 2
    assert {job["status"] for job in jobs} == {"completed"}
    assert {job["stage"] for job in jobs} == {"completed"}
    assert len(store.list_artifacts(jobs[0]["job_id"], kind="archive_record")) == 1

    repeated = watch_later_scan(
        store,
        profile_id="watch-later-main",
        source=_WatchLaterFixture(entries),
    )
    assert repeated["created_jobs"] == []
    assert len(store.list_jobs(profile_id="watch-later-main")) == 2

    verification = verify_migration(archive, target, expected_completed=2)
    assert verification["valid"] is True
    assert verification["errors"] == []


def test_plan_rejects_published_or_incomplete_history(tmp_path: Path) -> None:
    source = tmp_path / "source-state"
    archive = tmp_path / "archive"
    target = tmp_path / "target"
    _build_source(source, published=True)

    with pytest.raises(ValueError, match="published=false"):
        plan_migration(source, archive, target, expected_completed=2)


def test_apply_refuses_existing_destinations(tmp_path: Path) -> None:
    source = tmp_path / "source-state"
    archive = tmp_path / "archive"
    target = tmp_path / "target"
    _build_source(source)
    archive.mkdir()

    with pytest.raises(FileExistsError, match="Archive destination"):
        apply_migration(source, archive, target, expected_completed=2)


def test_cli_defaults_to_dry_run(tmp_path: Path) -> None:
    source = tmp_path / "source-state"
    archive = tmp_path / "archive"
    target = tmp_path / "target"
    _build_source(source)

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "migrate_legacy_state.py"),
            "--source",
            str(source),
            "--archive",
            str(archive),
            "--target",
            str(target),
            "--expect-completed",
            "2",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["schema_version"] == "video-content/state-migration-plan-v1"
    assert report["ready"] is True
    assert source.is_dir()
    assert not archive.exists()
    assert not target.exists()
