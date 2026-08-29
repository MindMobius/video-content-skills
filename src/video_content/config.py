from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .util import write_json_atomic

CONFIG_SCHEMA_VERSION = "video-content/config-v1"
PROJECT_STATE_DIRNAME = ".video-content"
CONFIG_FILENAME = "config.json"

CONFIG_ENVIRONMENT = {
    "opencli": "VIDEO_CONTENT_OPENCLI",
    "opencli_profile": "VIDEO_CONTENT_OPENCLI_PROFILE",
    "ytdlp": "VIDEO_CONTENT_YTDLP",
    "ffmpeg": "VIDEO_CONTENT_FFMPEG",
    "videocr": "VIDEO_CONTENT_VIDEOCR",
    "asr_python": "VIDEO_CONTENT_ASR_PYTHON",
    "qwen_asr_model": "VIDEO_CONTENT_QWEN_ASR_MODEL",
    "qwen_aligner_model": "VIDEO_CONTENT_QWEN_ALIGNER_MODEL",
    "home": "VIDEO_CONTENT_HOME",
    "media_execution": "VIDEO_CONTENT_MEDIA_EXECUTION",
    "opencli_browser_timeout": "VIDEO_CONTENT_OPENCLI_BROWSER_TIMEOUT",
    "download_retries": "VIDEO_CONTENT_DOWNLOAD_RETRIES",
    "download_retry_backoff": "VIDEO_CONTENT_DOWNLOAD_RETRY_BACKOFF",
    "download_cache": "VIDEO_CONTENT_DOWNLOAD_CACHE",
}


def resolve_config_path(value: str | Path | None = None) -> Path:
    """Resolve one deterministic configuration file for this invocation.

    Explicit paths and environment overrides remain authoritative. When they
    are absent, a project-local .video-content/config.json is preferred over
    the operating-system fallback so repository commands and direct API calls
    use the same runtime configuration.
    """

    selected = value or os.getenv("VIDEO_CONTENT_CONFIG")
    if selected:
        return Path(selected).expanduser().resolve()

    configured_home = os.getenv("VIDEO_CONTENT_HOME")
    if configured_home:
        home_config = Path(configured_home).expanduser() / CONFIG_FILENAME
        if home_config.is_file():
            return home_config.resolve()

    project_root = find_project_root()
    if project_root is not None:
        project_config = project_root / PROJECT_STATE_DIRNAME / CONFIG_FILENAME
        if project_config.is_file():
            return project_config.resolve()

    return _default_global_config_path()


def find_project_root(start: str | Path | None = None) -> Path | None:
    """Find the repository root without depending on the current shell path."""

    candidate = Path(start or Path.cwd()).expanduser().resolve()
    if candidate.is_file():
        candidate = candidate.parent
    for directory in (candidate, *candidate.parents):
        if (directory / "pyproject.toml").is_file() and (
            directory / "src" / "video_content"
        ).is_dir():
            return directory
    return None


def default_state_root(start: str | Path | None = None) -> Path:
    """Return the repository-local or user-level state root.

    A package invoked outside a discoverable checkout must not create a new
    ``.video-content`` directory in whatever directory happened to be the
    caller's current working directory. Use the same user-level location as
    the configuration fallback instead.
    """

    project_root = find_project_root(start)
    if project_root is not None:
        return (project_root / PROJECT_STATE_DIRNAME).resolve()
    return _default_global_config_path().parent.resolve()


def configured_home(
    value: str | Path | None = None,
    *,
    explicit_home: str | Path | None = None,
) -> Path | None:
    """Return the active state root selected by one config context."""

    if explicit_home:
        return Path(explicit_home).expanduser().resolve()
    environment_home = os.getenv("VIDEO_CONTENT_HOME")
    if environment_home:
        return Path(environment_home).expanduser().resolve()
    configuration = read_configuration(value)
    configured = configuration["values"].get("home")
    if configured:
        selected = Path(configured).expanduser()
        if not selected.is_absolute():
            selected = Path(configuration["path"]).parent / selected
        return selected.resolve()

    # A config file is itself a state-root anchor when it lives at the
    # canonical ``<state-root>/config.json`` location. This keeps an explicit
    # config context from silently falling back to the repository that happens
    # to be the current working directory.
    config_path = Path(configuration["path"]).expanduser()
    explicitly_selected = value is not None or bool(os.getenv("VIDEO_CONTENT_CONFIG"))
    if (
        configuration["exists"] or explicitly_selected
    ) and config_path.name == CONFIG_FILENAME:
        return config_path.parent.resolve()
    return None


def _default_global_config_path() -> Path:
    if os.name == "nt" and os.getenv("APPDATA"):
        return (
            Path(os.environ["APPDATA"]) / "video-content" / CONFIG_FILENAME
        ).resolve()
    xdg_home = os.getenv("XDG_CONFIG_HOME")
    if xdg_home:
        return (Path(xdg_home) / "video-content" / CONFIG_FILENAME).resolve()
    return (Path.home() / ".config" / "video-content" / CONFIG_FILENAME).resolve()


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
        raise ValueError(f"Video content config is not valid JSON: {path}") from error
    if not isinstance(payload, dict):
        raise TypeError(f"Video content config must be a JSON object: {path}")
    if payload.get("schema_version") not in {None, CONFIG_SCHEMA_VERSION}:
        raise ValueError(
            f"Unsupported video content config schema: {payload.get('schema_version')!r}"
        )
    raw_values = payload.get("values", payload)
    if not isinstance(raw_values, dict):
        raise TypeError(f"Video content config values must be an object: {path}")
    values: dict[str, str] = {}
    for field, item in raw_values.items():
        if (
            field == "schema_version"
            or field not in CONFIG_ENVIRONMENT
            or item in {None, ""}
        ):
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
        else:
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
