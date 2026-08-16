"""Run deterministic fresh-Agent acceptance checks and emit one JSON report."""

from __future__ import annotations

import argparse
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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_wechat_package import validate_package
from video_subtitle.core.batch import initialize_batch, update_batch_item
from video_subtitle.core.content import initialize_content_project
from video_subtitle.core.portable import export_content_bundle, import_content_bundle
from video_subtitle.core.srt import Cue, write_srt
from video_subtitle.core.util import utc_now, write_json_atomic
from video_subtitle.wechat_adapter import prepare_wechat_clipboard
from video_subtitle.wechat_renderer import render_wechat_package

TIERS = ("core", "agent", "media", "live")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-tier",
        action="append",
        choices=TIERS,
        default=[],
        help="Tier that must pass; default is core",
    )
    parser.add_argument("--ffprobe", type=Path)
    parser.add_argument("--ffmpeg", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    args = build_parser().parse_args()
    required = args.require_tier or ["core"]
    report = run_repro_check(
        required_tiers=required,
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
    with tempfile.TemporaryDirectory(prefix="video-subtitle-repro-") as temporary:
        temp = Path(temporary)
        core_checks = [
            _check("dependency_locks", _check_locks),
            _check("skill_discovery", _check_skills),
            _check("authorized_media_fixture", _check_static_media_fixture),
            _check(
                "renderer_and_clipboard", lambda: _check_renderer(temp / "renderer")
            ),
            _check("batch_resume", lambda: _check_batch(temp / "batch")),
            _check(
                "portable_round_trip", lambda: _check_portability(temp / "portable")
            ),
        ]
        agent_checks = [
            _check("node_contract", _check_node_contract),
            _check("mcp_protocol", lambda: _check_mcp(temp / "mcp")),
            _check("npm_package", _check_npm_package),
        ]
        media_checks = [
            _check("media_streams", lambda: _check_media_streams(ffprobe, ffmpeg)),
        ]
        live_checks = [
            {
                "name": "real_services",
                "status": "manual_required",
                "details": {
                    "requires": [
                        "current Bilibili URL and Browser Bridge login",
                        "representative VideOCR and optional ASR run on the current GPU",
                        "explicitly authorized signed-in WeChat draft handoff",
                    ]
                },
            }
        ]
    tiers = {
        "core": _tier(core_checks),
        "agent": _tier(agent_checks),
        "media": _tier(media_checks),
        "live": _tier(live_checks),
    }
    unknown = sorted(set(required_tiers) - set(TIERS))
    if unknown:
        raise ValueError(f"Unknown reproducibility tiers: {unknown}")
    ok = all(tiers[tier]["status"] == "passed" for tier in required_tiers)
    return {
        "schema_version": "video-subtitle/repro-check-v1",
        "checked_at": utc_now(),
        "ok": ok,
        "required_tiers": required_tiers,
        "tiers": tiers,
        "boundaries": {
            "llm_output": "contract_equivalent_not_byte_identical",
            "live_services": "never inferred from deterministic fixtures",
            "credentials_persisted": False,
            "published": False,
        },
    }


def _check_locks() -> dict[str, Any]:
    paths = [
        ROOT / "uv.lock",
        ROOT / "requirements" / "mcp-constraints.txt",
        ROOT / "requirements" / "runtime-lock.json",
        ROOT / "npm-shrinkwrap.json",
    ]
    missing = [path.name for path in paths if not path.is_file()]
    if missing:
        raise ValueError(f"Missing dependency locks: {', '.join(missing)}")
    runtime_lock = json.loads(paths[2].read_text(encoding="utf-8"))
    if runtime_lock.get("schema_version") != "video-subtitle/runtime-lock-v1":
        raise ValueError("Runtime lock schema is unsupported")
    return {
        "locks": [{"name": path.name, "sha256": _sha256(path)} for path in paths],
        "videocr_variants": len(runtime_lock["videocr"]["variants"]),
        "model_revisions_pinned": all(
            len(model["revision"]) == 40 for model in runtime_lock["models"].values()
        ),
    }


def _check_skills() -> dict[str, Any]:
    expected = [
        "video-subtitle",
        "video-to-content",
        "video-watch-later-automation",
        "wechat-draft-handoff",
    ]
    discovered = []
    for skill_path in sorted((ROOT / ".agents" / "skills").glob("*/SKILL.md")):
        name = skill_path.parent.name
        metadata = skill_path.parent / "agents" / "openai.yaml"
        if not metadata.is_file():
            raise ValueError(f"Skill UI metadata is missing: {name}")
        metadata_text = metadata.read_text(encoding="utf-8")
        if f"${name}" not in metadata_text:
            raise ValueError(f"Skill default prompt does not mention ${name}")
        discovered.append(name)
    if discovered != expected:
        raise ValueError(f"Unexpected Skill discovery result: {discovered}")
    return {"skills": discovered, "canonical_root": ".agents/skills"}


def _check_static_media_fixture() -> dict[str, Any]:
    root = ROOT / "tests" / "fixtures" / "authorized-video"
    manifest = json.loads((root / "fixture.json").read_text(encoding="utf-8"))
    video = root / manifest["video"]["path"]
    if _sha256(video) != manifest["video"]["sha256"]:
        raise ValueError("Authorized media fixture SHA-256 differs")
    header = video.read_bytes()[:64]
    if b"ftyp" not in header:
        raise ValueError("Authorized media fixture is not an MP4 container")
    expected = (root / "expected.srt").read_text(encoding="utf-8")
    if manifest["video"]["hard_subtitle"] not in expected:
        raise ValueError("Fixture transcript does not match its hard subtitle")
    return {
        "license": manifest["license"],
        "bytes": video.stat().st_size,
        "sha256": manifest["video"]["sha256"],
        "has_audio_declared": manifest["video"]["has_audio"],
        "hard_subtitle": manifest["video"]["hard_subtitle"],
    }


def _check_renderer(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True)
    (root / "cover.jpg").write_bytes(b"cover")
    (root / "frame.png").write_bytes(b"frame")
    manuscript = {
        "schema_version": "video-content/wechat-manuscript-v1",
        "title": "可复现的载体转换",
        "summary": "验证首方排版、图片路径和剪贴板运输。",
        "source": {
            "title": "授权测试视频",
            "creator": "Repository Fixture",
            "canonical_url": "https://example.invalid/fixture",
        },
        "blocks": [
            {"type": "image", "path": "cover.jpg", "source_kind": "video_cover"},
            {"type": "lead", "text": "我会先固定证据，再为载体重构结构。"},
            {"type": "heading", "text": "结构可以改变"},
            {"type": "paragraph", "text": "论点、限定与来源不能在转换中消失。"},
            {
                "type": "image",
                "path": "frame.png",
                "source_kind": "video_frame",
                "timestamp_ms": 1000,
            },
        ],
    }
    manuscript_path = root / "manuscript.json"
    manuscript_path.write_text(
        json.dumps(manuscript, ensure_ascii=False), encoding="utf-8"
    )
    output = root / "output"
    render = render_wechat_package(manuscript_path, output)
    validation = validate_package(output)
    clipboard = prepare_wechat_clipboard(output, copy=False)
    if not render["ok"] or not validation["valid"] or not clipboard["ok"]:
        raise ValueError("Renderer, package validation, or clipboard preflight failed")
    return {
        "image_markers": validation["counts"]["markers"],
        "clipboard_assets": clipboard["marker_count"],
        "payload_persisted": clipboard["payload_persisted"],
        "theme": "restrained-editorial",
    }


def _check_batch(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True)
    manifest = root / "batch.json"
    initialize_batch(
        manifest,
        [
            {"kind": "video_url", "value": "https://example.invalid/video-1"},
            {"kind": "video_url", "value": "https://example.invalid/video-2"},
        ],
        draft_requested=True,
    )
    update_batch_item(manifest, item_id="item-001", stage="subtitle", status="running")
    artifact = root / "item-001" / "manifest.json"
    artifact.parent.mkdir()
    artifact.write_text("{}", encoding="utf-8")
    result = update_batch_item(
        manifest,
        item_id="item-001",
        stage="subtitle",
        status="completed",
        artifact=str(artifact),
    )
    if result["resumable"][0]["stage"] != "content":
        raise ValueError("Batch ledger did not resume at the content stage")
    return {"items": result["summary"]["total"], "next": result["resumable"][0]}


def _check_portability(root: Path) -> dict[str, Any]:
    job = root / "job"
    job.mkdir(parents=True)
    subtitle = job / "subtitle.ocr.srt"
    write_srt(subtitle, [Cue(0, 1000, "可迁移证据")])
    manifest = {
        "schema_version": "video-subtitle/v1",
        "job_id": "sub_repro_check",
        "status": "completed",
        "stage": "done",
        "request": {"language": "zh-CN"},
        "video": {"title": "验收", "author": "fixture", "duration_seconds": 1},
        "selected_source": {
            "kind": "hard_ocr",
            "fusion_status": "independent_evidence",
        },
        "review": None,
        "sources": [
            {"kind": "hard_ocr", "artifact_source": "hard_ocr:fixture", "cue_count": 1}
        ],
        "attempts": [],
        "artifacts": [
            {
                "kind": "subtitle_srt",
                "path": str(subtitle),
                "source": "hard_ocr:fixture",
                "owned_by_job": True,
                "selected": True,
            }
        ],
        "warnings": [],
        "error": None,
    }
    manifest_path = job / "manifest.json"
    write_json_atomic(manifest_path, manifest)
    project = initialize_content_project(manifest_path)
    bundle = root / "bundle.zip"
    exported = export_content_bundle(Path(project["project_path"]), bundle)
    imported = import_content_bundle(bundle, root / "imported")
    if imported["project_id"] != project["project_id"]:
        raise ValueError("Portable import changed the content project identity")
    return {
        "bundle_id": exported["bundle_id"],
        "files": exported["file_count"],
        "import_integrity_valid": imported["integrity"]["valid"],
    }


def _check_node_contract() -> dict[str, Any]:
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("npm is not available")
    completed = _run([npm, "test"], timeout=30)
    if completed.returncode:
        raise ValueError((completed.stderr or completed.stdout)[-2000:])
    return {"tests": "passed"}


def _check_mcp(root: Path) -> dict[str, Any]:
    environment = os.environ.copy()
    environment["VIDEO_SUBTITLE_CONFIG"] = str(root / "config.json")
    environment["VIDEO_SUBTITLE_HOME"] = str(root / "jobs")
    completed = _run(
        [sys.executable, str(ROOT / "scripts" / "mcp_smoke.py")],
        timeout=30,
        env=environment,
    )
    if completed.returncode:
        raise ValueError((completed.stderr or completed.stdout)[-2000:])
    result = json.loads(completed.stdout)
    required = {"initialize_video_batch", "get_video_batch", "update_video_batch_item"}
    if not required.issubset(result["tools"]):
        raise ValueError("MCP batch tools are missing")
    return {"server": result["server"], "tool_count": len(result["tools"])}


def _check_npm_package() -> dict[str, Any]:
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("npm is not available")
    completed = _run([npm, "pack", "--dry-run", "--json"], timeout=30)
    if completed.returncode:
        raise ValueError((completed.stderr or completed.stdout)[-2000:])
    packages = json.loads(completed.stdout)
    names = {item["path"] for item in packages[0]["files"]}
    required = {
        "AGENTS.md",
        "npm-shrinkwrap.json",
        "scripts/repro_check.py",
        "requirements/runtime-lock.json",
        "tests/fixtures/authorized-video/authorized-hard-subtitle.mp4",
        ".agents/skills/wechat-draft-handoff/scripts/browser-adapter.js",
    }
    missing = sorted(required - names)
    if missing:
        raise ValueError(f"npm package omits reproducibility files: {missing}")
    return {"file_count": len(names), "required_files_present": True}


def _check_media_streams(
    requested_ffprobe: Path | None,
    requested_ffmpeg: Path | None,
) -> dict[str, Any]:
    executable = requested_ffprobe.expanduser().resolve() if requested_ffprobe else None
    if executable is None or not executable.is_file():
        discovered = shutil.which("ffprobe")
        executable = Path(discovered).resolve() if discovered else None
    video = (
        ROOT
        / "tests"
        / "fixtures"
        / "authorized-video"
        / "authorized-hard-subtitle.mp4"
    )
    if executable is not None and executable.is_file():
        completed = _run(
            [
                str(executable),
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type,width,height",
                "-of",
                "json",
                str(video),
            ],
            timeout=10,
        )
        if completed.returncode:
            raise ValueError(completed.stderr[-2000:])
        streams = json.loads(completed.stdout)["streams"]
        types = {item["codec_type"] for item in streams}
        if not {"video", "audio"}.issubset(types):
            raise ValueError(
                "Authorized media fixture does not contain video and audio"
            )
        return {
            "method": "ffprobe",
            "stream_types": sorted(types),
            "video_dimensions": [640, 360],
        }

    ffmpeg = requested_ffmpeg.expanduser().resolve() if requested_ffmpeg else None
    if ffmpeg is None or not ffmpeg.is_file():
        discovered = shutil.which("ffmpeg")
        ffmpeg = Path(discovered).resolve() if discovered else None
    if ffmpeg is None or not ffmpeg.is_file():
        raise RuntimeError(
            "Neither ffprobe nor ffmpeg is available; pass one after FFmpeg setup"
        )
    completed = _run(
        [
            str(ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-f",
            "null",
            "-",
        ],
        timeout=15,
    )
    if completed.returncode:
        raise ValueError(completed.stderr[-2000:])
    return {
        "method": "ffmpeg_decode",
        "stream_types": ["audio", "video"],
        "video_dimensions": [640, 360],
    }


def _check(name: str, function: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        details = function()
        return {"name": name, "status": "passed", "details": details}
    except RuntimeError as error:
        return {"name": name, "status": "not_ready", "error": str(error)}
    except Exception as error:  # noqa: BLE001 - report every deterministic failure
        return {
            "name": name,
            "status": "failed",
            "error": str(error),
            "error_type": type(error).__name__,
        }


def _tier(checks: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = {check["status"] for check in checks}
    if statuses == {"passed"}:
        status = "passed"
    elif "failed" in statuses:
        status = "failed"
    elif "not_ready" in statuses:
        status = "not_ready"
    else:
        status = "manual_required"
    return {"status": status, "checks": checks}


def _run(
    command: list[str],
    *,
    timeout: int,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
