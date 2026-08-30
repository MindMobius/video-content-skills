from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .frames import image_dimensions
from .jobs import update_job
from .models import CONTENT_SCHEMA, TRANSCRIPT_SCHEMA, Content, Transcript
from .store import Store
from .util import reject_secrets, sha256_file, utc_now
from .wechat_renderer import MANUSCRIPT_VERSION, render_wechat_package

_ALLOWED_MEDIA_SOURCES = {"video_cover", "video_frame"}
_APPROVED_AUDIT_STATES = {"passed", "approved"}
_RAW_TRANSCRIPT_MIN_BODY_CHARS = 500
_RAW_TRANSCRIPT_SHINGLE_SIZE = 12
_RAW_TRANSCRIPT_MIN_OVERLAP = 0.90
_RAW_TRANSCRIPT_MAX_PUNCTUATION_PER_100 = 4.0
_RAW_TRANSCRIPT_MIN_MAX_CLAUSE = 60
_WRITTEN_BLOCK_TYPES = {"paragraph", "lead", "key_point", "quote"}
_EXPRESSION_AUDIT_POLICY = "source_aware_minimal"
_EXPRESSION_AUDIT_REQUIRED_TARGETS = {
    "title_summary",
    "headings",
    "transitions",
    "evidence_boundaries",
    "ending",
    "material_details",
}
_EXPRESSION_AUDIT_REQUIRED_CHECKS = {
    "source_expression_priority",
    "information_density_preserved",
    "structure_and_media_preserved",
    "final_source_fidelity_rechecked",
}
_EXPRESSION_AUDIT_RULES = {
    "manufactured_contrast",
    "empty_signpost",
    "repeated_sentence_scaffold",
    "agent_abstraction",
    "carrier_template",
    "dense_enumeration",
    "missing_anaphora",
    "translationese_shell",
    "decorative_personification",
}
_EXPRESSION_AUDIT_DECISIONS = {"revised", "retained"}
_EXPRESSION_AUDIT_ORIGINS = {
    "agent_added",
    "carrier_adaptation",
    "source_expression",
}
_EXPRESSION_AUDIT_REVISED_ORIGINS = {"agent_added", "carrier_adaptation"}
_EXPRESSION_AUDIT_TARGET_FIELDS = {"title", "summary", "block"}
_EXPRESSION_AUDIT_TEXT_BLOCK_TYPES = {
    "heading",
    "paragraph",
    "lead",
    "key_point",
    "quote",
    "list",
}


def _store_content_render_asset(
    store: Store, job_id: str, path: Path
) -> dict[str, Any]:
    digest = sha256_file(path)
    existing = next(
        (
            reference
            for reference in store.list_artifacts(job_id, kind="content_render")
            if reference.get("sha256") == digest
        ),
        None,
    )
    if existing is not None:
        store.read_artifact(job_id, str(existing["artifact_id"]))
        return existing
    return store.put_artifact(
        job_id,
        kind="content_render",
        source_path=path,
    )


def transcript_save(
    store: Store,
    *,
    job_id: str,
    evidence_ids: list[str],
    cues: list[dict[str, Any]],
    text: str,
    corrections: list[dict[str, Any]] | None = None,
    uncertainties: list[dict[str, Any]] | None = None,
    quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    job = store.get_job(job_id)
    if job["stage"] not in {"evidence", "transcript", "content", "handoff"}:
        raise ValueError("Transcript requires completed evidence acquisition")
    _require_transcript_evidence_ready(store, job_id, evidence_ids)
    _validate_cues(cues)
    selected_quality = dict(quality or {})
    if selected_quality.get("status") not in {"usable", "verified"}:
        raise ValueError("Transcript quality.status must be usable or verified")
    basis = {
        "job_id": job_id,
        "evidence_ids": evidence_ids,
        "cues": cues,
        "text": text,
        "corrections": corrections or [],
        "uncertainties": uncertainties or [],
        "quality": selected_quality,
    }
    transcript_id = _stable_id("transcript", basis)
    existing = _find_product(
        store, job_id, "transcript", "transcript_id", transcript_id
    )
    if existing:
        return {"transcript": existing, "reused": True, "job": store.get_job(job_id)}
    document = Transcript(
        transcript_id=transcript_id,
        job_id=job_id,
        evidence_ids=evidence_ids,
        cues=cues,
        text=text,
        corrections=corrections or [],
        uncertainties=uncertainties or [],
        quality=selected_quality,
        created_at=utc_now(),
        schema_version=TRANSCRIPT_SCHEMA,
    ).as_dict()
    saved, reference = store.save_document(
        job_id,
        kind="transcript",
        document=document,
        identifier_field="transcript_id",
        identifier_prefix="transcript",
    )
    current = store.get_job(job_id)
    if current["stage"] == "evidence":
        current = update_job(store, job_id, stage="transcript", status="running")
    return {"transcript": saved, "artifact": reference, "reused": False, "job": current}


def content_save(
    store: Store,
    *,
    job_id: str,
    transcript_id: str,
    carrier: str,
    document: dict[str, Any],
    media: list[dict[str, Any]] | None = None,
    audit: dict[str, Any] | None = None,
    render: bool = True,
) -> dict[str, Any]:
    store.get_job(job_id)
    _require_product_ids(
        store,
        job_id,
        kind="transcript",
        field="transcript_id",
        values=[transcript_id],
    )
    selected_media = list(media or _media_from_document(document))
    _validate_media(store, job_id, selected_media)
    _validate_document_media_alignment(document, selected_media)
    selected_audit = dict(audit or {})
    if selected_audit.get("status") not in _APPROVED_AUDIT_STATES:
        raise ValueError("Content audit.status must be passed or approved")
    reject_secrets(document)
    basis = {
        "job_id": job_id,
        "transcript_id": transcript_id,
        "carrier": carrier,
        "document": document,
        "media": selected_media,
        "audit": selected_audit,
    }
    content_id = _stable_id("content", basis)
    existing = _find_product(store, job_id, "content", "content_id", content_id)
    if existing:
        return {
            "content": existing,
            "reused": True,
            "validation": content_validate(store, job_id=job_id, content_id=content_id),
            "job": store.get_job(job_id),
        }

    render_references: list[dict[str, Any]] = []
    render_result: dict[str, Any] | None = None
    if carrier == "wechat_article" and render:
        manuscript = _stage_wechat_manuscript(store, job_id, content_id, document)
        render_root = store.job_dir(job_id) / "work" / content_id / "render"
        render_result = render_wechat_package(manuscript, render_root)
        for record in render_result["files"]:
            path = render_root / record["path"]
            stored_reference = _store_content_render_asset(store, job_id, path)
            render_references.append(
                {
                    **stored_reference,
                    "metadata": {
                        "content_id": content_id,
                        "relative_path": record["path"],
                    },
                }
            )
    product = Content(
        content_id=content_id,
        job_id=job_id,
        transcript_id=transcript_id,
        carrier=carrier,
        document=document,
        media=selected_media,
        audit=selected_audit,
        artifact_refs=render_references,
        created_at=utc_now(),
        schema_version=CONTENT_SCHEMA,
    ).as_dict()
    saved, reference = store.save_document(
        job_id,
        kind="content",
        document=product,
        identifier_field="content_id",
        identifier_prefix="content",
    )
    current = store.get_job(job_id)
    if current["stage"] in {"evidence", "transcript"}:
        current = update_job(store, job_id, stage="content", status="running")
    validation = content_validate(store, job_id=job_id, content_id=content_id)
    return {
        "content": saved,
        "artifact": reference,
        "render": render_result,
        "validation": validation,
        "reused": False,
        "job": current,
    }


def content_validate(store: Store, *, job_id: str, content_id: str) -> dict[str, Any]:
    content = _find_product(store, job_id, "content", "content_id", content_id)
    if content is None:
        raise FileNotFoundError(f"Content not found: {content_id}")
    errors: list[str] = []
    try:
        _require_product_ids(
            store,
            job_id,
            kind="transcript",
            field="transcript_id",
            values=[str(content.get("transcript_id") or "")],
        )
    except (FileNotFoundError, ValueError) as error:
        errors.append(str(error))
    try:
        selected_media = list(content.get("media") or [])
        _validate_media(store, job_id, selected_media)
        _validate_document_media_alignment(
            dict(content.get("document") or {}), selected_media
        )
    except (FileNotFoundError, ValueError) as error:
        errors.append(str(error))
    if content.get("audit", {}).get("status") not in _APPROVED_AUDIT_STATES:
        errors.append("Content audit is not approved")
    errors.extend(_profile_content_contract_errors(store, job_id, content))
    for reference in content.get("artifact_refs", []):
        try:
            store.read_artifact(job_id, str(reference["artifact_id"]))
        except (FileNotFoundError, ValueError) as error:
            errors.append(str(error))
    try:
        reject_secrets(content)
    except ValueError as error:
        errors.append(str(error))
    return {
        "schema_version": "video-content/content-validation-v1",
        "content_id": content_id,
        "job_id": job_id,
        "valid": not errors,
        "errors": errors,
        "checked_at": utc_now(),
    }


def _profile_content_contract_errors(
    store: Store, job_id: str, content: dict[str, Any]
) -> list[str]:
    job = store.get_job(job_id)
    profile_id = str(job.get("profile_id") or "").strip()
    if not profile_id:
        return []
    try:
        settings = dict(store.get_profile(profile_id).get("settings") or {})
    except FileNotFoundError as error:
        return [str(error)]
    expected_mode = settings.get("adaptation_mode")
    if expected_mode != "source_faithful_full":
        return []

    errors: list[str] = []
    audit = content.get("audit")
    if not isinstance(audit, dict):
        return ["source_faithful_full Content requires an audit object"]
    if audit.get("adaptation_mode") != expected_mode:
        errors.append("source_faithful_full Content audit must declare adaptation_mode")
    expected_visual_policy = settings.get("visual_policy")
    if audit.get("visual_policy") != expected_visual_policy:
        errors.append("Content audit visual_policy does not match the Profile")

    document = dict(content.get("document") or {})
    blocks = list(document.get("blocks") or [])
    transcript = _find_product(
        store,
        job_id,
        "transcript",
        "transcript_id",
        str(content.get("transcript_id") or ""),
    )
    cue_count = len(list((transcript or {}).get("cues") or []))
    errors.extend(_written_adaptation_errors(document, transcript))
    errors.extend(_expression_audit_errors(document, audit.get("expression_audit")))

    sections = audit.get("material_sections")
    if not isinstance(sections, dict):
        errors.append("Content audit requires material_sections")
    else:
        total = sections.get("total")
        preserved = sections.get("preserved")
        items = sections.get("items")
        if not isinstance(items, list) or not items:
            errors.append("Content audit requires material_sections.items")
            items = []
        preserved_items = 0
        section_ids: set[str] = set()
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(f"material_sections.items[{index}] must be an object")
                continue
            section_id = str(item.get("section_id") or "").strip()
            label = str(item.get("label") or "").strip()
            if not section_id or section_id in section_ids:
                errors.append(
                    f"material_sections.items[{index}] requires a unique section_id"
                )
            else:
                section_ids.add(section_id)
            if not label:
                errors.append(f"material_sections.items[{index}] requires a label")
            if item.get("status") != "preserved":
                errors.append(
                    f"material_sections.items[{index}] must have status=preserved"
                )
            else:
                preserved_items += 1
            source_cues = item.get("source_cue_indices")
            if not isinstance(source_cues, list) or not source_cues:
                errors.append(
                    f"material_sections.items[{index}] requires source_cue_indices"
                )
            else:
                for cue_index in source_cues:
                    if (
                        not isinstance(cue_index, int)
                        or isinstance(cue_index, bool)
                        or cue_index < 0
                        or cue_index >= cue_count
                    ):
                        errors.append(
                            f"material_sections.items[{index}] has an invalid source cue index"
                        )
                        break
            output_indices = item.get("output_block_indices")
            if not isinstance(output_indices, list) or not output_indices:
                errors.append(
                    f"material_sections.items[{index}] requires output_block_indices"
                )
            else:
                selected_blocks: list[dict[str, Any]] = []
                for block_index in output_indices:
                    if (
                        not isinstance(block_index, int)
                        or isinstance(block_index, bool)
                        or block_index < 0
                        or block_index >= len(blocks)
                    ):
                        errors.append(
                            f"material_sections.items[{index}] has an invalid output block index"
                        )
                        continue
                    block = blocks[block_index]
                    if isinstance(block, dict):
                        selected_blocks.append(block)
                if selected_blocks and not any(
                    block.get("type") != "image"
                    and str(block.get("text") or "").strip()
                    for block in selected_blocks
                ):
                    errors.append(
                        f"material_sections.items[{index}] must map to written content"
                    )
        if (
            not isinstance(total, int)
            or isinstance(total, bool)
            or total <= 0
            or total != len(items)
            or not isinstance(preserved, int)
            or isinstance(preserved, bool)
            or preserved != total
            or preserved_items != total
        ):
            errors.append(
                "Content audit material_sections must explicitly preserve every material section"
            )
    if not isinstance(audit.get("omissions"), list):
        errors.append("Content audit omissions must be an explicit list")

    minimum_frames = settings.get("minimum_source_frames", 0)
    if (
        not isinstance(minimum_frames, int)
        or isinstance(minimum_frames, bool)
        or minimum_frames < 0
    ):
        errors.append("Profile minimum_source_frames must be a non-negative integer")
        minimum_frames = 0
    frames = [
        item
        for item in list(content.get("media") or [])
        if item.get("source_kind") == "video_frame"
    ]
    if len(frames) < minimum_frames:
        exception = audit.get("visual_exception")
        if not _valid_visual_exception(store, job_id, exception):
            errors.append(
                f"Content requires minimum_source_frames={minimum_frames}; found {len(frames)}"
            )
    errors.extend(_final_source_frame_errors(store, job_id, frames))

    plan = audit.get("visual_plan")
    if not isinstance(plan, list):
        errors.append("Content audit requires a visual_plan list")
        return errors
    planned: dict[str, dict[str, Any]] = {}
    planned_block_indices: set[int] = set()
    for index, item in enumerate(plan):
        if not isinstance(item, dict):
            errors.append(f"visual_plan[{index}] must be an object")
            continue
        artifact_id = str(item.get("artifact_id") or "")
        timestamp_ms = item.get("timestamp_ms")
        block_index = item.get("block_index")
        reason = str(item.get("reason") or "").strip()
        if not artifact_id or artifact_id in planned:
            errors.append(f"visual_plan[{index}] requires a unique artifact_id")
            continue
        if not isinstance(timestamp_ms, int) or isinstance(timestamp_ms, bool):
            errors.append(f"visual_plan[{index}] requires timestamp_ms")
        if (
            not isinstance(block_index, int)
            or isinstance(block_index, bool)
            or block_index < 0
            or block_index >= len(blocks)
        ):
            errors.append(f"visual_plan[{index}] requires a valid block_index")
        elif block_index in planned_block_indices:
            errors.append(f"visual_plan[{index}] requires a unique block_index")
        else:
            planned_block_indices.add(block_index)
            block = blocks[block_index]
            if (
                not isinstance(block, dict)
                or block.get("type") != "image"
                or str(block.get("artifact_id") or "") != artifact_id
                or block.get("source_kind") != "video_frame"
            ):
                errors.append(
                    f"visual_plan[{index}] does not point to its document image block"
                )
        if not reason:
            errors.append(f"visual_plan[{index}] requires a placement reason")
        planned[artifact_id] = item
    frame_ids = {str(item.get("artifact_id") or "") for item in frames}
    if set(planned) != frame_ids:
        errors.append(
            "visual_plan must cover exactly the Content video_frame artifacts"
        )
    for frame in frames:
        artifact_id = str(frame.get("artifact_id") or "")
        plan_item = planned.get(artifact_id)
        if plan_item is None:
            continue
        if plan_item.get("timestamp_ms") != frame.get("timestamp_ms"):
            errors.append(
                f"visual_plan timestamp does not match media for {artifact_id}"
            )
    return errors


def _final_source_frame_errors(
    store: Store, job_id: str, frames: list[dict[str, Any]]
) -> list[str]:
    errors: list[str] = []
    for frame in frames:
        artifact_id = str(frame.get("artifact_id") or "")
        problems: list[str] = []
        try:
            reference, _ = store.read_artifact(job_id, artifact_id)
        except (FileNotFoundError, ValueError) as error:
            errors.append(
                f"video_frame {artifact_id or '<missing>'} must be a final source extraction: {error}"
            )
            continue
        metadata = reference.get("metadata", {})
        if metadata.get("extraction_role") != "final":
            problems.append("extraction_role must be final")
        if metadata.get("extraction_method") != "ffmpeg_source_frame":
            problems.append("extraction_method must be ffmpeg_source_frame")
        if metadata.get("resolution_policy") != "source_display_native":
            problems.append("resolution_policy must be source_display_native")
        if metadata.get("display_aspect_preserved") is not True:
            problems.append("display_aspect_preserved must be true")
        if metadata.get("timestamp_ms") != frame.get("timestamp_ms"):
            problems.append("timestamp_ms does not match Content media")
        width = metadata.get("pixel_width")
        height = metadata.get("pixel_height")
        if (
            not isinstance(width, int)
            or isinstance(width, bool)
            or width <= 0
            or not isinstance(height, int)
            or isinstance(height, bool)
            or height <= 0
        ):
            problems.append("pixel dimensions must be positive integers")
        else:
            try:
                actual_width, actual_height = image_dimensions(
                    store.job_dir(job_id) / reference["path"]
                )
            except (OSError, ValueError) as error:
                problems.append(str(error))
            else:
                if (actual_width, actual_height) != (width, height):
                    problems.append("pixel dimensions do not match Artifact bytes")
        source_artifact_id = str(metadata.get("source_video_artifact_id") or "")
        if not source_artifact_id:
            problems.append("source_video_artifact_id is required")
        else:
            try:
                source_reference, _ = store.read_artifact(job_id, source_artifact_id)
            except (FileNotFoundError, ValueError) as error:
                problems.append(str(error))
            else:
                if source_reference.get("kind") != "source_video":
                    problems.append(
                        "source_video_artifact_id must reference source_video"
                    )
                if metadata.get("source_video_sha256") != source_reference.get(
                    "sha256"
                ):
                    problems.append(
                        "source_video_sha256 does not match source Artifact"
                    )
        if problems:
            errors.append(
                f"video_frame {artifact_id} must be a final source extraction: "
                + "; ".join(problems)
            )
    return errors


def _expression_audit_errors(document: dict[str, Any], value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["source_faithful_full Content requires audit.expression_audit"]

    errors: list[str] = []
    status = value.get("status")
    if not isinstance(status, str) or status not in _APPROVED_AUDIT_STATES:
        errors.append("expression_audit status must be passed or approved")
    if value.get("reviewed_by") != "agent":
        errors.append("expression_audit reviewed_by must be agent")
    if value.get("policy") != _EXPRESSION_AUDIT_POLICY:
        errors.append(f"expression_audit policy must be {_EXPRESSION_AUDIT_POLICY}")

    reviewed_targets = value.get("reviewed_targets")
    if not isinstance(reviewed_targets, list) or not all(
        isinstance(item, str) and item.strip() for item in reviewed_targets
    ):
        errors.append("expression_audit reviewed_targets must be a text list")
    else:
        missing_targets = sorted(
            _EXPRESSION_AUDIT_REQUIRED_TARGETS - set(reviewed_targets)
        )
        if missing_targets:
            errors.append(
                "expression_audit reviewed_targets missing: "
                + ", ".join(missing_targets)
            )

    checks = value.get("checks")
    if not isinstance(checks, dict):
        errors.append("expression_audit checks must be an object")
    else:
        failed_checks = sorted(
            key
            for key in _EXPRESSION_AUDIT_REQUIRED_CHECKS
            if checks.get(key) is not True
        )
        if failed_checks:
            errors.append(
                "expression_audit checks must be true: " + ", ".join(failed_checks)
            )

    items = value.get("items")
    if not isinstance(items, list):
        errors.append("expression_audit items must be a list")
        return errors

    for index, item in enumerate(items):
        prefix = f"expression_audit.items[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue

        rule = item.get("rule")
        if not isinstance(rule, str) or rule not in _EXPRESSION_AUDIT_RULES:
            errors.append(f"{prefix}.rule is unsupported")

        decision = item.get("decision")
        if not isinstance(decision, str) or decision not in _EXPRESSION_AUDIT_DECISIONS:
            errors.append(f"{prefix}.decision must be revised or retained")

        origin = item.get("origin")
        if not isinstance(origin, str) or origin not in _EXPRESSION_AUDIT_ORIGINS:
            errors.append(f"{prefix}.origin is unsupported")

        reason = item.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"{prefix}.reason must explain the source/editorial judgment")
        elif "".join(reason.split()) == "去AI味":
            errors.append(f"{prefix}.reason cannot only say 去 AI 味")

        before = item.get("before")
        after = item.get("after")
        if not isinstance(before, str) or not before.strip():
            errors.append(f"{prefix}.before must be complete non-empty text")
        if not isinstance(after, str) or not after.strip():
            errors.append(f"{prefix}.after must be complete non-empty text")

        target = item.get("target")
        target_text, target_error = _expression_audit_target_text(document, target)
        if target_error:
            errors.append(f"{prefix}.{target_error}")
        elif isinstance(after, str) and after != target_text:
            errors.append(
                f"{prefix}.after does not match the final document target text"
            )

        if decision == "revised":
            if isinstance(before, str) and isinstance(after, str) and before == after:
                errors.append(f"{prefix} revised text must change before to after")
            if origin not in _EXPRESSION_AUDIT_REVISED_ORIGINS:
                errors.append(
                    f"{prefix} cannot revise origin={origin}; "
                    "source_expression must be retained"
                )
        elif (
            decision == "retained"
            and isinstance(before, str)
            and isinstance(after, str)
            and before != after
        ):
            errors.append(f"{prefix} retained text must keep before equal to after")

    return errors


def _expression_audit_target_text(
    document: dict[str, Any], target: Any
) -> tuple[str | None, str | None]:
    if not isinstance(target, dict):
        return None, "target must be an object"
    field = target.get("field")
    if not isinstance(field, str) or field not in _EXPRESSION_AUDIT_TARGET_FIELDS:
        return None, "target.field must be title, summary, or block"
    if field in {"title", "summary"}:
        value = document.get(field)
        if not isinstance(value, str) or not value.strip():
            return None, f"target.field={field} is missing from the final document"
        return value, None

    block_index = target.get("block_index")
    blocks = document.get("blocks")
    if (
        not isinstance(blocks, list)
        or not isinstance(block_index, int)
        or isinstance(block_index, bool)
        or block_index < 0
        or block_index >= len(blocks)
    ):
        return None, "target.block_index must point to a valid text block"
    block = blocks[block_index]
    block_type = block.get("type") if isinstance(block, dict) else None
    if (
        not isinstance(block_type, str)
        or block_type not in _EXPRESSION_AUDIT_TEXT_BLOCK_TYPES
    ):
        return None, "target.block_index must point to a valid text block"
    if block_type == "list":
        items = block.get("items")
        if not isinstance(items, list) or not all(
            isinstance(item, str) and item.strip() for item in items
        ):
            return None, "target.block_index must point to a valid text block"
        return "\n".join(items), None
    text = block.get("text")
    if not isinstance(text, str) or not text.strip():
        return None, "target.block_index must point to a valid text block"
    return text, None


def _written_adaptation_errors(
    document: dict[str, Any], transcript: dict[str, Any] | None
) -> list[str]:
    """Reject only the high-confidence shape of mechanically pasted cues.

    This is a handoff safety check, not a style score: source wording may remain
    highly similar when the source itself already has publication-ready sentences.
    """
    if not isinstance(transcript, dict):
        return []
    body_text = _written_body_text(document)
    source_text = "".join(
        str(cue.get("text") or "")
        for cue in list(transcript.get("cues") or [])
        if isinstance(cue, dict)
    )
    normalized_body = _normalize_written_text(body_text)
    normalized_source = _normalize_written_text(source_text)
    if (
        len(normalized_body) < _RAW_TRANSCRIPT_MIN_BODY_CHARS
        or len(normalized_source) < _RAW_TRANSCRIPT_MIN_BODY_CHARS
    ):
        return []

    overlap = _shingle_coverage(
        normalized_body,
        normalized_source,
        size=_RAW_TRANSCRIPT_SHINGLE_SIZE,
    )
    punctuation_count = sum(body_text.count(char) for char in "，。！？；：,.!?;:")
    punctuation_per_100 = punctuation_count * 100 / len(normalized_body)
    clauses = [
        _normalize_written_text(value)
        for value in re.split(r"[，。！？；：,.!?;:\n]+", body_text)
    ]
    max_clause = max((len(value) for value in clauses), default=0)
    if (
        overlap >= _RAW_TRANSCRIPT_MIN_OVERLAP
        and punctuation_per_100 < _RAW_TRANSCRIPT_MAX_PUNCTUATION_PER_100
        and max_clause >= _RAW_TRANSCRIPT_MIN_MAX_CLAUSE
    ):
        return [
            (
                "source_faithful_full Content looks like raw Transcript passthrough "
                f"(12-character overlap={overlap:.1%}, "
                f"punctuation={punctuation_per_100:.1f}/100 characters, "
                f"max_clause={max_clause}); produce a readable written edition before handoff"
            )
        ]
    return []


def _written_body_text(document: dict[str, Any]) -> str:
    parts: list[str] = []
    for block in list(document.get("blocks") or []):
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type in _WRITTEN_BLOCK_TYPES:
            if value := str(block.get("text") or "").strip():
                parts.append(value)
        elif block_type == "list":
            for item in list(block.get("items") or []):
                if value := str(item or "").strip():
                    parts.append(value)
    return "\n".join(parts)


def _normalize_written_text(value: str) -> str:
    return "".join(char.lower() for char in value if char.isalnum())


def _shingle_coverage(value: str, source: str, *, size: int) -> float:
    if len(value) < size or len(source) < size:
        return 0.0
    source_shingles = {
        source[index : index + size] for index in range(len(source) - size + 1)
    }
    windows = len(value) - size + 1
    matches = sum(
        value[index : index + size] in source_shingles for index in range(windows)
    )
    return matches / windows


def _valid_visual_exception(store: Store, job_id: str, value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("approved") is not True or not str(value.get("reason") or "").strip():
        return False
    evidence_ids = value.get("evidence_artifact_ids")
    if not isinstance(evidence_ids, list) or not evidence_ids:
        return False
    for artifact_id in evidence_ids:
        try:
            reference, _ = store.read_artifact(job_id, str(artifact_id or ""))
        except (FileNotFoundError, ValueError):
            return False
        if reference.get("kind") not in {
            "ocr_scout_contact_sheet",
            "ocr_scout_plan",
        }:
            return False
    return True


def get_transcript(store: Store, job_id: str, transcript_id: str) -> dict[str, Any]:
    document = _find_product(
        store, job_id, "transcript", "transcript_id", transcript_id
    )
    if document is None:
        raise FileNotFoundError(f"Transcript not found: {transcript_id}")
    return document


def get_content(store: Store, job_id: str, content_id: str) -> dict[str, Any]:
    document = _find_product(store, job_id, "content", "content_id", content_id)
    if document is None:
        raise FileNotFoundError(f"Content not found: {content_id}")
    return document


def _stage_wechat_manuscript(
    store: Store, job_id: str, content_id: str, document: dict[str, Any]
) -> Path:
    manuscript = json.loads(json.dumps(document, ensure_ascii=False))
    manuscript.setdefault("schema_version", MANUSCRIPT_VERSION)
    for block in manuscript.get("blocks") or []:
        if block.get("type") != "image":
            continue
        artifact_id = str(block.pop("artifact_id", ""))
        reference, _ = store.read_artifact(job_id, artifact_id)
        block["path"] = str(store.job_dir(job_id) / reference["path"])
    root = store.job_dir(job_id) / "work" / content_id
    root.mkdir(parents=True, exist_ok=True)
    path = root / "manuscript.json"
    path.write_text(
        json.dumps(manuscript, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def _media_from_document(document: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "artifact_id": block.get("artifact_id"),
            "source_kind": block.get("source_kind"),
            "timestamp_ms": block.get("timestamp_ms"),
        }
        for block in document.get("blocks") or []
        if isinstance(block, dict) and block.get("type") == "image"
    ]


def _normalized_media_item(item: dict[str, Any]) -> dict[str, Any]:
    source_kind = item.get("source_kind")
    return {
        "artifact_id": str(item.get("artifact_id") or ""),
        "source_kind": source_kind,
        "timestamp_ms": item.get("timestamp_ms")
        if source_kind == "video_frame"
        else None,
    }


def _validate_document_media_alignment(
    document: dict[str, Any], media: list[dict[str, Any]]
) -> None:
    document_media = [
        _normalized_media_item(item) for item in _media_from_document(document)
    ]
    selected_media = [_normalized_media_item(item) for item in media]
    if document_media != selected_media:
        raise ValueError(
            "Content media must exactly match the ordered document image blocks"
        )


def _validate_media(store: Store, job_id: str, media: list[dict[str, Any]]) -> None:
    seen_artifacts: set[str] = set()
    for index, item in enumerate(media):
        source_kind = item.get("source_kind")
        if source_kind not in _ALLOWED_MEDIA_SOURCES:
            raise ValueError(f"media[{index}] uses a non-source image: {source_kind!r}")
        if source_kind == "video_frame" and (
            not isinstance(item.get("timestamp_ms"), int)
            or isinstance(item.get("timestamp_ms"), bool)
        ):
            raise ValueError(f"media[{index}] video frame requires timestamp_ms")
        artifact_id = str(item.get("artifact_id") or "")
        if not artifact_id or artifact_id in seen_artifacts:
            raise ValueError(f"media[{index}] requires a unique artifact_id")
        seen_artifacts.add(artifact_id)
        reference, _ = store.read_artifact(job_id, artifact_id)
        if reference.get("kind") != source_kind:
            raise ValueError(
                f"media[{index}] kind mismatch: {reference.get('kind')} != {source_kind}"
            )
        recorded_timestamp = reference.get("metadata", {}).get("timestamp_ms")
        if (
            source_kind == "video_frame"
            and recorded_timestamp is not None
            and recorded_timestamp != item.get("timestamp_ms")
        ):
            raise ValueError(
                f"media[{index}] timestamp does not match the source Artifact"
            )
    if media and not any(item.get("source_kind") == "video_cover" for item in media):
        raise ValueError("A video-derived article requires the original video cover")


def _validate_cues(cues: list[dict[str, Any]]) -> None:
    previous_end = -1
    for index, cue in enumerate(cues):
        try:
            start = int(cue["start_ms"])
            end = int(cue["end_ms"])
            text = str(cue["text"]).strip()
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Invalid transcript cue at index {index}") from error
        if start < 0 or end <= start or not text:
            raise ValueError(f"Invalid transcript cue at index {index}")
        if start < previous_end:
            raise ValueError("Transcript cues must be time ordered and non-overlapping")
        previous_end = end


def _require_transcript_evidence_ready(
    store: Store, job_id: str, evidence_ids: list[str]
) -> None:
    documents: list[dict[str, Any]] = []
    missing: list[str] = []
    for evidence_id in evidence_ids:
        document = _find_product(store, job_id, "evidence", "evidence_id", evidence_id)
        if document is None:
            missing.append(evidence_id)
        else:
            documents.append(document)
    if missing:
        raise FileNotFoundError(f"Missing evidence product(s): {', '.join(missing)}")
    continuous = any(
        item.get("decision", {}).get("hard_subtitle_visual_decision") == "continuous"
        for item in documents
    )
    has_hard_ocr = any(
        observation.get("kind") == "hard_ocr"
        for item in documents
        for observation in item.get("observations", [])
    )
    if continuous and not has_hard_ocr:
        raise ValueError(
            "Transcript cannot finalize continuous hard subtitles without full-video OCR evidence"
        )


def _require_product_ids(
    store: Store,
    job_id: str,
    *,
    kind: str,
    field: str,
    values: list[str],
) -> None:
    available = {
        str(reference.get("metadata", {}).get(field))
        for reference in store.list_artifacts(job_id, kind=kind)
    }
    missing = [value for value in values if value not in available]
    if missing:
        raise FileNotFoundError(f"Missing {kind} product(s): {', '.join(missing)}")


def _find_product(
    store: Store, job_id: str, kind: str, field: str, value: str
) -> dict[str, Any] | None:
    for reference in store.list_artifacts(job_id, kind=kind):
        if reference.get("metadata", {}).get(field) == value:
            return store.read_json_artifact(job_id, reference["artifact_id"])
    return None


def _stable_id(prefix: str, value: dict[str, Any]) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return f"{prefix}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"
