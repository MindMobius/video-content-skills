from __future__ import annotations

import os
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .store import Store

FRAME_EXTRACTION_SCHEMA = "video-content/source-frame-extraction-v1"
FINAL_FRAME_ROLE = "final"
FINAL_FRAME_METHOD = "ffmpeg_source_frame"
FINAL_FRAME_RESOLUTION_POLICY = "source_display_native"
_DISPLAY_ASPECT_FILTER = "scale=w=round(iw*sar):h=ih:flags=lanczos,setsar=1"


def extract_source_frame(
    store: Store,
    *,
    job_id: str,
    timestamp_ms: int,
    selection_reason: str,
    ffmpeg_path: str | None = None,
) -> dict[str, Any]:
    """Extract one final source-native frame and register it as a Job Artifact.

    Scout/contact-sheet images are intentionally never accepted as inputs. A retry may
    reuse only a previously registered final extraction for the same source bytes and
    timestamp.
    """

    if (
        not isinstance(timestamp_ms, int)
        or isinstance(timestamp_ms, bool)
        or timestamp_ms < 0
    ):
        raise ValueError("timestamp_ms must be a non-negative integer")
    reason = str(selection_reason or "").strip()
    if not reason:
        raise ValueError("selection_reason is required")

    source = _source_video_reference(store, job_id)
    for reference in reversed(store.list_artifacts(job_id, kind="video_frame")):
        metadata = reference.get("metadata", {})
        if (
            metadata.get("extraction_role") == FINAL_FRAME_ROLE
            and metadata.get("extraction_method") == FINAL_FRAME_METHOD
            and metadata.get("resolution_policy") == FINAL_FRAME_RESOLUTION_POLICY
            and metadata.get("source_video_artifact_id") == source["artifact_id"]
            and metadata.get("source_video_sha256") == source["sha256"]
            and metadata.get("timestamp_ms") == timestamp_ms
            and metadata.get("display_aspect_preserved") is True
        ):
            _validate_recorded_dimensions(store, job_id, reference)
            return {
                "schema_version": FRAME_EXTRACTION_SCHEMA,
                "job_id": job_id,
                "timestamp_ms": timestamp_ms,
                "source_video_artifact_id": source["artifact_id"],
                "artifact": reference,
                "reused": True,
            }

    executable = _resolve_ffmpeg(ffmpeg_path)
    source_path = store.job_dir(job_id) / source["path"]
    work_root = store.job_dir(job_id) / "work" / "source-frame-extract"
    work_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"{timestamp_ms}-", dir=work_root) as value:
        output = Path(value) / "frame.png"
        command = [
            executable,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{timestamp_ms / 1000:.3f}",
            "-i",
            str(source_path),
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-vf",
            _DISPLAY_ASPECT_FILTER,
            "-y",
            str(output),
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if (
            completed.returncode != 0
            or not output.is_file()
            or output.stat().st_size <= 0
        ):
            detail = (completed.stderr or completed.stdout or "").strip()
            raise OSError(
                "FFmpeg source-frame extraction failed"
                + (f": {detail[-1000:]}" if detail else "")
            )
        width, height = image_dimensions(output)
        metadata = {
            "timestamp_ms": timestamp_ms,
            "selection_reason": reason,
            "extraction_role": FINAL_FRAME_ROLE,
            "extraction_method": FINAL_FRAME_METHOD,
            "resolution_policy": FINAL_FRAME_RESOLUTION_POLICY,
            "source_video_artifact_id": source["artifact_id"],
            "source_video_sha256": source["sha256"],
            "pixel_width": width,
            "pixel_height": height,
            "display_aspect_preserved": True,
        }
        artifact = store.put_artifact(
            job_id,
            kind="video_frame",
            source_path=output,
            filename=f"frame-{timestamp_ms:012d}.png",
            media_type="image/png",
            metadata=metadata,
        )
    return {
        "schema_version": FRAME_EXTRACTION_SCHEMA,
        "job_id": job_id,
        "timestamp_ms": timestamp_ms,
        "source_video_artifact_id": source["artifact_id"],
        "artifact": artifact,
        "reused": False,
    }


def image_dimensions(path: str | Path) -> tuple[int, int]:
    selected = Path(path)
    data = selected.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return _positive_dimensions(width, height, selected)
    if data.startswith(b"\xff\xd8"):
        position = 2
        start_of_frame = {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }
        while position + 4 <= len(data):
            if data[position] != 0xFF:
                position += 1
                continue
            while position < len(data) and data[position] == 0xFF:
                position += 1
            if position >= len(data):
                break
            marker = data[position]
            position += 1
            if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
                continue
            if position + 2 > len(data):
                break
            segment_length = int.from_bytes(data[position : position + 2], "big")
            if marker in start_of_frame and position + 7 <= len(data):
                height = int.from_bytes(data[position + 3 : position + 5], "big")
                width = int.from_bytes(data[position + 5 : position + 7], "big")
                return _positive_dimensions(width, height, selected)
            if segment_length < 2:
                break
            position += segment_length
    raise ValueError(f"Unsupported or malformed image: {selected}")


def _source_video_reference(store: Store, job_id: str) -> dict[str, Any]:
    references = store.list_artifacts(job_id, kind="source_video")
    if not references:
        raise FileNotFoundError(f"No source_video Artifact for {job_id}")
    reference = references[-1]
    store.read_artifact(job_id, str(reference["artifact_id"]))
    return reference


def _resolve_ffmpeg(value: str | None) -> str:
    selected = str(value or os.getenv("VIDEO_CONTENT_FFMPEG") or "").strip()
    if selected:
        path = Path(selected).expanduser()
        if path.is_absolute() or path.parent != Path("."):
            if not path.is_file():
                raise FileNotFoundError(f"FFmpeg executable not found: {path}")
            return str(path.resolve())
        resolved = shutil.which(selected)
        if resolved:
            return resolved
        raise FileNotFoundError(f"FFmpeg executable not found: {selected}")
    resolved = shutil.which("ffmpeg")
    if not resolved:
        raise FileNotFoundError("FFmpeg executable is not configured")
    return resolved


def _validate_recorded_dimensions(
    store: Store, job_id: str, reference: dict[str, Any]
) -> None:
    metadata = reference.get("metadata", {})
    path = store.job_dir(job_id) / reference["path"]
    width, height = image_dimensions(path)
    if metadata.get("pixel_width") != width or metadata.get("pixel_height") != height:
        raise ValueError(
            f"Final frame dimension metadata does not match Artifact bytes: {reference['artifact_id']}"
        )


def _positive_dimensions(width: int, height: int, path: Path) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        raise ValueError(f"Image has invalid dimensions: {path}")
    return width, height
