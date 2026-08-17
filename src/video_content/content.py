from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .jobs import update_job
from .models import CONTENT_SCHEMA, TRANSCRIPT_SCHEMA, Content, Transcript
from .store import Store
from .util import reject_secrets, utc_now
from .wechat_renderer import MANUSCRIPT_VERSION, render_wechat_package

_ALLOWED_MEDIA_SOURCES = {"video_cover", "video_frame"}
_APPROVED_AUDIT_STATES = {"passed", "approved"}


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
    _require_product_ids(
        store, job_id, kind="evidence", field="evidence_id", values=evidence_ids
    )
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
            render_references.append(
                store.put_artifact(
                    job_id,
                    kind="content_render",
                    source_path=path,
                    metadata={
                        "content_id": content_id,
                        "relative_path": record["path"],
                    },
                )
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
        _validate_media(store, job_id, list(content.get("media") or []))
    except (FileNotFoundError, ValueError) as error:
        errors.append(str(error))
    if content.get("audit", {}).get("status") not in _APPROVED_AUDIT_STATES:
        errors.append("Content audit is not approved")
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
        if block.get("type") == "image"
    ]


def _validate_media(store: Store, job_id: str, media: list[dict[str, Any]]) -> None:
    for index, item in enumerate(media):
        source_kind = item.get("source_kind")
        if source_kind not in _ALLOWED_MEDIA_SOURCES:
            raise ValueError(f"media[{index}] uses a non-source image: {source_kind!r}")
        if source_kind == "video_frame" and not isinstance(
            item.get("timestamp_ms"), int
        ):
            raise ValueError(f"media[{index}] video frame requires timestamp_ms")
        artifact_id = str(item.get("artifact_id") or "")
        reference, _ = store.read_artifact(job_id, artifact_id)
        if reference.get("kind") != source_kind:
            raise ValueError(
                f"media[{index}] kind mismatch: {reference.get('kind')} != {source_kind}"
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
