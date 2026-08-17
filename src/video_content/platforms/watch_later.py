"""Transport-independent Bilibili Watch Later normalization and snapshots."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from ..util import utc_now

BVID_RE = re.compile(r"^BV[A-Za-z0-9]+$")


@dataclass(frozen=True)
class WatchLaterEntry:
    bvid: str
    page: int
    title: str
    url: str
    position: int
    added_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class WatchLaterSource(Protocol):
    def list_entries(self, *, limit: int | None = None) -> list[dict[str, Any]]: ...


class OpenCliWatchLaterSource:
    def __init__(self, client: Any) -> None:
        self.client = client

    def list_entries(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        return self.client.watch_later(limit=limit)


def normalize_watch_later_entries(
    rows: list[dict[str, Any]],
) -> list[WatchLaterEntry]:
    if not isinstance(rows, list):
        raise TypeError("Watch Later rows must be an array")
    unique: dict[tuple[str, int], WatchLaterEntry] = {}
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise TypeError("Watch Later row must be an object")
        bvid = str(row.get("bvid") or "").strip()
        if not BVID_RE.fullmatch(bvid):
            raise ValueError(f"Watch Later row has an invalid BVID: {bvid!r}")
        page = _positive_int(row.get("page", 1), "page")
        title = str(row.get("title") or "").strip()
        expected_url = f"https://www.bilibili.com/video/{bvid}/"
        supplied_url = str(row.get("url") or expected_url).strip()
        if supplied_url.rstrip("/") != expected_url.rstrip("/") or "?" in supplied_url:
            raise ValueError("Watch Later rows require a canonical Bilibili video URL")
        position = _positive_int(row.get("position", index), "position")
        added_at = _optional_timestamp(row.get("addedAt", row.get("added_at")))
        entry = WatchLaterEntry(
            bvid=bvid,
            page=page,
            title=title,
            url=expected_url,
            position=position,
            added_at=added_at,
        )
        unique.setdefault((bvid, page), entry)
    return sorted(
        unique.values(), key=lambda item: (item.position, item.bvid, item.page)
    )


def build_watch_later_snapshot(
    profile_id: str,
    account_profile_alias: str,
    entries: list[WatchLaterEntry],
    *,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile_id = profile_id.strip()
    account_profile_alias = account_profile_alias.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", profile_id):
        raise ValueError("Watch Later snapshot profile_id is invalid")
    if not account_profile_alias:
        raise ValueError("Watch Later snapshot requires an account profile alias")
    rows = [entry.as_dict() for entry in entries]
    previous_ids: set[tuple[str, int]] = set()
    if previous is not None:
        if previous.get("schema_version") != "video-content/watch-later-snapshot-v1":
            raise ValueError("Unsupported previous Watch Later snapshot")
        previous_ids = {
            (str(item["bvid"]), int(item["page"]))
            for item in previous.get("entries", [])
        }
    new_entries = [
        item
        for item in rows
        if (str(item["bvid"]), int(item["page"])) not in previous_ids
    ]
    digest = hashlib.sha256(
        json.dumps(rows, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    captured_at = utc_now()
    identity = {
        "profile_id": profile_id,
        "captured_at": captured_at,
        "source_digest": digest,
    }
    snapshot_hash = hashlib.sha256(
        json.dumps(identity, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": "video-content/watch-later-snapshot-v1",
        "snapshot_id": f"snapshot_{snapshot_hash[:16]}",
        "captured_at": captured_at,
        "profile_id": profile_id,
        "account_profile_alias": account_profile_alias,
        "entries": rows,
        "new_entries": new_entries,
        "source_digest": digest,
    }


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"Watch Later {label} must be a positive integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Watch Later {label} must be a positive integer") from error
    if result < 1:
        raise ValueError(f"Watch Later {label} must be a positive integer")
    return result


def _optional_timestamp(value: Any) -> str | None:
    if value in {None, ""}:
        return None
    if isinstance(value, bool):
        raise TypeError("Watch Later added_at timestamp is invalid")
    if isinstance(value, (int, float)):
        parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("Watch Later added_at timestamp is invalid") from error
        if parsed.tzinfo is None:
            raise ValueError("Watch Later added_at timestamp requires a timezone")
        parsed = parsed.astimezone(timezone.utc)
    return parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")
