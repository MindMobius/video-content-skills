"""Run deterministic fresh-Agent acceptance checks and emit one JSON report."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from video_content.automation import save_watch_later_profile, watch_later_scan
from video_content.content import content_save, transcript_save
from video_content.mcp_server import TOOL_NAMES, mcp
from video_content.store import Store
from video_content.wechat import wechat_bind, wechat_prepare

TIERS = ("core", "agent", "media", "live")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-tier", action="append", choices=TIERS, default=[])
    parser.add_argument("--ffprobe", type=Path)
    parser.add_argument("--ffmpeg", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    args = build_parser().parse_args()
    report = run_repro_check(
        required_tiers=args.require_tier or ["core"],
        ffprobe=args.ffprobe,
        ffmpeg=args.ffmpeg,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    raise SystemExit(0 if report["ok"] else 1)


def run_repro_check(
    *,
    required_tiers: list[str],
    ffprobe: Path | None = None,
    ffmpeg: Path | None = None,
) -> dict[str, Any]:
    unknown = sorted(set(required_tiers) - set(TIERS))
    if unknown:
        raise ValueError(f"Unknown reproducibility tier: {', '.join(unknown)}")
    with tempfile.TemporaryDirectory(prefix="video-content-repro-") as temporary:
        temp = Path(temporary)
        tiers = {
            "core": _tier(
                [
                    _check("dependency_locks", _check_locks),
                    _check("skill_discovery", _check_skills),
                    _check("authorized_media_fixture", _check_static_media_fixture),
                    _check(
                        "six_product_flow",
                        lambda: _check_six_product_flow(temp / "flow"),
                    ),
                ]
            ),
            "agent": _tier(
                [
                    _check("mcp_protocol", _check_mcp),
                    _check(
                        "watch_later_idempotency",
                        lambda: _check_watch_later(temp / "watch"),
                    ),
                    _check("node_contract", _check_node_contract),
                    _check("npm_workspace", _check_npm_workspace),
                ]
            ),
            "media": _tier(
                [_check("media_streams", lambda: _check_media_streams(ffprobe, ffmpeg))]
            ),
            "live": {
                "status": "manual_required",
                "checks": [
                    {
                        "name": "current_services",
                        "status": "manual_required",
                        "details": {
                            "requires": [
                                "current Bilibili and Browser Bridge login",
                                "representative VideOCR and optional ASR on this machine",
                                "separately authorized visible WeChat editor interaction",
                            ]
                        },
                    }
                ],
            },
        }
    required_status = {name: tiers[name]["status"] for name in required_tiers}
    return {
        "schema_version": "video-content/repro-check-v1",
        "ok": all(status == "passed" for status in required_status.values()),
        "required_tiers": required_tiers,
        "tiers": tiers,
        "boundaries": {
            "credentials_persisted": False,
            "clipboard_payload_persisted": False,
            "published": False,
            "live_inferred_from_fixture": False,
        },
    }


def _check(name: str, callback: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        details = callback()
    except (AssertionError, OSError, RuntimeError, TypeError, ValueError) as error:
        return {"name": name, "status": "failed", "error": str(error)}
    status = str(details.pop("status", "passed"))
    return {"name": name, "status": status, "details": details}


def _tier(checks: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = {item["status"] for item in checks}
    if "failed" in statuses:
        status = "failed"
    elif statuses == {"skipped"}:
        status = "skipped"
    elif "manual_required" in statuses:
        status = "manual_required"
    else:
        status = "passed"
    return {"status": status, "checks": checks}


def _check_locks() -> dict[str, Any]:
    constraints = ROOT / "requirements" / "mcp-constraints.txt"
    runtime = json.loads(
        (ROOT / "requirements" / "runtime-lock.json").read_text(encoding="utf-8")
    )
    assert runtime["schema_version"] == "video-content/runtime-lock-v1"
    digest = hashlib.sha256(constraints.read_bytes()).hexdigest()
    return {
        "constraints_sha256": digest,
        "runtime_lock_schema": runtime["schema_version"],
        "version": "1.0.0",
    }


def _check_skills() -> dict[str, Any]:
    names = sorted(
        path.parent.name for path in (ROOT / ".agents" / "skills").glob("*/SKILL.md")
    )
    expected = [
        "video-evidence",
        "video-to-content",
        "watch-later-to-wechat",
        "wechat-draft",
    ]
    assert names == expected
    return {"skills": names}


def _check_static_media_fixture() -> dict[str, Any]:
    root = ROOT / "tests" / "fixtures" / "authorized-video"
    fixture = json.loads((root / "fixture.json").read_text(encoding="utf-8"))
    video = root / fixture["video"]["path"]
    subtitle = root / fixture["expected_subtitle"]["path"]
    assert fixture["schema_version"] == "video-content/authorized-media-fixture-v1"
    assert fixture["generated"] is True
    assert fixture["license"] == "CC0-1.0"
    assert hashlib.sha256(video.read_bytes()).hexdigest() == fixture["video"]["sha256"]
    assert (
        hashlib.sha256(subtitle.read_bytes()).hexdigest()
        == fixture["expected_subtitle"]["sha256"]
    )
    return {
        "video_bytes": video.stat().st_size,
        "subtitle_bytes": subtitle.stat().st_size,
    }


def _check_six_product_flow(root: Path) -> dict[str, Any]:
    store = Store(root / "home")
    profile = save_watch_later_profile(
        store, profile_id="repro", account_profile_alias="fixture-browser"
    )
    job, _ = store.create_job(
        source={"platform": "bilibili", "bvid": "BV1repro", "page": 1},
        idempotency_key="bilibili_BV1repro_p1",
        profile_id=profile["profile_id"],
        initial_stage="evidence",
        initial_status="running",
    )
    evidence_id = "evidence_repro"
    evidence, _ = store.save_document(
        job["job_id"],
        kind="evidence",
        document={
            "schema_version": "video-content/evidence-v1",
            "evidence_id": evidence_id,
            "job_id": job["job_id"],
            "source": job["source"],
            "observations": [
                {
                    "kind": "hard_ocr",
                    "artifact_source": "authorized_fixture",
                    "cue_count": 1,
                }
            ],
            "artifact_refs": [],
            "decision": {"hard_subtitle_visual_decision": "continuous"},
            "created_at": "2026-08-17T00:00:00Z",
        },
        identifier_field="evidence_id",
        identifier_prefix="evidence",
    )
    transcript = transcript_save(
        store,
        job_id=job["job_id"],
        evidence_ids=[evidence["evidence_id"]],
        cues=[{"start_ms": 0, "end_ms": 1000, "text": "可复现内容"}],
        text="可复现内容",
        quality={"status": "verified", "reviewed_by": "repro"},
    )["transcript"]
    root.mkdir(parents=True, exist_ok=True)
    cover_path = root / "cover.jpg"
    cover_path.write_bytes(b"fixture-cover")
    cover = store.put_artifact(
        job["job_id"], kind="video_cover", source_path=cover_path
    )
    frames: list[tuple[dict[str, Any], int]] = []
    for index, timestamp_ms in enumerate((10000, 20000, 30000), start=1):
        frame_path = root / f"frame-{index}.png"
        frame_path.write_bytes(f"fixture-frame-{index}".encode())
        frames.append(
            (
                store.put_artifact(
                    job["job_id"],
                    kind="video_frame",
                    source_path=frame_path,
                    metadata={"timestamp_ms": timestamp_ms},
                ),
                timestamp_ms,
            )
        )
    content_document = {
        "schema_version": "video-content/wechat-manuscript-v1",
        "title": "可复现视频内容文章",
        "summary": "离线合同检查",
        "source": {
            "title": "授权测试视频",
            "creator": "fixture",
            "canonical_url": "https://www.bilibili.com/video/BV1repro",
        },
        "blocks": [
            {
                "type": "image",
                "artifact_id": cover["artifact_id"],
                "source_kind": "video_cover",
            },
            *[
                block
                for index, (reference, timestamp_ms) in enumerate(frames, start=1)
                for block in (
                    {"type": "paragraph", "text": f"可复现实质章节 {index}"},
                    {
                        "type": "image",
                        "artifact_id": reference["artifact_id"],
                        "source_kind": "video_frame",
                        "timestamp_ms": timestamp_ms,
                    },
                )
            ],
        ],
    }
    content_audit = {
        "status": "passed",
        "reviewed_by": "repro",
        "adaptation_mode": "source_faithful_full",
        "visual_policy": "source_frames_at_material_transitions",
        "material_sections": {
            "total": 3,
            "preserved": 3,
            "items": [
                {
                    "section_id": f"section-{index}",
                    "label": f"可复现实质章节 {index}",
                    "source_cue_indices": [0],
                    "output_block_indices": [index * 2 - 1, index * 2],
                    "status": "preserved",
                }
                for index in range(1, 4)
            ],
        },
        "omissions": [],
        "visual_plan": [
            {
                "artifact_id": reference["artifact_id"],
                "timestamp_ms": timestamp_ms,
                "block_index": index * 2,
                "reason": "authorized fixture material transition",
            }
            for index, (reference, timestamp_ms) in enumerate(frames, start=1)
        ],
        "expression_audit": {
            "status": "passed",
            "reviewed_by": "agent",
            "policy": "source_aware_minimal",
            "reviewed_targets": [
                "title_summary",
                "headings",
                "transitions",
                "evidence_boundaries",
                "ending",
                "material_details",
            ],
            "checks": {
                "source_expression_priority": True,
                "information_density_preserved": True,
                "structure_and_media_preserved": True,
                "final_source_fidelity_rechecked": True,
            },
            "items": [],
        },
    }
    content_result = content_save(
        store,
        job_id=job["job_id"],
        transcript_id=transcript["transcript_id"],
        carrier="wechat_article",
        document=content_document,
        audit=content_audit,
    )
    content = content_result["content"]
    prepared = wechat_prepare(
        store,
        job_id=job["job_id"],
        content_id=content["content_id"],
        authorized=True,
        save_draft=True,
    )
    observation = {
        "schema_version": "video-content/wechat-editor-observation-v2",
        "started_at": "2026-08-17T00:01:00Z",
        "saved_at": "2026-08-17T00:02:00Z",
        "title": "可复现视频内容文章",
        "content_sha256": prepared["content_sha256"],
        "draft_identity": {"appmsgid": "100000001"},
        "body_images": {
            "intended": 4,
            "items": [
                {
                    "visible": True,
                    "complete": True,
                    "natural_width": 100,
                    "width": 100,
                    "height": 100,
                    "host_class": "wechat",
                }
                for _ in range(4)
            ],
            "local_path_markers_remaining": 0,
        },
        "cover": {"selected": True},
        "summary": {"filled": True},
        "content_checks": {"source_disclosure_present": True},
        "save": {"saved": True, "mode": "draft"},
        "refresh_readback": {
            "performed": True,
            "same_draft": True,
            "content_present": True,
        },
        "creation_source": {
            "declared": True,
            "type": "ai_generated",
            "read_back": True,
        },
        "published": False,
    }
    receipt = wechat_bind(
        store,
        job_id=job["job_id"],
        content_id=content["content_id"],
        observation=observation,
    )
    repeated_job, reused_job = store.create_job(
        source={"platform": "bilibili", "bvid": "BV1repro", "page": 1},
        idempotency_key="bilibili_BV1repro_p1",
        profile_id=profile["profile_id"],
    )
    repeated_content = content_save(
        store,
        job_id=job["job_id"],
        transcript_id=transcript["transcript_id"],
        carrier="wechat_article",
        document=content_document,
        audit=content_audit,
    )
    second_draft_blocked = False
    try:
        wechat_bind(
            store,
            job_id=job["job_id"],
            content_id=content["content_id"],
            observation=observation,
        )
    except ValueError as error:
        if "already has a validated WeChat draft receipt" not in str(error):
            raise
        second_draft_blocked = True
    assert repeated_job["job_id"] == job["job_id"]
    products = {
        "profiles": len(store.list_profiles()),
        "jobs": len(store.list_jobs()),
        "evidence": len(store.list_artifacts(job["job_id"], kind="evidence")),
        "transcript": len(store.list_artifacts(job["job_id"], kind="transcript")),
        "content": len(store.list_artifacts(job["job_id"], kind="content")),
        "draft_receipt": len(store.list_artifacts(job["job_id"], kind="draft_receipt")),
    }
    assert all(value == 1 for value in products.values())
    assert receipt["validation"]["valid"] is True
    assert receipt["receipt"]["published"] is False
    idempotency = {
        "reused_job": reused_job,
        "reused_content": repeated_content["reused"],
        "second_draft_blocked": second_draft_blocked,
        "jobs": len(store.list_jobs()),
        "content": len(store.list_artifacts(job["job_id"], kind="content")),
        "draft_receipt": len(store.list_artifacts(job["job_id"], kind="draft_receipt")),
    }
    assert idempotency == {
        "reused_job": True,
        "reused_content": True,
        "second_draft_blocked": True,
        "jobs": 1,
        "content": 1,
        "draft_receipt": 1,
    }
    return {
        "products": products,
        "idempotency": idempotency,
        "job_status": receipt["job"]["status"],
        "published": False,
    }


async def _list_mcp_tools() -> list[str]:
    return [tool.name for tool in await mcp.list_tools()]


def _check_mcp() -> dict[str, Any]:
    names = asyncio.run(_list_mcp_tools())
    assert set(names) == set(TOOL_NAMES)
    return {"tool_count": len(names), "tools": names}


class _FixtureWatchLater:
    def __init__(self, path: Path) -> None:
        self.path = path

    def list_entries(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        rows = json.loads(self.path.read_text(encoding="utf-8-sig"))
        return rows[:limit] if limit else rows


def _check_watch_later(root: Path) -> dict[str, Any]:
    store = Store(root)
    save_watch_later_profile(store, profile_id="daily", account_profile_alias="fixture")
    fixtures = ROOT / "tests" / "fixtures" / "bilibili-watch-later"
    first = watch_later_scan(
        store, profile_id="daily", source=_FixtureWatchLater(fixtures / "first.json")
    )
    repeat = watch_later_scan(
        store, profile_id="daily", source=_FixtureWatchLater(fixtures / "first.json")
    )
    changed = watch_later_scan(
        store,
        profile_id="daily",
        source=_FixtureWatchLater(fixtures / "reordered-with-new.json"),
    )
    assert len(first["created_jobs"]) == 2
    assert repeat["created_jobs"] == []
    assert len(changed["created_jobs"]) == 1
    return {"jobs": len(store.list_jobs()), "duplicates": 0, "new_after_reorder": 1}


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _check_node_contract() -> dict[str, Any]:
    npm = shutil.which("npm")
    if not npm:
        return {"status": "skipped", "reason": "npm is unavailable"}
    result = _run([npm, "test"])
    assert result.returncode == 0, (result.stderr or result.stdout)[-2000:]
    return {"passed": True}


def _check_npm_workspace() -> dict[str, Any]:
    npm = shutil.which("npm")
    if not npm:
        return {"status": "skipped", "reason": "npm is unavailable"}
    result = _run([npm, "pack", "--dry-run", "--json"])
    assert result.returncode == 0, (result.stderr or result.stdout)[-2000:]
    payload = json.loads(result.stdout)
    files = [item["path"] for item in payload[0]["files"]]
    assert not any(path.startswith("dsh/") for path in files)
    removed_package = "src/video_" + "subtitle/"
    assert not any(path.startswith(removed_package) for path in files)
    return {"file_count": len(files), "private_workspace": True}


def _check_media_streams(ffprobe: Path | None, ffmpeg: Path | None) -> dict[str, Any]:
    probe = _resolve_executable(ffprobe, "ffprobe")
    encoder = _resolve_executable(ffmpeg, "ffmpeg")
    if not probe or not encoder:
        return {"status": "skipped", "reason": "FFprobe/FFmpeg are unavailable"}
    video = (
        ROOT
        / "tests"
        / "fixtures"
        / "authorized-video"
        / "authorized-hard-subtitle.mp4"
    )
    result = subprocess.run(
        [str(probe), "-v", "error", "-show_streams", "-of", "json", str(video)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    streams = json.loads(result.stdout)["streams"]
    assert any(item.get("codec_type") == "video" for item in streams)
    return {"stream_count": len(streams), "ffprobe": str(probe), "ffmpeg": str(encoder)}


def _resolve_executable(value: Path | None, name: str) -> Path | None:
    if value:
        selected = value.expanduser().resolve()
        return selected if selected.is_file() else None
    found = shutil.which(name)
    return Path(found).resolve() if found else None


if __name__ == "__main__":
    main()
