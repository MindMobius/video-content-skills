from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .backends.asr import Qwen3AsrOptions
from .backends.ocr import VideOcrOptions
from .config import CONFIG_ENVIRONMENT, apply_configuration, update_configuration
from .core.content import (
    get_content_project,
    initialize_content_project,
    read_content_artifact,
    save_content_deliverable,
    save_content_document,
    validate_content_project,
)
from .core.evidence import (
    list_subtitle_evidence_for_manifest,
    read_subtitle_evidence_range,
)
from .core.review import (
    ReviewOptions,
    apply_review_document,
    get_review_window,
    prepare_review_for_manifest,
)
from .core.util import json_for_stdout, read_json, utc_now
from .diagnostics import doctor
from .environment import normalize_capabilities
from .jobs import JobStore, run_worker_request
from .pipeline import ExtractionPipeline, ExtractionRequest
from .platforms.bilibili import (
    OpenCliClient,
    OpenCliError,
    OpenCliSettings,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="video-subtitle",
        description="Composable video subtitle evidence tools",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--config",
        type=Path,
        help="Persistent config file (default: VIDEO_SUBTITLE_CONFIG or user config)",
    )
    parser.add_argument(
        "--opencli",
        help="Path to opencli, opencli executable, or the built OpenCLI main.js",
    )
    parser.add_argument("--profile", help="OpenCLI Browser Bridge profile alias")
    parser.add_argument("--ytdlp", help="Absolute path to yt-dlp executable")
    parser.add_argument("--ffmpeg", help="Absolute path to ffmpeg executable")
    parser.add_argument(
        "--opencli-browser-timeout",
        type=_positive_int,
        help="OpenCLI browser command timeout in seconds (default: 180)",
    )
    parser.add_argument(
        "--download-retries",
        type=_nonnegative_int,
        help="Retries after transient OpenCLI download failures (default: 2)",
    )
    parser.add_argument(
        "--download-retry-backoff",
        type=_nonnegative_float,
        help="Linear retry backoff in seconds (default: 2)",
    )
    parser.add_argument(
        "--asr-python",
        help="Python executable containing torch, qwen-asr, and CUDA support",
    )
    parser.add_argument(
        "--qwen-asr-model",
        help="Local Qwen3-ASR model directory or model identifier",
    )
    parser.add_argument(
        "--qwen-aligner-model",
        help="Local Qwen3 Forced Aligner directory or model identifier",
    )
    parser.add_argument(
        "--home",
        help="Job store directory (default: VIDEO_SUBTITLE_HOME or ./.video-subtitle)",
    )

    commands = parser.add_subparsers(dest="command", required=True)
    doctor_parser = commands.add_parser(
        "doctor",
        help="Verify required capabilities, login state, OCR, and ASR runtime",
    )
    _add_capability_arguments(doctor_parser)
    doctor_parser.add_argument(
        "--quick",
        action="store_true",
        help="Check paths and configuration without importing CUDA models",
    )

    setup_parser = commands.add_parser(
        "setup",
        help="Return machine-readable agent and human dependency actions",
    )
    _add_capability_arguments(setup_parser)
    setup_parser.add_argument(
        "--deep",
        action="store_true",
        help="Also import the ASR runtime and verify CUDA",
    )

    configure_parser = commands.add_parser(
        "configure",
        help="Persist discovered dependency paths for future CLI and MCP runs",
    )
    configure_parser.add_argument("--opencli", dest="config_opencli")
    configure_parser.add_argument("--profile", dest="config_opencli_profile")
    configure_parser.add_argument("--ytdlp", dest="config_ytdlp")
    configure_parser.add_argument("--ffmpeg", dest="config_ffmpeg")
    configure_parser.add_argument("--videocr", dest="config_videocr")
    configure_parser.add_argument("--asr-python", dest="config_asr_python")
    configure_parser.add_argument("--qwen-asr-model", dest="config_qwen_asr_model")
    configure_parser.add_argument(
        "--qwen-aligner-model", dest="config_qwen_aligner_model"
    )
    configure_parser.add_argument("--home", dest="config_home")
    configure_parser.add_argument(
        "--opencli-browser-timeout",
        dest="config_opencli_browser_timeout",
        type=_positive_int,
    )
    configure_parser.add_argument(
        "--download-retries",
        dest="config_download_retries",
        type=_nonnegative_int,
    )
    configure_parser.add_argument(
        "--download-retry-backoff",
        dest="config_download_retry_backoff",
        type=_nonnegative_float,
    )
    configure_parser.add_argument(
        "--download-cache",
        dest="config_download_cache",
        type=Path,
    )
    configure_parser.add_argument(
        "--media-execution",
        dest="config_media_execution",
        choices=("auto", "serial", "parallel"),
    )
    configure_parser.add_argument(
        "--clear",
        action="append",
        choices=tuple(CONFIG_ENVIRONMENT),
        default=[],
        help="Remove one persisted field; may be repeated",
    )

    inspect_parser = commands.add_parser("inspect", help="Read Bilibili video metadata")
    inspect_parser.add_argument("url")
    inspect_parser.add_argument("--page", type=_positive_int)

    extract_parser = commands.add_parser(
        "extract",
        help="Run extraction synchronously and write a manifest",
    )
    extract_parser.add_argument("url")
    extract_parser.add_argument("--output", type=Path, required=True)
    _add_extraction_arguments(extract_parser)

    start_parser = commands.add_parser(
        "start",
        help="Start extraction as a durable background job",
    )
    start_parser.add_argument("url")
    _add_extraction_arguments(start_parser)

    status_parser = commands.add_parser("status", help="Read a background job manifest")
    status_parser.add_argument("job_id")

    evidence_list_parser = commands.add_parser(
        "evidence-list",
        help="List subtitle evidence that an Agent can inspect independently",
    )
    evidence_list_parser.add_argument("--manifest", type=Path, required=True)

    evidence_read_parser = commands.add_parser(
        "evidence-read",
        help="Read an Agent-selected time range from one subtitle evidence source",
    )
    evidence_read_parser.add_argument("--manifest", type=Path, required=True)
    evidence_read_parser.add_argument("--evidence-id", required=True)
    evidence_read_parser.add_argument("--start-ms", type=int, default=0)
    evidence_read_parser.add_argument("--end-ms", type=int)
    evidence_read_parser.add_argument("--max-cues", type=int, default=120)

    review_prepare_parser = commands.add_parser(
        "review-prepare",
        help="Build time-aligned OCR/ASR review windows for an existing manifest",
    )
    review_prepare_parser.add_argument("--manifest", type=Path, required=True)
    review_prepare_parser.add_argument("--window-seconds", type=int, default=30)
    review_prepare_parser.add_argument("--context-seconds", type=float, default=2.0)

    review_window_parser = commands.add_parser(
        "review-window",
        help="Read the review-window index or one structured review window",
    )
    review_window_parser.add_argument("--manifest", type=Path, required=True)
    review_window_parser.add_argument("--window-id")

    review_apply_parser = commands.add_parser(
        "review-apply",
        help="Apply agent review-window decisions without modifying raw evidence",
    )
    review_apply_parser.add_argument("--manifest", type=Path, required=True)
    review_apply_parser.add_argument("--decisions", type=Path, required=True)

    content_init_parser = commands.add_parser(
        "content-init",
        help="Create a content project pinned to one completed subtitle manifest",
    )
    content_init_parser.add_argument("--manifest", type=Path, required=True)
    content_init_parser.add_argument(
        "--objective", default="faithful_information_transfer"
    )
    content_init_parser.add_argument("--audience", default="")
    content_init_parser.add_argument("--output-language", default="zh-CN")

    content_status_parser = commands.add_parser(
        "content-status", help="Read a content project and its integrity status"
    )
    content_status_parser.add_argument("--project", type=Path, required=True)

    content_save_parser = commands.add_parser(
        "content-save",
        help="Validate and version an Agent-authored content document",
    )
    content_save_parser.add_argument("--project", type=Path, required=True)
    content_save_parser.add_argument(
        "--kind",
        choices=("content_map", "media_plan", "fidelity_audit"),
        required=True,
    )
    content_save_parser.add_argument("--document", type=Path, required=True)

    content_deliverable_parser = commands.add_parser(
        "content-deliverable",
        help="Version a generated article, one-page visual, card set, brief, or script",
    )
    content_deliverable_parser.add_argument("--project", type=Path, required=True)
    content_deliverable_parser.add_argument(
        "--medium",
        choices=("article", "one_page", "card_series", "brief", "script", "custom"),
        required=True,
    )
    content_deliverable_parser.add_argument(
        "--format",
        choices=("markdown", "html", "svg", "json", "text"),
        required=True,
    )
    content_deliverable_parser.add_argument("--content-file", type=Path, required=True)
    content_deliverable_parser.add_argument("--title", required=True)
    content_deliverable_parser.add_argument(
        "--used-claim-id", action="append", default=[]
    )
    content_deliverable_parser.add_argument(
        "--used-caveat-id", action="append", default=[]
    )

    content_read_parser = commands.add_parser(
        "content-read", help="Read a bounded content-project artifact"
    )
    content_read_parser.add_argument("--project", type=Path, required=True)
    content_read_parser.add_argument(
        "--artifact",
        choices=(
            "project",
            "latest_content_map",
            "latest_media_plan",
            "latest_deliverable",
            "latest_fidelity_audit",
            "artifact_id",
        ),
        default="latest_deliverable",
    )
    content_read_parser.add_argument("--artifact-id", default="")
    content_read_parser.add_argument("--offset", type=int, default=0)
    content_read_parser.add_argument("--max-chars", type=int, default=20_000)

    content_validate_parser = commands.add_parser(
        "content-validate",
        help="Verify pinned evidence, artifact hashes, and delivery readiness",
    )
    content_validate_parser.add_argument("--project", type=Path, required=True)

    worker_parser = commands.add_parser("_worker", help=argparse.SUPPRESS)
    worker_parser.add_argument("--request-file", type=Path, required=True)
    return parser


def _add_capability_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--capability",
        action="append",
        choices=(
            "all",
            "platform_subtitle",
            "video_download",
            "hard_ocr_local",
            "hard_ocr_url",
            "audio_asr_local",
            "audio_asr_url",
        ),
        help=(
            "Capability that must be ready; may be repeated. Defaults to platform "
            "subtitles plus URL hard-OCR fallback."
        ),
    )


def _add_extraction_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--lang", default="ai-zh", help="Requested Bilibili subtitle language"
    )
    parser.add_argument(
        "--page", type=_positive_int, help="1-based Bilibili multipart index"
    )
    parser.add_argument(
        "--ocr-backend",
        choices=("auto", "videocr", "none"),
        default="auto",
    )
    parser.add_argument(
        "--collect-all-sources",
        action="store_true",
        help="Continue after platform subtitles and preserve all configured evidence",
    )
    parser.add_argument(
        "--media-execution",
        choices=("auto", "serial", "parallel"),
        default=None,
        help=(
            "Schedule OCR/ASR serially or concurrently. auto uses serial when "
            "both backends share the GPU and parallel otherwise."
        ),
    )
    parser.add_argument(
        "--asr-backend",
        choices=("none", "auto", "qwen3"),
        default="none",
        help="Optional audio transcription backend",
    )
    parser.add_argument(
        "--asr-language",
        default="auto",
        help="Qwen3-ASR language name or auto",
    )
    parser.add_argument(
        "--asr-context",
        default="",
        help="Verified spelling context for names and technical terms",
    )
    parser.add_argument(
        "--asr-context-file",
        type=Path,
        help="UTF-8 file containing verified ASR spelling context",
    )
    parser.add_argument("--asr-time-start", default="0:00")
    parser.add_argument("--asr-time-end", default="")
    parser.add_argument("--asr-chunk-seconds", type=int, default=240)
    parser.add_argument("--asr-max-cue-seconds", type=float, default=10.0)
    parser.add_argument("--asr-max-cue-chars", type=int, default=84)
    parser.add_argument("--ocr-executable", help="Path to videocr-cli executable")
    parser.add_argument("--ocr-lang", default="ch", help="VideOCR/PaddleOCR language")
    parser.add_argument(
        "--ocr-gpu",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Pass GPU mode to VideOCR",
    )
    parser.add_argument(
        "--download",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Allow OpenCLI to download the video when hard OCR is needed",
    )
    parser.add_argument(
        "--quality",
        choices=("best", "1080p", "720p", "480p"),
        default="1080p",
    )
    parser.add_argument(
        "--download-cache",
        type=Path,
        help=(
            "Persistent media cache. Background jobs default to "
            "<VIDEO_SUBTITLE_HOME>/cache/media."
        ),
    )
    parser.add_argument(
        "--video", type=Path, help="Existing local video; skips download"
    )
    parser.add_argument(
        "--full-frame",
        action="store_true",
        help="OCR the full frame instead of VideOCR's bottom-third default",
    )
    parser.add_argument(
        "--crop",
        help="OCR crop as x,y,width,height; cannot be combined with --full-frame",
    )
    parser.add_argument("--time-start", default="0:00")
    parser.add_argument("--time-end", default="")
    parser.add_argument("--conf-threshold", type=int, default=75)
    parser.add_argument("--sim-threshold", type=int, default=80)
    parser.add_argument("--frames-to-skip", type=int, default=1)
    parser.add_argument("--ocr-image-max-width", type=int, default=720)
    parser.add_argument(
        "--ocr-consensus-image-max-width",
        type=int,
        help=(
            "Run a second OCR pass at this width and keep text corroborated across "
            "both scales"
        ),
    )
    parser.add_argument("--min-subtitle-duration", type=float, default=0.2)


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        apply_configuration(args.config)
        result, exit_code = dispatch(args)
    except (TypeError, ValueError, FileNotFoundError, OpenCliError) as error:
        code = (
            error.code
            if isinstance(error, OpenCliError)
            else type(error).__name__.upper()
        )
        result = {
            "ok": False,
            "error": {
                "code": code,
                "message": str(error),
            },
        }
        exit_code = 1
    except KeyboardInterrupt:
        result = {
            "ok": False,
            "error": {"code": "INTERRUPTED", "message": "Operation interrupted"},
        }
        exit_code = 130
    except Exception as error:  # noqa: BLE001 - CLI must preserve its JSON error contract
        result = {
            "ok": False,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": str(error),
                "type": type(error).__name__,
            },
        }
        exit_code = 1
    print(json_for_stdout(result))
    raise SystemExit(exit_code)


def dispatch(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    if args.command == "_worker":
        result = run_worker_request(args.request_file)
        return result, _manifest_exit_code(result)

    if args.command == "status":
        store = JobStore.from_environment(args.home)
        result = store.get(args.job_id)
        return result, _manifest_exit_code(result, status_command=True)

    if args.command == "evidence-list":
        return list_subtitle_evidence_for_manifest(args.manifest), 0

    if args.command == "evidence-read":
        return (
            read_subtitle_evidence_range(
                args.manifest,
                evidence_id=args.evidence_id,
                start_ms=args.start_ms,
                end_ms=args.end_ms,
                max_cues=args.max_cues,
            ),
            0,
        )

    if args.command == "review-prepare":
        result = prepare_review_for_manifest(
            args.manifest,
            options=ReviewOptions(
                window_seconds=args.window_seconds,
                context_seconds=args.context_seconds,
            ),
        )
        return result, 0

    if args.command == "review-window":
        return get_review_window(args.manifest, args.window_id), 0

    if args.command == "review-apply":
        decisions = read_json(args.decisions.resolve())
        if not isinstance(decisions, dict):
            raise ValueError("Review decisions must be a JSON object")
        return apply_review_document(args.manifest, decisions), 0

    if args.command == "content-init":
        return (
            initialize_content_project(
                args.manifest,
                objective=args.objective,
                audience=args.audience,
                output_language=args.output_language,
            ),
            0,
        )

    if args.command == "content-status":
        return get_content_project(args.project), 0

    if args.command == "content-save":
        document = read_json(args.document.resolve())
        if not isinstance(document, dict):
            raise ValueError("Content document must be a JSON object")
        return (
            save_content_document(args.project, kind=args.kind, document=document),
            0,
        )

    if args.command == "content-deliverable":
        content_path = args.content_file.resolve()
        if not content_path.is_file():
            raise FileNotFoundError(
                f"Deliverable source does not exist: {content_path}"
            )
        return (
            save_content_deliverable(
                args.project,
                medium=args.medium,
                format=args.format,
                content=content_path.read_text(encoding="utf-8", errors="replace"),
                title=args.title,
                used_claim_ids=args.used_claim_id,
                used_caveat_ids=args.used_caveat_id,
            ),
            0,
        )

    if args.command == "content-read":
        return (
            read_content_artifact(
                args.project,
                artifact=args.artifact,
                artifact_id=args.artifact_id,
                offset=args.offset,
                max_chars=args.max_chars,
            ),
            0,
        )

    if args.command == "content-validate":
        result = validate_content_project(args.project)
        return result, 0 if result["valid"] else 1

    if args.command == "configure":
        result = update_configuration(
            _configuration_values_from_args(args),
            clear=args.clear,
            path=args.config,
        )
        return result, 0

    settings = OpenCliSettings.discover(
        opencli=args.opencli,
        profile=args.profile,
        ytdlp=args.ytdlp,
        ffmpeg=args.ffmpeg,
        browser_command_timeout_seconds=args.opencli_browser_timeout,
        download_retries=args.download_retries,
        download_retry_backoff_seconds=args.download_retry_backoff,
        allow_missing=args.command in {"doctor", "setup"},
    )
    client = OpenCliClient(settings)

    if args.command in {"doctor", "setup"}:
        capabilities = normalize_capabilities(args.capability)
        result = doctor(
            client,
            Qwen3AsrOptions(
                python_executable=args.asr_python,
                ffmpeg_executable=args.ffmpeg,
                model=args.qwen_asr_model,
                aligner=args.qwen_aligner_model,
            ),
            capabilities=capabilities,
            deep=(not args.quick if args.command == "doctor" else args.deep),
            config_path=args.config,
        )
        return (result if args.command == "doctor" else result["setup"]), 0

    if args.command == "inspect":
        metadata = client.video(args.url, page=args.page)
        return {
            "schema_version": "video-subtitle/inspect-v1",
            "ok": True,
            "checked_at": utc_now(),
            "source": "opencli:bilibili",
            "video": metadata,
        }, 0

    if args.command in {"extract", "start"}:
        output = args.output if args.command == "extract" else Path(".")
        request = _request_from_args(args, output)
        if args.command == "start":
            store = JobStore.from_environment(args.home)
            manifest = store.start(request, settings)
            return manifest, 0 if manifest.get("status") != "failed" else 1
        pipeline = ExtractionPipeline(client)
        manifest = pipeline.run(request)
        return manifest, _manifest_exit_code(manifest)

    raise ValueError(f"Unsupported command: {args.command}")


def _request_from_args(args: argparse.Namespace, output_dir: Path) -> ExtractionRequest:
    crop = _parse_crop(args.crop) if args.crop else None
    if crop and args.full_frame:
        raise ValueError("--crop and --full-frame are mutually exclusive")
    if not 0 <= args.conf_threshold <= 100:
        raise ValueError("--conf-threshold must be between 0 and 100")
    if not 0 <= args.sim_threshold <= 100:
        raise ValueError("--sim-threshold must be between 0 and 100")
    if args.frames_to_skip < 0:
        raise ValueError("--frames-to-skip cannot be negative")
    if args.ocr_image_max_width < 1:
        raise ValueError("--ocr-image-max-width must be positive")
    if (
        args.ocr_consensus_image_max_width is not None
        and args.ocr_consensus_image_max_width < 1
    ):
        raise ValueError("--ocr-consensus-image-max-width must be positive")
    if args.min_subtitle_duration < 0:
        raise ValueError("--min-subtitle-duration cannot be negative")
    if args.asr_context and args.asr_context_file:
        raise ValueError("--asr-context and --asr-context-file are mutually exclusive")
    if not 30 <= args.asr_chunk_seconds <= 300:
        raise ValueError("--asr-chunk-seconds must be between 30 and 300")
    if args.asr_max_cue_seconds <= 0:
        raise ValueError("--asr-max-cue-seconds must be positive")
    if args.asr_max_cue_chars < 10:
        raise ValueError("--asr-max-cue-chars must be at least 10")
    asr_context = args.asr_context
    context_source = "request" if asr_context else "none"
    if args.asr_context_file:
        asr_context = args.asr_context_file.resolve().read_text(
            encoding="utf-8",
            errors="replace",
        )
        context_source = f"file:{args.asr_context_file.resolve()}"
    options = VideOcrOptions(
        executable=args.ocr_executable,
        language=args.ocr_lang,
        use_gpu=args.ocr_gpu,
        full_frame=args.full_frame,
        crop=crop,
        time_start=args.time_start,
        time_end=args.time_end,
        confidence_threshold=args.conf_threshold,
        similarity_threshold=args.sim_threshold,
        frames_to_skip=args.frames_to_skip,
        image_max_width=args.ocr_image_max_width,
        consensus_image_max_width=args.ocr_consensus_image_max_width,
        min_subtitle_duration=args.min_subtitle_duration,
    )
    asr_options = Qwen3AsrOptions(
        python_executable=args.asr_python,
        ffmpeg_executable=args.ffmpeg,
        model=args.qwen_asr_model,
        aligner=args.qwen_aligner_model,
        language=args.asr_language,
        context=asr_context,
        context_source=context_source,
        time_start=args.asr_time_start,
        time_end=args.asr_time_end,
        chunk_seconds=args.asr_chunk_seconds,
        max_cue_seconds=args.asr_max_cue_seconds,
        max_cue_chars=args.asr_max_cue_chars,
    )
    return ExtractionRequest(
        url=args.url,
        output_dir=output_dir,
        language=args.lang,
        page=args.page,
        ocr_backend=args.ocr_backend,
        video_path=args.video,
        download_if_needed=args.download,
        download_quality=args.quality,
        download_cache_dir=(
            args.download_cache
            or (
                Path(os.environ["VIDEO_SUBTITLE_DOWNLOAD_CACHE"])
                if os.getenv("VIDEO_SUBTITLE_DOWNLOAD_CACHE")
                else None
            )
        ),
        collect_all_sources=args.collect_all_sources,
        asr_backend=args.asr_backend,
        media_execution=(
            args.media_execution
            or os.getenv("VIDEO_SUBTITLE_MEDIA_EXECUTION")
            or "auto"
        ),
        videocr=options,
        qwen3_asr=asr_options,
    )


def _configuration_values_from_args(
    args: argparse.Namespace,
) -> dict[str, Any]:
    return {
        "opencli": args.config_opencli,
        "opencli_profile": args.config_opencli_profile,
        "ytdlp": args.config_ytdlp,
        "ffmpeg": args.config_ffmpeg,
        "videocr": args.config_videocr,
        "asr_python": args.config_asr_python,
        "qwen_asr_model": args.config_qwen_asr_model,
        "qwen_aligner_model": args.config_qwen_aligner_model,
        "home": args.config_home,
        "media_execution": args.config_media_execution,
        "opencli_browser_timeout": args.config_opencli_browser_timeout,
        "download_retries": args.config_download_retries,
        "download_retry_backoff": args.config_download_retry_backoff,
        "download_cache": args.config_download_cache,
    }


def _parse_crop(value: str) -> tuple[int, int, int, int]:
    try:
        crop = tuple(int(item.strip()) for item in value.split(","))
    except ValueError as error:
        raise ValueError("--crop must be x,y,width,height") from error
    if len(crop) != 4:
        raise ValueError("--crop must contain exactly x,y,width,height")
    x, y, width, height = crop
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError("--crop requires x/y >= 0 and width/height > 0")
    return x, y, width, height


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("cannot be negative")
    return parsed


def _nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("cannot be negative")
    return parsed


def _manifest_exit_code(
    manifest: dict[str, Any],
    *,
    status_command: bool = False,
) -> int:
    status = manifest.get("status")
    if status in {"completed", "queued", "running"}:
        return 0
    if status == "needs_ocr":
        return 0 if status_command else 2
    return 1


if __name__ == "__main__":
    main()
