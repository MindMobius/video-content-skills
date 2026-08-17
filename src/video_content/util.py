from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SECRET_KEY = re.compile(
    r"(?i)(cookie|token|password|passwd|secret|sessdata|authorization)"
)


def utc_now() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def new_id(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{prefix}_{stamp}_{os.urandom(6).hex()}"


def safe_id(value: str, *, label: str = "identifier") -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ValueError(f"Invalid {label}: {value!r}")
    return value


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def write_json_atomic(path: Path, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    write_text_atomic(path, payload)


def write_text_atomic(path: Path, value: str) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def append_json_line(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(line)
        stream.flush()
        os.fsync(stream.fileno())


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_within(root: Path, path: Path) -> Path:
    root = root.expanduser().resolve()
    path = path.expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError(f"Path escapes store root: {path}") from error
    return path


def reject_secrets(value: Any, *, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if _SECRET_KEY.search(str(key)):
                raise ValueError(
                    f"Persistent document contains secret-like field: {path}.{key}"
                )
            reject_secrets(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reject_secrets(item, path=f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.lower()
        if value.startswith("data:") and ";base64," in lowered[:160]:
            raise ValueError(f"Persistent document contains Base64 payload: {path}")
        if re.search(r"(?i)(?:[?&](?:token|cookie|sessdata|password|secret)=)", value):
            raise ValueError(f"Persistent document contains secret URL value: {path}")


def json_for_stdout(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def local_job_id() -> str:
    return new_id("job")


def tail_text(path: Path, max_chars: int = 12_000) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[-max_chars:]
