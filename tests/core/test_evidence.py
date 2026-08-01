from pathlib import Path

import pytest

from video_subtitle.core.evidence import (
    list_subtitle_evidence_for_manifest,
    read_subtitle_evidence_range,
)
from video_subtitle.core.srt import Cue, write_srt
from video_subtitle.core.util import write_json_atomic


def _manifest(tmp_path: Path) -> Path:
    ocr_path = tmp_path / "subtitle.ocr.srt"
    asr_path = tmp_path / "subtitle.asr.srt"
    write_srt(
        ocr_path,
        [
            Cue(1_000, 2_000, "第一句"),
            Cue(3_000, 4_000, "第二句"),
            Cue(5_000, 6_000, "第三句"),
        ],
    )
    write_srt(
        asr_path,
        [Cue(1_100, 2_100, "First sentence")],
    )
    manifest_path = tmp_path / "manifest.json"
    write_json_atomic(
        manifest_path,
        {
            "schema_version": "video-subtitle/v1",
            "job_id": "sub_evidence",
            "status": "completed",
            "video": {"bvid": "BV1evidence", "duration_seconds": 10},
            "selected_source": {"kind": "hard_ocr"},
            "sources": [
                {
                    "kind": "hard_ocr",
                    "artifact_source": "hard_ocr:videocr",
                    "cue_count": 3,
                },
                {
                    "kind": "audio_asr",
                    "artifact_source": "audio_asr:qwen3",
                    "cue_count": 1,
                },
            ],
            "review": None,
            "artifacts": [
                {
                    "kind": "subtitle_srt",
                    "source": "hard_ocr:videocr",
                    "path": str(ocr_path),
                    "owned_by_job": True,
                    "selected": True,
                    "cue_count": 3,
                },
                {
                    "kind": "subtitle_srt",
                    "source": "audio_asr:qwen3",
                    "path": str(asr_path),
                    "owned_by_job": True,
                    "cue_count": 1,
                },
                {
                    "kind": "process_log",
                    "source": "videocr",
                    "path": str(tmp_path / "ocr.log"),
                    "owned_by_job": True,
                },
            ],
        },
    )
    return manifest_path


def test_list_evidence_exposes_agent_selectable_sources(tmp_path: Path) -> None:
    manifest_path = _manifest(tmp_path)

    result = list_subtitle_evidence_for_manifest(manifest_path)

    assert result["schema_version"] == "video-subtitle/evidence-catalog-v1"
    assert [item["evidence_id"] for item in result["evidence"]] == [
        "ev-0001",
        "ev-0002",
    ]
    assert result["evidence"][0]["source_kind"] == "hard_ocr"
    assert result["evidence"][0]["selected"] is True
    assert result["evidence"][1]["source_kind"] == "audio_asr"


def test_read_evidence_uses_agent_selected_time_range(tmp_path: Path) -> None:
    manifest_path = _manifest(tmp_path)

    result = read_subtitle_evidence_range(
        manifest_path,
        evidence_id="ev-0001",
        start_ms=2_500,
        end_ms=5_100,
    )

    assert [cue["text"] for cue in result["cues"]] == ["第二句", "第三句"]
    assert result["cues"][0]["cue_id"] == "ev-0001-cue-00002"
    assert result["matching_cue_count"] == 2
    assert result["has_more"] is False


def test_read_evidence_is_bounded_and_returns_resume_timestamp(
    tmp_path: Path,
) -> None:
    manifest_path = _manifest(tmp_path)

    result = read_subtitle_evidence_range(
        manifest_path,
        evidence_id="ev-0001",
        max_cues=2,
    )

    assert result["returned_cue_count"] == 2
    assert result["has_more"] is True
    assert result["next_start_ms"] == 5_000


def test_read_evidence_rejects_paths_outside_job_directory(tmp_path: Path) -> None:
    manifest_path = _manifest(tmp_path)
    outside = tmp_path.parent / "outside.srt"
    write_srt(outside, [Cue(0, 1_000, "outside")])
    manifest = {
        "schema_version": "video-subtitle/v1",
        "job_id": "sub_outside",
        "status": "completed",
        "sources": [],
        "artifacts": [
            {
                "kind": "subtitle_srt",
                "source": "external",
                "path": str(outside),
                "owned_by_job": False,
            }
        ],
    }
    write_json_atomic(manifest_path, manifest)

    catalog = list_subtitle_evidence_for_manifest(manifest_path)
    assert catalog["evidence"][0]["available"] is False
    assert "outside" in catalog["evidence"][0]["path_error"]
    with pytest.raises(ValueError, match="outside the job directory"):
        read_subtitle_evidence_range(
            manifest_path,
            evidence_id="ev-0001",
        )


@pytest.mark.parametrize(
    ("start_ms", "end_ms", "max_cues", "message"),
    [
        (-1, None, 10, "start_ms"),
        (5_000, 5_000, 10, "end_ms"),
        (0, None, 0, "max_cues"),
    ],
)
def test_read_evidence_validates_bounds(
    tmp_path: Path,
    start_ms: int,
    end_ms: int | None,
    max_cues: int,
    message: str,
) -> None:
    manifest_path = _manifest(tmp_path)
    with pytest.raises(ValueError, match=message):
        read_subtitle_evidence_range(
            manifest_path,
            evidence_id="ev-0001",
            start_ms=start_ms,
            end_ms=end_ms,
            max_cues=max_cues,
        )
