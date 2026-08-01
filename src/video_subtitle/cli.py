from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .backends.asr import Qwen3AsrOptions, asr_doctor
from .backends.ocr import VideOcrOptions, ocr_doctor
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
from .jobs import JobStore, run_worker_request
from .pipeline import ExtractionPipeline, ExtractionRequest
from .platforms.bilibili import (
    OpenCliClient,
    OpenCliError,
    OpenCliSettings,
    bilibili_auth_ready,
    executable_status,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="video-subtitle",
        description="Composable video subtitle evidence tools",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--opencli",
        help="Path to opencli, opencli executable, or the built OpenCLI main.js",
    )
    parser.add_argument("--profile", help="OpenCLI Browser Bridge profile alias")
    parser.add_argument("--ytdlp", help="Absolute path to yt-dlp executable")
    parser.add_argument("--ffmpeg", help="Absolute path to ffmpeg executable")
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
    commands.add_parser("doctor", help="Check OpenCLI login transport and OCR backend")

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

    worker_parser = commands.add_parser("_worker", help=argparse.SUPPRESS)
    worker_parser.add_argument("--request-file", type=Path, required=True)
    return parser


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

    settings = OpenCliSettings.discover(
        opencli=args.opencli,
        profile=args.profile,
        ytdlp=args.ytdlp,
        ffmpeg=args.ffmpeg,
    )
    client = OpenCliClient(settings)

    if args.command == "doctor":
        return _doctor(
            client,
            Qwen3AsrOptions(
                python_executable=args.asr_python,
                ffmpeg_executable=args.ffmpeg,
                model=args.qwen_asr_model,
                aligner=args.qwen_aligner_model,
            ),
        ), 0

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


def _doctor(
    client: OpenCliClient,
    asr_options: Qwen3AsrOptions | None = None,
) -> dict[str, Any]:
    opencli_result: dict[str, Any] = {
        "command": client.settings.display_command,
        "profile": client.settings.profile,
        "ytdlp": client.settings.ytdlp_path,
        "ffmpeg": client.settings.ffmpeg_path,
        "available": client.is_command_available(),
        "platform_ready": False,
    }
    if opencli_result["available"]:
        try:
            opencli_result["auth"] = client.auth_status()
            opencli_result["platform_ready"] = bilibili_auth_ready(
                opencli_result["auth"]
            )
            if not opencli_result["platform_ready"]:
                opencli_result["error"] = {
                    "code": "BILIBILI_LOGIN_REQUIRED",
                    "message": "The selected OpenCLI profile is not logged in to Bilibili.",
                }
        except OpenCliError as error:
            opencli_result["error"] = error.as_dict()

    download_tools = {
        "yt_dlp": executable_status(client.settings.ytdlp_path, "yt-dlp"),
        "ffmpeg": executable_status(client.settings.ffmpeg_path, "ffmpeg"),
    }
    videocr_options = VideOcrOptions()
    ocr_result = ocr_doctor(videocr_options)
    asr_result = asr_doctor(asr_options or Qwen3AsrOptions())
    local_ocr_ready = bool(ocr_result["available"])
    url_ocr_ready = local_ocr_ready and all(
        bool(item["available"]) for item in download_tools.values()
    )
    return {
        "schema_version": "video-subtitle/doctor-v1",
        "ok": bool(opencli_result["platform_ready"]),
        "checked_at": utc_now(),
        "opencli": opencli_result,
        "download_tools": download_tools,
        "hard_ocr": ocr_result,
        "audio_asr": asr_result,
        "capabilities": {
            "platform_subtitle": bool(opencli_result["platform_ready"]),
            "hard_subtitle_ocr_local_video": local_ocr_ready,
            "hard_subtitle_ocr_from_url": url_ocr_ready,
            "audio_asr_local_video": bool(asr_result["available"]),
            "audio_asr_from_url": bool(asr_result["available"])
            and all(bool(item["available"]) for item in download_tools.values()),
        },
    }


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
        collect_all_sources=args.collect_all_sources,
        asr_backend=args.asr_backend,
        videocr=options,
        qwen3_asr=asr_options,
    )


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
