from __future__ import annotations

import struct
import subprocess
import zlib
from pathlib import Path

from video_content.frames import extract_source_frame
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

    assert result["schema_version"] == "video-content/source-frame-extraction-v1"
    assert result["reused"] is False
    assert result["artifact"]["artifact_id"] != scout["artifact_id"]
    assert len(calls) == 1
    video_filter = calls[0][calls[0].index("-vf") + 1]
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
        "pixel_width": 1920,
        "pixel_height": 1080,
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
    assert len(calls) == 1
