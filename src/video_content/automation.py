from __future__ import annotations

from typing import Any

from .models import Profile
from .platforms.watch_later import WatchLaterSource, normalize_watch_later_entries
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
            **(settings or {}),
        },
        enabled=enabled,
    )
    if profile.settings.get("gpu_parallelism") != 1:
        raise ValueError("OCR and ASR must share the GPU serially")
    if profile.settings.get("publish") is not False:
        raise ValueError("Watch Later automation may save drafts but never publish")
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
    initialized = not seen and baseline_if_empty
    new_entries = (
        []
        if initialized
        else [
            entry for entry in entries if _entry_key(entry.bvid, entry.page) not in seen
        ]
    )
    run_id = new_id("run")
    created: list[str] = []
    existing: list[str] = []
    for entry in new_entries:
        job, reused = store.create_job(
            source={
                "platform": "bilibili",
                "bvid": entry.bvid,
                "page": entry.page,
                "title": entry.title,
                "url": entry.url,
                "added_at": entry.added_at,
            },
            idempotency_key=f"bilibili_{entry.bvid}_p{entry.page}",
            run_id=run_id,
            profile_id=profile_id,
        )
        (existing if reused else created).append(job["job_id"])
    baseline["seen"] = sorted(seen | current)
    baseline["last_scan_at"] = utc_now()
    baseline["last_entry_count"] = len(entries)
    baseline["last_run_id"] = run_id
    profile["baseline"] = baseline
    saved_profile = store.save_profile(profile)
    return {
        "schema_version": "video-content/watch-later-scan-v1",
        "profile_id": profile_id,
        "run_id": run_id,
        "baseline_initialized": initialized,
        "entry_count": len(entries),
        "new_entry_count": len(new_entries),
        "created_jobs": created,
        "existing_jobs": existing,
        "profile": saved_profile,
    }


def _entry_key(bvid: str, page: int) -> str:
    return f"{bvid}:p{page}"
