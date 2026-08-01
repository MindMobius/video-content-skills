from pathlib import Path

import pytest

from video_subtitle.core.review import (
    ReviewOptions,
    get_review_window,
    prepare_review_for_manifest,
    submit_review_window,
)
from video_subtitle.core.srt import Cue, parse_srt, write_srt
from video_subtitle.core.util import read_json, write_json_atomic


def _review_manifest(tmp_path: Path) -> Path:
    ocr_path = tmp_path / "subtitle.ocr.srt"
    primary_path = tmp_path / "subtitle.ocr.primary.srt"
    validation_path = tmp_path / "subtitle.ocr.validation.srt"
    asr_path = tmp_path / "subtitle.asr.srt"
    ocr_cues = [
        Cue(1_000, 3_000, "这是结论"),
        Cue(5_000, 6_000, "spin up reach out"),
        Cue(7_000, 8_000, "spin up reach out"),
        Cue(9_000, 10_000, "spin up reach out"),
        Cue(31_000, 33_000, "吉论是"),
    ]
    write_srt(ocr_path, ocr_cues)
    write_srt(primary_path, ocr_cues)
    write_srt(
        validation_path,
        [
            Cue(1_000, 3_000, "这是结论"),
            Cue(5_000, 6_000, "spin up reach out"),
            Cue(7_000, 8_000, "spin up reach out"),
            Cue(9_000, 10_000, "spin up reach out"),
            Cue(31_000, 33_000, "结论是"),
        ],
    )
    write_srt(
        asr_path,
        [
            Cue(1_000, 4_000, "This is the conclusion."),
            Cue(5_000, 10_000, "Use simple verbs."),
            Cue(20_000, 24_000, "This complete sentence is missing from OCR."),
            Cue(31_000, 34_000, "So the verdict is clear."),
        ],
    )
    manifest = {
        "schema_version": "video-subtitle/v1",
        "job_id": "sub_review_test",
        "status": "completed",
        "stage": "done",
        "updated_at": "2026-08-01T00:00:00Z",
        "request": {"language": "ai-zh", "videocr": {"language": "ch"}},
        "video": {
            "bvid": "BV1review",
            "series_title": "跨语言字幕测试",
            "description": "verdict means 结论",
        },
        "selected_source": {
            "kind": "evidence_bundle",
            "primary": {"kind": "hard_ocr"},
            "fusion_status": "independent_evidence",
        },
        "sources": [
            {
                "kind": "hard_ocr",
                "artifact_source": "hard_ocr:videocr",
                "cue_count": len(ocr_cues),
            },
            {
                "kind": "audio_asr",
                "artifact_source": "audio_asr:qwen3",
                "cue_count": 4,
                "detected_languages": ["English"],
            },
        ],
        "artifacts": [
            {
                "kind": "subtitle_srt",
                "path": str(ocr_path),
                "source": "hard_ocr:videocr",
                "owned_by_job": True,
                "selected": True,
            },
            {
                "kind": "ocr_primary_srt",
                "path": str(primary_path),
                "source": "hard_ocr:videocr",
                "owned_by_job": True,
            },
            {
                "kind": "ocr_validation_srt",
                "path": str(validation_path),
                "source": "hard_ocr:videocr",
                "owned_by_job": True,
            },
            {
                "kind": "subtitle_srt",
                "path": str(asr_path),
                "source": "audio_asr:qwen3",
                "owned_by_job": True,
            },
        ],
        "warnings": [],
        "error": None,
    }
    write_json_atomic(
        tmp_path / "evidence.index.json",
        {"schema_version": "video-subtitle/evidence-v1"},
    )
    (tmp_path / "evidence.index.md").write_text(
        "# 字幕证据索引\n",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.json"
    write_json_atomic(manifest_path, manifest)
    return manifest_path


def test_prepare_review_packet_detects_cross_language_scene_text(
    tmp_path: Path,
) -> None:
    manifest_path = _review_manifest(tmp_path)
    raw_before = (tmp_path / "subtitle.ocr.srt").read_bytes()

    result = prepare_review_for_manifest(
        manifest_path,
        options=ReviewOptions(window_seconds=30),
    )

    assert result["review"]["mode"] == "cross_language"
    assert result["review"]["window_count"] == 2
    packet = read_json(tmp_path / "review.packet.json")
    assert packet["algorithm_version"] == "time-window-cross-language-v2"
    assert packet["statistics"]["repeated_visual_phrases"] == [
        {"phrase": "spin up", "cue_count": 3},
        {"phrase": "up reach", "cue_count": 3},
        {"phrase": "reach out", "cue_count": 3},
    ]
    first_window = get_review_window(manifest_path, "rw-0001")["window"]
    assert first_window["priority"] == "high"
    assert "repeated_latin_scene_text" in first_window["reasons"]
    assert "asr_speech_low_ocr_coverage" in first_window["reasons"]
    assert any(
        flag["code"] == "asr_speech_low_ocr_coverage"
        for cue in first_window["corroborating_cues"]
        for flag in cue["flags"]
    )
    assert (tmp_path / "subtitle.ocr.srt").read_bytes() == raw_before


def test_agent_review_applies_only_high_confidence_and_preserves_raw(
    tmp_path: Path,
) -> None:
    manifest_path = _review_manifest(tmp_path)
    prepare_review_for_manifest(manifest_path)
    raw_before = (tmp_path / "subtitle.ocr.srt").read_bytes()

    first = submit_review_window(
        manifest_path,
        window_id="rw-0001",
        decisions=[
            {"cue_id": "ocr-0001", "action": "keep"},
            *[
                {
                    "cue_id": f"ocr-{index:04d}",
                    "action": "delete",
                    "confidence": "high",
                    "reason": "Repeated slide text is absent from the matching speech",
                    "evidence": ["repeated_latin_scene_text", "asr-0002"],
                }
                for index in range(2, 5)
            ],
            {
                "action": "insert",
                "start_ms": 20_000,
                "end_ms": 24_000,
                "confidence": "high",
                "reviewed_text": "漏掉的完整句子",
                "reason": "ASR contains a complete sentence with no OCR coverage",
                "evidence": ["asr-0003"],
            },
        ],
    )
    assert first["review"]["status"] == "in_progress"

    final = submit_review_window(
        manifest_path,
        window_id="rw-0002",
        decisions=[
            {
                "cue_id": "ocr-0005",
                "action": "replace",
                "confidence": "high",
                "reviewed_text": "结论是",
                "reason": "ASR verdict and validation OCR both support 结论",
                "evidence": ["asr-0004", "ocr_validation"],
            }
        ],
    )

    assert final["review"]["status"] == "complete"
    assert final["review"]["applied_change_count"] == 5
    reviewed = parse_srt(tmp_path / "subtitle.reviewed.srt")
    assert [cue.text for cue in reviewed] == [
        "这是结论",
        "漏掉的完整句子",
        "结论是",
    ]
    assert (tmp_path / "subtitle.ocr.srt").read_bytes() == raw_before
    manifest = read_json(manifest_path)
    assert manifest["selected_source"]["fusion_status"] == "agent_review_complete"
    assert any(
        artifact.get("kind") == "reviewed_subtitle_srt"
        and artifact.get("selected") is True
        for artifact in manifest["artifacts"]
    )
    reused = prepare_review_for_manifest(manifest_path)
    assert reused["reused_existing_review"] is True
    assert reused["review"]["status"] == "complete"


def test_medium_confidence_change_is_recorded_but_not_applied(tmp_path: Path) -> None:
    manifest_path = _review_manifest(tmp_path)
    prepare_review_for_manifest(manifest_path)

    result = submit_review_window(
        manifest_path,
        window_id="rw-0002",
        decisions=[
            {
                "cue_id": "ocr-0005",
                "action": "replace",
                "confidence": "medium",
                "reviewed_text": "结论是",
                "reason": "Plausible semantic repair",
                "evidence": ["asr-0004"],
            }
        ],
    )

    assert result["review"]["status"] == "in_progress"
    assert parse_srt(tmp_path / "subtitle.reviewed.srt")[-1].text == "吉论是"
    report = read_json(tmp_path / "review.report.json")
    assert report["unresolved"][0]["proposed_text"] == "结论是"


def test_review_rejects_stale_original_text(tmp_path: Path) -> None:
    manifest_path = _review_manifest(tmp_path)
    prepare_review_for_manifest(manifest_path)

    with pytest.raises(ValueError, match="no longer matches"):
        submit_review_window(
            manifest_path,
            window_id="rw-0002",
            decisions=[
                {
                    "cue_id": "ocr-0005",
                    "action": "replace",
                    "original_text": "旧文本",
                    "reviewed_text": "结论是",
                    "reason": "test",
                }
            ],
        )


def test_review_rejects_insertion_overlapping_retained_cue(tmp_path: Path) -> None:
    manifest_path = _review_manifest(tmp_path)
    prepare_review_for_manifest(manifest_path)

    with pytest.raises(ValueError, match="overlaps retained cue"):
        submit_review_window(
            manifest_path,
            window_id="rw-0001",
            decisions=[
                {
                    "action": "insert",
                    "start_ms": 2_000,
                    "end_ms": 4_000,
                    "reviewed_text": "重叠字幕",
                    "reason": "test",
                }
            ],
        )
