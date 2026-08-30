from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .jobs import update_job
from .models import EVIDENCE_SCHEMA, Evidence
from .pipeline import ExtractionPipeline, ExtractionRequest
from .platforms.bilibili import OpenCliClient, OpenCliError, OpenCliSettings
from .scout import plan_hard_subtitle_scout
from .store import Store
from .util import new_id, sha256_file, utc_now

_BVID = re.compile(r"(?i)(BV[A-Za-z0-9]+)")
_VISUAL_DECISIONS = {"not_assessed", "continuous", "not_continuous", "uncertain"}
_MAX_COVER_BYTES = 20 * 1024 * 1024
_COVER_MEDIA_SUFFIXES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/avif": ".avif",
}


def source_identity(url: str, page: int | None = None) -> dict[str, Any]:
    match = _BVID.search(url)
    selected_page = page or 1
    if match:
        bvid = match.group(1)
        return {
            "platform": "bilibili",
            "bvid": bvid,
            "page": selected_page,
            "url": url,
            "idempotency_key": f"bilibili_{bvid}_p{selected_page}",
        }
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
    return {
        "platform": "bilibili",
        "page": selected_page,
        "url": url,
        "idempotency_key": f"bilibili_url_{digest}_p{selected_page}",
    }


def source_inspect(
    url: str,
    *,
    page: int | None = None,
    client: OpenCliClient | None = None,
    settings: OpenCliSettings | None = None,
) -> dict[str, Any]:
    selected_client = client or OpenCliClient(settings or OpenCliSettings.discover())
    metadata = selected_client.video(url, page=page)
    identity = source_identity(url, page)
    if metadata.get("bvid"):
        identity["bvid"] = metadata["bvid"]
        identity["idempotency_key"] = (
            f"bilibili_{metadata['bvid']}_p{int(page or metadata.get('page') or 1)}"
        )
    return {
        "schema_version": "video-content/source-inspection-v1",
        "source": identity,
        "metadata": metadata,
        "inspected_at": utc_now(),
    }


def evidence_start(
    store: Store,
    *,
    url: str,
    page: int | None = None,
    run_id: str | None = None,
    profile_id: str | None = None,
    language: str = "ai-zh",
    ocr_backend: str = "auto",
    asr_backend: str = "none",
    video_path: str | Path | None = None,
    download_if_needed: bool = True,
    collect_all_sources: bool = False,
    media_execution: str = "auto",
    hard_subtitle_visual_decision: str = "not_assessed",
    visual_assessment: dict[str, Any] | None = None,
    client: OpenCliClient | None = None,
    settings: OpenCliSettings | None = None,
    pipeline_factory: Callable[[Any], ExtractionPipeline] = ExtractionPipeline,
) -> dict[str, Any]:
    selected_visual_decision = hard_subtitle_visual_decision.strip().lower()
    if selected_visual_decision not in _VISUAL_DECISIONS:
        raise ValueError(
            "hard_subtitle_visual_decision must be one of: "
            + ", ".join(sorted(_VISUAL_DECISIONS))
        )
    selected_visual_assessment = dict(visual_assessment or {})
    identity = source_identity(url, page)
    job, reused = store.create_job(
        source={
            key: value for key, value in identity.items() if key != "idempotency_key"
        },
        idempotency_key=identity["idempotency_key"],
        run_id=run_id,
        profile_id=profile_id,
    )
    if job["status"] in {"completed", "unprocessable"}:
        return {
            "job": job,
            "reused_existing_job": True,
            "evidence": _latest_evidence(store, job["job_id"]),
        }
    if job["status"] in {"retryable", "paused_auth"}:
        job = update_job(
            store, job["job_id"], status="queued", error=None, retry_at=None
        )
    if job["stage"] == "queued":
        job = update_job(
            store,
            job["job_id"],
            stage="inspecting",
            status="running",
            increment_attempts=True,
        )
    elif job["status"] == "queued":
        job = update_job(
            store,
            job["job_id"],
            status="running",
            increment_attempts=True,
        )
    selected_client = client or OpenCliClient(settings or OpenCliSettings.discover())
    attempt_root = (
        store.job_dir(job["job_id"]) / "work" / f"evidence-{job['attempts']:03d}"
    )
    request = ExtractionRequest(
        url=url,
        output_dir=attempt_root,
        language=language,
        page=page,
        ocr_backend=ocr_backend,
        video_path=Path(video_path).expanduser().resolve() if video_path else None,
        download_if_needed=download_if_needed,
        download_cache_dir=store.cache_dir,
        collect_all_sources=collect_all_sources,
        asr_backend=asr_backend,
        media_execution=media_execution,
    )
    try:
        manifest = pipeline_factory(selected_client).run(
            request,
            job_id=job["job_id"],
            on_update=lambda current: store.append_event(
                job["job_id"],
                {
                    "type": "evidence.progress",
                    "stage": current.get("stage"),
                    "status": current.get("status"),
                },
            ),
        )
    except OpenCliError as error:
        return _record_pipeline_exception(
            store, job["job_id"], error.code, error.message
        )
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        return _record_pipeline_exception(
            store, job["job_id"], type(error).__name__, str(error)
        )

    references: list[dict[str, Any]] = []
    for artifact in manifest.get("artifacts", []):
        path_value = artifact.get("path")
        if not path_value:
            continue
        path = Path(str(path_value)).expanduser().resolve()
        if not path.is_file():
            continue
        kind = _artifact_kind(str(artifact.get("kind") or "evidence_file"))
        reference = (
            _existing_source_video_reference(store, job["job_id"], path)
            if kind == "source_video"
            else None
        )
        if reference is None:
            reference = store.put_artifact(
                job["job_id"],
                kind=kind,
                source_path=path,
                metadata={
                    key: value
                    for key, value in artifact.items()
                    if key not in {"path", "sha256", "bytes"} and value is not None
                },
            )
        references.append(reference)

    cover_reference: dict[str, Any] | None = None
    cover_url = _cover_url(job, manifest)
    if cover_url:
        try:
            cover_reference = _ensure_video_cover(store, job["job_id"], cover_url)
            if not any(
                item.get("artifact_id") == cover_reference.get("artifact_id")
                for item in references
            ):
                references.append(cover_reference)
        except (OSError, TypeError, ValueError) as error:
            manifest.setdefault("warnings", []).append(
                {
                    "code": "VIDEO_COVER_UNAVAILABLE",
                    "message": str(error),
                }
            )

    frame_references = store.list_artifacts(job["job_id"], kind="video_frame")
    scout_references = [
        *store.list_artifacts(job["job_id"], kind="ocr_scout_plan"),
        *store.list_artifacts(job["job_id"], kind="ocr_scout_contact_sheet"),
    ]
    for scout_reference in [*frame_references, *scout_references]:
        if not any(
            item.get("artifact_id") == scout_reference.get("artifact_id")
            for item in references
        ):
            references.append(scout_reference)

    manifest_reference = store.put_artifact(
        job["job_id"],
        kind="extraction_manifest",
        data=manifest,
        filename="manifest.json",
        media_type="application/json",
    )
    references.append(manifest_reference)

    if manifest.get("status") != "completed" or not manifest.get("sources"):
        limitation = _pipeline_limitation(manifest)
        target_status = limitation["status"]
        updated = update_job(
            store,
            job["job_id"],
            stage="evidence" if job["stage"] != "inspecting" else "inspecting",
            status=target_status,
            error=limitation["error"],
        )
        return {
            "job": updated,
            "reused_existing_job": reused,
            "manifest": manifest,
            "evidence": None,
        }

    evidence_id = new_id("evidence")
    observations = [
        {
            "kind": item.get("kind"),
            "artifact_source": item.get("artifact_source"),
            "cue_count": item.get("cue_count"),
            "backend": item.get("backend"),
            "detected_languages": item.get("detected_languages"),
        }
        for item in manifest.get("sources", [])
    ]
    if cover_reference is not None:
        observations.append(
            {
                "kind": "video_cover",
                "artifact_id": cover_reference["artifact_id"],
                "artifact_source": "bilibili_public_cover",
            }
        )
    for frame_reference in frame_references:
        observations.append(
            {
                "kind": "video_frame",
                "artifact_id": frame_reference["artifact_id"],
                "artifact_source": "agent_visual_scout",
                "timestamp_ms": frame_reference.get("metadata", {}).get("timestamp_ms"),
            }
        )
    current_has_hard_ocr = any(
        item.get("kind") == "hard_ocr" for item in manifest.get("sources", [])
    )
    has_hard_ocr = current_has_hard_ocr or _job_evidence_has_observation(
        store, job["job_id"], "hard_ocr"
    )
    decision = {
        "platform_track_available": any(
            item.get("kind") == "platform_subtitle"
            for item in manifest.get("sources", [])
        ),
        "hard_subtitle_visual_decision": selected_visual_decision,
        "fusion_status": (
            "not_required"
            if len(manifest.get("sources", [])) == 1
            else "independent_evidence"
        ),
        "agent_action": _visual_agent_action(
            selected_visual_decision, has_hard_ocr=has_hard_ocr
        ),
    }
    if selected_visual_assessment:
        decision["visual_assessment"] = selected_visual_assessment
    evidence = Evidence(
        evidence_id=evidence_id,
        job_id=job["job_id"],
        source=job["source"],
        observations=observations,
        artifact_refs=references,
        decision=decision,
        created_at=utc_now(),
        schema_version=EVIDENCE_SCHEMA,
    ).as_dict()
    saved_evidence, evidence_reference = store.save_document(
        job["job_id"],
        kind="evidence",
        document=evidence,
        identifier_field="evidence_id",
        identifier_prefix="evidence",
    )
    if selected_visual_decision == "continuous" and not has_hard_ocr:
        updated = update_job(
            store,
            job["job_id"],
            stage="evidence",
            status="retryable",
            error={
                "code": "HARD_OCR_REQUIRED",
                "message": (
                    "Continuous hard subtitles were visually confirmed, but the "
                    "current evidence pass did not produce full-video OCR."
                ),
            },
        )
    else:
        updated = update_job(store, job["job_id"], stage="evidence", status="running")
    return {
        "job": updated,
        "reused_existing_job": reused,
        "evidence": saved_evidence,
        "evidence_artifact": evidence_reference,
        "manifest": manifest,
    }


def _latest_evidence(store: Store, job_id: str) -> dict[str, Any] | None:
    refs = store.list_artifacts(job_id, kind="evidence")
    if not refs:
        return None
    return store.read_json_artifact(job_id, refs[-1]["artifact_id"])


def _record_pipeline_exception(
    store: Store, job_id: str, code: str, message: str
) -> dict[str, Any]:
    lowered = f"{code} {message}".lower()
    status = (
        "paused_auth"
        if any(token in lowered for token in ("login", "auth", "cookie"))
        else "retryable"
    )
    stage = store.get_job(job_id)["stage"]
    updated = update_job(
        store,
        job_id,
        stage=stage,
        status=status,
        error={"code": code, "message": message},
    )
    return {"job": updated, "evidence": None, "reused_existing_job": False}


def _job_evidence_has_observation(store: Store, job_id: str, kind: str) -> bool:
    for reference in store.list_artifacts(job_id, kind="evidence"):
        document = store.read_json_artifact(job_id, reference["artifact_id"])
        if any(
            observation.get("kind") == kind
            for observation in document.get("observations", [])
        ):
            return True
    return False


def _cover_url(job: dict[str, Any], manifest: dict[str, Any]) -> str | None:
    candidates = [
        job.get("source", {}).get("cover_url"),
        (manifest.get("video") or {}).get("cover_url"),
        (manifest.get("video") or {}).get("cover"),
        (manifest.get("video") or {}).get("pic"),
        (manifest.get("video") or {}).get("thumbnail"),
    ]
    for value in candidates:
        selected = str(value or "").strip()
        if selected:
            return selected
    return None


def _ensure_video_cover(store: Store, job_id: str, cover_url: str) -> dict[str, Any]:
    existing = store.list_artifacts(job_id, kind="video_cover")
    if existing:
        return existing[-1]
    selected_url = cover_url.strip()
    if selected_url.startswith("http://"):
        selected_url = "https://" + selected_url[len("http://") :]
    parsed = urlsplit(selected_url)
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or not (hostname == "hdslb.com" or hostname.endswith(".hdslb.com"))
    ):
        raise ValueError("Bilibili cover URL is not an approved public image URL")
    request = Request(
        selected_url,
        headers={
            "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
            "Referer": "https://www.bilibili.com/",
            "User-Agent": "Mozilla/5.0 VideoContentSkills/1.0",
        },
    )
    with urlopen(request, timeout=30) as response:
        final_url = urlsplit(str(response.geturl()))
        final_hostname = (final_url.hostname or "").lower()
        if (
            final_url.scheme != "https"
            or final_url.username is not None
            or final_url.password is not None
            or not (
                final_hostname == "hdslb.com" or final_hostname.endswith(".hdslb.com")
            )
        ):
            raise ValueError("Bilibili cover redirect left the approved image host")
        media_type = response.headers.get_content_type().lower()
        suffix = _COVER_MEDIA_SUFFIXES.get(media_type)
        if suffix is None:
            raise ValueError("Bilibili cover response uses an unsupported image type")
        declared = response.headers.get("Content-Length")
        if declared and int(declared) > _MAX_COVER_BYTES:
            raise ValueError("Bilibili cover exceeds the 20 MiB safety limit")
        payload = response.read(_MAX_COVER_BYTES + 1)
    if len(payload) > _MAX_COVER_BYTES:
        raise ValueError("Bilibili cover exceeds the 20 MiB safety limit")
    if not payload:
        raise ValueError("Bilibili cover response is empty")
    return store.put_artifact(
        job_id,
        kind="video_cover",
        data=payload,
        filename=f"cover{suffix}",
        media_type=media_type,
        metadata={
            "provider": "bilibili",
            "source_kind": "video_cover",
            "source_host": final_hostname,
        },
    )


def _visual_agent_action(decision: str, *, has_hard_ocr: bool) -> str:
    if decision == "continuous":
        if has_hard_ocr:
            return "Continuous hard subtitles were visually confirmed and full-video OCR was collected."
        return "Continuous hard subtitles were visually confirmed; full-video OCR is still required."
    if decision == "not_continuous":
        return "The visual scout found no continuous hard subtitles; use the remaining evidence sources."
    if decision == "uncertain":
        return "Hard-subtitle continuity remains uncertain; inspect more frames before finalizing the Transcript."
    return "Inspect sampled video frames before deciding whether full-video OCR can be skipped."


def _pipeline_limitation(manifest: dict[str, Any]) -> dict[str, Any]:
    error = dict(manifest.get("error") or manifest.get("next_action") or {})
    status = str(manifest.get("status") or "")
    error.setdefault("code", status.upper() or "EVIDENCE_INCOMPLETE")
    error.setdefault(
        "message", "The available physical source did not produce usable evidence."
    )
    lowered = f"{error.get('code')} {error.get('message')}".lower()
    if any(token in lowered for token in ("login", "auth", "cookie")):
        return {"status": "paused_auth", "error": error}
    if status in {"needs_backend", "needs_ocr"}:
        return {"status": "retryable", "error": error}
    if status == "failed" and any(
        token in lowered
        for token in ("missing", "unavailable", "timeout", "download", "runtime")
    ):
        return {"status": "retryable", "error": error}
    return {"status": "unprocessable", "error": error}


def _existing_source_video_reference(
    store: Store, job_id: str, path: Path
) -> dict[str, Any] | None:
    digest = sha256_file(path)
    return next(
        (
            reference
            for reference in store.list_artifacts(job_id, kind="source_video")
            if reference.get("sha256") == digest
        ),
        None,
    )


def _artifact_kind(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return normalized or "evidence_file"


__all__ = [
    "evidence_start",
    "plan_hard_subtitle_scout",
    "source_identity",
    "source_inspect",
]
