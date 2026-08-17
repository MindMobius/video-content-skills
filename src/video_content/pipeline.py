from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any

from .backends.asr import (
    AsrBackend,
    AsrExecutionError,
    AsrUnavailable,
    Qwen3AsrOptions,
    resolve_asr_backend,
)
from .backends.ocr import (
    OcrBackend,
    OcrExecutionError,
    OcrUnavailable,
    VideOcrOptions,
    resolve_ocr_backend,
)
from .platforms.base import PlatformError, VideoPlatformClient
from .srt import (
    Cue,
    parse_srt,
    platform_rows_to_cues,
    write_cues_json,
    write_srt,
    write_transcript_markdown,
)
from .util import local_job_id, utc_now, write_json_atomic

ManifestCallback = Callable[[dict[str, Any]], None]
OcrResolver = Callable[[str, VideOcrOptions], OcrBackend]
AsrResolver = Callable[[str, Qwen3AsrOptions], AsrBackend]


@dataclass(frozen=True)
class ExtractionRequest:
    url: str
    output_dir: Path
    language: str = "ai-zh"
    page: int | None = None
    ocr_backend: str = "auto"
    video_path: Path | None = None
    download_if_needed: bool = True
    download_quality: str = "1080p"
    download_cache_dir: Path | None = None
    collect_all_sources: bool = False
    asr_backend: str = "none"
    media_execution: str = "auto"
    videocr: VideOcrOptions = field(default_factory=VideOcrOptions)
    qwen3_asr: Qwen3AsrOptions = field(default_factory=Qwen3AsrOptions)

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "output_dir": str(self.output_dir.resolve()),
            "language": self.language,
            "page": self.page,
            "ocr_backend": self.ocr_backend,
            "video_path": str(self.video_path.resolve()) if self.video_path else None,
            "download_if_needed": self.download_if_needed,
            "download_quality": self.download_quality,
            "download_cache_dir": (
                str(self.download_cache_dir.resolve())
                if self.download_cache_dir
                else None
            ),
            "collect_all_sources": self.collect_all_sources,
            "asr_backend": self.asr_backend,
            "media_execution": self.media_execution,
            "videocr": self.videocr.as_dict(),
            "qwen3_asr": self.qwen3_asr.as_dict(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ExtractionRequest:
        video_path = value.get("video_path")
        download_cache_dir = value.get("download_cache_dir")
        return cls(
            url=str(value["url"]),
            output_dir=Path(str(value["output_dir"])),
            language=str(value.get("language") or "ai-zh"),
            page=int(value["page"]) if value.get("page") is not None else None,
            ocr_backend=str(value.get("ocr_backend") or "auto"),
            video_path=Path(str(video_path)) if video_path else None,
            download_if_needed=bool(value.get("download_if_needed", True)),
            download_quality=str(value.get("download_quality") or "1080p"),
            download_cache_dir=(
                Path(str(download_cache_dir)) if download_cache_dir else None
            ),
            collect_all_sources=bool(value.get("collect_all_sources", False)),
            asr_backend=str(value.get("asr_backend") or "none"),
            media_execution=str(value.get("media_execution") or "auto"),
            videocr=VideOcrOptions.from_dict(value.get("videocr") or {}),
            qwen3_asr=Qwen3AsrOptions.from_dict(value.get("qwen3_asr") or {}),
        )


class ExtractionPipeline:
    def __init__(
        self,
        client: VideoPlatformClient,
        *,
        ocr_resolver: OcrResolver = resolve_ocr_backend,
        asr_resolver: AsrResolver = resolve_asr_backend,
    ) -> None:
        self.client = client
        self.ocr_resolver = ocr_resolver
        self.asr_resolver = asr_resolver

    def run(
        self,
        request: ExtractionRequest,
        *,
        job_id: str | None = None,
        on_update: ManifestCallback | None = None,
    ) -> dict[str, Any]:
        output_dir = request.output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = output_dir / "manifest.json"
        job_id = job_id or local_job_id()
        manifest: dict[str, Any] = {
            "schema_version": "video-content/extraction-run-v1",
            "job_id": job_id,
            "status": "running",
            "stage": "inspect",
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "request": request.as_dict(),
            "video": None,
            "selected_source": None,
            "sources": [],
            "review": None,
            "attempts": [],
            "artifacts": [],
            "warnings": [],
            "error": None,
            "next_action": None,
        }

        def save() -> None:
            manifest["updated_at"] = utc_now()
            write_json_atomic(manifest_path, manifest)
            if on_update:
                on_update(manifest)

        save()

        platform = str(self.client.platform)
        platform_artifact_source = f"platform_subtitle:{platform}"
        ocr_requested = request.ocr_backend.lower() != "none"
        asr_requested = request.asr_backend.lower() != "none"
        effective_page = request.page
        metadata_attempt = _start_attempt(manifest, f"{platform}_metadata")
        save()
        try:
            metadata = self.client.video(request.url, page=request.page)
            parts = _optional_positive_int(metadata.get("parts")) or 1
            if request.page is None and parts > 1:
                effective_page = 1
                metadata = self.client.video(request.url, page=effective_page)
                manifest["warnings"].append(
                    {
                        "code": "MULTIPART_DEFAULTED_TO_PAGE_1",
                        "message": (
                            f"This {platform} item has {parts} parts. The request did not "
                            "select a page, so only page 1 is being processed."
                        ),
                        "parts": parts,
                        "selected_page": effective_page,
                    }
                )
            manifest["video"] = _normalize_metadata(metadata, request.url)
            _finish_attempt(
                metadata_attempt,
                "succeeded",
                selected_page=effective_page,
            )
        except PlatformError as error:
            _finish_attempt(metadata_attempt, "failed", error=error.as_dict())
            return _finish_failed(
                manifest,
                manifest_path,
                error={
                    "code": error.code,
                    "message": error.message,
                    "help": error.help_text,
                    "stage": "inspect",
                },
                on_update=on_update,
            )
        save()

        platform_available = False
        manifest["stage"] = "platform_subtitle"
        platform_attempt = _start_attempt(
            manifest,
            platform_artifact_source,
            language=request.language,
        )
        save()
        try:
            rows = self.client.subtitles(
                request.url,
                lang=request.language,
                page=effective_page,
            )
            cues = platform_rows_to_cues(rows)
            if not cues:
                raise PlatformError(
                    "EMPTY_RESULT",
                    f"{platform} returned a subtitle track with no usable cues",
                )
            artifacts = _write_subtitle_artifacts(
                output_dir,
                cues,
                stem="subtitle.platform",
                title=str((manifest["video"] or {}).get("title") or "视频字幕"),
                source=platform_artifact_source,
            )
            manifest["artifacts"].extend(artifacts)
            manifest["sources"].append(
                {
                    "kind": "platform_subtitle",
                    "platform": platform,
                    "artifact_source": platform_artifact_source,
                    "language_requested": request.language,
                    "cue_count": len(cues),
                    "provenance_note": (
                        "The platform adapter returned subtitle cues but did not prove "
                        "whether the selected track was human-authored or machine-generated."
                    ),
                }
            )
            platform_available = True
            _finish_attempt(
                platform_attempt,
                "succeeded",
                cue_count=len(cues),
            )
            if (
                not request.collect_all_sources
                and not ocr_requested
                and not asr_requested
            ):
                _finalize_evidence_bundle(manifest, output_dir)
                return _finish_completed(
                    manifest,
                    manifest_path,
                    on_update=on_update,
                )
        except PlatformError as error:
            if error.code == "EMPTY_RESULT":
                _finish_attempt(platform_attempt, "unavailable", error=error.as_dict())
            else:
                _finish_attempt(platform_attempt, "failed", error=error.as_dict())
                manifest["warnings"].append(
                    {
                        "code": error.code,
                        "message": (
                            "Platform subtitle lookup failed; configured media "
                            "transcription backends will be tried."
                        ),
                        "detail": error.message,
                    }
                )
        except ValueError as error:
            _finish_attempt(
                platform_attempt,
                "failed",
                error={"code": "INVALID_PLATFORM_CUES", "message": str(error)},
            )
            manifest["warnings"].append(
                {
                    "code": "INVALID_PLATFORM_CUES",
                    "message": (
                        "Platform cues were malformed; configured media transcription "
                        "backends will be tried."
                    ),
                }
            )
        save()

        ocr_backend: OcrBackend | None = None
        ocr_attempt: dict[str, Any] | None = None
        asr_backend: AsrBackend | None = None
        asr_attempt: dict[str, Any] | None = None
        asr_backend_description: dict[str, Any] | None = None
        legacy_disabled_ocr_path = (
            not platform_available and not ocr_requested and not asr_requested
        )

        if ocr_requested or legacy_disabled_ocr_path:
            manifest["stage"] = "resolve_ocr"
            ocr_attempt = _start_attempt(
                manifest,
                "hard_ocr",
                backend=request.ocr_backend,
            )
            save()
            try:
                ocr_backend = self.ocr_resolver(
                    request.ocr_backend,
                    request.videocr,
                )
                ocr_attempt["backend"] = ocr_backend.describe()
            except OcrUnavailable as error:
                _finish_attempt(
                    ocr_attempt,
                    "unavailable",
                    error={"code": "OCR_BACKEND_UNAVAILABLE", "message": str(error)},
                )
                manifest["warnings"].append(
                    {
                        "code": "OCR_BACKEND_UNAVAILABLE",
                        "message": str(error),
                    }
                )
                if not platform_available and not asr_requested:
                    return _finish_needs_backend(
                        manifest,
                        manifest_path,
                        request,
                        save=save,
                    )

        effective_asr_options = request.qwen3_asr
        if asr_requested:
            manifest["stage"] = "resolve_asr"
            save()
            try:
                asr_backend = self.asr_resolver(
                    request.asr_backend,
                    effective_asr_options,
                )
                asr_backend_description = asr_backend.describe()
            except AsrUnavailable as error:
                asr_attempt = _start_attempt(
                    manifest,
                    "audio_asr",
                    backend=request.asr_backend,
                    context_source=effective_asr_options.context_source,
                )
                _finish_attempt(
                    asr_attempt,
                    "unavailable",
                    error={"code": "ASR_BACKEND_UNAVAILABLE", "message": str(error)},
                )
                manifest["warnings"].append(
                    {
                        "code": "ASR_BACKEND_UNAVAILABLE",
                        "message": str(error),
                    }
                )

        if ocr_backend is None and asr_backend is None:
            if platform_available:
                _finalize_evidence_bundle(manifest, output_dir)
                return _finish_completed(
                    manifest,
                    manifest_path,
                    on_update=on_update,
                )
            return _finish_needs_backend(
                manifest,
                manifest_path,
                request,
                save=save,
            )

        video_path = request.video_path.resolve() if request.video_path else None
        if video_path:
            if not video_path.is_file():
                _finish_media_attempts(
                    (ocr_attempt, asr_attempt),
                    status="failed",
                    error={
                        "code": "VIDEO_NOT_FOUND",
                        "message": f"Local video does not exist: {video_path}",
                    },
                )
                return _finish_failed(
                    manifest,
                    manifest_path,
                    error={
                        "code": "VIDEO_NOT_FOUND",
                        "message": f"Local video does not exist: {video_path}",
                        "stage": "resolve_video",
                    },
                    on_update=on_update,
                )
            manifest["artifacts"].append(
                _artifact("source_video", video_path, source="local", owned=False)
            )
        elif request.download_if_needed:
            manifest["stage"] = "download_video"
            download_attempt = _start_attempt(
                manifest,
                f"{platform}_video_download",
                quality=request.download_quality,
            )
            save()
            try:
                video_path, download_result = self.client.download(
                    request.url,
                    output_dir / "video",
                    quality=request.download_quality,
                    page=effective_page,
                    cache_dir=request.download_cache_dir,
                    cache_key=str(
                        (manifest.get("video") or {}).get("bvid") or request.url
                    ),
                )
                download_observation = _download_observation(
                    video_path,
                    download_result,
                )
                _finish_attempt(
                    download_attempt,
                    "succeeded",
                    result=download_result,
                    **download_observation,
                )
                manifest["artifacts"].append(
                    _artifact(
                        "source_video",
                        video_path,
                        source=f"{platform}_download",
                        owned=request.download_cache_dir is None,
                    )
                )
            except PlatformError as error:
                _finish_attempt(download_attempt, "failed", error=error.as_dict())
                _finish_media_attempts(
                    (ocr_attempt, asr_attempt),
                    status="failed",
                    error=error.as_dict(),
                )
                return _finish_failed(
                    manifest,
                    manifest_path,
                    error={
                        "code": error.code,
                        "message": error.message,
                        "help": error.help_text,
                        "stage": "download_video",
                    },
                    on_update=on_update,
                )
        else:
            _finish_media_attempts(
                (ocr_attempt, asr_attempt),
                status="unavailable",
                error={
                    "code": "VIDEO_REQUIRED",
                    "message": (
                        "Hard OCR and audio ASR require --video or video download "
                        "permission."
                    ),
                },
            )
            if platform_available:
                manifest["warnings"].append(
                    {
                        "code": "VIDEO_REQUIRED",
                        "message": (
                            "Additional evidence sources were skipped because no local "
                            "video or download permission was provided."
                        ),
                    }
                )
                _finalize_evidence_bundle(manifest, output_dir)
                return _finish_completed(
                    manifest,
                    manifest_path,
                    on_update=on_update,
                )
            manifest["status"] = "needs_ocr"
            manifest["stage"] = "waiting_for_video"
            manifest["next_action"] = {
                "code": "PROVIDE_VIDEO",
                "message": "Rerun with --video <path> or without --no-download.",
            }
            manifest["finished_at"] = utc_now()
            save()
            return manifest

        title = str((manifest["video"] or {}).get("title") or "视频字幕")
        media_jobs: list[tuple[str, dict[str, Any], Callable[[], dict[str, Any]]]] = []
        if ocr_backend is not None and ocr_attempt is not None:
            media_jobs.append(
                (
                    "hard_ocr",
                    ocr_attempt,
                    lambda: _run_ocr_evidence(
                        ocr_backend,
                        video_path,
                        output_dir,
                        title,
                    ),
                )
            )

        if asr_backend is not None:
            asr_attempt = _start_attempt(
                manifest,
                "audio_asr",
                backend=asr_backend_description or asr_backend.describe(),
                context_source=effective_asr_options.context_source,
            )
            media_jobs.append(
                (
                    "audio_asr",
                    asr_attempt,
                    lambda: _run_asr_evidence(
                        asr_backend,
                        video_path,
                        output_dir,
                        title,
                    ),
                )
            )

        resolved_ocr_options = (
            ocr_backend.describe().get("options") or {}
            if ocr_backend is not None
            else {}
        )
        resolved_ocr_uses_gpu = bool(
            resolved_ocr_options.get("use_gpu", request.videocr.use_gpu)
        )
        shared_gpu = bool(
            ocr_backend is not None
            and asr_backend is not None
            and resolved_ocr_uses_gpu
        )
        resolved_execution = _resolve_media_execution(
            request.media_execution,
            len(media_jobs),
            shared_gpu=shared_gpu,
        )
        manifest["execution"] = {
            "media_requested": request.media_execution,
            "media_resolved": resolved_execution,
            "backends": [name for name, _, _ in media_jobs],
            "shared_gpu": shared_gpu,
            "decision": (
                "explicit"
                if request.media_execution != "auto"
                else "auto_shared_gpu_safe_serial"
                if shared_gpu
                else "auto_independent_parallel"
                if len(media_jobs) > 1
                else "single_backend"
            ),
        }
        concurrent_group = f"{job_id}:media"
        for _, attempt, _ in media_jobs:
            attempt["execution"] = resolved_execution
            if resolved_execution == "parallel":
                attempt["concurrent_group"] = concurrent_group

        outcomes: list[dict[str, Any]] = []
        if resolved_execution == "parallel":
            manifest["stage"] = "media_parallel"
            save()
            with ThreadPoolExecutor(
                max_workers=len(media_jobs),
                thread_name_prefix="video-content",
            ) as executor:
                futures = [executor.submit(runner) for _, _, runner in media_jobs]
                outcomes = [future.result() for future in futures]
        else:
            for name, _, runner in media_jobs:
                manifest["stage"] = name
                save()
                outcomes.append(runner())

        for (_, attempt, _), outcome in zip(media_jobs, outcomes, strict=True):
            _apply_media_outcome(manifest, attempt, outcome)
            save()

        if manifest["sources"]:
            _finalize_evidence_bundle(manifest, output_dir)
            return _finish_completed(
                manifest,
                manifest_path,
                on_update=on_update,
            )
        return _finish_failed(
            manifest,
            manifest_path,
            error={
                "code": "TRANSCRIPTION_FAILED",
                "message": "No configured subtitle source produced usable cues.",
                "stage": manifest.get("stage") or "transcription",
            },
            on_update=on_update,
        )


def _finish_needs_backend(
    manifest: dict[str, Any],
    manifest_path: Path,
    request: ExtractionRequest,
    *,
    save: Callable[[], None],
) -> dict[str, Any]:
    del manifest_path
    manifest["status"] = "needs_ocr"
    manifest["finished_at"] = utc_now()
    if request.asr_backend.lower() != "none":
        manifest["stage"] = "waiting_for_transcription_backend"
        manifest["next_action"] = {
            "code": "CONFIGURE_TRANSCRIPTION_BACKEND",
            "message": (
                "Configure at least one usable OCR or ASR backend, then rerun. "
                "No video was downloaded."
            ),
            "environment": [
                "VIDEO_CONTENT_VIDEOCR=<absolute path to videocr-cli.exe>",
                "VIDEO_CONTENT_ASR_PYTHON=<absolute path to ASR python.exe>",
                "VIDEO_CONTENT_QWEN_ASR_MODEL=<local Qwen3-ASR model directory>",
                "VIDEO_CONTENT_QWEN_ALIGNER_MODEL=<local aligner model directory>",
            ],
        }
    elif request.ocr_backend.lower() == "none":
        manifest["stage"] = "waiting_for_ocr_backend"
        manifest["next_action"] = {
            "code": "ENABLE_OCR",
            "message": (
                "Rerun with --ocr-backend auto or videocr, or configure "
                "--asr-backend qwen3. No video was downloaded."
            ),
        }
    else:
        manifest["stage"] = "waiting_for_ocr_backend"
        manifest["next_action"] = {
            "code": "CONFIGURE_VIDEOCR",
            "message": (
                "Configure VideOCR, then rerun this extraction. No video was "
                "downloaded because the OCR backend was unavailable."
            ),
            "environment": "VIDEO_CONTENT_VIDEOCR=<absolute path to videocr-cli.exe>",
        }
    save()
    return manifest


def _finish_media_attempts(
    attempts: tuple[dict[str, Any] | None, ...],
    *,
    status: str,
    error: dict[str, Any],
) -> None:
    for attempt in attempts:
        if attempt is not None and attempt.get("status") == "running":
            _finish_attempt(attempt, status, error=error)


def _resolve_media_execution(
    requested: str,
    job_count: int,
    *,
    shared_gpu: bool,
) -> str:
    selected = requested.strip().lower()
    if selected not in {"auto", "serial", "parallel"}:
        raise ValueError("media_execution must be auto, serial, or parallel")
    if job_count < 2:
        return "serial"
    if selected == "auto":
        return "serial" if shared_gpu else "parallel"
    return selected


def _run_ocr_evidence(
    backend: OcrBackend,
    video_path: Path,
    output_dir: Path,
    title: str,
) -> dict[str, Any]:
    backend_started_at = utc_now()
    started = monotonic()
    output = output_dir / "subtitle.ocr.srt"
    log = output_dir / "ocr.log"
    try:
        run_result = backend.run(video_path, output, log) or {}
        cues = parse_srt(output)
        if not cues:
            raise OcrExecutionError(
                "VideOCR produced an SRT file with no usable cues",
                log_path=log,
            )
        write_srt(output, cues)
        artifact_source = f"hard_ocr:{backend.name}"
        artifacts = _write_subtitle_artifacts(
            output_dir,
            cues,
            stem="subtitle.ocr",
            title=title,
            source=artifact_source,
            existing_srt=output,
        )
        artifacts.extend(_supporting_artifacts(run_result, source=artifact_source))
        artifacts.append(_artifact("process_log", log, source=backend.name, owned=True))
        source = {
            "kind": "hard_ocr",
            "artifact_source": artifact_source,
            "backend": backend.name,
            "cue_count": len(cues),
            "strategy": (run_result.get("strategy") or "single_scale"),
        }
        if run_result.get("reconciliation"):
            source["reconciliation"] = run_result["reconciliation"]
        return {
            "status": "succeeded",
            "source": source,
            "artifacts": artifacts,
            "warnings": run_result.get("warnings", []),
            "attempt": {
                "cue_count": len(cues),
                "result": _run_summary(run_result),
                "backend_started_at": backend_started_at,
                "backend_elapsed_seconds": round(monotonic() - started, 3),
                "finished_at": utc_now(),
            },
        }
    except (OcrExecutionError, ValueError) as error:
        artifacts = []
        if log.exists():
            artifacts.append(
                _artifact("process_log", log, source=backend.name, owned=True)
            )
        detail = {"code": "OCR_FAILED", "message": str(error)}
        return {
            "status": "failed",
            "source": None,
            "artifacts": artifacts,
            "warnings": [detail],
            "attempt": {
                "error": detail,
                "backend_started_at": backend_started_at,
                "backend_elapsed_seconds": round(monotonic() - started, 3),
                "finished_at": utc_now(),
            },
        }


def _run_asr_evidence(
    backend: AsrBackend,
    video_path: Path,
    output_dir: Path,
    title: str,
) -> dict[str, Any]:
    backend_started_at = utc_now()
    started = monotonic()
    output = output_dir / "subtitle.asr.srt"
    log = output_dir / "asr.log"
    try:
        run_result = backend.run(video_path, output, log)
        cues = parse_srt(output)
        if not cues:
            raise AsrExecutionError(
                "Qwen3-ASR produced an SRT file with no usable cues",
                log_path=log,
            )
        write_srt(output, cues)
        artifact_source = f"audio_asr:{backend.name}"
        artifacts = _write_subtitle_artifacts(
            output_dir,
            cues,
            stem="subtitle.asr",
            title=title,
            source=artifact_source,
            existing_srt=output,
        )
        artifacts.extend(_supporting_artifacts(run_result, source=artifact_source))
        artifacts.append(_artifact("process_log", log, source=backend.name, owned=True))
        return {
            "status": "succeeded",
            "source": {
                "kind": "audio_asr",
                "artifact_source": artifact_source,
                "backend": backend.name,
                "cue_count": len(cues),
                "strategy": run_result.get("strategy"),
                "language_requested": run_result.get("language_requested"),
                "detected_languages": run_result.get("detected_languages", []),
                "context_source": run_result.get("context_source"),
                "context_echo_retries": run_result.get("context_echo_retries", 0),
            },
            "artifacts": artifacts,
            "warnings": run_result.get("warnings", []),
            "attempt": {
                "cue_count": len(cues),
                "result": _run_summary(run_result),
                "backend_started_at": backend_started_at,
                "backend_elapsed_seconds": round(monotonic() - started, 3),
                "finished_at": utc_now(),
            },
        }
    except (AsrExecutionError, ValueError) as error:
        artifacts = []
        if log.exists():
            artifacts.append(
                _artifact("process_log", log, source=backend.name, owned=True)
            )
        detail = {"code": "ASR_FAILED", "message": str(error)}
        return {
            "status": "failed",
            "source": None,
            "artifacts": artifacts,
            "warnings": [detail],
            "attempt": {
                "error": detail,
                "backend_started_at": backend_started_at,
                "backend_elapsed_seconds": round(monotonic() - started, 3),
                "finished_at": utc_now(),
            },
        }


def _apply_media_outcome(
    manifest: dict[str, Any],
    attempt: dict[str, Any],
    outcome: dict[str, Any],
) -> None:
    manifest["artifacts"].extend(outcome["artifacts"])
    manifest["warnings"].extend(outcome["warnings"])
    if outcome.get("source"):
        manifest["sources"].append(outcome["source"])
    attempt_details = dict(outcome["attempt"])
    finished_at = attempt_details.pop("finished_at", None)
    _finish_attempt(
        attempt,
        outcome["status"],
        finished_at=finished_at,
        **attempt_details,
    )


def _run_summary(run_result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in run_result.items()
        if key not in {"supporting_artifacts", "warnings"}
    }


def _supporting_artifacts(
    run_result: dict[str, Any],
    *,
    source: str,
) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for supporting in run_result.get("supporting_artifacts", []):
        supporting_path = Path(str(supporting["path"])).resolve()
        if not supporting_path.is_file():
            continue
        cue_count = supporting.get("cue_count")
        artifacts.append(
            _artifact(
                str(supporting["kind"]),
                supporting_path,
                source=source,
                owned=True,
                cue_count=int(cue_count) if cue_count is not None else None,
            )
        )
    return artifacts


def _finalize_evidence_bundle(
    manifest: dict[str, Any],
    output_dir: Path,
) -> None:
    sources = list(manifest.get("sources") or [])
    if not sources:
        return
    priority = {
        "platform_subtitle": 0,
        "hard_ocr": 1,
        "audio_asr": 2,
    }
    primary = min(
        sources,
        key=lambda item: priority.get(str(item.get("kind")), 99),
    )
    if len(sources) == 1:
        manifest["selected_source"] = dict(primary)
    else:
        manifest["selected_source"] = {
            "kind": "evidence_bundle",
            "primary": dict(primary),
            "sources": sources,
            "fusion_status": "independent_evidence",
            "provenance_note": (
                "The CLI preserves independent subtitle evidence without forcing a "
                "fusion strategy. The calling Agent chooses sources and time ranges."
            ),
        }

    primary_artifact_source = str(primary.get("artifact_source") or "")
    for artifact in manifest.get("artifacts", []):
        if artifact.get("source") == primary_artifact_source and artifact.get(
            "kind"
        ) in {"subtitle_srt", "subtitle_json", "transcript_markdown"}:
            artifact["selected"] = True

    fusion_status = "not_required" if len(sources) == 1 else "independent_evidence"

    evidence_json = output_dir / "evidence.index.json"
    write_json_atomic(
        evidence_json,
        {
            "schema_version": "video-content/evidence-index-v1",
            "job_id": manifest.get("job_id"),
            "video": manifest.get("video"),
            "primary": primary,
            "sources": sources,
            "fusion_status": fusion_status,
            "review": manifest.get("review"),
        },
    )
    evidence_markdown = output_dir / "evidence.index.md"
    lines = [
        "# 字幕证据索引",
        "",
        f"- 主证据：`{primary.get('kind')}`",
        (
            "- 融合状态：`not_required`"
            if len(sources) == 1
            else f"- 融合状态：`{fusion_status}`"
        ),
        "",
        "## 已获得来源",
        "",
    ]
    for source in sources:
        details = [
            f"kind={source.get('kind')}",
            f"cues={source.get('cue_count')}",
        ]
        if source.get("backend"):
            details.append(f"backend={source.get('backend')}")
        if source.get("detected_languages"):
            details.append(
                "languages=" + ",".join(source.get("detected_languages") or [])
            )
        lines.append("- " + "；".join(details))
    if len(sources) > 1:
        lines.extend(
            [
                "",
                "## Agent 取证原则",
                "",
                "1. 各来源是独立证据；Agent 按任务风险自行决定读取顺序。",
                "2. 使用时间范围读取所需片段，不要求先生成固定审阅窗口。",
                "3. ASR 可发现 OCR 漏句，但不可静默覆盖原始证据。",
                "4. 如需修改，创建派生产物并保留时间戳、理由和证据来源。",
            ]
        )
    evidence_markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    manifest["artifacts"].extend(
        [
            _artifact(
                "evidence_index_json",
                evidence_json,
                source="video_content",
                owned=True,
            ),
            _artifact(
                "evidence_index_markdown",
                evidence_markdown,
                source="video_content",
                owned=True,
            ),
        ]
    )


def _normalize_metadata(metadata: dict[str, str], url: str) -> dict[str, Any]:
    result: dict[str, Any] = dict(metadata)
    result["url"] = url
    duration = metadata.get("duration", "")
    seconds_match = None
    if duration:
        import re

        seconds_match = re.search(r"\((\d+)s\)", duration)
    result["duration_seconds"] = int(seconds_match.group(1)) if seconds_match else None
    for field_name in ("requires_payment", "pay_preview"):
        if field_name in result:
            result[field_name] = str(result[field_name]).lower() == "true"
    return result


def _optional_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _start_attempt(
    manifest: dict[str, Any],
    source: str,
    **details: Any,
) -> dict[str, Any]:
    attempt = {
        "source": source,
        "status": "running",
        "started_at": utc_now(),
        **details,
    }
    manifest["attempts"].append(attempt)
    return attempt


def _finish_attempt(
    attempt: dict[str, Any],
    status: str,
    *,
    finished_at: str | None = None,
    **details: Any,
) -> None:
    finished_at = finished_at or utc_now()
    attempt["status"] = status
    attempt["finished_at"] = finished_at
    started_at = attempt.get("started_at")
    if isinstance(started_at, str):
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
        attempt["elapsed_seconds"] = round((end - start).total_seconds(), 3)
    attempt.update(details)


def _write_subtitle_artifacts(
    output_dir: Path,
    cues: list[Cue],
    *,
    stem: str,
    title: str,
    source: str,
    existing_srt: Path | None = None,
) -> list[dict[str, Any]]:
    srt_path = existing_srt or output_dir / f"{stem}.srt"
    json_path = output_dir / f"{stem}.json"
    transcript_path = output_dir / f"{stem}.md"
    if existing_srt is None:
        write_srt(srt_path, cues)
    write_cues_json(json_path, cues)
    write_transcript_markdown(
        transcript_path,
        cues,
        title=title,
        source=source,
    )
    return [
        _artifact(
            "subtitle_srt", srt_path, source=source, owned=True, cue_count=len(cues)
        ),
        _artifact(
            "subtitle_json", json_path, source=source, owned=True, cue_count=len(cues)
        ),
        _artifact(
            "transcript_markdown",
            transcript_path,
            source=source,
            owned=True,
            cue_count=len(cues),
        ),
    ]


def _artifact(
    kind: str,
    path: Path,
    *,
    source: str,
    owned: bool,
    cue_count: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "kind": kind,
        "path": str(path.resolve()),
        "source": source,
        "owned_by_job": owned,
        "bytes": path.stat().st_size if path.exists() else None,
        "mib": (
            round(path.stat().st_size / (1024 * 1024), 3) if path.exists() else None
        ),
    }
    if cue_count is not None:
        result["cue_count"] = cue_count
    return result


def _download_observation(video_path: Path, result: Any) -> dict[str, Any]:
    stat = video_path.stat()
    observation: dict[str, Any] = {
        "path": str(video_path.resolve()),
        "actual_bytes": stat.st_size,
        "actual_mib": round(stat.st_size / (1024 * 1024), 3),
        "cache_hit": False,
        "retry_index": 0,
    }
    if not isinstance(result, dict):
        return observation
    for field_name in (
        "cache_key",
        "cache_hit",
        "cache_state",
        "retry_index",
        "attempt_count",
    ):
        if field_name in result:
            observation[field_name] = result[field_name]
    return observation


def _finish_completed(
    manifest: dict[str, Any],
    manifest_path: Path,
    *,
    on_update: ManifestCallback | None,
) -> dict[str, Any]:
    manifest["status"] = "completed"
    manifest["stage"] = "done"
    manifest["finished_at"] = utc_now()
    manifest["updated_at"] = utc_now()
    write_json_atomic(manifest_path, manifest)
    if on_update:
        on_update(manifest)
    return manifest


def _finish_failed(
    manifest: dict[str, Any],
    manifest_path: Path,
    *,
    error: dict[str, Any],
    on_update: ManifestCallback | None,
) -> dict[str, Any]:
    manifest["status"] = "failed"
    manifest["stage"] = error.get("stage") or manifest.get("stage")
    manifest["error"] = error
    manifest["finished_at"] = utc_now()
    manifest["updated_at"] = utc_now()
    write_json_atomic(manifest_path, manifest)
    if on_update:
        on_update(manifest)
    return manifest
