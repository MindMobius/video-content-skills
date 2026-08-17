from __future__ import annotations

import math
from typing import Any

DEFAULT_SCOUT_ANCHORS = (0.0, 0.25, 0.5, 0.75, 1.0)
_DEFAULT_LABELS = {
    0.0: "opening",
    0.25: "quarter",
    0.5: "middle",
    0.75: "three_quarters",
    1.0: "ending",
}


def plan_hard_subtitle_scout(
    duration_seconds: float,
    *,
    window_seconds: float = 20.0,
    anchors: list[float] | tuple[float, ...] | None = None,
) -> dict[str, Any]:
    """Plan deterministic OCR sample windows; the calling Agent judges the evidence."""
    duration_ms = _positive_milliseconds(duration_seconds, "duration_seconds")
    requested_window_ms = _positive_milliseconds(window_seconds, "window_seconds")
    window_ms = min(requested_window_ms, duration_ms)
    selected_anchors = _normalize_anchors(anchors)

    raw_windows: list[dict[str, Any]] = []
    for anchor in selected_anchors:
        anchor_ms = round(anchor * duration_ms)
        if anchor <= 0:
            start_ms = 0
        elif anchor >= 1:
            start_ms = duration_ms - window_ms
        else:
            start_ms = anchor_ms - window_ms // 2
            start_ms = max(0, min(start_ms, duration_ms - window_ms))
        end_ms = min(duration_ms, start_ms + window_ms)
        raw_windows.append(
            {
                "start_ms": start_ms,
                "end_ms": end_ms,
                "anchors": [anchor],
                "labels": [_anchor_label(anchor)],
            }
        )

    raw_windows.sort(key=lambda item: (item["start_ms"], item["end_ms"]))
    merged: list[dict[str, Any]] = []
    for window in raw_windows:
        if not merged or window["start_ms"] > merged[-1]["end_ms"]:
            merged.append(
                {
                    "start_ms": window["start_ms"],
                    "end_ms": window["end_ms"],
                    "anchors": list(window["anchors"]),
                    "labels": list(window["labels"]),
                }
            )
            continue
        current = merged[-1]
        current["end_ms"] = max(current["end_ms"], window["end_ms"])
        current["anchors"].extend(window["anchors"])
        current["labels"].extend(window["labels"])

    windows = []
    for index, window in enumerate(merged, start=1):
        windows.append(
            {
                "window_id": f"scout-{index:03d}",
                "start_ms": window["start_ms"],
                "end_ms": window["end_ms"],
                "duration_seconds": round(
                    (window["end_ms"] - window["start_ms"]) / 1000,
                    3,
                ),
                "time_start": _format_timestamp(window["start_ms"]),
                "time_end": _format_timestamp(window["end_ms"]),
                "anchors": window["anchors"],
                "labels": window["labels"],
            }
        )

    coverage_ms = sum(item["end_ms"] - item["start_ms"] for item in windows)
    coverage_ratio = coverage_ms / duration_ms
    return {
        "schema_version": "video-content/ocr-scout-plan-v1",
        "duration_seconds": round(duration_ms / 1000, 3),
        "requested_window_seconds": round(requested_window_ms / 1000, 3),
        "effective_window_seconds": round(window_ms / 1000, 3),
        "requested_anchors": selected_anchors,
        "raw_window_count": len(raw_windows),
        "window_count": len(windows),
        "windows": windows,
        "coverage_seconds": round(coverage_ms / 1000, 3),
        "coverage_ratio": round(coverage_ratio, 6),
        "estimated_full_ocr_savings_ratio": round(max(0.0, 1 - coverage_ratio), 6),
        "decision_boundary": {
            "owner": "calling_agent",
            "instruction": (
                "Run OCR on these windows as independent evidence. Inspect subtitle "
                "continuity, cue density, text role, and OCR quality before deciding "
                "whether full-video hard-subtitle OCR is warranted. A low cue count "
                "alone is not proof that hard subtitles are absent."
            ),
        },
    }


def _normalize_anchors(
    anchors: list[float] | tuple[float, ...] | None,
) -> list[float]:
    selected = DEFAULT_SCOUT_ANCHORS if anchors is None else anchors
    if not selected:
        raise ValueError("anchors cannot be empty")
    result = []
    seen = set()
    for raw in selected:
        try:
            anchor = float(raw)
        except (TypeError, ValueError) as error:
            raise ValueError("anchors must be numeric") from error
        if not math.isfinite(anchor) or not 0 <= anchor <= 1:
            raise ValueError("anchors must be finite values between 0 and 1")
        normalized = round(anchor, 6)
        if normalized not in seen:
            result.append(normalized)
            seen.add(normalized)
    return result


def _positive_milliseconds(value: float, label: str) -> int:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be numeric") from error
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{label} must be a finite positive value")
    milliseconds = round(parsed * 1000)
    if milliseconds < 1:
        raise ValueError(f"{label} must be at least 0.001 seconds")
    return milliseconds


def _anchor_label(anchor: float) -> str:
    return _DEFAULT_LABELS.get(anchor, f"anchor_{anchor:.6f}".rstrip("0"))


def _format_timestamp(milliseconds: int) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"
