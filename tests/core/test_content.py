from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from video_subtitle.core.content import (
    initialize_content_project,
    read_content_artifact,
    save_content_deliverable,
    save_content_document,
    validate_content_project,
)
from video_subtitle.core.srt import Cue, write_srt
from video_subtitle.core.util import read_json, write_json_atomic

SCHEMA_DIR = Path(__file__).parents[2] / "schemas"


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _manifest(tmp_path: Path) -> Path:
    subtitle_path = tmp_path / "subtitle.ocr.srt"
    write_srt(
        subtitle_path,
        [
            Cue(0, 4_000, "长视频的问题不是信息少，而是接收门槛高。"),
            Cue(4_000, 9_000, "转换媒介时要保留论点、证据和限定条件。"),
        ],
    )
    manifest = {
        "schema_version": "video-subtitle/v1",
        "job_id": "sub_content_test",
        "status": "completed",
        "stage": "done",
        "request": {"language": "zh-CN"},
        "video": {
            "title": "长视频如何转换为其他内容媒介",
            "author": "测试作者",
            "duration_seconds": 9,
        },
        "selected_source": {
            "kind": "hard_ocr",
            "fusion_status": "independent_evidence",
        },
        "review": None,
        "sources": [
            {
                "kind": "hard_ocr",
                "artifact_source": "hard_ocr:videocr",
                "cue_count": 2,
            }
        ],
        "attempts": [],
        "artifacts": [
            {
                "kind": "subtitle_srt",
                "path": str(subtitle_path),
                "source": "hard_ocr:videocr",
                "owned_by_job": True,
                "selected": True,
            }
        ],
        "warnings": [],
        "error": None,
    }
    manifest_path = tmp_path / "manifest.json"
    write_json_atomic(manifest_path, manifest)
    return manifest_path


def _content_map(project: dict) -> dict:
    return {
        "schema_version": "video-content/content-map-v1",
        "project_id": project["project_id"],
        "source_manifest_sha256": project["source"]["manifest_sha256"],
        "content_type": "explanation",
        "summary": "长视频需要转换为更低接收门槛的载体，但压缩时必须保留论证边界。",
        "coverage": {
            "mode": "full",
            "evidence_ids": ["ev-0001"],
            "analyzed_ranges": [{"start_ms": 0, "end_ms": 9_000}],
            "omitted_ranges": [],
        },
        "thesis": {
            "text": "媒介可以改变，证据边界不能丢失。",
            "claim_ids": ["claim-0001", "claim-0002"],
        },
        "evidence_refs": [
            {
                "evidence_ref_id": "evref-0001",
                "evidence_id": "ev-0001",
                "cue_ids": ["ev-0001-cue-00001"],
                "start_ms": 0,
                "end_ms": 4_000,
                "text": "长视频的问题不是信息少，而是接收门槛高。",
                "language": "zh-CN",
                "relationship": "supports",
            },
            {
                "evidence_ref_id": "evref-0002",
                "evidence_id": "ev-0001",
                "cue_ids": ["ev-0001-cue-00002"],
                "start_ms": 4_000,
                "end_ms": 9_000,
                "text": "转换媒介时要保留论点、证据和限定条件。",
                "language": "zh-CN",
                "relationship": "supports",
            },
        ],
        "speakers": [
            {"speaker_id": "speaker-0001", "name": "测试作者", "role": "讲述者"}
        ],
        "claims": [
            {
                "claim_id": "claim-0001",
                "text": "长视频具有较高的接收门槛。",
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
                "text": "转换媒介必须保留论点、证据和限定条件。",
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
                "text": "字幕只能证明视频表达了什么，不自动证明观点为事实。",
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
                "title": "问题与原则",
                "purpose": "说明为什么需要转换以及转换边界",
                "claim_ids": ["claim-0001", "claim-0002"],
            }
        ],
    }


def _media_plan(project: dict, content_map_sha256: str) -> dict:
    return {
        "schema_version": "video-content/media-plan-v1",
        "project_id": project["project_id"],
        "source_manifest_sha256": project["source"]["manifest_sha256"],
        "content_map_sha256": content_map_sha256,
        "communication_goal": "让没有时间看视频的人理解核心观点及其边界",
        "audience": "对主题有轻度兴趣但时间有限的人",
        "content_topology": {
            "argument_depth": "medium",
            "context_dependency": "medium",
            "visual_potential": "high",
            "uncertainty_level": "low",
        },
        "selected_medium": "one_page",
        "selection_reason": "两个核心观点可以在单页中形成问题—原则结构。",
        "alternatives": [
            {"medium": "article", "rejected_because": "当前论证较短，不需要长文展开。"}
        ],
        "required_claim_ids": ["claim-0001", "claim-0002"],
        "required_caveat_ids": ["caveat-0001"],
        "omissions": [],
        "structure": [
            {
                "unit_id": "unit-0001",
                "purpose": "呈现问题",
                "claim_ids": ["claim-0001"],
                "caveat_ids": [],
                "visual_direction": "用门槛图形表现观看成本",
                "approximate_chars": 40,
            },
            {
                "unit_id": "unit-0002",
                "purpose": "呈现转换原则与边界",
                "claim_ids": ["claim-0002"],
                "caveat_ids": ["caveat-0001"],
                "visual_direction": "用证据链表现可追溯关系",
                "approximate_chars": 80,
            },
        ],
        "rendering_contract": {
            "format": "svg",
            "tone": "克制、清晰、非营销",
            "length_or_dimensions": "1080x1440",
            "accessibility": ["正文不小于32px", "颜色不是唯一编码"],
        },
        "fidelity_rules": [
            "不得新增视频未表达的结论",
            "必须保留字幕证据不等于事实核验的限定",
        ],
    }


def _audit(project: dict, content_map_sha256: str, deliverable: dict) -> dict:
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
                "statement": "长视频的接收门槛高",
                "claim_ids": ["claim-0001"],
                "verdict": "compressed_but_faithful",
                "notes": "保留了原句的核心含义",
            },
            {
                "statement": "转换媒介必须保留论点、证据和限定条件",
                "claim_ids": ["claim-0002"],
                "verdict": "faithful",
                "notes": "与内容地图一致",
            },
        ],
        "required_element_checks": [
            {
                "element_type": "claim",
                "element_id": "claim-0001",
                "present": True,
                "notes": "位于问题区",
            },
            {
                "element_type": "claim",
                "element_id": "claim-0002",
                "present": True,
                "notes": "位于原则区",
            },
            {
                "element_type": "caveat",
                "element_id": "caveat-0001",
                "present": True,
                "notes": "位于页脚限定说明",
            },
        ],
        "findings": [],
        "repair_actions": [],
    }


def test_content_project_versions_agent_artifacts_and_preserves_evidence(
    tmp_path: Path,
) -> None:
    manifest_path = _manifest(tmp_path)
    evidence_path = tmp_path / "subtitle.ocr.srt"
    evidence_before = evidence_path.read_bytes()

    project = initialize_content_project(
        manifest_path,
        audience="时间有限的普通读者",
    )
    project_path = Path(project["project_path"])
    jsonschema.validate(read_json(project_path), _schema("content-project.schema.json"))

    map_result = save_content_document(
        project_path,
        kind="content_map",
        document=_content_map(project),
    )
    map_path = project_path.parent / map_result["artifact"]["path"]
    jsonschema.validate(read_json(map_path), _schema("content-map.schema.json"))

    plan = _media_plan(project, map_result["artifact"]["sha256"])
    plan_result = save_content_document(
        project_path,
        kind="media_plan",
        document=plan,
    )
    plan_path = project_path.parent / plan_result["artifact"]["path"]
    jsonschema.validate(read_json(plan_path), _schema("media-plan.schema.json"))

    deliverable_result = save_content_deliverable(
        project_path,
        medium="one_page",
        format="svg",
        title="长视频转换原则",
        content="<svg><text>长视频的接收门槛高；转换时保留论点、证据和限定条件。</text></svg>",
        used_claim_ids=["claim-0001", "claim-0002"],
        used_caveat_ids=["caveat-0001"],
    )
    deliverable = deliverable_result["deliverable"]
    audit = _audit(project, map_result["artifact"]["sha256"], deliverable)
    audit_result = save_content_document(
        project_path,
        kind="fidelity_audit",
        document=audit,
    )
    audit_path = project_path.parent / audit_result["artifact"]["path"]
    jsonschema.validate(read_json(audit_path), _schema("fidelity-audit.schema.json"))
    jsonschema.validate(read_json(project_path), _schema("content-project.schema.json"))

    validation = validate_content_project(project_path)
    assert validation["valid"] is True
    assert validation["ready_for_delivery"] is True
    assert evidence_path.read_bytes() == evidence_before

    read_result = read_content_artifact(
        project_path,
        artifact="latest_deliverable",
        max_chars=10,
    )
    assert read_result["has_more"] is True
    assert read_result["content"] == "<svg><text"


def test_content_project_is_idempotent_for_the_same_intent(tmp_path: Path) -> None:
    manifest_path = _manifest(tmp_path)
    first = initialize_content_project(manifest_path, audience="读者")
    second = initialize_content_project(manifest_path, audience="读者")
    different = initialize_content_project(manifest_path, audience="专业研究者")

    assert second["project_id"] == first["project_id"]
    assert second["reused_existing_project"] is True
    assert different["project_id"] != first["project_id"]


def test_content_map_rejects_unknown_evidence_reference(tmp_path: Path) -> None:
    project = initialize_content_project(_manifest(tmp_path))
    document = _content_map(project)
    document["claims"][0]["evidence_refs"] = ["evref-9999"]

    with pytest.raises(ValueError, match="unknown references"):
        save_content_document(
            Path(project["project_path"]),
            kind="content_map",
            document=document,
        )


def test_deliverable_requires_every_media_plan_core_element(tmp_path: Path) -> None:
    project = initialize_content_project(_manifest(tmp_path))
    project_path = Path(project["project_path"])
    map_result = save_content_document(
        project_path,
        kind="content_map",
        document=_content_map(project),
    )
    save_content_document(
        project_path,
        kind="media_plan",
        document=_media_plan(project, map_result["artifact"]["sha256"]),
    )

    with pytest.raises(ValueError, match="missing required claim"):
        save_content_deliverable(
            project_path,
            medium="one_page",
            format="svg",
            title="不完整稿",
            content="<svg />",
            used_claim_ids=["claim-0001"],
            used_caveat_ids=["caveat-0001"],
        )


def test_validation_detects_changed_source_evidence(tmp_path: Path) -> None:
    manifest_path = _manifest(tmp_path)
    project = initialize_content_project(manifest_path)
    (tmp_path / "subtitle.ocr.srt").write_text("changed", encoding="utf-8")

    validation = validate_content_project(Path(project["project_path"]))

    assert validation["valid"] is False
    assert validation["errors"][0]["code"] == "EVIDENCE_ev-0001_CHANGED"


def test_passing_audit_must_cover_every_used_claim(tmp_path: Path) -> None:
    project = initialize_content_project(_manifest(tmp_path))
    project_path = Path(project["project_path"])
    map_result = save_content_document(
        project_path,
        kind="content_map",
        document=_content_map(project),
    )
    save_content_document(
        project_path,
        kind="media_plan",
        document=_media_plan(project, map_result["artifact"]["sha256"]),
    )
    deliverable = save_content_deliverable(
        project_path,
        medium="one_page",
        format="svg",
        title="完整稿",
        content="<svg />",
        used_claim_ids=["claim-0001", "claim-0002"],
        used_caveat_ids=["caveat-0001"],
    )["deliverable"]
    audit = _audit(project, map_result["artifact"]["sha256"], deliverable)
    audit["claim_checks"] = audit["claim_checks"][:1]

    with pytest.raises(ValueError, match="does not cover used claims"):
        save_content_document(
            project_path,
            kind="fidelity_audit",
            document=audit,
        )
