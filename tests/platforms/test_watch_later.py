from __future__ import annotations

import json
from pathlib import Path

import pytest

from video_content.platforms.watch_later import (
    build_watch_later_snapshot,
    normalize_watch_later_entries,
)

ROOT = Path(__file__).resolve().parents[2]


def _rows(name: str) -> list[dict]:
    return json.loads(
        (ROOT / "tests" / "fixtures" / "bilibili-watch-later" / name).read_text(
            encoding="utf-8-sig"
        )
    )


def test_snapshot_detects_new_identity_without_requeueing_reorders() -> None:
    first_entries = normalize_watch_later_entries(_rows("first.json"))
    first = build_watch_later_snapshot(
        "profile-watch-later", "bilibili-main", first_entries
    )
    second_entries = normalize_watch_later_entries(_rows("reordered-with-new.json"))
    second = build_watch_later_snapshot(
        "profile-watch-later", "bilibili-main", second_entries, previous=first
    )
    assert [(item["bvid"], item["page"]) for item in second["new_entries"]] == [
        ("BV1new", 2)
    ]
    assert second["entries"][0]["position"] == 1


def test_normalization_deduplicates_and_rejects_secret_urls() -> None:
    rows = _rows("first.json")
    rows.append({**rows[0], "position": 9})
    normalized = normalize_watch_later_entries(rows)
    assert len(normalized) == 2
    assert normalized[0].position == 1

    rows[0]["url"] = "https://www.bilibili.com/video/BV1alpha/?token=secret"
    with pytest.raises(ValueError, match="canonical"):
        normalize_watch_later_entries(rows)


def test_snapshot_contains_no_raw_provider_payload() -> None:
    entries = normalize_watch_later_entries(_rows("first.json"))
    snapshot = build_watch_later_snapshot(
        "profile-watch-later", "bilibili-main", entries
    )
    assert "raw" not in snapshot
    assert "cookie" not in json.dumps(snapshot).lower()
