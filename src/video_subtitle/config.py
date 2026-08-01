from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .core.util import write_json_atomic

CONFIG_SCHEMA_VERSION = "video-subtitle/config-v1"

CONFIG_ENVIRONMENT = {
    "opencli": "VIDEO_SUBTITLE_OPENCLI",
    "opencli_profile": "VIDEO_SUBTITLE_OPENCLI_PROFILE",
    "ytdlp": "VIDEO_SUBTITLE_YTDLP",
    "ffmpeg": "VIDEO_SUBTITLE_FFMPEG",
    "videocr": "VIDEO_SUBTITLE_VIDEOCR",
    "asr_python": "VIDEO_SUBTITLE_ASR_PYTHON",
    "qwen_asr_model": "VIDEO_SUBTITLE_QWEN_ASR_MODEL",
    "qwen_aligner_model": "VIDEO_SUBTITLE_QWEN_ALIGNER_MODEL",
    "home": "VIDEO_SUBTITLE_HOME",
    "media_execution": "VIDEO_SUBTITLE_MEDIA_EXECUTION",
}


def resolve_config_path(value: str | Path | None = None) -> Path:
    selected = value or os.getenv("VIDEO_SUBTITLE_CONFIG")
    if selected:
        return Path(selected).expanduser().resolve()
    if os.name == "nt" and os.getenv("APPDATA"):
        return (
            Path(os.environ["APPDATA"]) / "video-subtitle" / "config.json"
        ).resolve()
    xdg_home = os.getenv("XDG_CONFIG_HOME")
    if xdg_home:
        return (Path(xdg_home) / "video-subtitle" / "config.json").resolve()
    return (Path.home() / ".config" / "video-subtitle" / "config.json").resolve()


def read_configuration(value: str | Path | None = None) -> dict[str, Any]:
    path = resolve_config_path(value)
    if not path.is_file():
        return {
            "schema_version": CONFIG_SCHEMA_VERSION,
            "path": str(path),
            "exists": False,
            "values": {},
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Video subtitle config is not valid JSON: {path}") from error
    if not isinstance(payload, dict):
        raise TypeError(f"Video subtitle config must be a JSON object: {path}")
    schema_version = payload.get("schema_version")
    if schema_version not in {None, CONFIG_SCHEMA_VERSION}:
        raise ValueError(
            f"Unsupported video subtitle config schema: {schema_version!r}"
        )
    raw_values = payload.get("values", payload)
    if not isinstance(raw_values, dict):
        raise TypeError(f"Video subtitle config values must be an object: {path}")
    values: dict[str, str] = {}
    for field, item in raw_values.items():
        if field == "schema_version":
            continue
        if field not in CONFIG_ENVIRONMENT:
            continue
        if item is None or item == "":
            continue
        if not isinstance(item, str):
            raise TypeError(f"Config field {field!r} must be a string")
        values[field] = item
    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "path": str(path),
        "exists": True,
        "values": values,
    }


def apply_configuration(value: str | Path | None = None) -> dict[str, Any]:
    document = read_configuration(value)
    applied: list[str] = []
    shadowed: list[str] = []
    for field, item in document["values"].items():
        environment = CONFIG_ENVIRONMENT[field]
        if os.getenv(environment):
            shadowed.append(field)
            continue
        os.environ[environment] = item
        applied.append(field)
    document["applied_fields"] = applied
    document["shadowed_by_environment"] = shadowed
    return document


def update_configuration(
    values: dict[str, str | None],
    *,
    clear: list[str] | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    config_path = resolve_config_path(path)
    current = read_configuration(config_path)["values"]
    for field in clear or []:
        if field not in CONFIG_ENVIRONMENT:
            raise ValueError(f"Unknown configuration field: {field}")
        current.pop(field, None)
    for field, item in values.items():
        if field not in CONFIG_ENVIRONMENT:
            raise ValueError(f"Unknown configuration field: {field}")
        if item is None:
            continue
        selected = str(item).strip()
        if selected:
            current[field] = selected
        else:
            current.pop(field, None)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(
        config_path,
        {
            "schema_version": CONFIG_SCHEMA_VERSION,
            "values": dict(sorted(current.items())),
        },
    )
    return read_configuration(config_path)
