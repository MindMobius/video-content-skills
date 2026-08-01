from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from .backends.asr import Qwen3AsrOptions, asr_doctor
from .backends.ocr import VideOcrOptions, ocr_doctor
from .core.evidence import (
    list_subtitle_evidence_for_manifest,
    read_subtitle_evidence_range,
)
from .core.review import (
    ReviewOptions,
    get_review_window,
    prepare_review_for_manifest,
    submit_review_window,
)
from .core.util import utc_now
from .jobs import JobStore
from .pipeline import ExtractionRequest
from .platforms.bilibili import (
    OpenCliClient,
    OpenCliError,
    OpenCliSettings,
    bilibili_auth_ready,
    executable_status,
)

try:
    # MCP Python SDK 2.x
    from mcp.server import MCPServer as McpServer
except ImportError:
    try:
        # MCP Python SDK 1.x
        from mcp.server.fastmcp import FastMCP as McpServer
    except ImportError:  # pragma: no cover - exercised by installation workflow
        McpServer = None  # type: ignore[assignment,misc]


@dataclass
class ReviewDecisionInput:
    """One auditable subtitle edit proposed by the calling Agent."""

    action: Literal["keep", "replace", "delete", "insert"]
    cue_id: str | None = None
    confidence: Literal["high", "medium", "low"] = "high"
    original_text: str | None = None
    reviewed_text: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    reason: str | None = None
    evidence: list[str] | None = None


@dataclass
class ReviewUnresolvedInput:
    """One ambiguity the calling Agent intentionally leaves unresolved."""

    issue: str
    cue_id: str | None = None
    evidence: list[str] | None = None


def _settings() -> OpenCliSettings:
    return OpenCliSettings.discover()


def _store() -> JobStore:
    return JobStore.from_environment()


def _environment(suffix: str) -> str | None:
    return os.getenv(f"VIDEO_SUBTITLE_{suffix}") or os.getenv(
        f"SUBTITLE_AGENT_{suffix}"
    )


def doctor() -> dict[str, Any]:
    """Inspect login transport and local extraction capabilities before use."""
    settings = _settings()
    client = OpenCliClient(settings)
    opencli: dict[str, Any] = {
        "command": settings.display_command,
        "profile": settings.profile,
        "ytdlp": settings.ytdlp_path,
        "ffmpeg": settings.ffmpeg_path,
        "available": client.is_command_available(),
        "platform_ready": False,
    }
    if opencli["available"]:
        try:
            opencli["auth"] = client.auth_status()
            opencli["platform_ready"] = bilibili_auth_ready(opencli["auth"])
            if not opencli["platform_ready"]:
                opencli["error"] = {
                    "code": "BILIBILI_LOGIN_REQUIRED",
                    "message": "The selected OpenCLI profile is not logged in to Bilibili.",
                }
        except OpenCliError as error:
            opencli["error"] = error.as_dict()
    download_tools = {
        "yt_dlp": executable_status(settings.ytdlp_path, "yt-dlp"),
        "ffmpeg": executable_status(settings.ffmpeg_path, "ffmpeg"),
    }
    ocr = ocr_doctor(VideOcrOptions())
    asr = asr_doctor(
        Qwen3AsrOptions(
            python_executable=_environment("ASR_PYTHON"),
            ffmpeg_executable=settings.ffmpeg_path,
            model=_environment("QWEN_ASR_MODEL"),
            aligner=_environment("QWEN_ALIGNER_MODEL"),
        )
    )
    local_ocr_ready = bool(ocr["available"])
    url_ocr_ready = local_ocr_ready and all(
        bool(item["available"]) for item in download_tools.values()
    )
    return {
        "schema_version": "video-subtitle/doctor-v1",
        "checked_at": utc_now(),
        "opencli": opencli,
        "download_tools": download_tools,
        "hard_ocr": ocr,
        "audio_asr": asr,
        "capabilities": {
            "platform_subtitle": bool(opencli["platform_ready"]),
            "hard_subtitle_ocr_local_video": local_ocr_ready,
            "hard_subtitle_ocr_from_url": url_ocr_ready,
            "audio_asr_local_video": bool(asr["available"]),
            "audio_asr_from_url": bool(asr["available"])
            and all(bool(item["available"]) for item in download_tools.values()),
        },
    }


def inspect_bilibili_video(url: str, page: int | None = None) -> dict[str, Any]:
    """Read Bilibili metadata without starting subtitle extraction."""
    metadata = OpenCliClient(_settings()).video(url, page=page)
    return {
        "schema_version": "video-subtitle/inspect-v1",
        "source": "opencli:bilibili",
        "video": metadata,
    }


def start_subtitle_extraction(
    url: str,
    language: str = "ai-zh",
    page: int | None = None,
    ocr_backend: str = "auto",
    collect_all_sources: bool = False,
    asr_backend: str = "none",
    asr_language: str = "auto",
    asr_context: str = "",
    asr_time_start: str = "0:00",
    asr_time_end: str = "",
    asr_chunk_seconds: int = 240,
    asr_max_cue_seconds: float = 10.0,
    asr_max_cue_chars: int = 84,
    video_path: str | None = None,
    download_if_needed: bool = True,
    download_quality: str = "1080p",
    ocr_language: str = "ch",
    ocr_gpu: bool = False,
    full_frame: bool = False,
    crop: list[int] | None = None,
    time_start: str = "0:00",
    time_end: str = "",
    ocr_image_max_width: int = 720,
    ocr_consensus_image_max_width: int | None = None,
    min_subtitle_duration: float = 0.2,
) -> dict[str, Any]:
    """Start a durable job; return immediately and poll get_subtitle_job."""
    parsed_crop: tuple[int, int, int, int] | None = None
    if crop is not None:
        if len(crop) != 4:
            raise ValueError("crop must be [x, y, width, height]")
        parsed_crop = tuple(int(item) for item in crop)  # type: ignore[assignment]
        if parsed_crop[0] < 0 or parsed_crop[1] < 0:
            raise ValueError("crop x/y cannot be negative")
        if parsed_crop[2] <= 0 or parsed_crop[3] <= 0:
            raise ValueError("crop width/height must be positive")
    if full_frame and parsed_crop:
        raise ValueError("full_frame and crop are mutually exclusive")
    if page is not None and page < 1:
        raise ValueError("page must be at least 1")
    if ocr_image_max_width < 1:
        raise ValueError("ocr_image_max_width must be positive")
    if ocr_consensus_image_max_width is not None and ocr_consensus_image_max_width < 1:
        raise ValueError("ocr_consensus_image_max_width must be positive")
    if min_subtitle_duration < 0:
        raise ValueError("min_subtitle_duration cannot be negative")
    if asr_backend not in {"none", "auto", "qwen3"}:
        raise ValueError("asr_backend must be none, auto, or qwen3")
    if not 30 <= asr_chunk_seconds <= 300:
        raise ValueError("asr_chunk_seconds must be between 30 and 300")
    if asr_max_cue_seconds <= 0:
        raise ValueError("asr_max_cue_seconds must be positive")
    if asr_max_cue_chars < 10:
        raise ValueError("asr_max_cue_chars must be at least 10")

    options = VideOcrOptions(
        executable=_environment("VIDEOCR"),
        language=ocr_language,
        use_gpu=ocr_gpu,
        full_frame=full_frame,
        crop=parsed_crop,
        time_start=time_start,
        time_end=time_end,
        image_max_width=ocr_image_max_width,
        consensus_image_max_width=ocr_consensus_image_max_width,
        min_subtitle_duration=min_subtitle_duration,
    )
    asr_options = Qwen3AsrOptions(
        python_executable=_environment("ASR_PYTHON"),
        ffmpeg_executable=_environment("FFMPEG"),
        model=_environment("QWEN_ASR_MODEL"),
        aligner=_environment("QWEN_ALIGNER_MODEL"),
        language=asr_language,
        context=asr_context,
        context_source="mcp_request" if asr_context else "none",
        time_start=asr_time_start,
        time_end=asr_time_end,
        chunk_seconds=asr_chunk_seconds,
        max_cue_seconds=asr_max_cue_seconds,
        max_cue_chars=asr_max_cue_chars,
    )
    request = ExtractionRequest(
        url=url,
        output_dir=Path("."),
        language=language,
        page=page,
        ocr_backend=ocr_backend,
        video_path=Path(video_path) if video_path else None,
        download_if_needed=download_if_needed,
        download_quality=download_quality,
        collect_all_sources=collect_all_sources,
        asr_backend=asr_backend,
        videocr=options,
        qwen3_asr=asr_options,
    )
    return _store().start(request, _settings())


def get_subtitle_job(job_id: str) -> dict[str, Any]:
    """Read the current manifest of a durable subtitle extraction job."""
    return _store().get(job_id)


def list_subtitle_evidence(job_id: str) -> dict[str, Any]:
    """List independent subtitle evidence so the Agent can choose what to inspect."""
    return list_subtitle_evidence_for_manifest(_job_manifest_path(job_id))


def read_subtitle_evidence(
    job_id: str,
    evidence_id: str,
    start_ms: int = 0,
    end_ms: int | None = None,
    max_cues: int = 120,
) -> dict[str, Any]:
    """Read an arbitrary time range from one Agent-selected subtitle source."""
    return read_subtitle_evidence_range(
        _job_manifest_path(job_id),
        evidence_id=evidence_id,
        start_ms=start_ms,
        end_ms=end_ms,
        max_cues=max_cues,
    )


def prepare_subtitle_review(
    job_id: str,
    window_seconds: int = 30,
    context_seconds: float = 2.0,
) -> dict[str, Any]:
    """Optionally suggest fixed OCR/ASR review windows; this is not a required flow."""
    return prepare_review_for_manifest(
        _job_manifest_path(job_id),
        options=ReviewOptions(
            window_seconds=window_seconds,
            context_seconds=context_seconds,
        ),
    )


def get_subtitle_review_window(
    job_id: str,
    window_id: str = "",
) -> dict[str, Any]:
    """Read the review index or one bounded time-aligned OCR/ASR window."""
    return get_review_window(
        _job_manifest_path(job_id),
        window_id or None,
    )


def submit_subtitle_review_window(
    job_id: str,
    window_id: str,
    decisions: list[ReviewDecisionInput],
    unresolved: list[ReviewUnresolvedInput] | None = None,
    notes: str = "",
    reviewer: str = "agent",
) -> dict[str, Any]:
    """Persist one Agent review window and apply only high-confidence changes."""
    return submit_review_window(
        _job_manifest_path(job_id),
        window_id=window_id,
        decisions=[_compact_dataclass(item) for item in decisions],
        unresolved=(
            [_compact_dataclass(item) for item in unresolved]
            if unresolved is not None
            else None
        ),
        notes=notes,
        reviewer=reviewer,
    )


def read_subtitle_artifact(
    job_id: str,
    artifact_kind: str = "transcript_markdown",
    offset: int = 0,
    max_chars: int = 20_000,
) -> dict[str, Any]:
    """Read a bounded chunk from a text artifact produced by a subtitle job."""
    if offset < 0:
        raise ValueError("offset cannot be negative")
    if max_chars < 1 or max_chars > 100_000:
        raise ValueError("max_chars must be between 1 and 100000")
    manifest = _store().get(job_id)
    requested_artifact_kind = artifact_kind
    reviewed_alias = {
        "subtitle_srt": "reviewed_subtitle_srt",
        "subtitle_json": "reviewed_subtitle_json",
        "transcript_markdown": "reviewed_transcript_markdown",
    }.get(artifact_kind)
    if (
        reviewed_alias
        and (manifest.get("review") or {}).get("status") == "complete"
        and any(
            artifact.get("kind") == reviewed_alias and artifact.get("selected") is True
            for artifact in manifest.get("artifacts", [])
        )
    ):
        artifact_kind = reviewed_alias
    artifacts = [
        artifact
        for artifact in manifest.get("artifacts", [])
        if artifact.get("kind") == artifact_kind
    ]
    if not artifacts:
        raise FileNotFoundError(
            f"Job {job_id} has no artifact with kind {artifact_kind!r}"
        )
    job_directory = Path(manifest["job_directory"]).resolve()
    selected_artifacts = [
        artifact for artifact in artifacts if artifact.get("selected") is True
    ]
    artifact_path = Path(str((selected_artifacts or artifacts)[-1]["path"])).resolve()
    try:
        artifact_path.relative_to(job_directory)
    except ValueError as error:
        raise ValueError(
            "Refusing to read an artifact outside the job directory"
        ) from error
    content = artifact_path.read_text(encoding="utf-8", errors="replace")
    chunk = content[offset : offset + max_chars]
    return {
        "job_id": job_id,
        "requested_artifact_kind": requested_artifact_kind,
        "artifact_kind": artifact_kind,
        "path": str(artifact_path),
        "offset": offset,
        "next_offset": offset + len(chunk),
        "total_chars": len(content),
        "has_more": offset + len(chunk) < len(content),
        "content": chunk,
    }


if McpServer is not None:
    mcp = McpServer(
        "video-subtitle",
        instructions=(
            "Use OpenCLI, hard OCR, and optional Qwen3-ASR as independent evidence "
            "sources. Prefer list_subtitle_evidence and read_subtitle_evidence so the "
            "calling Agent chooses which source and time range to inspect. Fixed review "
            "windows are an optional hint, not a required workflow. Raw evidence is "
            "immutable; create derived artifacts for corrections. needs_ocr is an "
            "actionable state, not success."
        ),
    )
    mcp.tool(name="video_subtitle_doctor")(doctor)
    mcp.tool(name="inspect_bilibili_video")(inspect_bilibili_video)
    mcp.tool(name="start_subtitle_extraction")(start_subtitle_extraction)
    mcp.tool(name="get_subtitle_job")(get_subtitle_job)
    mcp.tool(name="list_subtitle_evidence")(list_subtitle_evidence)
    mcp.tool(name="read_subtitle_evidence")(read_subtitle_evidence)
    mcp.tool(name="prepare_subtitle_review")(prepare_subtitle_review)
    mcp.tool(name="get_subtitle_review_window")(get_subtitle_review_window)
    mcp.tool(name="submit_subtitle_review_window")(submit_subtitle_review_window)
    mcp.tool(name="read_subtitle_artifact")(read_subtitle_artifact)
else:
    mcp = None


def main() -> None:
    if mcp is None:
        raise SystemExit(
            'MCP dependency is missing. Install with: pip install -e ".[mcp]"'
        )
    mcp.run(transport="stdio")


def _job_manifest_path(job_id: str) -> Path:
    manifest = _store().get(job_id)
    return Path(str(manifest["job_directory"])) / "manifest.json"


def _compact_dataclass(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        payload = dict(value)
    else:
        payload = asdict(value)
    return {key: item for key, item in payload.items() if item is not None}


if __name__ == "__main__":
    main()
