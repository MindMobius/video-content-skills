from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path
from typing import Any

from .store import Store

FRAME_EXTRACTION_SCHEMA = "video-content/source-frame-extraction-v2"
FRAME_GEOMETRY_SCHEMA = "video-content/source-frame-geometry-v1"
FINAL_FRAME_ROLE = "final"
FINAL_FRAME_METHOD = "ffmpeg_source_frame"
FINAL_FRAME_RESOLUTION_POLICY = "source_display_native"
ASPECT_RATIO_TOLERANCE = 0.01
_DISPLAY_ASPECT_FILTER = "scale=w=round(iw*sar):h=ih:flags=lanczos,setsar=1"


def extract_source_frame(
    store: Store,
    *,
    job_id: str,
    timestamp_ms: int,
    selection_reason: str,
    ffmpeg_path: str | None = None,
    ffprobe_path: str | None = None,
) -> dict[str, Any]:
    """Extract one final source-native frame and register it as a Job Artifact.

    Scout/contact-sheet images are intentionally never accepted as inputs. The
    source display geometry is probed independently and the resulting PNG must
    preserve that geometry before it may be registered as a final frame.
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
    source_path = store.job_dir(job_id) / source["path"]
    executable = _resolve_ffmpeg(ffmpeg_path)
    geometry = probe_video_geometry(
        source_path,
        ffprobe_path=ffprobe_path,
        ffmpeg_path=executable,
    )
    for reference in reversed(store.list_artifacts(job_id, kind="video_frame")):
        metadata = reference.get("metadata", {})
        if (
            metadata.get("extraction_role") == FINAL_FRAME_ROLE
            and metadata.get("extraction_method") == FINAL_FRAME_METHOD
            and metadata.get("resolution_policy") == FINAL_FRAME_RESOLUTION_POLICY
            and metadata.get("source_video_artifact_id") == source["artifact_id"]
            and metadata.get("source_video_sha256") == source["sha256"]
            and metadata.get("timestamp_ms") == timestamp_ms
            and metadata.get("source_geometry_schema") == FRAME_GEOMETRY_SCHEMA
            and metadata.get("display_aspect_preserved") is True
        ):
            width, height = _validate_recorded_dimensions(store, job_id, reference)
            _validate_recorded_geometry(metadata, width, height, geometry)
            return {
                "schema_version": FRAME_EXTRACTION_SCHEMA,
                "job_id": job_id,
                "timestamp_ms": timestamp_ms,
                "source_video_artifact_id": source["artifact_id"],
                "source_geometry": geometry,
                "artifact": reference,
                "reused": True,
            }

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
        aspect = frame_geometry_report(width, height, geometry)
        if aspect["display_aspect_preserved"] is not True:
            raise ValueError(
                "Extracted frame does not preserve the source display aspect ratio: "
                f"drift={aspect['aspect_ratio_drift']:.6f}"
            )
        metadata = {
            "timestamp_ms": timestamp_ms,
            "selection_reason": reason,
            "extraction_role": FINAL_FRAME_ROLE,
            "extraction_method": FINAL_FRAME_METHOD,
            "resolution_policy": FINAL_FRAME_RESOLUTION_POLICY,
            "source_video_artifact_id": source["artifact_id"],
            "source_video_sha256": source["sha256"],
            "source_geometry_schema": FRAME_GEOMETRY_SCHEMA,
            "source_pixel_width": geometry["source_pixel_width"],
            "source_pixel_height": geometry["source_pixel_height"],
            "source_coded_width": geometry["source_coded_width"],
            "source_coded_height": geometry["source_coded_height"],
            "source_sample_aspect_ratio": geometry["source_sample_aspect_ratio"],
            "source_display_width": geometry["source_display_width"],
            "source_display_height": geometry["source_display_height"],
            "source_display_aspect_ratio": geometry["source_display_aspect_ratio"],
            "source_rotation_degrees": geometry["source_rotation_degrees"],
            "pixel_width": width,
            "pixel_height": height,
            "output_pixel_width": width,
            "output_pixel_height": height,
            "aspect_ratio_drift": aspect["aspect_ratio_drift"],
            "display_aspect_preserved": aspect["display_aspect_preserved"],
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
        "source_geometry": geometry,
        "artifact": artifact,
        "reused": False,
    }


def probe_video_geometry(
    path: str | Path,
    *,
    ffprobe_path: str | None = None,
    ffmpeg_path: str | None = None,
) -> dict[str, Any]:
    """Read the first video stream's coded, sample, display, and rotation geometry."""

    selected = Path(path).expanduser().resolve()
    if not selected.is_file():
        raise FileNotFoundError(f"Source video does not exist: {selected}")
    executable = _resolve_ffprobe(ffprobe_path, ffmpeg_path=ffmpeg_path)
    command = [
        executable,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        (
            "stream=width,height,coded_width,coded_height,sample_aspect_ratio,"
            "display_aspect_ratio:stream_tags=rotate:stream_side_data=rotation"
        ),
        "-of",
        "json",
        str(selected),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise OSError(
            "FFprobe video geometry inspection failed"
            + (f": {detail[-1000:]}" if detail else "")
        )
    try:
        document = json.loads(completed.stdout or "{}")
        stream = document["streams"][0]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        raise ValueError("FFprobe did not return one usable video stream") from error

    pixel_width = _positive_int(
        stream.get("width") or stream.get("coded_width"), "video width"
    )
    pixel_height = _positive_int(
        stream.get("height") or stream.get("coded_height"), "video height"
    )
    coded_width = _positive_int(
        stream.get("coded_width") or pixel_width, "coded video width"
    )
    coded_height = _positive_int(
        stream.get("coded_height") or pixel_height, "coded video height"
    )
    sample_aspect = _parse_ratio(stream.get("sample_aspect_ratio")) or Fraction(1, 1)
    display_ratio = Fraction(
        pixel_width * sample_aspect.numerator,
        pixel_height * sample_aspect.denominator,
    )
    rotation = _stream_rotation(stream)
    display_width = Fraction(
        pixel_width * sample_aspect.numerator, sample_aspect.denominator
    )
    display_height = Fraction(pixel_height, 1)
    if rotation in {90, 270}:
        display_width, display_height = display_height, display_width
        display_ratio = 1 / display_ratio
    reported_display = _parse_ratio(stream.get("display_aspect_ratio"))

    return {
        "schema_version": FRAME_GEOMETRY_SCHEMA,
        "source_pixel_width": pixel_width,
        "source_pixel_height": pixel_height,
        "source_coded_width": coded_width,
        "source_coded_height": coded_height,
        "source_sample_aspect_ratio": _ratio_text(sample_aspect),
        "source_reported_display_aspect_ratio": (
            _ratio_text(reported_display) if reported_display is not None else None
        ),
        "source_display_width": _fraction_number(display_width),
        "source_display_height": _fraction_number(display_height),
        "source_display_aspect_ratio": _ratio_text(display_ratio),
        "source_display_aspect_ratio_value": float(display_ratio),
        "source_rotation_degrees": rotation,
    }


def frame_geometry_report(
    width: int,
    height: int,
    source_geometry: dict[str, Any],
    *,
    tolerance: float = ASPECT_RATIO_TOLERANCE,
) -> dict[str, Any]:
    width, height = _positive_dimensions(width, height, Path("<frame>"))
    expected = _parse_ratio(source_geometry.get("source_display_aspect_ratio"))
    if expected is None:
        raise ValueError("Source geometry has no display aspect ratio")
    actual = Fraction(width, height)
    drift = abs(float(actual / expected) - 1.0)
    return {
        "expected_aspect_ratio": _ratio_text(expected),
        "output_aspect_ratio": _ratio_text(actual),
        "aspect_ratio_drift": drift,
        "display_aspect_preserved": drift <= tolerance,
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
        return _resolve_executable(selected, "FFmpeg")
    resolved = shutil.which("ffmpeg")
    if not resolved:
        raise FileNotFoundError("FFmpeg executable is not configured")
    return resolved


def _resolve_ffprobe(value: str | None, *, ffmpeg_path: str | None = None) -> str:
    selected = str(value or os.getenv("VIDEO_CONTENT_FFPROBE") or "").strip()
    if selected:
        return _resolve_executable(selected, "FFprobe")
    configured_ffmpeg = str(
        ffmpeg_path or os.getenv("VIDEO_CONTENT_FFMPEG") or ""
    ).strip()
    if configured_ffmpeg:
        candidate = Path(configured_ffmpeg).expanduser()
        if candidate.is_file():
            suffix = (
                candidate.suffix
                if candidate.suffix
                else (".exe" if os.name == "nt" else "")
            )
            sibling = candidate.with_name(f"ffprobe{suffix}")
            if sibling.is_file():
                return str(sibling.resolve())
    resolved = shutil.which("ffprobe")
    if not resolved:
        raise FileNotFoundError("FFprobe executable is not configured")
    return resolved


def _resolve_executable(value: str, label: str) -> str:
    path = Path(value).expanduser()
    if path.is_absolute() or path.parent != Path("."):
        if not path.is_file():
            raise FileNotFoundError(f"{label} executable not found: {path}")
        return str(path.resolve())
    resolved = shutil.which(value)
    if resolved:
        return resolved
    raise FileNotFoundError(f"{label} executable not found: {value}")


def _validate_recorded_dimensions(
    store: Store, job_id: str, reference: dict[str, Any]
) -> tuple[int, int]:
    metadata = reference.get("metadata", {})
    path = store.job_dir(job_id) / reference["path"]
    width, height = image_dimensions(path)
    if metadata.get("pixel_width") != width or metadata.get("pixel_height") != height:
        raise ValueError(
            f"Final frame dimension metadata does not match Artifact bytes: {reference['artifact_id']}"
        )
    return width, height


def _validate_recorded_geometry(
    metadata: dict[str, Any],
    width: int,
    height: int,
    geometry: dict[str, Any],
) -> None:
    report = frame_geometry_report(width, height, geometry)
    if report["display_aspect_preserved"] is not True:
        raise ValueError(
            "Recorded final frame no longer matches source display geometry"
        )
    required_matches = {
        "source_geometry_schema": FRAME_GEOMETRY_SCHEMA,
        "source_pixel_width": geometry["source_pixel_width"],
        "source_pixel_height": geometry["source_pixel_height"],
        "source_coded_width": geometry["source_coded_width"],
        "source_coded_height": geometry["source_coded_height"],
        "source_sample_aspect_ratio": geometry["source_sample_aspect_ratio"],
        "source_display_aspect_ratio": geometry["source_display_aspect_ratio"],
        "source_rotation_degrees": geometry["source_rotation_degrees"],
        "output_pixel_width": width,
        "output_pixel_height": height,
    }
    mismatched = [
        field
        for field, expected in required_matches.items()
        if metadata.get(field) != expected
    ]
    recorded_drift = metadata.get("aspect_ratio_drift")
    if (
        not isinstance(recorded_drift, (int, float))
        or isinstance(recorded_drift, bool)
        or abs(float(recorded_drift) - report["aspect_ratio_drift"]) > 1e-9
    ):
        mismatched.append("aspect_ratio_drift")
    if metadata.get("display_aspect_preserved") is not True:
        mismatched.append("display_aspect_preserved")
    if mismatched:
        raise ValueError(
            "Recorded final frame geometry metadata is stale or inconsistent: "
            + ", ".join(sorted(set(mismatched)))
        )


def _parse_ratio(value: Any) -> Fraction | None:
    if isinstance(value, Fraction):
        return value if value > 0 else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return Fraction(str(value)) if value > 0 else None
    text = str(value or "").strip()
    if not text or text.upper() in {"N/A", "UNKNOWN", "0:1", "0/1"}:
        return None
    separator = ":" if ":" in text else ("/" if "/" in text else None)
    try:
        if separator:
            numerator, denominator = text.split(separator, 1)
            result = Fraction(int(numerator), int(denominator))
        else:
            result = Fraction(text)
    except (ValueError, ZeroDivisionError):
        return None
    return result if result > 0 else None


def _stream_rotation(stream: dict[str, Any]) -> int:
    candidates: list[Any] = []
    tags = stream.get("tags")
    if isinstance(tags, dict):
        candidates.append(tags.get("rotate"))
    side_data = stream.get("side_data_list")
    if isinstance(side_data, list):
        candidates.extend(
            item.get("rotation") for item in side_data if isinstance(item, dict)
        )
    selected = next((item for item in candidates if item not in {None, ""}), 0)
    try:
        rotation = round(float(selected)) % 360
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"Unsupported video rotation metadata: {selected!r}"
        ) from error
    if rotation not in {0, 90, 180, 270}:
        raise ValueError(f"Unsupported non-right-angle video rotation: {rotation}")
    return rotation


def _ratio_text(value: Fraction) -> str:
    return f"{value.numerator}:{value.denominator}"


def _fraction_number(value: Fraction) -> int | float:
    return value.numerator if value.denominator == 1 else float(value)


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"FFprobe returned an invalid {label}: {value!r}")
    return value


def _positive_dimensions(width: int, height: int, path: Path) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        raise ValueError(f"Image has invalid dimensions: {path}")
    return width, height
