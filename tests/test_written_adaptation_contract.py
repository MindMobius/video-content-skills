from __future__ import annotations

from pathlib import Path

from video_content.automation import save_watch_later_profile
from video_content.content import content_save, transcript_save
from video_content.store import Store


def _save_watch_later_content(
    tmp_path: Path,
    *,
    cue_texts: list[str],
    paragraph_texts: list[str],
) -> dict:
    store = Store(tmp_path / "home")
    save_watch_later_profile(
        store,
        profile_id="daily",
        account_profile_alias="fixture-browser",
    )
    job, _ = store.create_job(
        source={"platform": "bilibili", "bvid": "BV1written"},
        idempotency_key="bilibili_BV1written_p1",
        profile_id="daily",
        initial_stage="evidence",
        initial_status="running",
    )
    evidence_id = "evidence_written_adaptation"
    store.save_document(
        job["job_id"],
        kind="evidence",
        document={
            "schema_version": "video-content/evidence-v1",
            "evidence_id": evidence_id,
            "job_id": job["job_id"],
            "source": {"platform": "bilibili"},
            "observations": [],
            "artifact_refs": [],
            "decision": {},
            "created_at": "2026-08-25T00:00:00Z",
        },
        identifier_field="evidence_id",
        identifier_prefix="evidence",
    )
    cues = [
        {
            "start_ms": index * 1000,
            "end_ms": (index + 1) * 1000,
            "text": text,
        }
        for index, text in enumerate(cue_texts)
    ]
    transcript = transcript_save(
        store,
        job_id=job["job_id"],
        evidence_ids=[evidence_id],
        cues=cues,
        text="".join(cue_texts),
        quality={"status": "verified", "reviewed_by": "agent"},
    )["transcript"]

    cover_path = tmp_path / "cover.jpg"
    cover_path.write_bytes(b"cover")
    cover = store.put_artifact(
        job["job_id"], kind="video_cover", source_path=cover_path
    )
    frames: list[tuple[dict, int]] = []
    for index, timestamp_ms in enumerate((5000, 11000, 17000), start=1):
        frame_path = tmp_path / f"frame-{index}.jpg"
        frame_path.write_bytes(f"frame-{index}".encode())
        reference = store.put_artifact(
            job["job_id"],
            kind="video_frame",
            source_path=frame_path,
            metadata={"timestamp_ms": timestamp_ms},
        )
        frames.append((reference, timestamp_ms))

    blocks: list[dict] = [
        {
            "type": "image",
            "artifact_id": cover["artifact_id"],
            "source_kind": "video_cover",
        }
    ]
    material_items: list[dict] = []
    visual_plan: list[dict] = []
    cues_per_section = len(cue_texts) // len(paragraph_texts)
    for index, (paragraph, (frame, timestamp_ms)) in enumerate(
        zip(paragraph_texts, frames, strict=True)
    ):
        paragraph_index = len(blocks)
        blocks.append({"type": "paragraph", "text": paragraph})
        image_index = len(blocks)
        blocks.append(
            {
                "type": "image",
                "artifact_id": frame["artifact_id"],
                "source_kind": "video_frame",
                "timestamp_ms": timestamp_ms,
            }
        )
        source_start = index * cues_per_section
        source_end = (
            len(cue_texts)
            if index == len(paragraph_texts) - 1
            else (index + 1) * cues_per_section
        )
        material_items.append(
            {
                "section_id": f"section-{index + 1}",
                "label": f"第 {index + 1} 节",
                "source_cue_indices": list(range(source_start, source_end)),
                "output_block_indices": [paragraph_index, image_index],
                "status": "preserved",
            }
        )
        visual_plan.append(
            {
                "artifact_id": frame["artifact_id"],
                "timestamp_ms": timestamp_ms,
                "block_index": image_index,
                "reason": "对应本节论述的原视频画面",
            }
        )

    return content_save(
        store,
        job_id=job["job_id"],
        transcript_id=transcript["transcript_id"],
        carrier="wechat_article",
        document={
            "schema_version": "video-content/wechat-manuscript-v1",
            "title": "书面化质量测试",
            "summary": "验证逐条字幕不能冒充来源忠实书面稿。",
            "source": {
                "title": "测试视频",
                "creator": "测试作者",
                "canonical_url": "https://www.bilibili.com/video/BV1written",
            },
            "blocks": blocks,
        },
        audit={
            "status": "passed",
            "reviewed_by": "agent",
            "adaptation_mode": "source_faithful_full",
            "visual_policy": "source_frames_at_material_transitions",
            "material_sections": {
                "total": len(material_items),
                "preserved": len(material_items),
                "items": material_items,
            },
            "omissions": [],
            "visual_plan": visual_plan,
        },
        render=False,
    )


def test_source_faithful_content_rejects_mechanical_transcript_passthrough(
    tmp_path: Path,
) -> None:
    cue_texts = [
        f"第{index}段我们继续把字幕片段直接连在一起这里保留大量口语连接词"
        "然后没有真正修复句子边界也没有整理成适合阅读的书面表达"
        for index in range(18)
    ]
    paragraph_texts = [
        "".join(cue_texts[start : start + 6]) + "。"
        for start in range(0, len(cue_texts), 6)
    ]

    result = _save_watch_later_content(
        tmp_path,
        cue_texts=cue_texts,
        paragraph_texts=paragraph_texts,
    )

    assert result["validation"]["valid"] is False
    assert any(
        "raw Transcript passthrough" in error
        for error in result["validation"]["errors"]
    )


def test_source_faithful_content_allows_publication_ready_source_wording(
    tmp_path: Path,
) -> None:
    cue_texts = [
        f"第{index}段先说明问题。这里保留原有术语，也补足清晰的句子边界；"
        "因为来源本身已有成熟文稿，所以无需为了降低重合度而改写。"
        for index in range(18)
    ]
    paragraph_texts = [
        "".join(cue_texts[start : start + 6])
        for start in range(0, len(cue_texts), 6)
    ]

    result = _save_watch_later_content(
        tmp_path,
        cue_texts=cue_texts,
        paragraph_texts=paragraph_texts,
    )

    assert result["validation"]["valid"] is True
