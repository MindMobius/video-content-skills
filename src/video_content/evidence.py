from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .jobs import update_job
from .models import EVIDENCE_SCHEMA, Evidence
from .pipeline import ExtractionPipeline, ExtractionRequest
from .platforms.bilibili import OpenCliClient, OpenCliError, OpenCliSettings
from .scout import plan_hard_subtitle_scout
from .store import Store
from .util import new_id, utc_now

_BVID = re.compile(r"(?i)(BV[A-Za-z0-9]+)")


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
    client: OpenCliClient | None = None,
    settings: OpenCliSettings | None = None,
    pipeline_factory: Callable[[Any], ExtractionPipeline] = ExtractionPipeline,
) -> dict[str, Any]:
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
    evidence = Evidence(
        evidence_id=evidence_id,
        job_id=job["job_id"],
        source=job["source"],
        observations=[
            {
                "kind": item.get("kind"),
                "artifact_source": item.get("artifact_source"),
                "cue_count": item.get("cue_count"),
                "backend": item.get("backend"),
                "detected_languages": item.get("detected_languages"),
            }
            for item in manifest.get("sources", [])
        ],
        artifact_refs=references,
        decision={
            "platform_track_available": any(
                item.get("kind") == "platform_subtitle"
                for item in manifest.get("sources", [])
            ),
            "hard_subtitle_visual_decision": "not_assessed",
            "fusion_status": (
                "not_required"
                if len(manifest.get("sources", [])) == 1
                else "independent_evidence"
            ),
            "agent_action": (
                "Inspect sampled video frames before deciding whether full-video OCR can be skipped."
            ),
        },
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


def _pipeline_limitation(manifest: dict[str, Any]) -> dict[str, Any]:
    error = dict(manifest.get("error") or {})
    error.setdefault(
        "code", str(manifest.get("status") or "EVIDENCE_INCOMPLETE").upper()
    )
    error.setdefault(
        "message", "The available physical source did not produce usable evidence."
    )
    lowered = f"{error.get('code')} {error.get('message')}".lower()
    if any(token in lowered for token in ("login", "auth", "cookie")):
        return {"status": "paused_auth", "error": error}
    if manifest.get("status") in {"needs_backend", "failed"} and any(
        token in lowered for token in ("missing", "unavailable", "timeout", "download")
    ):
        return {"status": "retryable", "error": error}
    return {"status": "unprocessable", "error": error}


def _artifact_kind(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return normalized or "evidence_file"


__all__ = [
    "evidence_start",
    "plan_hard_subtitle_scout",
    "source_identity",
    "source_inspect",
]
