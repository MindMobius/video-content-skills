"""Durable per-video batch ledger for Agent-managed multi-video work."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from .util import read_json, utc_now, write_json_atomic

BatchStage = Literal["subtitle", "content", "handoff"]
BatchStageStatus = Literal[
    "pending",
    "running",
    "completed",
    "failed",
    "blocked",
    "skipped",
    "not_requested",
]
INPUT_KINDS = {"video_url", "video_file", "audio_file", "subtitle_file"}
TARGET_MEDIA = {
    "article",
    "one_page",
    "card_series",
    "brief",
    "script",
    "custom",
    "subtitles_only",
}
STAGES = ("subtitle", "content", "handoff")
TERMINAL_STAGE_STATES = {"completed", "skipped", "not_requested"}
TOKEN_QUERY_RE = re.compile(r"(?i)(?:^|[?&])(token|cookie|sessdata|password)=[^&]+")


def initialize_batch(
    manifest_path: Path,
    inputs: list[dict[str, str]],
    *,
    target_medium: str = "article",
    draft_requested: bool = False,
) -> dict[str, Any]:
    """Create or idempotently reuse one batch without merging item artifacts."""
    manifest_path = manifest_path.expanduser().resolve()
    if not inputs:
        raise ValueError("A batch requires at least one input")
    if target_medium not in TARGET_MEDIA:
        raise ValueError(f"Unsupported target medium: {target_medium}")
    if target_medium == "subtitles_only" and draft_requested:
        raise ValueError("A subtitles-only batch cannot request a WeChat draft")
    normalized = [_normalize_input(item) for item in inputs]
    if len({json.dumps(item, sort_keys=True) for item in normalized}) != len(
        normalized
    ):
        raise ValueError("Batch inputs must be unique")
    identity = {
        "inputs": normalized,
        "target_medium": target_medium,
        "draft_requested": draft_requested,
    }
    batch_hash = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    batch_id = f"batch_{batch_hash[:16]}"
    if manifest_path.is_file():
        existing = get_batch(manifest_path)
        if existing["batch_id"] != batch_id:
            raise ValueError("Batch manifest already belongs to a different input set")
        existing["reused_existing_batch"] = True
        return existing
    now = utc_now()
    content_state = "not_requested" if target_medium == "subtitles_only" else "pending"
    handoff_state = "pending" if draft_requested else "not_requested"
    items = []
    for index, item in enumerate(normalized, start=1):
        items.append(
            {
                "item_id": f"item-{index:03d}",
                "input": item,
                "status": "pending",
                "stages": {
                    "subtitle": _stage("pending"),
                    "content": _stage(content_state),
                    "handoff": _stage(handoff_state),
                },
                "created_at": now,
                "updated_at": now,
            }
        )
    document = {
        "schema_version": "video-content/batch-v1",
        "batch_id": batch_id,
        "created_at": now,
        "updated_at": now,
        "intent": {
            "target_medium": target_medium,
            "draft_requested": draft_requested,
        },
        "items": items,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(manifest_path, document)
    result = get_batch(manifest_path)
    result["reused_existing_batch"] = False
    return result


def get_batch(manifest_path: Path) -> dict[str, Any]:
    manifest_path = _require_manifest(manifest_path)
    document = read_json(manifest_path)
    _validate_batch(document)
    return {
        **document,
        "manifest_path": str(manifest_path),
        "summary": _summary(document),
        "resumable": _resumable(document),
    }


def update_batch_item(
    manifest_path: Path,
    *,
    item_id: str,
    stage: BatchStage,
    status: BatchStageStatus,
    artifact: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Apply one guarded stage transition with an atomic cross-process lock."""
    manifest_path = _require_manifest(manifest_path)
    if stage not in STAGES:
        raise ValueError(f"Unsupported batch stage: {stage}")
    if status not in {
        "pending",
        "running",
        "completed",
        "failed",
        "blocked",
        "skipped",
        "not_requested",
    }:
        raise ValueError(f"Unsupported batch stage status: {status}")
    with _manifest_lock(manifest_path):
        document = read_json(manifest_path)
        _validate_batch(document)
        item = next(
            (
                candidate
                for candidate in document["items"]
                if candidate["item_id"] == item_id
            ),
            None,
        )
        if item is None:
            raise ValueError(f"Batch item not found: {item_id}")
        state = item["stages"][stage]
        if status == "completed" and artifact:
            artifact = _artifact_reference(manifest_path, artifact)
        if error:
            error = _safe_error(error)
        _validate_transition(item, stage, state["status"], status, artifact, error)
        now = utc_now()
        state["status"] = status
        if status == "running":
            state["attempts"] += 1
            state["started_at"] = now
            state["finished_at"] = None
            state["artifact"] = None
            state["last_error"] = None
        elif status in {"completed", "failed", "blocked", "skipped"}:
            state["finished_at"] = now
            state["artifact"] = artifact.strip() if artifact else None
            state["last_error"] = error.strip() if error else None
        item["updated_at"] = now
        item["status"] = _item_status(item)
        document["updated_at"] = now
        write_json_atomic(manifest_path, document)
    result = get_batch(manifest_path)
    result["updated_item"] = item_id
    result["updated_stage"] = stage
    return result


def _normalize_input(item: Any) -> dict[str, str]:
    if not isinstance(item, dict):
        raise TypeError("Each batch input must be an object")
    kind = str(item.get("kind") or "").strip()
    value = str(item.get("value") or "").strip()
    if kind not in INPUT_KINDS:
        raise ValueError(f"Unsupported batch input kind: {kind}")
    if not value:
        raise ValueError("Batch input value cannot be empty")
    if TOKEN_QUERY_RE.search(value):
        raise ValueError("Batch inputs must not contain credentials or URL tokens")
    return {"kind": kind, "value": value}


def _stage(status: str) -> dict[str, Any]:
    return {
        "status": status,
        "attempts": 0,
        "started_at": None,
        "finished_at": None,
        "artifact": None,
        "last_error": None,
    }


def _validate_transition(
    item: dict[str, Any],
    stage: str,
    previous: str,
    status: str,
    artifact: str | None,
    error: str | None,
) -> None:
    if previous in TERMINAL_STAGE_STATES:
        raise ValueError(f"Stage {stage} is already terminal as {previous}")
    if status == "running":
        if previous not in {"pending", "failed", "blocked"}:
            raise ValueError(f"Cannot start {stage} from {previous}")
        _require_prerequisites(item, stage)
    elif status in {"completed", "failed", "blocked", "skipped"}:
        if previous != "running":
            raise ValueError(f"Stage {stage} must be running before {status}")
        if status == "completed" and not artifact:
            raise ValueError(f"Completed {stage} stage requires an artifact path")
        if status in {"failed", "blocked"} and not error:
            raise ValueError(f"{status.title()} {stage} stage requires an error")
    else:
        raise ValueError(f"Direct transition to {status} is not supported")


def _require_prerequisites(item: dict[str, Any], stage: str) -> None:
    if stage == "content" and item["stages"]["subtitle"]["status"] != "completed":
        raise ValueError("Content stage requires a completed subtitle manifest")
    if stage == "handoff" and item["stages"]["content"]["status"] != "completed":
        raise ValueError("Handoff stage requires a completed content project")


def _item_status(item: dict[str, Any]) -> str:
    states = [item["stages"][stage]["status"] for stage in STAGES]
    if any(state == "running" for state in states):
        return "running"
    if any(state == "blocked" for state in states):
        return "blocked"
    if any(state == "failed" for state in states):
        return "failed"
    if all(state in TERMINAL_STAGE_STATES for state in states):
        return "completed"
    return "pending"


def _summary(document: dict[str, Any]) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    for item in document["items"]:
        by_status[item["status"]] = by_status.get(item["status"], 0) + 1
    return {"total": len(document["items"]), "by_status": by_status}


def _resumable(document: dict[str, Any]) -> list[dict[str, str]]:
    result = []
    for item in document["items"]:
        for stage in STAGES:
            state = item["stages"][stage]["status"]
            if state in {"pending", "failed", "blocked"}:
                try:
                    _require_prerequisites(item, stage)
                except ValueError:
                    continue
                result.append(
                    {"item_id": item["item_id"], "stage": stage, "status": state}
                )
                break
    return result


def _validate_batch(document: Any) -> None:
    if not isinstance(document, dict):
        raise TypeError("Batch manifest must be a JSON object")
    if document.get("schema_version") != "video-content/batch-v1":
        raise ValueError("Unsupported batch manifest schema")
    if not isinstance(document.get("items"), list) or not document["items"]:
        raise ValueError("Batch manifest items are missing")


def _artifact_reference(manifest_path: Path, value: str) -> str:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = manifest_path.parent / candidate
    candidate = candidate.resolve()
    if not candidate.is_file():
        raise FileNotFoundError(f"Completed batch artifact does not exist: {candidate}")
    try:
        return candidate.relative_to(manifest_path.parent).as_posix()
    except ValueError as error:
        raise ValueError(
            "Batch artifacts must stay under the batch directory"
        ) from error


def _safe_error(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Batch error cannot be empty")
    if len(value) > 2000:
        raise ValueError("Batch error exceeds 2000 characters")
    if TOKEN_QUERY_RE.search(value):
        raise ValueError("Batch errors must not contain credentials or URL tokens")
    return value


def _require_manifest(path: Path) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Batch manifest does not exist: {path}")
    return path


@contextmanager
def _manifest_lock(path: Path, timeout_seconds: float = 5.0) -> Iterator[None]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    deadline = time.monotonic() + timeout_seconds
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Batch manifest is locked: {path}") from None
            time.sleep(0.05)
    try:
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        os.close(descriptor)
        descriptor = None
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        lock_path.unlink(missing_ok=True)
