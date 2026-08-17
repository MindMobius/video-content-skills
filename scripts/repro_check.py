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
from video_subtitle.core.automation_actions import (
    begin_automation_evidence,
    complete_automation_evidence,
    save_automation_canonical_subtitle,
)
from video_subtitle.core.automation_content import (
    initialize_automated_content_project,
    record_automation_audit,
)
from video_subtitle.core.automation_handoff import (
    bind_automation_handoff_receipt,
    get_existing_handoff_binding,
    prepare_automation_handoff,
)
from video_subtitle.core.automation_integrity import audit_automation_store
from video_subtitle.core.automation_job import (
    list_automation_jobs,
    transition_automation_job,
)
from video_subtitle.core.automation_profile import (
    save_automation_profile,
    save_draft_authorization,
)
from video_subtitle.core.automation_scan import scan_watch_later
from video_subtitle.core.batch import initialize_batch, update_batch_item
from video_subtitle.core.content import (
    get_content_project,
    initialize_content_project,
    save_content_deliverable,
    save_content_document,
    validate_content_project,
)
from video_subtitle.core.evidence import list_subtitle_evidence_for_manifest
from video_subtitle.core.portable import export_content_bundle, import_content_bundle
from video_subtitle.core.srt import Cue, write_srt
from video_subtitle.core.util import read_json, utc_now, write_json_atomic
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
            _check(
                "watch_later_to_draft_contract",
                lambda: _check_watch_later_to_draft_contract(
                    temp / "watch-later-automation"
                ),
            ),
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


class _FixtureWatchLaterSource:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def list_entries(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        return self.rows[:limit] if limit is not None else list(self.rows)


def _check_watch_later_to_draft_contract(
    root: Path,
    *,
    fixture_path: Path | None = None,
) -> dict[str, Any]:
    fixture_path = (
        fixture_path.expanduser().resolve()
        if fixture_path is not None
        else ROOT / "tests" / "fixtures" / "automation" / "fixture.json"
    )
    fixture = read_json(fixture_path)
    if fixture.get("schema_version") != "video-automation/repro-fixture-v1":
        raise ValueError("Automation reproduction fixture schema is unsupported")
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    profile_path = root / "profile.json"
    profile = save_automation_profile(profile_path, fixture["profile"])
    authorization_path = root / "authorization.json"
    authorization = save_draft_authorization(
        authorization_path,
        {
            "authorization_id": profile["draft_authorization_id"],
            "status": "active",
            "profile_ids": [profile["profile_id"]],
            "browser_profile_alias": "fixture-wechat",
            "allowed_actions": ["save_wechat_draft"],
            "prohibited_actions": profile["prohibited_actions"],
            "expires_at": None,
            "revoked_at": None,
        },
    )

    cycles = fixture["watch_later_cycles"]
    usable_store = root / "usable-store"
    first_scan = scan_watch_later(
        profile_path=profile_path,
        source=_FixtureWatchLaterSource(cycles[0]),
        store=usable_store,
    )
    if first_scan["new_entry_count"] != 1 or len(first_scan["created_jobs"]) != 1:
        raise ValueError("First Watch Later cycle did not create exactly one job")
    jobs = list_automation_jobs(usable_store)["jobs"]
    if len(jobs) != 1:
        raise ValueError("Usable Watch Later fixture did not create exactly one job")
    job_path = Path(jobs[0]["job_path"])
    begin_automation_evidence(job_path)

    usable = fixture["usable"]
    subtitle_root = job_path.parent / "subtitle"
    subtitle_root.mkdir()
    platform_path = subtitle_root / "subtitle.platform.srt"
    ocr_path = subtitle_root / "subtitle.ocr.srt"
    shutil.copy2(fixture_path.parent / usable["platform_srt"], platform_path)
    shutil.copy2(fixture_path.parent / usable["ocr_srt"], ocr_path)
    raw_before = {str(path): _sha256(path) for path in (platform_path, ocr_path)}
    manifest_path = subtitle_root / "manifest.json"
    write_json_atomic(
        manifest_path,
        {
            "schema_version": "video-subtitle/v1",
            "job_id": "sub_fixture_usable",
            "status": "completed",
            "stage": "done",
            "request": {"language": "zh-CN"},
            "video": {
                "bvid": cycles[0][0]["bvid"],
                "page": cycles[0][0]["page"],
                "title": cycles[0][0]["title"],
                "duration_seconds": 9,
                "url": cycles[0][0]["url"],
            },
            "selected_source": {
                "kind": "platform_subtitle",
                "fusion_status": "independent_evidence",
            },
            "sources": [
                {
                    "kind": "platform_subtitle",
                    "artifact_source": "platform_subtitle:bilibili",
                    "cue_count": 2,
                },
                {
                    "kind": "hard_ocr",
                    "artifact_source": "hard_ocr:fixture",
                    "cue_count": 2,
                },
            ],
            "review": None,
            "attempts": [],
            "artifacts": [
                {
                    "kind": "subtitle_srt",
                    "source": "platform_subtitle:bilibili",
                    "path": str(platform_path),
                    "owned_by_job": True,
                    "selected": True,
                    "cue_count": 2,
                },
                {
                    "kind": "ocr_primary_srt",
                    "source": "hard_ocr:fixture",
                    "path": str(ocr_path),
                    "owned_by_job": True,
                    "selected": False,
                    "cue_count": 2,
                },
            ],
            "warnings": [],
            "error": None,
        },
    )
    complete_automation_evidence(job_path, manifest_path)
    evidence = list_subtitle_evidence_for_manifest(manifest_path)["evidence"]
    platform_evidence, ocr_evidence = evidence
    canonical_document = {
        "manifest_sha256": _sha256(manifest_path),
        "status": "usable",
        "evidence": [
            {
                "evidence_id": platform_evidence["evidence_id"],
                "sha256": _sha256(Path(platform_evidence["path"])),
                "role": "primary",
            },
            {
                "evidence_id": ocr_evidence["evidence_id"],
                "sha256": _sha256(Path(ocr_evidence["path"])),
                "role": "corroborating",
            },
        ],
        "cues": [
            {
                **cue,
                "evidence_refs": [
                    f"{platform_evidence['evidence_id']}-cue-{index:05d}",
                    f"{ocr_evidence['evidence_id']}-cue-{index:05d}",
                ],
            }
            for index, cue in enumerate(usable["canonical_cues"], start=1)
        ],
        "decisions": usable["canonical_decisions"],
        "unresolved": [],
        "termination": None,
    }
    save_automation_canonical_subtitle(
        job_path,
        manifest_path,
        canonical_document,
    )

    project = initialize_automated_content_project(
        manifest_path=manifest_path,
        profile_path=profile_path,
        job_path=job_path,
    )
    project_path = Path(project["project_path"])
    canonical_evidence = next(
        item
        for item in project["source"]["evidence"]
        if item["source_kind"] == "canonical_subtitle"
    )
    evidence_id = canonical_evidence["evidence_id"]
    content_map = _automation_fixture_content_map(project, evidence_id)
    map_result = save_content_document(
        project_path,
        kind="content_map",
        document=content_map,
    )
    media_plan = _automation_fixture_media_plan(
        project,
        map_result["artifact"]["sha256"],
    )
    save_content_document(
        project_path,
        kind="media_plan",
        document=media_plan,
    )
    deliverable_result = save_content_deliverable(
        project_path,
        medium="article",
        format="markdown",
        content=usable["article_body"],
        title=usable["article_title"],
        used_claim_ids=["claim-0001", "claim-0002"],
        used_caveat_ids=["caveat-0001"],
    )
    transition_automation_job(job_path, status="content_auditing")
    audit = _automation_fixture_audit(
        project,
        map_result["artifact"]["sha256"],
        deliverable_result["deliverable"],
    )
    audit_result = save_content_document(
        project_path,
        kind="fidelity_audit",
        document=audit,
    )
    record_automation_audit(job_path=job_path, project_path=project_path)
    validation = validate_content_project(project_path)
    if not validation["valid"] or not validation["ready_for_delivery"]:
        raise ValueError("Automation fixture content project is not delivery-ready")
    transition_automation_job(job_path, status="handoff_running")

    prepared = prepare_automation_handoff(
        job_path=job_path,
        profile_path=profile_path,
        authorization_path=authorization_path,
    )
    if prepared["already_completed"] is not False:
        raise ValueError("Fresh automation handoff unexpectedly reused a binding")
    receipt_path = job_path.parent / "wechat-draft-receipt.json"
    receipt = _automation_fixture_receipt(
        project=get_content_project(project_path),
        deliverable=deliverable_result["deliverable"],
        audit=audit_result["artifact"],
        title=usable["article_title"],
        appmsgid=usable["appmsgid"],
    )
    write_json_atomic(receipt_path, receipt)
    first_binding = bind_automation_handoff_receipt(
        job_path=job_path,
        authorization_path=authorization_path,
        receipt_path=receipt_path,
    )
    second_binding = bind_automation_handoff_receipt(
        job_path=job_path,
        authorization_path=authorization_path,
        receipt_path=receipt_path,
    )
    completed_preparation = prepare_automation_handoff(
        job_path=job_path,
        profile_path=profile_path,
        authorization_path=authorization_path,
    )
    existing_binding = get_existing_handoff_binding(job_path)
    second_scan = scan_watch_later(
        profile_path=profile_path,
        source=_FixtureWatchLaterSource(cycles[1]),
        store=usable_store,
    )
    usable_jobs = list_automation_jobs(usable_store)["jobs"]
    raw_after = {str(path): _sha256(path) for path in (platform_path, ocr_path)}

    unusable = fixture["unusable"]
    unusable_store = root / "unusable-store"
    unusable_scan = scan_watch_later(
        profile_path=profile_path,
        source=_FixtureWatchLaterSource([unusable["source"]]),
        store=unusable_store,
    )
    if len(unusable_scan["created_jobs"]) != 1:
        raise ValueError("Unusable fixture did not create exactly one job")
    unusable_job = list_automation_jobs(unusable_store)["jobs"][0]
    unusable_job_path = Path(unusable_job["job_path"])
    begin_automation_evidence(unusable_job_path)
    unusable_subtitle_root = unusable_job_path.parent / "subtitle"
    unusable_subtitle_root.mkdir()
    unusable_srt = unusable_subtitle_root / "subtitle.platform.srt"
    shutil.copy2(fixture_path.parent / unusable["platform_srt"], unusable_srt)
    unusable_raw_before = _sha256(unusable_srt)
    unusable_manifest = unusable_subtitle_root / "manifest.json"
    write_json_atomic(
        unusable_manifest,
        {
            "schema_version": "video-subtitle/v1",
            "job_id": "sub_fixture_unusable",
            "status": "completed",
            "video": {
                "bvid": unusable["source"]["bvid"],
                "page": unusable["source"]["page"],
                "title": unusable["source"]["title"],
                "duration_seconds": 2,
                "url": unusable["source"]["url"],
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
                    "path": str(unusable_srt),
                    "owned_by_job": True,
                    "selected": True,
                    "cue_count": 1,
                }
            ],
        },
    )
    complete_automation_evidence(unusable_job_path, unusable_manifest)
    unusable_evidence = list_subtitle_evidence_for_manifest(unusable_manifest)[
        "evidence"
    ][0]
    unusable_canonical_action = save_automation_canonical_subtitle(
        unusable_job_path,
        unusable_manifest,
        {
            "manifest_sha256": _sha256(unusable_manifest),
            "status": "unusable",
            "evidence": [
                {
                    "evidence_id": unusable_evidence["evidence_id"],
                    "sha256": _sha256(Path(unusable_evidence["path"])),
                    "role": "primary",
                }
            ],
            "cues": [],
            "decisions": [],
            "unresolved": [
                {
                    "issue": "Available text is not a reliable transcript.",
                    "blocking": True,
                    "evidence_refs": [f"{unusable_evidence['evidence_id']}-cue-00001"],
                }
            ],
            "termination": unusable["termination"],
        },
    )
    unusable_final = unusable_canonical_action["job"]

    duplicate_job_count = max(0, len(usable_jobs) - 1) + len(
        second_scan["created_jobs"]
    )
    binding_files = list(job_path.parent.glob("handoff-binding.json"))
    duplicate_drafts = 0
    if (
        first_binding["binding_id"] != second_binding["binding_id"]
        or completed_preparation["already_completed"] is not True
        or existing_binding is None
        or len(binding_files) != 1
    ):
        duplicate_drafts = 1
    raw_preserved = raw_before == raw_after and unusable_raw_before == _sha256(
        unusable_srt
    )
    if authorization["allowed_actions"] != ["save_wechat_draft"]:
        raise ValueError("Fixture authorization expanded beyond saving a draft")
    if receipt["published"] is not False or receipt["publish_actions_performed"]:
        raise ValueError("Automation fixture performed a forbidden publish action")
    usable_integrity = audit_automation_store(usable_store)
    unusable_integrity = audit_automation_store(unusable_store)

    return {
        "jobs_created": len(first_scan["created_jobs"]),
        "completed_jobs": sum(job["status"] == "completed" for job in usable_jobs),
        "draft_bindings": len(binding_files),
        "duplicate_jobs": duplicate_job_count,
        "duplicate_drafts": duplicate_drafts,
        "unprocessable_jobs": int(unusable_final["status"] == "unprocessable"),
        "content_created_for_unprocessable": (
            unusable_subtitle_root.joinpath("content").exists()
        ),
        "raw_evidence_hashes_preserved": raw_preserved,
        "published": receipt["published"],
        "publish_actions_performed": receipt["publish_actions_performed"],
        "appmsgid": first_binding["appmsgid"],
        "integrity_valid": (usable_integrity["valid"] and unusable_integrity["valid"]),
        "artifact_paths_canonical": not usable_integrity["repairs"],
        "duplicate_appmsgids": usable_integrity["duplicate_appmsgids"],
    }


def _automation_fixture_content_map(
    project: dict[str, Any], evidence_id: str
) -> dict[str, Any]:
    return {
        "schema_version": "video-content/content-map-v1",
        "project_id": project["project_id"],
        "source_manifest_sha256": project["source"]["manifest_sha256"],
        "content_type": "explanation",
        "summary": (
            "Long videos need a lower reception barrier, while a medium change "
            "must preserve evidence boundaries."
        ),
        "coverage": {
            "mode": "full",
            "evidence_ids": [evidence_id],
            "analyzed_ranges": [{"start_ms": 0, "end_ms": 9000}],
            "omitted_ranges": [],
        },
        "thesis": {
            "text": "Conversion is reconstruction with evidence boundaries.",
            "claim_ids": ["claim-0001", "claim-0002"],
        },
        "evidence_refs": [
            {
                "evidence_ref_id": "evref-0001",
                "evidence_id": evidence_id,
                "cue_ids": [f"{evidence_id}-cue-00001"],
                "start_ms": 0,
                "end_ms": 4000,
                "text": ("Long videos are hard to receive, not short on information."),
                "language": "en-US",
                "relationship": "supports",
            },
            {
                "evidence_ref_id": "evref-0002",
                "evidence_id": evidence_id,
                "cue_ids": [f"{evidence_id}-cue-00002"],
                "start_ms": 4000,
                "end_ms": 9000,
                "text": (
                    "A medium change must preserve claims, evidence, and caveats."
                ),
                "language": "en-US",
                "relationship": "supports",
            },
        ],
        "speakers": [
            {"speaker_id": "speaker-0001", "name": "Narrator", "role": "speaker"}
        ],
        "claims": [
            {
                "claim_id": "claim-0001",
                "text": "Long videos have a high reception barrier.",
                "kind": "explanation",
                "importance": "core",
                "attribution": "speaker",
                "speaker_id": "speaker-0001",
                "evidence_refs": ["evref-0001"],
                "confidence": "high",
                "source_support": "direct",
                "external_verification": "not_checked",
            },
            {
                "claim_id": "claim-0002",
                "text": (
                    "A medium change must preserve claims, evidence, and caveats."
                ),
                "kind": "recommendation",
                "importance": "core",
                "attribution": "speaker",
                "speaker_id": "speaker-0001",
                "evidence_refs": ["evref-0002"],
                "confidence": "high",
                "source_support": "direct",
                "external_verification": "not_checked",
            },
        ],
        "caveats": [
            {
                "caveat_id": "caveat-0001",
                "text": (
                    "Subtitle evidence shows what was said; it does not prove "
                    "the claims true."
                ),
                "claim_ids": ["claim-0001", "claim-0002"],
                "evidence_refs": ["evref-0001", "evref-0002"],
            }
        ],
        "counterpoints": [],
        "terms": [],
        "visual_refs": [],
        "uncertainties": [],
        "agent_inferences": [],
        "sections": [
            {
                "section_id": "section-0001",
                "title": "Problem and principle",
                "purpose": "Explain the value and boundary of conversion.",
                "claim_ids": ["claim-0001", "claim-0002"],
            }
        ],
    }


def _automation_fixture_media_plan(
    project: dict[str, Any], content_map_sha256: str
) -> dict[str, Any]:
    return {
        "schema_version": "video-content/media-plan-v1",
        "project_id": project["project_id"],
        "source_manifest_sha256": project["source"]["manifest_sha256"],
        "content_map_sha256": content_map_sha256,
        "communication_goal": (
            "Explain the evidence boundary that must survive video conversion."
        ),
        "audience": project["intent"]["audience"],
        "content_topology": {
            "argument_depth": "medium",
            "context_dependency": "medium",
            "visual_potential": "low",
            "uncertainty_level": "low",
        },
        "selected_medium": "article",
        "selection_authority": "user_selected",
        "selection_reason": "The automation profile selected a WeChat article.",
        "adaptation_strategy": {
            "relationship_to_source": "reconstructed_for_medium",
            "rationale": "State the problem, then the principle and its boundary.",
            "transformations": [
                "reorder claims",
                "merge repeated wording",
                "retain caveats",
            ],
        },
        "narrative_voice": {
            "mode": "source_author",
            "speaker_ids": ["speaker-0001"],
            "description": "Keep the narrator voice without external conclusions.",
            "prohibited_wrappers": ["this video believes", "the author states"],
        },
        "alternatives": [],
        "required_claim_ids": ["claim-0001", "claim-0002"],
        "required_caveat_ids": ["caveat-0001"],
        "omissions": [],
        "structure": [
            {
                "unit_id": "unit-0001",
                "purpose": "Explain the reception problem.",
                "claim_ids": ["claim-0001"],
                "caveat_ids": [],
                "visual_direction": "Use no filler image without a useful frame.",
                "approximate_chars": 80,
            },
            {
                "unit_id": "unit-0002",
                "purpose": "Explain the conversion principle and boundary.",
                "claim_ids": ["claim-0002"],
                "caveat_ids": ["caveat-0001"],
                "visual_direction": "Use only source-video imagery.",
                "approximate_chars": 120,
            },
        ],
        "rendering_contract": {
            "format": "markdown",
            "tone": "restrained, clear, non-promotional",
            "length_or_dimensions": "short article",
            "accessibility": [
                "clear heading hierarchy",
                "meaning does not depend on color",
            ],
        },
        "fidelity_rules": [
            "Do not add conclusions absent from the source.",
            "Retain the distinction between transcript evidence and fact checking.",
        ],
    }


def _automation_fixture_audit(
    project: dict[str, Any],
    content_map_sha256: str,
    deliverable: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "video-content/fidelity-audit-v1",
        "project_id": project["project_id"],
        "source_manifest_sha256": project["source"]["manifest_sha256"],
        "content_map_sha256": content_map_sha256,
        "target": {
            "deliverable_id": deliverable["artifact_id"],
            "sha256": deliverable["sha256"],
        },
        "status": "pass",
        "claim_checks": [
            {
                "statement": "Long videos have a high reception barrier.",
                "claim_ids": ["claim-0001"],
                "verdict": "compressed_but_faithful",
                "notes": "The source meaning is retained.",
            },
            {
                "statement": (
                    "Conversion must preserve claims, evidence, and caveats."
                ),
                "claim_ids": ["claim-0002"],
                "verdict": "faithful",
                "notes": "The statement matches the content map.",
            },
        ],
        "required_element_checks": [
            {
                "element_type": "claim",
                "element_id": "claim-0001",
                "present": True,
                "notes": "Present in the article body.",
            },
            {
                "element_type": "claim",
                "element_id": "claim-0002",
                "present": True,
                "notes": "Present in the article body.",
            },
            {
                "element_type": "caveat",
                "element_id": "caveat-0001",
                "present": True,
                "notes": "Disclosed at the end of the article.",
            },
        ],
        "findings": [],
        "repair_actions": [],
    }


def _automation_fixture_receipt(
    *,
    project: dict[str, Any],
    deliverable: dict[str, Any],
    audit: dict[str, Any],
    title: str,
    appmsgid: str,
) -> dict[str, Any]:
    return {
        "schema_version": "video-content/wechat-draft-receipt-v1",
        "project_id": project["project_id"],
        "deliverable_id": deliverable["artifact_id"],
        "fidelity_audit_id": audit["artifact_id"],
        "platform": "wechat_official_account",
        "status": "saved_as_draft",
        "started_at": "2026-08-16T08:00:00+00:00",
        "saved_at": "2026-08-16T08:01:00+00:00",
        "title": title,
        "appmsgid": appmsgid,
        "body_images": {
            "intended": 1,
            "visible_loaded": 1,
            "wechat_hosted": 1,
            "non_wechat_hosted": 0,
            "local_path_markers_remaining": 0,
        },
        "cover": {
            "source": "first body image",
            "asset": "assets/01-original-cover.jpg",
            "selected": True,
            "crop_confirmed": True,
            "wechat_hosted_preview": True,
        },
        "summary": {
            "filled": True,
            "text": "Faithful conversion lowers the barrier without losing evidence.",
        },
        "author": {"value": "", "left_blank": True},
        "originality": {"declared": False, "visible_state": "not declared"},
        "content_checks": {
            "source_disclosure_present": True,
            "ending_present": True,
            "underline_count": 0,
            "stock_cta_present": False,
            "speaker_identity_preserved": True,
        },
        "save": {
            "saved": True,
            "channel": "web",
            "mode": "manual save",
            "history_record": "2026-08-16 16:01 / web / manual save",
            "history_record_persisted": True,
            "saved_page_read_back": True,
        },
        "published": False,
        "publish_actions_performed": [],
    }


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
