from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .util import utc_now, write_json_atomic

STATE_LAYOUT_SCHEMA_VERSION = "video-content/state-layout-v1"
STATE_CONFIG_FILENAME = "config.json"
PATH_RELOCATION_SCHEMA_VERSION = "video-content/path-relocation-v1"
PATH_RELOCATION_FILENAME = "path-relocation.json"

# These are the only directories allowed directly below the active state root.
STATE_TOP_LEVEL_DIRECTORIES = (
    "profiles",
    "jobs",
    "cache",
    "indexes",
    "locks",
    "meta",
    "runs",
    "archive",
)

# The media cache is the only required nested runtime directory. Other nested
# paths are created by the Job and renderer contracts as needed.
STATE_REQUIRED_NESTED_DIRECTORIES = ("cache/media",)
_WINDOWS_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")


def state_paths(root: str | Path) -> dict[str, Path]:
    """Return the canonical paths belonging to one active state root."""

    resolved = Path(root).expanduser().resolve()
    return {
        "root": resolved,
        "config": resolved / STATE_CONFIG_FILENAME,
        **{name: resolved / name for name in STATE_TOP_LEVEL_DIRECTORIES},
    }


def ensure_state_layout(root: str | Path) -> dict[str, Path]:
    """Create the fixed runtime directories without creating ad-hoc siblings."""

    paths = state_paths(root)
    for name in STATE_TOP_LEVEL_DIRECTORIES:
        paths[name].mkdir(parents=True, exist_ok=True)
    (paths["cache"] / "media").mkdir(parents=True, exist_ok=True)
    return paths


def inspect_state_layout(
    root: str | Path,
    *,
    require_config: bool = False,
) -> dict[str, Any]:
    """Describe whether a state root still matches the canonical layout."""

    paths = state_paths(root)
    state_root = paths["root"]
    expected_entries = {STATE_CONFIG_FILENAME, *STATE_TOP_LEVEL_DIRECTORIES}
    if not state_root.is_dir():
        existing_entries: list[str] = []
    else:
        existing_entries = sorted(item.name for item in state_root.iterdir())

    missing_directories = [
        name for name in STATE_TOP_LEVEL_DIRECTORIES if not paths[name].is_dir()
    ]
    missing_nested_directories = [
        relative
        for relative in STATE_REQUIRED_NESTED_DIRECTORIES
        if not (state_root / Path(*relative.split("/"))).is_dir()
    ]
    unexpected_entries = sorted(
        name for name in existing_entries if name not in expected_entries
    )
    config_present = paths["config"].is_file()
    ready = (
        state_root.is_dir()
        and not missing_directories
        and not missing_nested_directories
        and not unexpected_entries
        and (config_present or not require_config)
    )
    return {
        "schema_version": STATE_LAYOUT_SCHEMA_VERSION,
        "root": str(state_root),
        "expected_config": STATE_CONFIG_FILENAME,
        "config_present": config_present,
        "expected_top_level_directories": list(STATE_TOP_LEVEL_DIRECTORIES),
        "required_nested_directories": list(STATE_REQUIRED_NESTED_DIRECTORIES),
        "existing_entries": existing_entries,
        "missing_directories": missing_directories,
        "missing_nested_directories": missing_nested_directories,
        "unexpected_entries": unexpected_entries,
        "ready": ready,
    }


def path_relocation_path(root: str | Path) -> Path:
    """Return the metadata file that explains historical absolute paths."""

    return state_paths(root)["meta"] / PATH_RELOCATION_FILENAME


def read_path_relocation(root: str | Path) -> dict[str, Any]:
    """Read the optional historical-path relocation registry."""

    path = path_relocation_path(root)
    if not path.is_file():
        return {
            "schema_version": PATH_RELOCATION_SCHEMA_VERSION,
            "path": str(path),
            "exists": False,
            "current_state_root": str(state_paths(root)["root"]),
            "relocations": [],
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"Path relocation registry must be an object: {path}")
    if payload.get("schema_version") not in {
        None,
        PATH_RELOCATION_SCHEMA_VERSION,
    }:
        raise ValueError(
            f"Unsupported path relocation schema: {payload.get('schema_version')!r}"
        )
    relocations = payload.get("relocations", [])
    if not isinstance(relocations, list):
        raise TypeError(f"Path relocation entries must be a list: {path}")
    return {
        **payload,
        "schema_version": PATH_RELOCATION_SCHEMA_VERSION,
        "path": str(path),
        "exists": True,
        "relocations": relocations,
    }


def write_path_relocation(
    root: str | Path,
    *,
    recorded_root: str | Path,
    current_root: str | Path | None = None,
    archive_root: str | Path | None = None,
    reason: str = "state-root-relocation",
) -> dict[str, Any]:
    """Register a non-destructive mapping for paths in immutable history."""

    paths = ensure_state_layout(root)
    current = Path(current_root or root).expanduser().resolve()
    recorded = str(Path(recorded_root).expanduser().resolve(strict=False))
    archive = (
        str(Path(archive_root).expanduser().resolve(strict=False))
        if archive_root is not None
        else None
    )
    existing = read_path_relocation(root)
    entries = [
        item
        for item in existing.get("relocations", [])
        if isinstance(item, dict) and str(item.get("recorded_root") or "") != recorded
    ]
    entries.append(
        {
            "recorded_root": recorded,
            "current_root": str(current),
            "archive_root": archive,
            "reason": reason,
            "registered_at": utc_now(),
        }
    )
    document = {
        "schema_version": PATH_RELOCATION_SCHEMA_VERSION,
        "updated_at": utc_now(),
        "current_state_root": str(current),
        "resolution_order": ["current_root", "archive_root"],
        "immutable_history": True,
        "relocations": entries,
    }
    write_json_atomic(paths["meta"] / PATH_RELOCATION_FILENAME, document)
    return {
        **document,
        "path": str(paths["meta"] / PATH_RELOCATION_FILENAME),
        "exists": True,
    }


def resolve_recorded_path(
    value: str | Path,
    *,
    state_root: str | Path,
    relocation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve a recorded path without rewriting the original evidence.

    A path is first checked as-is. If it belongs to a registered historical
    root, the same relative path is checked below the active root and then the
    retained archive. The returned status is for display/diagnostics only; it
    never changes an Artifact or its recorded bytes.
    """

    recorded = str(value)
    direct = Path(recorded).expanduser()
    if direct.exists():
        return {
            "recorded_path": recorded,
            "resolved_path": str(direct.resolve()),
            "status": "direct",
        }

    registry = relocation or read_path_relocation(state_root)
    for item in registry.get("relocations", []):
        if not isinstance(item, dict):
            continue
        recorded_root = str(item.get("recorded_root") or "").strip()
        relative = _relative_recorded_path(recorded, recorded_root)
        if relative is None:
            continue
        for field, status in (
            ("current_root", "relocated"),
            ("archive_root", "archived"),
        ):
            base_value = item.get(field)
            if not base_value:
                continue
            base = Path(str(base_value)).expanduser().resolve(strict=False)
            candidate = (base / relative).resolve(strict=False)
            if base != candidate and base not in candidate.parents:
                continue
            if candidate.exists():
                return {
                    "recorded_path": recorded,
                    "relative_path": relative.as_posix(),
                    "resolved_path": str(candidate),
                    "status": status,
                    "relocation_root": recorded_root,
                }
        return {
            "recorded_path": recorded,
            "relative_path": relative.as_posix(),
            "resolved_path": None,
            "status": "missing",
            "relocation_root": recorded_root,
        }
    return {
        "recorded_path": recorded,
        "resolved_path": None,
        "status": "unmapped",
    }


def _relative_recorded_path(value: str, root: str) -> Path | None:
    if not value or not root:
        return None
    if _WINDOWS_ABSOLUTE.match(value) or _WINDOWS_ABSOLUTE.match(root):
        normalized_value = value.replace("/", "\\").rstrip("\\").casefold()
        normalized_root = root.replace("/", "\\").rstrip("\\").casefold()
        if normalized_value == normalized_root:
            return Path()
        prefix = normalized_root + "\\"
        if not normalized_value.startswith(prefix):
            return None
        relative = (
            value.replace("/", "\\")
            .rstrip("\\")[len(root.rstrip("/" + "\\")) :]
            .lstrip("\\")
        )
        parts = [part for part in relative.split("\\") if part]
        if any(part in {".", ".."} for part in parts):
            return None
        return Path(*parts)
    try:
        return (
            Path(value)
            .expanduser()
            .resolve(strict=False)
            .relative_to(Path(root).expanduser().resolve(strict=False))
        )
    except ValueError:
        return None
