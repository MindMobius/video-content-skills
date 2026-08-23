from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .jobs import update_job
from .models import CONTENT_SCHEMA, TRANSCRIPT_SCHEMA, Content, Transcript
from .store import Store
from .util import reject_secrets, sha256_file, utc_now
from .wechat_renderer import MANUSCRIPT_VERSION, render_wechat_package

_ALLOWED_MEDIA_SOURCES = {"video_cover", "video_frame"}
_APPROVED_AUDIT_STATES = {"passed", "approved"}


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
