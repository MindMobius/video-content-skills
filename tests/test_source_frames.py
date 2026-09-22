from __future__ import annotations

import json
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

from video_content.frames import extract_source_frame, probe_video_geometry
from video_content.store import Store


def _png_bytes(width: int, height: int) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return (
            struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))
        )

    rows = b"".join(b"\x00" + (b"\x20\x40\x60" * width) for _ in range(height))
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
            chunk(b"IDAT", zlib.compress(rows)),
            chunk(b"IEND", b""),
        )
    )


def _probe_result(
    *,
    width: int = 1920,
    height: int = 1080,
    sar: str = "1:1",
    dar: str = "16:9",
    rotation: int | None = None,
) -> str:
    stream: dict = {
        "width": width,
        "height": height,
        "coded_width": width,
        "coded_height": height,
        "sample_aspect_ratio": sar,
        "display_aspect_ratio": dar,
        "tags": {},
    }
    if rotation is not None:
        stream["side_data_list"] = [{"rotation": rotation}]
    return json.dumps({"streams": [stream]})


def test_final_frame_extraction_ignores_scout_preview_and_is_idempotent(
    tmp_path: Path, monkeypatch
) -> None:
    store = Store(tmp_path / "home")
    job, _ = store.create_job(
        source={"platform": "bilibili", "bvid": "BV1frame"},
        idempotency_key="bilibili_BV1frame_p1",
        initial_stage="content",
        initial_status="running",
    )
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"source-video")
    source = store.put_artifact(
        job["job_id"], kind="source_video", source_path=source_path
    )
    scout_path = tmp_path / "scout.png"
    scout_path.write_bytes(_png_bytes(640, 360))
    scout = store.put_artifact(
        job["job_id"],
        kind="video_frame",
        source_path=scout_path,
        metadata={"timestamp_ms": 42000, "extraction_role": "scout"},
    )

    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if "ffprobe" in Path(command[0]).stem.lower():
            return subprocess.CompletedProcess(
                command, 0, stdout=_probe_result(), stderr=""
            )
        Path(command[-1]).write_bytes(_png_bytes(1920, 1080))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("video_content.frames.subprocess.run", fake_run)

    result = extract_source_frame(
        store,
        job_id=job["job_id"],
        timestamp_ms=42000,
        selection_reason="对应论述转场",
        ffmpeg_path="ffmpeg",
    )

    assert result["schema_version"] == "video-content/source-frame-extraction-v2"
    assert result["reused"] is False
    assert result["artifact"]["artifact_id"] != scout["artifact_id"]
    ffmpeg_calls = [
        call for call in calls if "ffprobe" not in Path(call[0]).stem.lower()
    ]
    assert len(ffmpeg_calls) == 1
    video_filter = ffmpeg_calls[0][ffmpeg_calls[0].index("-vf") + 1]
    assert video_filter == "scale=w=round(iw*sar):h=ih:flags=lanczos,setsar=1"
    assert "640" not in video_filter
    assert "960" not in video_filter
    metadata = result["artifact"]["metadata"]
    assert metadata == {
        "timestamp_ms": 42000,
        "selection_reason": "对应论述转场",
        "extraction_role": "final",
        "extraction_method": "ffmpeg_source_frame",
        "resolution_policy": "source_display_native",
        "source_video_artifact_id": source["artifact_id"],
        "source_video_sha256": source["sha256"],
        "source_geometry_schema": "video-content/source-frame-geometry-v1",
        "source_pixel_width": 1920,
        "source_pixel_height": 1080,
        "source_coded_width": 1920,
        "source_coded_height": 1080,
        "source_sample_aspect_ratio": "1:1",
        "source_display_width": 1920,
        "source_display_height": 1080,
        "source_display_aspect_ratio": "16:9",
        "source_rotation_degrees": 0,
        "pixel_width": 1920,
        "pixel_height": 1080,
        "output_pixel_width": 1920,
        "output_pixel_height": 1080,
        "aspect_ratio_drift": 0.0,
        "display_aspect_preserved": True,
    }

    reused = extract_source_frame(
        store,
        job_id=job["job_id"],
        timestamp_ms=42000,
        selection_reason="对应论述转场",
        ffmpeg_path="ffmpeg",
    )
    assert reused["reused"] is True
    assert reused["artifact"]["artifact_id"] == result["artifact"]["artifact_id"]
    ffmpeg_calls = [
        call for call in calls if "ffprobe" not in Path(call[0]).stem.lower()
    ]
    assert len(ffmpeg_calls) == 1


def test_final_frame_extraction_rejects_wrong_output_aspect(
    tmp_path: Path, monkeypatch
) -> None:
    store = Store(tmp_path / "home")
    job, _ = store.create_job(
        source={"platform": "bilibili", "bvid": "BV1badframe"},
        idempotency_key="bilibili_BV1badframe_p1",
        initial_stage="content",
        initial_status="running",
    )
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"source-video")
    store.put_artifact(job["job_id"], kind="source_video", source_path=source_path)

    def fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        if "ffprobe" in Path(command[0]).stem.lower():
            return subprocess.CompletedProcess(
                command, 0, stdout=_probe_result(), stderr=""
            )
        Path(command[-1]).write_bytes(_png_bytes(1000, 1000))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("video_content.frames.subprocess.run", fake_run)

    with pytest.raises(ValueError, match="does not preserve"):
        extract_source_frame(
            store,
            job_id=job["job_id"],
            timestamp_ms=1000,
            selection_reason="错误画幅回归",
            ffmpeg_path="ffmpeg",
        )


def test_video_geometry_accounts_for_non_square_sar_and_rotation(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "rotated.mp4"
    source.write_bytes(b"video")

    def fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=_probe_result(
                width=720,
                height=576,
                sar="16:15",
                dar="4:3",
                rotation=90,
            ),
            stderr="",
        )

    monkeypatch.setattr("video_content.frames.subprocess.run", fake_run)
    geometry = probe_video_geometry(source, ffprobe_path="ffprobe")

    assert geometry["source_sample_aspect_ratio"] == "16:15"
    assert geometry["source_display_width"] == 576
    assert geometry["source_display_height"] == 768
    assert geometry["source_display_aspect_ratio"] == "3:4"
    assert geometry["source_rotation_degrees"] == 90
