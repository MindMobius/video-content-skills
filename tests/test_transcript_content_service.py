from __future__ import annotations

from pathlib import Path

import pytest

from video_content.content import content_save, transcript_save
from video_content.store import Store


def _evidence(store: Store, job_id: str) -> str:
    evidence_id = "evidence_fixture"
    store.save_document(
        job_id,
        kind="evidence",
        document={
            "schema_version": "video-content/evidence-v1",
            "evidence_id": evidence_id,
            "job_id": job_id,
            "source": {"platform": "bilibili"},
            "observations": [],
            "artifact_refs": [],
            "decision": {},
            "created_at": "2026-08-17T00:00:00Z",
        },
        identifier_field="evidence_id",
        identifier_prefix="evidence",
    )
    return evidence_id


def _transcript(store: Store, job_id: str) -> str:
    evidence_id = _evidence(store, job_id)
    return transcript_save(
        store,
        job_id=job_id,
        evidence_ids=[evidence_id],
        cues=[{"start_ms": 1000, "end_ms": 2000, "text": "可靠字幕"}],
        text="可靠字幕",
        corrections=[],
        uncertainties=[],
        quality={"status": "verified", "reviewed_by": "agent"},
    )["transcript"]["transcript_id"]


def test_transcript_requires_registered_evidence_and_is_idempotent(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path)
    job, _ = store.create_job(
        source={"platform": "bilibili", "bvid": "BV1fixture"},
        idempotency_key="bilibili_BV1fixture_p1",
        initial_stage="evidence",
        initial_status="running",
    )
    evidence_id = _evidence(store, job["job_id"])
    first = transcript_save(
        store,
        job_id=job["job_id"],
        evidence_ids=[evidence_id],
        cues=[{"start_ms": 0, "end_ms": 1000, "text": "正文"}],
        text="正文",
        quality={"status": "verified"},
    )
    second = transcript_save(
        store,
        job_id=job["job_id"],
        evidence_ids=[evidence_id],
        cues=[{"start_ms": 0, "end_ms": 1000, "text": "正文"}],
        text="正文",
        quality={"status": "verified"},
    )
    assert first["transcript"]["schema_version"] == "video-content/transcript-v1"
    assert second["reused"] is True
    assert second["transcript"]["transcript_id"] == first["transcript"]["transcript_id"]


def test_transcript_rejects_continuous_hard_subtitles_without_ocr(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path)
    job, _ = store.create_job(
        source={"platform": "bilibili", "bvid": "BV1fixture"},
        idempotency_key="continuous_without_ocr",
        initial_stage="evidence",
        initial_status="retryable",
    )
    evidence_id = "evidence_without_ocr"
    store.save_document(
        job["job_id"],
        kind="evidence",
        document={
            "schema_version": "video-content/evidence-v1",
            "evidence_id": evidence_id,
            "job_id": job["job_id"],
            "source": {"platform": "bilibili"},
            "observations": [{"kind": "audio_asr"}],
            "artifact_refs": [],
            "decision": {"hard_subtitle_visual_decision": "continuous"},
            "created_at": "2026-08-17T00:00:00Z",
        },
        identifier_field="evidence_id",
        identifier_prefix="evidence",
    )
    with pytest.raises(ValueError, match="without full-video OCR"):
        transcript_save(
            store,
            job_id=job["job_id"],
            evidence_ids=[evidence_id],
            cues=[{"start_ms": 0, "end_ms": 1000, "text": "仅有 ASR"}],
            text="仅有 ASR",
            quality={"status": "usable"},
        )


def test_wechat_content_uses_only_cover_and_timestamped_frames(tmp_path: Path) -> None:
    store = Store(tmp_path / "home")
    job, _ = store.create_job(
        source={"platform": "bilibili", "bvid": "BV1fixture"},
        idempotency_key="bilibili_BV1fixture_p1",
        initial_stage="evidence",
        initial_status="running",
    )
    transcript_id = _transcript(store, job["job_id"])
    cover = tmp_path / "cover.jpg"
    frame = tmp_path / "frame.png"
    cover.write_bytes(b"cover")
    frame.write_bytes(b"frame")
    cover_ref = store.put_artifact(job["job_id"], kind="video_cover", source_path=cover)
    frame_ref = store.put_artifact(job["job_id"], kind="video_frame", source_path=frame)
    manuscript = {
        "schema_version": "video-content/wechat-manuscript-v1",
        "title": "从视频证据到一篇可信文章",
        "summary": "只使用原视频证据与画面。",
        "source": {
            "title": "测试视频",
            "creator": "测试作者",
            "canonical_url": "https://www.bilibili.com/video/BV1fixture",
        },
        "blocks": [
            {
                "type": "image",
                "artifact_id": cover_ref["artifact_id"],
                "source_kind": "video_cover",
            },
            {"type": "lead", "text": "这是开头。"},
            {
                "type": "image",
                "artifact_id": frame_ref["artifact_id"],
                "source_kind": "video_frame",
                "timestamp_ms": 42000,
            },
        ],
    }
    result = content_save(
        store,
        job_id=job["job_id"],
        transcript_id=transcript_id,
        carrier="wechat_article",
        document=manuscript,
        audit={"status": "passed", "reviewed_by": "agent"},
    )
    assert result["content"]["schema_version"] == "video-content/content-v1"
    assert result["validation"]["valid"] is True
    assert result["render"]["ok"] is True
    assert result["job"]["stage"] == "content"
    assert all(
        item["source_kind"] in {"video_cover", "video_frame"}
        for item in result["content"]["media"]
    )
    assert len(store.list_artifacts(job["job_id"], kind="content_render")) >= 4


def test_content_rejects_generated_images(tmp_path: Path) -> None:
    store = Store(tmp_path)
    job, _ = store.create_job(
        source={"platform": "bilibili"},
        idempotency_key="fixture_generated",
        initial_stage="evidence",
        initial_status="running",
    )
    transcript_id = _transcript(store, job["job_id"])
    image = tmp_path / "generated.png"
    image.write_bytes(b"generated")
    image_ref = store.put_artifact(job["job_id"], kind="generated", source_path=image)
    with pytest.raises(ValueError, match="non-source image"):
        content_save(
            store,
            job_id=job["job_id"],
            transcript_id=transcript_id,
            carrier="wechat_article",
            document={"blocks": []},
            media=[
                {"artifact_id": image_ref["artifact_id"], "source_kind": "generated"}
            ],
            audit={"status": "passed"},
            render=False,
        )
