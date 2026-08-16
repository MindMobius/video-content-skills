"""No-secret export, verification, and import for content projects."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from video_subtitle import __version__
from video_subtitle.wechat_adapter import (
    WECHAT_BROWSER_ADAPTER_ID,
    WECHAT_BROWSER_ADAPTER_VERSION,
)

from .content import get_content_project
from .util import read_json, utc_now

BUNDLE_VERSION = "video-content/portable-bundle-v1"
TEXT_SUFFIXES = frozenset(
    {
        ".css",
        ".csv",
        ".html",
        ".json",
        ".md",
        ".srt",
        ".svg",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }
)
SECRET_PATTERNS = {
    "browser_cookie": re.compile(r"(?i)\b(?:SESSDATA|bili_jct|DedeUserID)\s*[:=]"),
    "url_token": re.compile(
        r"(?i)(?:^|[?&])(token|access_token|refresh_token)=[^&\s]+"
    ),
    "password": re.compile(r"(?i)\bpassword\s*[:=]\s*[^\s,}\]]+"),
    "persisted_base64_image": re.compile(r"(?i)data:image/[^;]+;base64,"),
    "cookie_header": re.compile(r"(?i)\bcookie\s*:\s*[^\r\n]+"),
}
MAX_TEXT_SCAN_BYTES = 20 * 1024 * 1024
MAX_BUNDLE_MANIFEST_BYTES = 5 * 1024 * 1024
MAX_BUNDLE_BYTES = 20 * 1024 * 1024 * 1024
MAX_BUNDLE_FILES = 20_000


def export_content_bundle(
    project_path: Path,
    output_path: Path,
    *,
    include: list[Path] | None = None,
    agent_name: str = "not_recorded",
    model_name: str = "not_recorded",
) -> dict[str, Any]:
    """Create a verified ZIP while preserving the project's relative references."""
    project_path = project_path.expanduser().resolve()
    output_path = output_path.expanduser().resolve()
    if output_path.exists():
        raise FileExistsError(f"Portable bundle already exists: {output_path}")
    project = get_content_project(project_path)
    project_root = project_path.parent
    manifest_path = (project_root / project["source"]["manifest_path"]).resolve()
    workspace_root = manifest_path.parent
    _require_within(workspace_root, project_root, "content project")

    selected: dict[Path, str] = {}
    _add_tree(selected, project_root, "project")
    _add_file(selected, manifest_path, "manifest")
    for evidence in project["source"]["evidence"]:
        _add_file(selected, (project_root / evidence["path"]).resolve(), "evidence")

    excluded: list[dict[str, str]] = []
    manifest = read_json(manifest_path)
    for artifact in manifest.get("artifacts", []):
        raw_path = artifact.get("path")
        if not raw_path:
            continue
        artifact_path = Path(str(raw_path)).expanduser()
        if not artifact_path.is_absolute():
            artifact_path = manifest_path.parent / artifact_path
        artifact_path = artifact_path.resolve()
        if artifact.get("kind") == "source_video":
            excluded.append(
                {
                    "kind": "source_video",
                    "name": artifact_path.name,
                    "reason": "Large source media is excluded by default; subtitle evidence remains included.",
                }
            )
            continue
        if artifact_path.is_file():
            _add_file(selected, artifact_path, "evidence")

    for requested in include or []:
        candidate = requested.expanduser().resolve()
        _require_within(workspace_root, candidate, "included path")
        if candidate.is_dir():
            _add_tree(selected, candidate, "extra")
        elif candidate.is_file():
            _add_file(selected, candidate, "extra")
        else:
            raise FileNotFoundError(f"Included path does not exist: {candidate}")

    file_records: list[dict[str, Any]] = []
    for path, role in sorted(selected.items(), key=lambda item: str(item[0]).lower()):
        _require_within(workspace_root, path, "bundle file")
        relative = path.relative_to(workspace_root).as_posix()
        file_records.append(
            {
                "path": f"workspace/{relative}",
                "role": role,
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    secret_scan = _scan_files(selected)
    if not secret_scan["passed"]:
        first = secret_scan["findings"][0]
        raise ValueError(
            f"Portable bundle secret scan failed: {first['pattern']} in {first['path']}"
        )
    safe_agent_name = _safe_provenance_value(agent_name, "agent name")
    safe_model_name = _safe_provenance_value(model_name, "model name")
    bundle_id = _bundle_id(project["project_id"], file_records)
    bundle_manifest = {
        "schema_version": BUNDLE_VERSION,
        "bundle_id": bundle_id,
        "created_at": utc_now(),
        "project_id": project["project_id"],
        "project_entry": f"workspace/{project_path.relative_to(workspace_root).as_posix()}",
        "files": file_records,
        "excluded": excluded,
        "secret_scan": {
            "passed": True,
            "files_scanned": secret_scan["files_scanned"] + 1,
            "patterns": sorted(SECRET_PATTERNS),
        },
        "provenance": _provenance(
            project_root,
            agent_name=safe_agent_name,
            model_name=safe_model_name,
        ),
    }
    bundle_payload = (
        json.dumps(bundle_manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    if secret := _secret_in_text(bundle_payload.decode("utf-8")):
        raise ValueError(f"Portable bundle manifest secret scan failed: {secret}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as archive:
            _write_zip_bytes(
                archive,
                "bundle.json",
                bundle_payload,
            )
            for record in file_records:
                source = workspace_root / PurePosixPath(record["path"]).relative_to(
                    "workspace"
                )
                _write_zip_file(archive, record["path"], source)
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)
    verification = verify_content_bundle(output_path)
    if not verification["valid"]:
        output_path.unlink(missing_ok=True)
        raise ValueError("Created portable bundle failed its own verification")
    return {
        "schema_version": "video-content/portable-bundle-export-v1",
        "ok": True,
        "bundle": str(output_path),
        "bundle_id": bundle_id,
        "project_id": project["project_id"],
        "file_count": len(file_records),
        "bytes": output_path.stat().st_size,
        "excluded": excluded,
        "verification": verification,
    }


def verify_content_bundle(bundle_path: Path) -> dict[str, Any]:
    bundle_path = bundle_path.expanduser().resolve()
    errors: list[dict[str, str]] = []
    if not bundle_path.is_file():
        raise FileNotFoundError(f"Portable bundle does not exist: {bundle_path}")
    try:
        with zipfile.ZipFile(bundle_path, "r") as archive:
            members = archive.infolist()
            member_names = [member.filename for member in members]
            if len(member_names) != len(set(member_names)):
                errors.append(
                    _finding(
                        "duplicate_member", "Duplicate archive members are forbidden"
                    )
                )
            if len(members) > MAX_BUNDLE_FILES:
                errors.append(
                    _finding("too_many_files", "Bundle file count exceeds limit")
                )
            total = sum(member.file_size for member in members)
            if total > MAX_BUNDLE_BYTES:
                errors.append(
                    _finding("bundle_too_large", "Expanded bundle exceeds limit")
                )
            for member in members:
                if problem := _unsafe_member(member):
                    errors.append(_finding("unsafe_member", problem, member.filename))
            if "bundle.json" not in archive.namelist():
                errors.append(_finding("manifest_missing", "bundle.json is required"))
                return _verification_result(bundle_path, None, errors)
            manifest_payload = archive.read("bundle.json")
            if len(manifest_payload) > MAX_BUNDLE_MANIFEST_BYTES:
                errors.append(
                    _finding("manifest_too_large", "bundle.json exceeds size limit")
                )
                return _verification_result(bundle_path, None, errors)
            manifest_text = manifest_payload.decode("utf-8")
            if secret := _secret_in_text(manifest_text):
                errors.append(_finding("secret_detected", secret, "bundle.json"))
            bundle = json.loads(manifest_text)
            errors.extend(_validate_bundle_manifest(bundle))
            if errors:
                return _verification_result(bundle_path, bundle, errors)
            expected = {item["path"]: item for item in bundle.get("files", [])}
            actual = {name for name in archive.namelist() if name != "bundle.json"}
            if actual != set(expected):
                errors.append(
                    _finding("file_set", "Archive files do not match bundle.json")
                )
            for path, record in expected.items():
                if path not in actual:
                    continue
                with archive.open(path, "r") as stream:
                    digest, size, secret = _hash_and_scan_stream(path, stream)
                if digest != record.get("sha256") or size != record.get("bytes"):
                    errors.append(
                        _finding("hash_mismatch", "File size or SHA-256 differs", path)
                    )
                if secret:
                    errors.append(_finding("secret_detected", secret, path))
            project_entry = str(bundle.get("project_entry") or "")
            if project_entry not in expected:
                errors.append(_finding("project_entry", "Project entry is not bundled"))
            elif project_entry in actual:
                try:
                    project_document = json.loads(
                        archive.read(project_entry).decode("utf-8")
                    )
                    if project_document.get("project_id") != bundle["project_id"]:
                        errors.append(
                            _finding(
                                "project_id",
                                "Bundled project ID differs from bundle.json",
                                project_entry,
                            )
                        )
                except (AttributeError, UnicodeError, json.JSONDecodeError):
                    errors.append(
                        _finding(
                            "project_entry",
                            "Bundled project entry is not a readable project document",
                            project_entry,
                        )
                    )
            if bundle["bundle_id"] != _bundle_id(bundle["project_id"], bundle["files"]):
                errors.append(
                    _finding("bundle_id", "Bundle identity does not match its files")
                )
    except (
        AttributeError,
        KeyError,
        OSError,
        TypeError,
        UnicodeError,
        json.JSONDecodeError,
        zipfile.BadZipFile,
    ) as error:
        errors.append(_finding("invalid_archive", str(error)))
        bundle = None
    return _verification_result(bundle_path, bundle, errors)


def import_content_bundle(bundle_path: Path, destination: Path) -> dict[str, Any]:
    bundle_path = bundle_path.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if destination.exists():
        raise FileExistsError("Import destination must not already exist")
    verification = verify_content_bundle(bundle_path)
    if not verification["valid"]:
        raise ValueError(
            "Portable bundle verification failed; import was not attempted"
        )
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=parent))
    try:
        with zipfile.ZipFile(bundle_path, "r") as archive:
            bundle = json.loads(archive.read("bundle.json").decode("utf-8"))
            for record in bundle["files"]:
                relative = _safe_relative(record["path"])
                target = temporary / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with (
                    archive.open(record["path"], "r") as source,
                    target.open("wb") as output,
                ):
                    shutil.copyfileobj(source, output, length=1024 * 1024)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    project_path = destination / _safe_relative(verification["project_entry"])
    project = get_content_project(project_path)
    return {
        "schema_version": "video-content/portable-bundle-import-v1",
        "ok": True,
        "bundle_id": verification["bundle_id"],
        "destination": str(destination),
        "project_path": str(project_path),
        "project_id": project["project_id"],
        "integrity": project["integrity"],
    }


def _provenance(
    project_root: Path,
    *,
    agent_name: str,
    model_name: str,
) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[3]
    commit = _command_line(["git", "rev-parse", "HEAD"], cwd=repo_root)
    dirty = bool(_command_line(["git", "status", "--porcelain"], cwd=repo_root))
    skills = []
    for skill_path in sorted((repo_root / ".agents" / "skills").glob("*/SKILL.md")):
        skills.append(
            {"name": skill_path.parent.name, "sha256": _sha256_file(skill_path)}
        )
    renderers = []
    for render_manifest in sorted(project_root.rglob("render-manifest.json")):
        try:
            document = read_json(render_manifest)
        except (OSError, json.JSONDecodeError):
            continue
        renderer = document.get("renderer")
        if isinstance(renderer, dict):
            renderers.append(
                {
                    "id": renderer.get("id"),
                    "version": renderer.get("version"),
                    "package_version": renderer.get("package_version"),
                    "theme": renderer.get("theme"),
                }
            )
    return {
        "repository": {
            "commit": commit or "not_available",
            "dirty": dirty,
            "package_version": __version__,
        },
        "skills": skills,
        "agent": {
            "name": agent_name.strip() or "not_recorded",
            "model": model_name.strip() or "not_recorded",
        },
        "renderers": renderers,
        "browser_adapter": {
            "id": WECHAT_BROWSER_ADAPTER_ID,
            "version": WECHAT_BROWSER_ADAPTER_VERSION,
        },
        "host": {
            "os": platform.system(),
            "os_release": platform.release(),
            "architecture": platform.machine(),
            "python": platform.python_version(),
        },
        "tools": {
            "ffmpeg": _tool_version("ffmpeg", "-version"),
            "node": _tool_version("node", "--version"),
            "nvidia_smi": _tool_version(
                "nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"
            ),
        },
    }


def _scan_files(selected: dict[Path, str]) -> dict[str, Any]:
    findings = []
    files_scanned = 0
    for path in sorted(selected):
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        files_scanned += 1
        if path.stat().st_size > MAX_TEXT_SCAN_BYTES:
            findings.append(
                {"path": path.name, "pattern": "text_file_too_large_to_scan"}
            )
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if secret := _secret_in_text(text):
            findings.append({"path": path.name, "pattern": secret})
    return {
        "passed": not findings,
        "files_scanned": files_scanned,
        "findings": findings,
    }


def _hash_and_scan_stream(path: str, stream: Any) -> tuple[str, int, str | None]:
    digest = hashlib.sha256()
    size = 0
    text = bytearray() if Path(path).suffix.lower() in TEXT_SUFFIXES else None
    while block := stream.read(1024 * 1024):
        digest.update(block)
        size += len(block)
        if text is not None and len(text) <= MAX_TEXT_SCAN_BYTES:
            text.extend(block)
    if text is not None:
        if len(text) > MAX_TEXT_SCAN_BYTES:
            return digest.hexdigest(), size, "text_file_too_large_to_scan"
        value = text.decode("utf-8", errors="replace")
        if secret := _secret_in_text(value):
            return digest.hexdigest(), size, secret
    return digest.hexdigest(), size, None


def _verification_result(
    bundle_path: Path, bundle: dict[str, Any] | None, errors: list[dict[str, str]]
) -> dict[str, Any]:
    return {
        "schema_version": "video-content/portable-bundle-verification-v1",
        "valid": not errors,
        "bundle": bundle_path.name,
        "bundle_id": bundle.get("bundle_id") if isinstance(bundle, dict) else None,
        "project_id": bundle.get("project_id") if isinstance(bundle, dict) else None,
        "project_entry": (
            bundle.get("project_entry") if isinstance(bundle, dict) else None
        ),
        "file_count": (len(bundle.get("files", [])) if isinstance(bundle, dict) else 0),
        "errors": errors,
    }


def _unsafe_member(member: zipfile.ZipInfo) -> str | None:
    try:
        _safe_relative(member.filename)
    except ValueError as error:
        return str(error)
    mode = member.external_attr >> 16
    if mode and (mode & 0o170000) == 0o120000:
        return "symbolic links are forbidden"
    return None


def _safe_relative(value: str) -> Path:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or value.startswith("/")
        or ":" in value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"unsafe archive path: {value!r}")
    return Path(*path.parts)


def _validate_bundle_manifest(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, dict):
        return [_finding("schema", "bundle.json must be an object")]
    errors: list[dict[str, str]] = []
    if value.get("schema_version") != BUNDLE_VERSION:
        errors.append(_finding("schema", "Unsupported portable bundle schema"))
    if not re.fullmatch(r"bundle_[a-f0-9]{16}", str(value.get("bundle_id") or "")):
        errors.append(_finding("schema", "Invalid bundle_id"))
    if not isinstance(value.get("project_id"), str) or not value["project_id"]:
        errors.append(_finding("schema", "Invalid project_id"))
    project_entry = value.get("project_entry")
    if not isinstance(project_entry, str) or not project_entry.startswith("workspace/"):
        errors.append(_finding("schema", "Invalid project_entry"))
    else:
        try:
            _safe_relative(project_entry)
        except ValueError as error:
            errors.append(_finding("schema", str(error), "project_entry"))
    files = value.get("files")
    if not isinstance(files, list) or not files:
        errors.append(_finding("schema", "files must be a non-empty array"))
        return errors
    seen: set[str] = set()
    for index, item in enumerate(files):
        label = f"files[{index}]"
        if not isinstance(item, dict):
            errors.append(_finding("schema", "File record must be an object", label))
            continue
        path = item.get("path")
        if not isinstance(path, str) or not path.startswith("workspace/"):
            errors.append(_finding("schema", "Invalid file path", label))
        else:
            try:
                _safe_relative(path)
            except ValueError as error:
                errors.append(_finding("schema", str(error), label))
            if path in seen:
                errors.append(_finding("schema", "Duplicate file path", label))
            seen.add(path)
        size = item.get("bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            errors.append(_finding("schema", "Invalid file byte count", label))
        if not re.fullmatch(r"[a-f0-9]{64}", str(item.get("sha256") or "")):
            errors.append(_finding("schema", "Invalid file SHA-256", label))
        if item.get("role") not in {"project", "manifest", "evidence", "extra"}:
            errors.append(_finding("schema", "Invalid file role", label))
    if not isinstance(value.get("excluded"), list):
        errors.append(_finding("schema", "excluded must be an array"))
    if (
        not isinstance(value.get("secret_scan"), dict)
        or value["secret_scan"].get("passed") is not True
    ):
        errors.append(_finding("schema", "secret_scan must report passed=true"))
    if not isinstance(value.get("provenance"), dict):
        errors.append(_finding("schema", "provenance must be an object"))
    return errors


def _bundle_id(project_id: str, files: list[dict[str, Any]]) -> str:
    identity = {
        "project_id": project_id,
        "files": sorted((item["path"], item["sha256"]) for item in files),
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"bundle_{digest[:16]}"


def _secret_in_text(value: str) -> str | None:
    return next(
        (name for name, pattern in SECRET_PATTERNS.items() if pattern.search(value)),
        None,
    )


def _safe_provenance_value(value: str, label: str) -> str:
    result = value.strip() or "not_recorded"
    if len(result) > 200 or any(ord(character) < 32 for character in result):
        raise ValueError(f"Portable bundle {label} is invalid")
    if secret := _secret_in_text(result):
        raise ValueError(f"Portable bundle {label} contains forbidden {secret}")
    return result


def _write_zip_file(archive: zipfile.ZipFile, name: str, source: Path) -> None:
    info = _zip_info(name)
    with (
        source.open("rb") as stream,
        archive.open(info, "w", force_zip64=True) as output,
    ):
        shutil.copyfileobj(stream, output, length=1024 * 1024)


def _write_zip_bytes(archive: zipfile.ZipFile, name: str, payload: bytes) -> None:
    info = _zip_info(name)
    archive.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def _add_tree(selected: dict[Path, str], root: Path, role: str) -> None:
    if not root.is_dir():
        raise FileNotFoundError(f"Directory does not exist: {root}")
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        _add_file(selected, path, role)


def _add_file(selected: dict[Path, str], path: Path, role: str) -> None:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Bundle file does not exist: {path}")
    previous = selected.get(path)
    priorities = {"extra": 0, "evidence": 1, "manifest": 2, "project": 3}
    if previous is None or priorities[role] > priorities[previous]:
        selected[path] = role


def _require_within(root: Path, path: Path, label: str) -> None:
    root = root.resolve()
    path = path.resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"{label} must stay under the subtitle job directory")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _command_line(command: list[str], *, cwd: Path) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return (completed.stdout or completed.stderr).strip()


def _tool_version(name: str, *arguments: str) -> str:
    executable = shutil.which(name)
    if not executable:
        return "not_available"
    value = _command_line([executable, *arguments], cwd=Path.cwd())
    return value.splitlines()[0][:500] if value else "not_available"


def _finding(code: str, message: str, path: str | None = None) -> dict[str, str]:
    result = {"code": code, "message": message}
    if path:
        result["path"] = path
    return result
