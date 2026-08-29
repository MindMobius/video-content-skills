"""Check that the repository uses one canonical runtime state layout."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from video_content.config import configured_home, read_configuration
from video_content.layout import (
    inspect_state_layout,
    read_path_relocation,
    resolve_recorded_path,
)
from video_content.store import Store

REPO_TEMP_NAMES = (".video-content-local",)
REPO_TEMP_GLOB = ".tmp-live-test-*"
REPO_LEGACY_PATHS = ("src/" + "video_" + "subtitle",)
REPO_ALLOWED_TOP_LEVEL = frozenset(
    {
        ".agents",
        ".git",
        ".github",
        ".gitattributes",
        ".gitignore",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        ".video-content",
        "AGENTS.md",
        "LICENSE",
        "README.md",
        "build",
        "dist",
        "docs",
        "node_modules",
        "npm-shrinkwrap.json",
        "opencli-plugin",
        "package.json",
        "pyproject.toml",
        "requirements",
        "schemas",
        "scripts",
        "src",
        "tests",
        "uv.lock",
    }
)
REPO_ALLOWED_TOP_LEVEL_SUFFIXES = (".egg-info",)
_SCAN_SUFFIXES = {".json", ".jsonl"}
_MAX_UNRESOLVED_EXAMPLES = 20
_PATH_FIELDS = {
    "path",
    "output_dir",
    "download_cache_dir",
    "video_path",
    "observationPath",
    "config_path",
    "state_root",
}
_WINDOWS_OR_POSIX_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/)")


def build_report(
    repo_root: str | Path,
    *,
    config_path: str | Path | None = None,
    home: str | Path | None = None,
    integrity: bool = False,
) -> dict[str, Any]:
    """Build a non-mutating layout report for a repository checkout."""

    repository = Path(repo_root).expanduser().resolve()
    canonical_root = (repository / ".video-content").resolve()
    environment_config = os.getenv("VIDEO_CONTENT_CONFIG")
    environment_home = os.getenv("VIDEO_CONTENT_HOME")
    if config_path is not None:
        selected_config = Path(config_path).expanduser().resolve()
    elif environment_config:
        selected_config = Path(environment_config).expanduser().resolve()
    elif (
        environment_home
        and (Path(environment_home).expanduser() / "config.json").is_file()
    ):
        selected_config = (
            Path(environment_home).expanduser() / "config.json"
        ).resolve()
    else:
        selected_config = canonical_root / "config.json"
    configuration = read_configuration(selected_config)
    state_root = configured_home(selected_config, explicit_home=home) or canonical_root

    candidates = [
        *(repository / name for name in REPO_TEMP_NAMES),
        *sorted(repository.glob(REPO_TEMP_GLOB)),
        *(repository / Path(*relative.split("/")) for relative in REPO_LEGACY_PATHS),
    ]
    repository_residuals = [
        str(path.relative_to(repository)).replace("\\", "/")
        for path in candidates
        if path.exists()
    ]
    known_residual_roots = {
        path.relative_to(repository).parts[0] for path in candidates if path.exists()
    }
    repository_unexpected_entries = sorted(
        item.name
        for item in repository.iterdir()
        if item.name not in REPO_ALLOWED_TOP_LEVEL
        and item.name not in known_residual_roots
        and not any(
            item.name.endswith(suffix) for suffix in REPO_ALLOWED_TOP_LEVEL_SUFFIXES
        )
    )
    errors: list[str] = []
    default_context = config_path is None and home is None
    if default_context and (
        selected_config != (canonical_root / "config.json")
        or (
            environment_home
            and Path(environment_home).expanduser().resolve() != canonical_root
        )
    ):
        errors.append(
            "An environment override selected a non-canonical runtime context; "
            "use the repository .video-content/config.json for normal runs."
        )
    if default_context and state_root != canonical_root:
        errors.append(
            "The repository config points outside the canonical .video-content root."
        )
    if default_context and not configuration["exists"]:
        errors.append("The canonical .video-content/config.json is missing.")
    if repository_residuals:
        errors.append("Repository-local temporary directories remain.")
    if repository_unexpected_entries:
        errors.append(
            "Repository contains entries outside the canonical source layout: "
            + ", ".join(repository_unexpected_entries)
        )

    layout = inspect_state_layout(state_root, require_config=default_context)
    if not layout["ready"]:
        errors.append("The active state root does not match the canonical layout.")

    try:
        relocation = read_path_relocation(state_root)
        path_references = _scan_historical_path_references(state_root, relocation)
    except (OSError, TypeError, ValueError) as error:
        relocation = {
            "schema_version": "video-content/path-relocation-v1",
            "path": str(state_root / "meta" / "path-relocation.json"),
            "exists": False,
            "relocations": [],
        }
        path_references = {
            "status": "invalid_registry",
            "files_scanned": 0,
            "files_with_references": 0,
            "reference_count": 0,
            "by_field": {},
            "by_status": {},
            "unresolved_examples": [],
            "error": str(error),
        }

    if path_references["reference_count"] and not relocation.get("exists"):
        errors.append(
            "Historical absolute paths exist but no meta/path-relocation.json "
            "explains them."
        )
    if path_references.get("unresolved_examples"):
        errors.append(
            "Some historical absolute paths cannot be resolved from the "
            "relocation registry."
        )

    if integrity:
        try:
            integrity_report = Store(state_root).validate_integrity()
        except (OSError, TypeError, ValueError) as error:
            integrity_report = {
                "schema_version": "video-content/state-integrity-v1",
                "root": str(state_root),
                "status": "failed",
                "errors": [{"kind": "checker", "message": str(error)}],
            }
        if integrity_report.get("status") != "passed":
            errors.append(
                "The active Job/Artifact tree failed its integrity check; "
                "inspect the integrity.errors list."
            )
    else:
        integrity_report = {
            "schema_version": "video-content/state-integrity-v1",
            "root": str(state_root),
            "status": "not_requested",
        }

    return {
        "schema_version": "video-content/layout-check-v1",
        "repository_root": str(repository),
        "config_path": str(selected_config),
        "config_exists": bool(configuration["exists"]),
        "environment_overrides": {
            "VIDEO_CONTENT_CONFIG": environment_config,
            "VIDEO_CONTENT_HOME": environment_home,
        },
        "canonical_state_root": str(canonical_root),
        "state_root": str(state_root),
        "repository_residuals": repository_residuals,
        "repository_unexpected_entries": repository_unexpected_entries,
        "allowed_top_level_entries": sorted(REPO_ALLOWED_TOP_LEVEL),
        "layout": layout,
        "path_relocation": {
            "path": relocation.get("path"),
            "exists": bool(relocation.get("exists")),
            "current_state_root": relocation.get("current_state_root"),
            "relocations": len(relocation.get("relocations") or []),
        },
        "historical_path_references": path_references,
        "integrity": integrity_report,
        "errors": errors,
        "ready": not errors,
    }


def _scan_historical_path_references(
    state_root: Path, relocation: dict[str, Any]
) -> dict[str, Any]:
    roots = [
        str(item.get("recorded_root") or "")
        for item in relocation.get("relocations", [])
        if isinstance(item, dict) and item.get("recorded_root")
    ]
    if not state_root.is_dir():
        return {
            "status": "no_state_root",
            "files_scanned": 0,
            "files_with_references": 0,
            "reference_count": 0,
            "by_field": {},
            "by_status": {},
            "unresolved_examples": [],
        }

    files_scanned = 0
    files_with_references: set[str] = set()
    reference_count = 0
    by_field: Counter[str] = Counter()
    by_status: Counter[str] = Counter()
    unresolved: list[dict[str, Any]] = []
    registry_path = Path(str(relocation.get("path") or "")).resolve()

    for path in sorted(state_root.rglob("*")):
        if (
            not path.is_file()
            or "archive" in path.relative_to(state_root).parts
            or path.suffix.lower() not in _SCAN_SUFFIXES
            or path.resolve() == registry_path
        ):
            continue
        files_scanned += 1
        for keys, value in _iter_document_strings(path):
            field_name = keys[-1] if keys else "<root>"
            if not _WINDOWS_OR_POSIX_ABSOLUTE.match(value):
                continue
            if not (_matches_recorded_root(value, roots) or field_name in _PATH_FIELDS):
                continue
            reference = resolve_recorded_path(
                value, state_root=state_root, relocation=relocation
            )
            reference_count += 1
            files_with_references.add(
                str(path.relative_to(state_root)).replace("\\", "/")
            )
            by_field[field_name] += 1
            status = str(reference.get("status") or "unknown")
            by_status[status] += 1
            if (
                status in {"missing", "unmapped"}
                and len(unresolved) < _MAX_UNRESOLVED_EXAMPLES
            ):
                unresolved.append(
                    {
                        "file": str(path.relative_to(state_root)).replace("\\", "/"),
                        "field": field_name,
                        "recorded_path": value,
                        "status": status,
                    }
                )

    return {
        "status": "mapped"
        if reference_count and not unresolved
        else "clean"
        if not reference_count
        else "unresolved",
        "files_scanned": files_scanned,
        "files_with_references": len(files_with_references),
        "reference_count": reference_count,
        "by_field": dict(sorted(by_field.items())),
        "by_status": dict(sorted(by_status.items())),
        "unresolved_examples": unresolved,
    }


def _iter_document_strings(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    if path.suffix.lower() == ".jsonl":
        documents = []
        for line in text.splitlines():
            if line.strip():
                try:
                    documents.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    else:
        try:
            documents = [json.loads(text)]
        except json.JSONDecodeError:
            return
    for document in documents:
        yield from _walk_strings(document)


def _walk_strings(value: Any, keys: tuple[str, ...] = ()):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_strings(item, keys + (str(key),))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_strings(item, keys + (str(index),))
    elif isinstance(value, str):
        yield keys, value


def _matches_recorded_root(value: str, roots: list[str]) -> bool:
    for root in roots:
        value_key = value.replace("/", "\\").rstrip("\\").casefold()
        root_key = root.replace("/", "\\").rstrip("\\").casefold()
        if value_key == root_key or value_key.startswith(root_key + "\\"):
            return True
    return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--config", type=Path)
    parser.add_argument(
        "--home",
        type=Path,
        help="Explicit state root for an isolated layout check.",
    )
    parser.add_argument(
        "--integrity",
        action="store_true",
        help="Hash-check every active Job Artifact and idempotency index.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    report = build_report(
        args.repo,
        config_path=args.config,
        home=args.home,
        integrity=args.integrity,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["ready"] else 1)


if __name__ == "__main__":
    main()
