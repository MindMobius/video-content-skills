from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from video_content.automation import save_watch_later_profile
from video_content.content import content_save, transcript_save
from video_content.store import Store
from video_content.wechat import wechat_prepare


def _png_bytes(
    width: int, height: int, *, rgb: tuple[int, int, int] = (32, 64, 96)
) -> bytes:
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


def _save_watch_later_content(
    tmp_path: Path,
    *,
    cue_texts: list[str],
    paragraph_texts: list[str],
    include_expression_audit: bool = True,
    expression_items: list[dict] | None = None,
    frame_extraction_role: str = "final",
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
    source_video_path = tmp_path / "source.mp4"
    source_video_path.write_bytes(b"source-video")
    source_video = store.put_artifact(
        job["job_id"], kind="source_video", source_path=source_video_path
    )
    frames: list[tuple[dict, int]] = []
    for index, timestamp_ms in enumerate((5000, 11000, 17000), start=1):
        frame_path = tmp_path / f"frame-{index}.png"
        frame_path.write_bytes(_png_bytes(1600, 900, rgb=(32 + index, 64, 96)))
        metadata = {
            "timestamp_ms": timestamp_ms,
            "extraction_role": frame_extraction_role,
            "extraction_method": (
                "ffmpeg_source_frame"
                if frame_extraction_role == "final"
                else "deterministic_scout"
            ),
            "resolution_policy": (
                "source_display_native"
                if frame_extraction_role == "final"
                else "scout_preview"
            ),
            "source_video_artifact_id": source_video["artifact_id"],
            "source_video_sha256": source_video["sha256"],
            "pixel_width": 1600,
            "pixel_height": 900,
            "display_aspect_preserved": frame_extraction_role == "final",
        }
        reference = store.put_artifact(
            job["job_id"],
            kind="video_frame",
            source_path=frame_path,
            metadata=metadata,
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

    audit = {
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
    }
    if include_expression_audit:
        audit["expression_audit"] = _expression_audit(items=expression_items)

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
        audit=audit,
        render=False,
    )


def test_source_faithful_content_rejects_scout_preview_frames(tmp_path: Path) -> None:
    cue_texts = [
        f"第{index}段完整说明论点、例子和限定条件。"
        "来源本身已有清晰结构，文章按实质章节保留并完成书面化。"
        for index in range(18)
    ]
    paragraph_texts = [
        "".join(cue_texts[start : start + 6]) for start in range(0, len(cue_texts), 6)
    ]

    result = _save_watch_later_content(
        tmp_path,
        cue_texts=cue_texts,
        paragraph_texts=paragraph_texts,
        frame_extraction_role="scout",
    )

    assert result["validation"]["valid"] is False
    assert any(
        "final source extraction" in error for error in result["validation"]["errors"]
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

    store = Store(tmp_path / "home")
    content = result["content"]
    with pytest.raises(ValueError, match="validated content"):
        wechat_prepare(
            store,
            job_id=content["job_id"],
            content_id=content["content_id"],
            authorized=True,
            save_draft=True,
        )
    assert store.get_job(content["job_id"])["stage"] == "content"


def test_source_faithful_content_requires_expression_audit(tmp_path: Path) -> None:
    cue_texts = [
        f"第{index}段先说明问题。这里保留原有术语，也补足清晰的句子边界；"
        "因为来源本身已有成熟文稿，所以无需为了降低重合度而改写。"
        for index in range(18)
    ]
    paragraph_texts = [
        "".join(cue_texts[start : start + 6]) for start in range(0, len(cue_texts), 6)
    ]

    result = _save_watch_later_content(
        tmp_path,
        cue_texts=cue_texts,
        paragraph_texts=paragraph_texts,
        include_expression_audit=False,
    )

    assert result["validation"]["valid"] is False
    assert any("expression_audit" in error for error in result["validation"]["errors"])


def test_expression_audit_rejects_rewriting_source_expression(
    tmp_path: Path,
) -> None:
    cue_texts = [
        f"第{index}段先说明问题。这里保留原有术语，也补足清晰的句子边界；"
        "因为来源本身已有成熟文稿，所以无需为了降低重合度而改写。"
        for index in range(18)
    ]
    paragraph_texts = [
        "".join(cue_texts[start : start + 6]) for start in range(0, len(cue_texts), 6)
    ]

    result = _save_watch_later_content(
        tmp_path,
        cue_texts=cue_texts,
        paragraph_texts=paragraph_texts,
        expression_items=[
            {
                "target": {"field": "title"},
                "rule": "carrier_template",
                "decision": "revised",
                "origin": "source_expression",
                "before": "来源作者自己的标题",
                "after": "书面化质量测试",
                "reason": "故意把来源表达标成可改写，验证程序必须拒绝",
            }
        ],
    )

    assert result["validation"]["valid"] is False
    assert any("source_expression" in error for error in result["validation"]["errors"])


def test_expression_audit_rejects_malformed_contract_values(tmp_path: Path) -> None:
    cue_texts = [
        f"第{index}段先说明问题。这里保留原有术语，也补足清晰的句子边界；"
        "因为来源本身已有成熟文稿，所以无需为了降低重合度而改写。"
        for index in range(18)
    ]
    paragraph_texts = [
        "".join(cue_texts[start : start + 6]) for start in range(0, len(cue_texts), 6)
    ]

    result = _save_watch_later_content(
        tmp_path,
        cue_texts=cue_texts,
        paragraph_texts=paragraph_texts,
        expression_items=[
            {
                "target": {"field": []},
                "rule": [],
                "decision": {},
                "origin": [],
                "before": "旧文本",
                "after": "书面化质量测试",
                "reason": "故意使用错误类型，验证器应返回错误而不是崩溃",
            }
        ],
    )

    assert result["validation"]["valid"] is False
    assert any(
        "expression_audit.items[0]" in error for error in result["validation"]["errors"]
    )


def test_expression_audit_allows_source_retention_and_minimal_agent_revision(
    tmp_path: Path,
) -> None:
    cue_texts = [
        f"第{index}段先说明问题。这里保留原有术语，也补足清晰的句子边界；"
        "因为来源本身已有成熟文稿，所以无需为了降低重合度而改写。"
        for index in range(18)
    ]
    paragraph_texts = [
        "".join(cue_texts[start : start + 6]) for start in range(0, len(cue_texts), 6)
    ]

    result = _save_watch_later_content(
        tmp_path,
        cue_texts=cue_texts,
        paragraph_texts=paragraph_texts,
        expression_items=[
            {
                "target": {"field": "title"},
                "rule": "manufactured_contrast",
                "decision": "retained",
                "origin": "source_expression",
                "before": "书面化质量测试",
                "after": "书面化质量测试",
                "reason": "该标题来自来源表达，没有人为制造对照，明确保留",
            },
            {
                "target": {"field": "summary"},
                "rule": "empty_signpost",
                "decision": "revised",
                "origin": "agent_added",
                "before": "一句话总结：验证逐条字幕不能冒充来源忠实书面稿。",
                "after": "验证逐条字幕不能冒充来源忠实书面稿。",
                "reason": "删除 Agent 新增的空转提示语，保留原有结论",
            },
        ],
    )

    assert result["validation"]["valid"] is True


def test_source_faithful_content_allows_publication_ready_source_wording(
    tmp_path: Path,
) -> None:
    cue_texts = [
        f"第{index}段先说明问题。这里保留原有术语，也补足清晰的句子边界；"
        "因为来源本身已有成熟文稿，所以无需为了降低重合度而改写。"
        for index in range(18)
    ]
    paragraph_texts = [
        "".join(cue_texts[start : start + 6]) for start in range(0, len(cue_texts), 6)
    ]

    result = _save_watch_later_content(
        tmp_path,
        cue_texts=cue_texts,
        paragraph_texts=paragraph_texts,
    )

    assert result["validation"]["valid"] is True
