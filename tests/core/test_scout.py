from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from video_content.scout import plan_hard_subtitle_scout

SCHEMA_PATH = Path(__file__).parents[2] / "schemas" / "ocr-scout-plan.schema.json"


def test_default_scout_samples_five_spread_windows() -> None:
    plan = plan_hard_subtitle_scout(3600, window_seconds=20)

    assert plan["window_count"] == 5
    assert plan["coverage_seconds"] == 100
    assert plan["coverage_ratio"] == round(100 / 3600, 6)
    assert plan["windows"][0] == {
        "window_id": "scout-001",
        "start_ms": 0,
        "end_ms": 20_000,
        "duration_seconds": 20.0,
        "time_start": "00:00:00.000",
        "time_end": "00:00:20.000",
        "anchors": [0.0],
        "labels": ["opening"],
    }
    assert plan["windows"][-1]["start_ms"] == 3_580_000
    assert plan["windows"][-1]["end_ms"] == 3_600_000
    assert "low cue count" in plan["decision_boundary"]["instruction"]
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(plan, schema)


def test_scout_merges_overlapping_windows_for_short_video() -> None:
    plan = plan_hard_subtitle_scout(60, window_seconds=20)

    assert plan["raw_window_count"] == 5
    assert plan["window_count"] == 1
    assert plan["coverage_seconds"] == 60
    assert plan["coverage_ratio"] == 1
    assert plan["estimated_full_ocr_savings_ratio"] == 0
    assert plan["windows"][0]["labels"] == [
        "opening",
        "quarter",
        "middle",
        "three_quarters",
        "ending",
    ]


def test_scout_accepts_custom_deduplicated_anchors() -> None:
    plan = plan_hard_subtitle_scout(
        100,
        window_seconds=10,
        anchors=[0.1, 0.1, 0.9],
    )

    assert plan["requested_anchors"] == [0.1, 0.9]
    assert plan["window_count"] == 2
    assert plan["windows"][0]["time_start"] == "00:00:05.000"
    assert plan["windows"][1]["time_end"] == "00:01:35.000"


@pytest.mark.parametrize(
    ("duration", "window", "anchors"),
    [
        (0, 20, None),
        (60, 0, None),
        (60, 20, []),
        (60, 20, [-0.1]),
        (60, 20, [1.1]),
    ],
)
def test_scout_rejects_invalid_ranges(duration, window, anchors) -> None:
    with pytest.raises(ValueError):
        plan_hard_subtitle_scout(duration, window_seconds=window, anchors=anchors)
