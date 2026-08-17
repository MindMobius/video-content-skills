from pathlib import Path

import pytest

from video_content.srt import (
    Cue,
    format_srt_time,
    parse_srt,
    platform_rows_to_cues,
    reconcile_cross_scale_cues,
    write_srt,
)


def test_platform_rows_round_to_milliseconds() -> None:
    cues = platform_rows_to_cues(
        [
            {"from": "3.06s", "to": "5.981s", "content": "第一句"},
            {"from": 6, "to": 7.2, "content": "第二句"},
        ]
    )
    assert cues == [
        Cue(start_ms=3060, end_ms=5981, text="第一句"),
        Cue(start_ms=6000, end_ms=7200, text="第二句"),
    ]


def test_srt_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "subtitle.srt"
    expected = [
        Cue(0, 1234, "Hello"),
        Cue(3_661_001, 3_662_999, "多行\n字幕"),
    ]
    write_srt(path, expected)
    assert parse_srt(path) == expected
    assert "01:01:01,001" in path.read_text(encoding="utf-8")


def test_invalid_reverse_timing_is_rejected() -> None:
    with pytest.raises(ValueError, match="end precedes start"):
        platform_rows_to_cues([{"from": 2, "to": 1, "content": "bad"}])


def test_format_srt_time() -> None:
    assert format_srt_time(3_726_045) == "01:02:06,045"


def test_cross_scale_consensus_removes_overlapping_ui_text() -> None:
    primary = [
        Cue(1_000, 4_000, "高分辨率字幕"),
        Cue(4_000, 7_000, "README 中的界面小字\n开始执行即可"),
        Cue(7_000, 10_000, "中间如果遇到问题，codex会向你解释"),
    ]
    validation = [
        Cue(1_000, 4_000, "高分辨率字慕"),
        Cue(4_000, 7_000, "开始执行即可"),
        Cue(7_000, 10_000, "中间如果遇到问题，codex会向你解释"),
    ]

    reconciled, metrics = reconcile_cross_scale_cues(primary, validation)

    assert [cue.text for cue in reconciled] == [
        "高分辨率字幕",
        "开始执行即可",
        "中间如果遇到问题，codex会向你解释",
    ]
    assert metrics["strategy"] == "cross_scale_consensus"
    assert metrics["primary_line_window_selected"] == 1
    assert metrics["primary_text_selected"] == 3


def test_cross_scale_consensus_preserves_primary_when_validator_is_sparse() -> None:
    primary = [
        Cue(0, 2_000, "第一句"),
        Cue(2_000, 4_000, "第二句"),
        Cue(4_000, 6_000, "第三句"),
    ]
    validation = [Cue(0, 500, "第一句")]

    reconciled, metrics = reconcile_cross_scale_cues(primary, validation)

    assert reconciled == primary
    assert metrics["strategy"] == "primary_fallback"
    assert metrics["reason"] == "validation_coverage_insufficient"


def test_cross_scale_consensus_repairs_quote_glyphs_with_validation() -> None:
    primary = [
        Cue(0, 2_000, "答案说： 66 普通缓存匹配请求。"),
        Cue(2_000, 4_000, "稍作改动就会未命中。 99"),
    ]
    validation = [
        Cue(0, 2_000, "答案说：“普通缓存匹配请求。"),
        Cue(2_000, 4_000, "稍作改动就会未命中。”"),
    ]

    reconciled, metrics = reconcile_cross_scale_cues(primary, validation)

    assert [cue.text for cue in reconciled] == [
        "答案说：“普通缓存匹配请求。",
        "稍作改动就会未命中。”",
    ]
    assert metrics["strategy"] == "cross_scale_consensus"


def test_cross_scale_consensus_drops_unconfirmed_closing_quote_number() -> None:
    primary = [Cue(0, 2_000, "缓存未命中。 99")]
    validation = [Cue(0, 2_000, "缓存未命中。")]

    reconciled, _ = reconcile_cross_scale_cues(primary, validation)

    assert reconciled[0].text == "缓存未命中。"
