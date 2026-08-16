"""One-shot Watch Later scan and idempotent automation job creation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..platforms.watch_later import (
    WatchLaterSource,
    build_watch_later_snapshot,
    normalize_watch_later_entries,
)
from .automation_job import (
    initialize_automation_job,
    list_automation_jobs,
    transition_automation_job,
)
from .automation_profile import read_automation_profile
from .locking import exclusive_file_lock
from .util import read_json, write_json_atomic


def scan_watch_later(
    *,
    profile_path: Path,
    source: WatchLaterSource,
    store: Path,
    limit: int | None = None,
    baseline_if_empty: bool = False,
) -> dict[str, Any]:
    profile = read_automation_profile(profile_path)
    if profile["enabled"] is not True:
        raise ValueError("Automation profile is disabled")
    store = store.expanduser().resolve()
    rows = source.list_entries(limit=limit)
    entries = normalize_watch_later_entries(rows)
    snapshot_root = store / "automation" / profile["profile_id"] / "snapshots"
    latest_path = snapshot_root.parent / "watch-later-latest.json"
    latest_path.parent.mkdir(parents=True, exist_ok=True)

    created_jobs: list[str] = []
    existing_jobs: list[str] = []
    with exclusive_file_lock(latest_path):
        previous = read_json(latest_path) if latest_path.is_file() else None
        baseline_initialized = previous is None and baseline_if_empty
        snapshot = build_watch_later_snapshot(
            profile["profile_id"],
            profile["source"]["account_profile_alias"],
            entries,
            previous=previous,
        )
        if baseline_initialized:
            snapshot["new_entries"] = []
        archive_path = snapshot_root / f"{snapshot['snapshot_id']}.json"

        for entry in snapshot["new_entries"]:
            result = initialize_automation_job(
                store,
                {
                    "platform": "bilibili",
                    "bvid": entry["bvid"],
                    "page": entry["page"],
                    "title": entry["title"],
                    "url": entry["url"],
                },
                profile,
            )
            if result["reused_existing_job"]:
                if result["status"] == "discovered":
                    transition_automation_job(Path(result["job_path"]), status="queued")
                existing_jobs.append(result["job_id"])
                continue
            queued = transition_automation_job(
                Path(result["job_path"]), status="queued"
            )
            created_jobs.append(queued["job_id"])

        write_json_atomic(archive_path, snapshot)
        write_json_atomic(latest_path, snapshot)
    jobs = list_automation_jobs(store)["jobs"]
    return {
        "schema_version": "video-automation/scan-result-v1",
        "profile_id": profile["profile_id"],
        "snapshot_path": str(archive_path),
        "latest_snapshot_path": str(latest_path),
        "baseline_initialized": baseline_initialized,
        "entry_count": len(snapshot["entries"]),
        "new_entry_count": len(snapshot["new_entries"]),
        "created_jobs": created_jobs,
        "existing_jobs": existing_jobs,
        "job_count": len(jobs),
    }
