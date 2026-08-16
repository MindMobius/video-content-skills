from __future__ import annotations

from pathlib import Path
from typing import Any

from .backends.asr import Qwen3AsrOptions, asr_doctor
from .backends.ocr import VideOcrOptions, ocr_doctor
from .core.util import utc_now
from .environment import build_setup_report, normalize_capabilities
from .platforms.bilibili import (
    OpenCliClient,
    OpenCliError,
    bilibili_auth_ready,
    executable_status,
)


def doctor(
    client: OpenCliClient,
    asr_options: Qwen3AsrOptions | None = None,
    *,
    capabilities: list[str] | None = None,
    deep: bool = True,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    selected = normalize_capabilities(capabilities)
    watch_later_required = "watch_later_monitor" in selected
    platform_required = bool(
        {
            "watch_later_monitor",
            "platform_subtitle",
            "video_download",
            "hard_ocr_url",
            "audio_asr_url",
        }
        & set(selected)
    )
    download_required = bool(
        {"video_download", "hard_ocr_url", "audio_asr_url"} & set(selected)
    )
    ocr_required = bool({"hard_ocr_local", "hard_ocr_url"} & set(selected))
    asr_required = bool({"audio_asr_local", "audio_asr_url"} & set(selected))

    opencli: dict[str, Any] = {
        "command": client.settings.display_command,
        "profile": client.settings.profile,
        "ytdlp": client.settings.ytdlp_path,
        "ffmpeg": client.settings.ffmpeg_path,
        "checked": platform_required,
        "available": False,
        "platform_ready": False,
    }
    if platform_required:
        opencli["available"] = client.is_command_available()
    watch_later_adapter = {
        "checked": watch_later_required,
        "available": False,
    }
    if watch_later_required and opencli["available"]:
        watch_later_adapter["available"] = client.watch_later_adapter_available()
    auth_probe_ready = not watch_later_required or watch_later_adapter["available"]
    if platform_required and opencli["available"] and auth_probe_ready:
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

    download_tools: dict[str, Any] = {}
    if download_required:
        download_tools["yt_dlp"] = executable_status(
            client.settings.ytdlp_path,
            "yt-dlp",
        )
    if download_required or asr_required:
        download_tools["ffmpeg"] = executable_status(
            client.settings.ffmpeg_path,
            "ffmpeg",
        )
    ocr = (
        {**ocr_doctor(VideOcrOptions()), "checked": True}
        if ocr_required
        else {
            "backend": "videocr",
            "available": False,
            "checked": False,
            "skipped": "not_requested",
        }
    )
    asr = (
        {
            **asr_doctor(asr_options or Qwen3AsrOptions(), deep=deep),
            "checked": True,
        }
        if asr_required
        else {
            "backend": "qwen3",
            "available": False,
            "checked": False,
            "skipped": "not_requested",
        }
    )
    local_ocr_ready = bool(ocr["available"])
    download_ready = (
        bool(opencli["platform_ready"])
        and bool(download_tools)
        and all(bool(item["available"]) for item in download_tools.values())
    )
    url_ocr_ready = local_ocr_ready and download_ready
    local_asr_ready = bool(asr["available"])
    result: dict[str, Any] = {
        "schema_version": "video-subtitle/doctor-v2",
        "checked_at": utc_now(),
        "deep": deep,
        "requested_capabilities": selected,
        "probes": {
            "platform": platform_required,
            "watch_later": watch_later_required,
            "download": download_required,
            "hard_ocr": ocr_required,
            "audio_asr": asr_required,
        },
        "opencli": opencli,
        "watch_later_adapter": watch_later_adapter,
        "download_tools": download_tools,
        "hard_ocr": ocr,
        "audio_asr": asr,
        "capabilities": {
            "watch_later_monitor": bool(
                watch_later_adapter["available"] and opencli["platform_ready"]
            ),
            "platform_subtitle": bool(opencli["platform_ready"]),
            "video_download": download_ready,
            "hard_ocr_local": local_ocr_ready,
            "hard_ocr_url": url_ocr_ready,
            "audio_asr_local": local_asr_ready,
            "audio_asr_url": local_asr_ready and download_ready,
        },
    }
    setup = build_setup_report(
        result,
        capabilities=selected,
        config_path=config_path,
    )
    result["ok"] = setup["ready"]
    result["setup"] = setup
    return result
