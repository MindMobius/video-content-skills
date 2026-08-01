from __future__ import annotations

from pathlib import Path
from typing import Any

from .backends.asr import Qwen3AsrOptions, asr_doctor
from .backends.ocr import VideOcrOptions, ocr_doctor
from .core.util import utc_now
from .environment import build_setup_report
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
    opencli: dict[str, Any] = {
        "command": client.settings.display_command,
        "profile": client.settings.profile,
        "ytdlp": client.settings.ytdlp_path,
        "ffmpeg": client.settings.ffmpeg_path,
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
        "yt_dlp": executable_status(client.settings.ytdlp_path, "yt-dlp"),
        "ffmpeg": executable_status(client.settings.ffmpeg_path, "ffmpeg"),
    }
    ocr = ocr_doctor(VideOcrOptions())
    asr = asr_doctor(asr_options or Qwen3AsrOptions(), deep=deep)
    local_ocr_ready = bool(ocr["available"])
    url_ocr_ready = local_ocr_ready and all(
        bool(item["available"]) for item in download_tools.values()
    )
    result: dict[str, Any] = {
        "schema_version": "video-subtitle/doctor-v2",
        "checked_at": utc_now(),
        "deep": deep,
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
    setup = build_setup_report(
        result,
        capabilities=capabilities,
        config_path=config_path,
    )
    result["ok"] = setup["ready"]
    result["setup"] = setup
    return result
