from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import Profile
from .platforms.watch_later import (
    WatchLaterEntry,
    WatchLaterSource,
    normalize_watch_later_entries,
)
from .store import Store
from .util import new_id, utc_now


def save_watch_later_profile(
    store: Store,
    *,
    profile_id: str,
    account_profile_alias: str,
    carrier: str = "wechat_article",
    enabled: bool = True,
    baseline: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    alias = account_profile_alias.strip()
    if not alias:
        raise ValueError(
            "Watch Later profile requires a non-secret Browser/OpenCLI alias"
        )
    profile = Profile(
        profile_id=profile_id,
        source={
            "platform": "bilibili",
            "kind": "watch_later",
            "account_profile_alias": alias,
        },
        carrier=carrier,
        baseline=baseline or {"seen": [], "last_scan_at": None},
        settings={
            "max_retries": 3,
            "gpu_parallelism": 1,
            "publish": False,
            "adaptation_mode": "source_faithful_full",
            "visual_policy": "source_frames_at_material_transitions",
            "minimum_source_frames": 3,
            "wechat_creation_source": "ai_generated",
            **(settings or {}),
        },
        enabled=enabled,
    )
    if profile.settings.get("gpu_parallelism") != 1:
        raise ValueError("OCR and ASR must share the GPU serially")
    if profile.settings.get("publish") is not False:
        raise ValueError("Watch Later automation may save drafts but never publish")
    if profile.settings.get("adaptation_mode") != "source_faithful_full":
        raise ValueError("Watch Later content must use source_faithful_full adaptation")
    if profile.settings.get("visual_policy") != "source_frames_at_material_transitions":
        raise ValueError(
            "Watch Later content must use source frames at material transitions"
        )
    minimum_source_frames = profile.settings.get("minimum_source_frames")
    if (
        not isinstance(minimum_source_frames, int)
        or isinstance(minimum_source_frames, bool)
        or minimum_source_frames < 1
    ):
        raise ValueError("minimum_source_frames must be a positive integer")
    if profile.settings.get("wechat_creation_source") != "ai_generated":
        raise ValueError("Watch Later WeChat drafts must declare AI-generated content")
    return store.save_profile(profile)


def watch_later_scan(
    store: Store,
    *,
    profile_id: str,
    source: WatchLaterSource,
    limit: int | None = None,
    baseline_if_empty: bool = False,
) -> dict[str, Any]:
    profile = store.get_profile(profile_id)
    if profile.get("enabled") is not True:
        raise ValueError("Watch Later profile is disabled")
    if (
        profile.get("source", {}).get("platform") != "bilibili"
        or profile.get("source", {}).get("kind") != "watch_later"
    ):
        raise ValueError("Profile is not a Bilibili Watch Later profile")
    entries = normalize_watch_later_entries(source.list_entries(limit=limit))
    baseline = dict(profile.get("baseline") or {})
    seen = {str(value) for value in baseline.get("seen") or []}
    current = {_entry_key(entry.bvid, entry.page) for entry in entries}
    previous_watermark = _normalize_timestamp(
        baseline.get("latest_added_at"), label="Profile latest_added_at"
    )
    known_reentries = _known_reentries(entries, seen, previous_watermark)
    initialized = not seen and baseline_if_empty
    if initialized:
        new_entries: list[WatchLaterEntry] = []
        ignored_unseen: list[WatchLaterEntry] = []
        detection_mode = "baseline_initialization"
        watermark = _latest_added_at(entries)
        watermark_source = "current_snapshot"
    else:
        (
            new_entries,
            ignored_unseen,
            detection_mode,
            watermark,
            watermark_source,
        ) = _detect_new_watch_later_entries(entries, seen, baseline)
    run_id = new_id("run")
    created: list[str] = []
    existing: list[str] = []
    for entry in new_entries:
        job, reused = store.create_job(
            source={
                key: value
                for key, value in {
                    "platform": "bilibili",
                    "bvid": entry.bvid,
                    "page": entry.page,
                    "title": entry.title,
                    "url": entry.url,
                    "added_at": entry.added_at,
                    "cover_url": entry.cover_url,
                }.items()
                if value is not None
            },
            idempotency_key=f"bilibili_{entry.bvid}_p{entry.page}",
            run_id=run_id,
            profile_id=profile_id,
        )
        (existing if reused else created).append(job["job_id"])
    new_keys = {_entry_key(entry.bvid, entry.page) for entry in new_entries}
    ignored_keys = {_entry_key(entry.bvid, entry.page) for entry in ignored_unseen}
    known_reentry_keys = {
        _entry_key(entry.bvid, entry.page) for entry in known_reentries
    }
    pending_ignored = {
        str(value) for value in baseline.get("pending_ignored_unseen") or []
    }
    pending_ignored.difference_update(seen | new_keys)
    pending_ignored.update(ignored_keys)
    decision = {
        "schema_version": "video-content/watch-later-decision-v1",
        "run_id": run_id,
        "detection_mode": detection_mode,
        "detection_watermark": watermark,
        "detection_watermark_source": watermark_source,
        "new": sorted(new_keys),
        "ignored_unseen": sorted(ignored_keys),
        "known_reentries": sorted(known_reentry_keys),
    }
    baseline["seen"] = sorted(seen | (current - ignored_keys))
    if pending_ignored:
        baseline["pending_ignored_unseen"] = sorted(pending_ignored)
    else:
        baseline.pop("pending_ignored_unseen", None)
    baseline["last_scan_at"] = utc_now()
    baseline["last_entry_count"] = len(entries)
    baseline["last_run_id"] = run_id
    baseline["last_scan_decision"] = decision
    latest_added_at = _latest_added_at(entries, baseline.get("latest_added_at"))
    if latest_added_at is not None:
        baseline["latest_added_at"] = latest_added_at
    profile["baseline"] = baseline
    saved_profile = store.save_profile(profile)
    return {
        "schema_version": "video-content/watch-later-scan-v1",
        "profile_id": profile_id,
        "run_id": run_id,
        "baseline_initialized": initialized,
        "entry_count": len(entries),
        "new_entry_count": len(new_entries),
        "new_entries": [entry.as_dict() for entry in new_entries],
        "ignored_unseen_entry_count": len(ignored_unseen),
        "ignored_unseen_entries": [entry.as_dict() for entry in ignored_unseen],
        "known_reentry_count": len(known_reentries),
        "known_reentries": [entry.as_dict() for entry in known_reentries],
        "pending_ignored_unseen_count": len(pending_ignored),
        "pending_ignored_unseen": sorted(pending_ignored),
        "detection_mode": detection_mode,
        "detection_watermark": watermark,
        "detection_watermark_source": watermark_source,
        "created_jobs": created,
        "existing_jobs": existing,
        "profile": saved_profile,
    }


def _entry_key(bvid: str, page: int) -> str:
    return f"{bvid}:p{page}"


def _detect_new_watch_later_entries(
    entries: list[WatchLaterEntry],
    seen: set[str],
    baseline: dict[str, Any],
) -> tuple[
    list[WatchLaterEntry],
    list[WatchLaterEntry],
    str,
    str | None,
    str,
]:
    unseen = [
        entry for entry in entries if _entry_key(entry.bvid, entry.page) not in seen
    ]
    if not seen:
        return (
            unseen,
            [],
            "empty_profile",
            _latest_added_at(entries),
            "current_snapshot",
        )

    overlap = [entry for entry in entries if _entry_key(entry.bvid, entry.page) in seen]
    first_overlap_position = min(
        (entry.position for entry in overlap),
        default=None,
    )
    watermark = _normalize_timestamp(
        baseline.get("latest_added_at"), label="Profile latest_added_at"
    )
    if watermark is None:
        if not unseen:
            return [], [], "stable_identity_only", None, "none"
        raise ValueError(
            "Watch Later scan requires the persisted pre-scan latest_added_at "
            "watermark when the Profile already has unseen identities; repair or "
            "reinitialize the baseline instead of inferring from current rows"
        )

    watermark_value = _timestamp_value(watermark, label="detection watermark")
    new_entries: list[WatchLaterEntry] = []
    ignored: list[WatchLaterEntry] = []
    for entry in unseen:
        entry_value = (
            _timestamp_value(entry.added_at, label="Watch Later added_at")
            if entry.added_at is not None
            else None
        )
        is_newer = entry_value is not None and entry_value > watermark_value
        ties_front_anchor = (
            entry_value == watermark_value
            and first_overlap_position is not None
            and entry.position < first_overlap_position
        )
        missing_timestamp_front_anchor = (
            entry.added_at is None
            and first_overlap_position is not None
            and entry.position < first_overlap_position
        )
        if is_newer or ties_front_anchor or missing_timestamp_front_anchor:
            new_entries.append(entry)
        else:
            ignored.append(entry)
    return new_entries, ignored, "timestamp_watermark", watermark, "profile"


def _known_reentries(
    entries: list[WatchLaterEntry], seen: set[str], watermark: str | None
) -> list[WatchLaterEntry]:
    if not seen or watermark is None:
        return []
    watermark_value = _timestamp_value(watermark, label="Profile latest_added_at")
    return [
        entry
        for entry in entries
        if _entry_key(entry.bvid, entry.page) in seen
        and entry.added_at is not None
        and _timestamp_value(entry.added_at, label="Watch Later added_at")
        > watermark_value
    ]


def _latest_added_at(
    entries: list[WatchLaterEntry], previous: Any = None
) -> str | None:
    values = [entry.added_at for entry in entries if entry.added_at is not None]
    normalized_previous = _normalize_timestamp(
        previous, label="Profile latest_added_at"
    )
    if normalized_previous is not None:
        values.append(normalized_previous)
    if not values:
        return None
    latest = max(
        _timestamp_value(value, label="Watch Later added_at") for value in values
    )
    return latest.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _normalize_timestamp(value: Any, *, label: str) -> str | None:
    if value is None or value == "":
        return None
    parsed = _timestamp_value(value, label=label)
    return parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _timestamp_value(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a timestamp string")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} is invalid") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{label} requires a timezone")
    return parsed.astimezone(timezone.utc)
