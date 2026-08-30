from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from video_content.automation import save_watch_later_profile
from video_content.content import content_save, transcript_save
from video_content.store import Store


def _png_bytes(width: int, height: int, *, rgb: tuple[int, int, int]) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return (
            struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))
        )

    pixel = bytes(rgb)
    rows = b"".join(b"\x00" + (pixel * width) for _ in range(height))
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
            chunk(b"IDAT", zlib.compress(rows)),
            chunk(b"IEND", b""),
        )
    )


def _expression_audit(*, items: list[dict] | None = None) -> dict:
    return {
        "status": "passed",
        "reviewed_by": "agent",
        "policy": "source_aware_minimal",
        "reviewed_targets": [
            "title_summary",
            "headings",
            "transitions",
            "evidence_boundaries",
            "ending",
            "material_details",
        ],
        "checks": {
            "source_expression_priority": True,
            "information_density_preserved": True,
            "structure_and_media_preserved": True,
            "final_source_fidelity_rechecked": True,
        },
        "items": list(items or []),
    }


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


def test_wechat_content_revision_reuses_legacy_render_asset_metadata(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "home")
    job, _ = store.create_job(
        source={"platform": "bilibili", "bvid": "BV1legacyrender"},
        idempotency_key="bilibili_BV1legacyrender_p1",
        initial_stage="evidence",
        initial_status="running",
    )
    transcript_id = _transcript(store, job["job_id"])
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"same-rendered-cover")
    cover_ref = store.put_artifact(job["job_id"], kind="video_cover", source_path=cover)
    store.put_artifact(
        job["job_id"],
        kind="content_render",
        source_path=cover,
        metadata={
            "content_id": "content_legacy",
            "relative_path": "assets/01-legacy-cover.jpg",
        },
    )

    result = content_save(
        store,
        job_id=job["job_id"],
        transcript_id=transcript_id,
        carrier="wechat_article",
        document={
            "schema_version": "video-content/wechat-manuscript-v1",
            "title": "修订后的文章",
            "summary": "复用相同封面字节但绑定新的 Content。",
            "source": {
                "title": "测试视频",
                "creator": "测试作者",
                "canonical_url": "https://www.bilibili.com/video/BV1legacyrender",
            },
            "blocks": [
                {
                    "type": "image",
                    "artifact_id": cover_ref["artifact_id"],
                    "source_kind": "video_cover",
                },
                {"type": "paragraph", "text": "保留完整正文。"},
            ],
        },
        audit={"status": "passed", "reviewed_by": "agent"},
    )

    assert result["validation"]["valid"] is True
    assert any(
        reference.get("metadata", {}).get("content_id")
        == result["content"]["content_id"]
        for reference in result["content"]["artifact_refs"]
    )


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


def test_content_rejects_media_that_is_not_embedded_in_the_document(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path)
    job, _ = store.create_job(
        source={"platform": "bilibili"},
        idempotency_key="fixture_detached_media",
        initial_stage="evidence",
        initial_status="running",
    )
    transcript_id = _transcript(store, job["job_id"])
    cover_path = tmp_path / "cover.jpg"
    frame_path = tmp_path / "frame.png"
    cover_path.write_bytes(b"cover")
    frame_path.write_bytes(b"frame")
    cover = store.put_artifact(
        job["job_id"], kind="video_cover", source_path=cover_path
    )
    frame = store.put_artifact(
        job["job_id"],
        kind="video_frame",
        source_path=frame_path,
        metadata={"timestamp_ms": 1000},
    )

    with pytest.raises(ValueError, match="document image blocks"):
        content_save(
            store,
            job_id=job["job_id"],
            transcript_id=transcript_id,
            carrier="wechat_article",
            document={
                "blocks": [
                    {
                        "type": "image",
                        "artifact_id": cover["artifact_id"],
                        "source_kind": "video_cover",
                    },
                    {"type": "paragraph", "text": "正文没有插入视频截图。"},
                ]
            },
            media=[
                {
                    "artifact_id": cover["artifact_id"],
                    "source_kind": "video_cover",
                    "timestamp_ms": None,
                },
                {
                    "artifact_id": frame["artifact_id"],
                    "source_kind": "video_frame",
                    "timestamp_ms": 1000,
                },
            ],
            audit={"status": "passed"},
            render=False,
        )


def test_watch_later_content_requires_full_fidelity_audit_and_source_frames(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "home")
    save_watch_later_profile(
        store,
        profile_id="daily",
        account_profile_alias="fixture-browser",
    )
    job, _ = store.create_job(
        source={"platform": "bilibili", "bvid": "BV1fidelity"},
        idempotency_key="bilibili_BV1fidelity_p1",
        profile_id="daily",
        initial_stage="evidence",
        initial_status="running",
    )
    transcript_id = _transcript(store, job["job_id"])
    cover_path = tmp_path / "fidelity-cover.jpg"
    cover_path.write_bytes(b"cover")
    cover = store.put_artifact(
        job["job_id"], kind="video_cover", source_path=cover_path
    )
    source_video_path = tmp_path / "fidelity-source.mp4"
    source_video_path.write_bytes(b"source-video")
    source_video = store.put_artifact(
        job["job_id"], kind="source_video", source_path=source_video_path
    )
    frames = []
    for index, timestamp_ms in enumerate((10000, 20000, 30000), start=1):
        path = tmp_path / f"frame-{index}.png"
        path.write_bytes(_png_bytes(1600, 900, rgb=(32 + index, 64, 96)))
        reference = store.put_artifact(
            job["job_id"],
            kind="video_frame",
            source_path=path,
            metadata={
                "timestamp_ms": timestamp_ms,
                "extraction_role": "final",
                "extraction_method": "ffmpeg_source_frame",
                "resolution_policy": "source_display_native",
                "source_video_artifact_id": source_video["artifact_id"],
                "source_video_sha256": source_video["sha256"],
                "pixel_width": 1600,
                "pixel_height": 900,
                "display_aspect_preserved": True,
            },
        )
        frames.append((reference, timestamp_ms))
    blocks = [
        {
            "type": "image",
            "artifact_id": cover["artifact_id"],
            "source_kind": "video_cover",
        },
    ]
    for index, (reference, timestamp_ms) in enumerate(frames, start=1):
        blocks.extend(
            [
                {"type": "paragraph", "text": f"保留第 {index} 个实质论述。"},
                {
                    "type": "image",
                    "artifact_id": reference["artifact_id"],
                    "source_kind": "video_frame",
                    "timestamp_ms": timestamp_ms,
                },
            ]
        )
    material_sections = {
        "total": 3,
        "preserved": 3,
        "items": [
            {
                "section_id": f"section-{index}",
                "label": f"第 {index} 个实质论述",
                "source_cue_indices": [0],
                "output_block_indices": [index * 2 - 1, index * 2],
                "status": "preserved",
            }
            for index in range(1, 4)
        ],
    }
    result = content_save(
        store,
        job_id=job["job_id"],
        transcript_id=transcript_id,
        carrier="wechat_article",
        document={
            "schema_version": "video-content/wechat-manuscript-v1",
            "title": "忠实完整稿",
            "summary": "保留专业细节并在论述节点使用原视频画面。",
            "source": {
                "title": "测试视频",
                "creator": "测试作者",
                "canonical_url": "https://www.bilibili.com/video/BV1fidelity",
            },
            "blocks": blocks,
        },
        audit={
            "status": "passed",
            "reviewed_by": "agent",
            "adaptation_mode": "source_faithful_full",
            "visual_policy": "source_frames_at_material_transitions",
            "material_sections": material_sections,
            "omissions": [],
            "visual_plan": [
                {
                    "artifact_id": reference["artifact_id"],
                    "timestamp_ms": timestamp_ms,
                    "block_index": index * 2,
                    "reason": "对应原视频中的实质论述节点",
                }
                for index, (reference, timestamp_ms) in enumerate(frames, start=1)
            ],
            "expression_audit": _expression_audit(),
        },
    )
    assert result["validation"]["valid"] is True

    stale_text = content_save(
        store,
        job_id=job["job_id"],
        transcript_id=transcript_id,
        carrier="wechat_article",
        document=result["content"]["document"],
        audit={
            **result["content"]["audit"],
            "expression_audit": _expression_audit(
                items=[
                    {
                        "target": {"field": "title"},
                        "rule": "carrier_template",
                        "decision": "revised",
                        "origin": "agent_added",
                        "before": "先把话说清：忠实完整稿",
                        "after": "已经过期的旧标题",
                        "reason": "审校记录必须绑定最终标题，不能沿用旧稿文本",
                    }
                ]
            ),
        },
        render=False,
    )
    assert stale_text["validation"]["valid"] is False
    assert any(
        "expression_audit" in error and "final document" in error
        for error in stale_text["validation"]["errors"]
    )

    invalid_block = content_save(
        store,
        job_id=job["job_id"],
        transcript_id=transcript_id,
        carrier="wechat_article",
        document=result["content"]["document"],
        audit={
            **result["content"]["audit"],
            "expression_audit": _expression_audit(
                items=[
                    {
                        "target": {"field": "block", "block_index": 999},
                        "rule": "empty_signpost",
                        "decision": "revised",
                        "origin": "agent_added",
                        "before": "先把话说清，保留第 1 个实质论述。",
                        "after": "保留第 1 个实质论述。",
                        "reason": "故意使用不存在的 block，验证索引必须指向真实正文",
                    }
                ]
            ),
        },
        render=False,
    )
    assert invalid_block["validation"]["valid"] is False
    assert any(
        "expression_audit" in error and "block_index" in error
        for error in invalid_block["validation"]["errors"]
    )

    counts_only = content_save(
        store,
        job_id=job["job_id"],
        transcript_id=transcript_id,
        carrier="wechat_article",
        document={
            "schema_version": "video-content/wechat-manuscript-v1",
            "title": "只有数量没有追溯映射",
            "summary": "该稿件故意只声明数量。",
            "source": {
                "title": "测试视频",
                "creator": "测试作者",
                "canonical_url": "https://www.bilibili.com/video/BV1fidelity",
            },
            "blocks": blocks,
        },
        audit={
            "status": "passed",
            "reviewed_by": "agent",
            "adaptation_mode": "source_faithful_full",
            "visual_policy": "source_frames_at_material_transitions",
            "material_sections": {"total": 3, "preserved": 3},
            "omissions": [],
            "visual_plan": [
                {
                    "artifact_id": reference["artifact_id"],
                    "timestamp_ms": timestamp_ms,
                    "block_index": index * 2,
                    "reason": "对应原视频中的实质论述节点",
                }
                for index, (reference, timestamp_ms) in enumerate(frames, start=1)
            ],
            "expression_audit": _expression_audit(),
        },
        render=False,
    )
    assert counts_only["validation"]["valid"] is False
    assert any(
        "material_sections.items" in error
        for error in counts_only["validation"]["errors"]
    )

    wrong_placement = content_save(
        store,
        job_id=job["job_id"],
        transcript_id=transcript_id,
        carrier="wechat_article",
        document={
            "schema_version": "video-content/wechat-manuscript-v1",
            "title": "截图计划没有对应正文位置",
            "summary": "该稿件故意把截图计划指向正文段落。",
            "source": {
                "title": "测试视频",
                "creator": "测试作者",
                "canonical_url": "https://www.bilibili.com/video/BV1fidelity",
            },
            "blocks": blocks,
        },
        audit={
            "status": "passed",
            "reviewed_by": "agent",
            "adaptation_mode": "source_faithful_full",
            "visual_policy": "source_frames_at_material_transitions",
            "material_sections": material_sections,
            "omissions": [],
            "visual_plan": [
                {
                    "artifact_id": reference["artifact_id"],
                    "timestamp_ms": timestamp_ms,
                    "block_index": index * 2 - 1,
                    "reason": "故意指向错误的正文位置",
                }
                for index, (reference, timestamp_ms) in enumerate(frames, start=1)
            ],
            "expression_audit": _expression_audit(),
        },
        render=False,
    )
    assert wrong_placement["validation"]["valid"] is False
    assert any(
        "does not point to its document image block" in error
        for error in wrong_placement["validation"]["errors"]
    )

    invalid = content_save(
        store,
        job_id=job["job_id"],
        transcript_id=transcript_id,
        carrier="wechat_article",
        document={
            "schema_version": "video-content/wechat-manuscript-v1",
            "title": "缺少视觉计划的稿件",
            "summary": "该稿件故意缺少契约字段。",
            "source": {
                "title": "测试视频",
                "creator": "测试作者",
                "canonical_url": "https://www.bilibili.com/video/BV1fidelity",
            },
            "blocks": blocks[:2],
        },
        audit={"status": "passed", "reviewed_by": "agent"},
        render=False,
    )
    assert invalid["validation"]["valid"] is False
    assert any(
        "source_faithful_full" in error
        or "minimum_source_frames" in error
        or "material_sections" in error
        for error in invalid["validation"]["errors"]
    )

    scout_path = tmp_path / "static-source-contact-sheet.png"
    scout_path.write_bytes(b"static-contact-sheet")
    scout = store.put_artifact(
        job["job_id"], kind="ocr_scout_contact_sheet", source_path=scout_path
    )
    static_source = content_save(
        store,
        job_id=job["job_id"],
        transcript_id=transcript_id,
        carrier="wechat_article",
        document={
            "schema_version": "video-content/wechat-manuscript-v1",
            "title": "静态播客画面",
            "summary": "来源经侦察确认没有可用于正文的实质画面变化。",
            "source": {
                "title": "静态播客",
                "creator": "测试作者",
                "canonical_url": "https://www.bilibili.com/video/BV1fidelity",
            },
            "blocks": [
                {
                    "type": "image",
                    "artifact_id": cover["artifact_id"],
                    "source_kind": "video_cover",
                },
                {"type": "paragraph", "text": "正文仍保留完整讨论。"},
            ],
        },
        audit={
            "status": "passed",
            "reviewed_by": "agent",
            "adaptation_mode": "source_faithful_full",
            "visual_policy": "source_frames_at_material_transitions",
            "material_sections": {
                "total": 1,
                "preserved": 1,
                "items": [
                    {
                        "section_id": "section-1",
                        "label": "完整讨论",
                        "source_cue_indices": [0],
                        "output_block_indices": [1],
                        "status": "preserved",
                    }
                ],
            },
            "omissions": [],
            "visual_plan": [],
            "visual_exception": {
                "approved": True,
                "reason": "Source scout proved a static podcast cover with no material visual transitions.",
                "evidence_artifact_ids": [scout["artifact_id"]],
            },
            "expression_audit": _expression_audit(),
        },
        render=False,
    )
    assert static_source["validation"]["valid"] is True
