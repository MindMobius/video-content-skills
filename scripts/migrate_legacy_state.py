"""Archive a previous local state and seed the Video Content Skills 1.0 store."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from video_content.automation import save_watch_later_profile
from video_content.config import CONFIG_ENVIRONMENT, update_configuration
from video_content.store import Store
from video_content.util import reject_secrets, sha256_file, utc_now, write_json_atomic

PLAN_SCHEMA = "video-content/state-migration-plan-v1"
MIGRATION_SCHEMA = "video-content/state-migration-v1"
ARCHIVE_MANIFEST_SCHEMA = "video-content/archive-manifest-v1"
ARCHIVE_RECORD_SCHEMA = "video-content/archive-record-v1"
PROFILE_ID = "watch-later-main"
_BVID = re.compile(r"^BV[0-9A-Za-z]+$")
_NUMERIC = re.compile(r"^[0-9]+$")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--expect-completed", type=int)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--no-protect-archive", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.apply:
        report = apply_migration(
            args.source,
            args.archive,
            args.target,
            expected_completed=args.expect_completed,
            protect_archive=not args.no_protect_archive,
        )
    else:
        report = plan_migration(
            args.source,
            args.archive,
            args.target,
            expected_completed=args.expect_completed,
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))


def plan_migration(
    source: str | Path,
    archive: str | Path,
    target: str | Path,
    *,
    expected_completed: int | None = None,
) -> dict[str, Any]:
    source_path, archive_path, target_path = _migration_paths(source, archive, target)
    _require_new_destinations(archive_path, target_path)
    state = _inspect_source(source_path, expected_completed=expected_completed)
    source_inventory = _inventory_summary(source_path)
    cache_root = state["cache_root"]
    cache_inventory = (
        _inventory_summary(cache_root) if cache_root else {"files": 0, "bytes": 0}
    )
    plan = {
        "schema_version": PLAN_SCHEMA,
        "ready": True,
        "mode": "dry_run",
        "source": str(source_path),
        "archive": str(archive_path),
        "target": str(target_path),
        "source_inventory": source_inventory,
        "cache": {
            "source_relative": (
                cache_root.relative_to(source_path).as_posix() if cache_root else None
            ),
            **cache_inventory,
        },
        "profile": state["profile"],
        "sources": [_public_source(item) for item in state["jobs"]],
        "validated": state["validated"],
        "warnings": state["warnings"],
        "configuration_fields": sorted(state["configuration"]),
        "actions": [
            "hash every source file",
            "atomically move the source directory to the archive destination",
            "copy and verify the media cache into the new state",
            "seed one profile and completed idempotency job per validated source",
            "write a new no-secret configuration and migration receipt",
            "mark archived files read-only after verification",
        ],
        "published": False,
    }
    reject_secrets(plan)
    return plan


def apply_migration(
    source: str | Path,
    archive: str | Path,
    target: str | Path,
    *,
    expected_completed: int | None = None,
    protect_archive: bool = True,
) -> dict[str, Any]:
    source_path, archive_path, target_path = _migration_paths(source, archive, target)
    _require_new_destinations(archive_path, target_path)
    state = _inspect_source(source_path, expected_completed=expected_completed)
    inventory = _build_inventory(source_path)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.rename(archive_path)
    _verify_inventory(archive_path, inventory["entries"])
    manifest = {
        "schema_version": ARCHIVE_MANIFEST_SCHEMA,
        "created_at": utc_now(),
        "original_root": str(source_path),
        "archive_root": str(archive_path),
        "files": inventory["files"],
        "bytes": inventory["bytes"],
        "entries": inventory["entries"],
    }
    manifest_path = archive_path / "archive-manifest.json"
    write_json_atomic(manifest_path, manifest)
    manifest_sha256 = sha256_file(manifest_path)

    staging = target_path.with_name(f".{target_path.name}.migrating")
    if staging.exists():
        raise FileExistsError(
            f"Migration staging destination already exists: {staging}"
        )
    store = Store(staging)
    store.initialize()
    configuration = _translated_configuration(
        state["configuration"],
        source=source_path,
        archive=archive_path,
        target=target_path,
    )
    update_configuration(configuration, path=staging / "config.json")

    identities = sorted(
        {_identity(item["bvid"], item["page"]) for item in state["snapshot_entries"]}
        | {_identity(item["bvid"], item["page"]) for item in state["jobs"]}
    )
    profile = save_watch_later_profile(
        store,
        profile_id=PROFILE_ID,
        account_profile_alias=state["profile"]["account_profile_alias"],
        baseline={
            "seen": identities,
            "last_scan_at": state["profile"].get("captured_at"),
            "last_entry_count": len(identities),
            "migration_manifest_sha256": manifest_sha256,
        },
        settings={
            "archive_root": str(archive_path),
            "archive_manifest_sha256": manifest_sha256,
        },
    )

    run_id = f"run_migration_{manifest_sha256[:16]}"
    migrated_sources: list[dict[str, Any]] = []
    for item in state["jobs"]:
        idempotency_key = f"bilibili_{item['bvid']}_p{item['page']}"
        job_digest = hashlib.sha256(idempotency_key.encode()).hexdigest()[:16]
        job, reused = store.create_job(
            source={
                "platform": "bilibili",
                "bvid": item["bvid"],
                "page": item["page"],
                "url": item["url"],
            },
            idempotency_key=idempotency_key,
            run_id=run_id,
            profile_id=PROFILE_ID,
            job_id=f"job_migrated_{job_digest}",
            initial_status="completed",
            initial_stage="completed",
        )
        if reused:
            raise RuntimeError(f"Unexpected duplicate migration job: {idempotency_key}")
        archive_record = {
            "schema_version": ARCHIVE_RECORD_SCHEMA,
            "job_id": job["job_id"],
            "source": {"bvid": item["bvid"], "page": item["page"]},
            "archive_root": str(archive_path),
            "original_job_id": item["original_job_id"],
            "original_job_path": item["job_relative"],
            "original_job_sha256": item["job_sha256"],
            "content_project": item["content_project"],
            "draft_receipt": item["draft_receipt"],
            "appmsgid": item["appmsgid"],
            "published": False,
            "integrity_warnings": item["warnings"],
            "migrated_at": utc_now(),
        }
        record_ref = store.put_artifact(
            job["job_id"],
            kind="archive_record",
            data=archive_record,
            filename="archive-record.json",
            media_type="application/json",
            metadata={"source_identity": _identity(item["bvid"], item["page"])},
        )
        job = store.get_job(job["job_id"])
        job["created_at"] = item["created_at"] or job["created_at"]
        job["completed_at"] = item["completed_at"] or utc_now()
        store.write_job(job)
        store.append_event(
            job["job_id"],
            {
                "type": "job.migrated",
                "archive_record_artifact_id": record_ref["artifact_id"],
                "published": False,
            },
        )
        migrated_sources.append(
            {
                "bvid": item["bvid"],
                "page": item["page"],
                "job_id": job["job_id"],
                "idempotency_key": idempotency_key,
            }
        )

    cache_result = _copy_cache(
        archive=archive_path,
        staging=staging,
        cache_root=state["cache_root"],
        original_source=source_path,
        inventory_entries=inventory["entries"],
    )
    receipt = {
        "schema_version": MIGRATION_SCHEMA,
        "migrated_at": utc_now(),
        "archive_root": str(archive_path),
        "archive_manifest": str(manifest_path),
        "archive_manifest_sha256": manifest_sha256,
        "state_root": str(target_path),
        "config_path": str(target_path / "config.json"),
        "profile_id": profile["profile_id"],
        "sources": migrated_sources,
        "validated": state["validated"],
        "warnings": state["warnings"],
        "cache": cache_result,
        "archive_read_only": protect_archive,
        "published": False,
    }
    reject_secrets(receipt)
    write_json_atomic(staging / "migration-receipt.json", receipt)
    _verify_target(staging, receipt, expected_completed=expected_completed)
    staging.rename(target_path)

    verification = verify_migration(
        archive_path,
        target_path,
        expected_completed=expected_completed,
    )
    if not verification["valid"]:
        raise RuntimeError(
            "Migration verification failed: " + "; ".join(verification["errors"])
        )
    if protect_archive:
        _protect_archive(archive_path)
    return receipt


def verify_migration(
    archive: str | Path,
    target: str | Path,
    *,
    expected_completed: int | None = None,
) -> dict[str, Any]:
    archive_path = Path(archive).expanduser().resolve()
    target_path = Path(target).expanduser().resolve()
    errors: list[str] = []
    try:
        manifest_path = archive_path / "archive-manifest.json"
        manifest = _read_object(manifest_path)
        if manifest.get("schema_version") != ARCHIVE_MANIFEST_SCHEMA:
            raise ValueError("Unsupported archive manifest schema")
        _verify_inventory(archive_path, list(manifest.get("entries") or []))
        receipt = _read_object(target_path / "migration-receipt.json")
        if receipt.get("schema_version") != MIGRATION_SCHEMA:
            raise ValueError("Unsupported migration receipt schema")
        if receipt.get("published") is not False:
            raise ValueError("Migration receipt must state published=false")
        if receipt.get("archive_manifest_sha256") != sha256_file(manifest_path):
            raise ValueError("Archive manifest hash mismatch")
        _verify_target(target_path, receipt, expected_completed=expected_completed)
    except (FileNotFoundError, OSError, TypeError, ValueError) as error:
        errors.append(str(error))
    return {
        "schema_version": "video-content/state-migration-verification-v1",
        "valid": not errors,
        "archive": str(archive_path),
        "target": str(target_path),
        "errors": errors,
        "checked_at": utc_now(),
        "published": False,
    }


def _inspect_source(source: Path, *, expected_completed: int | None) -> dict[str, Any]:
    configuration = _read_configuration_values(source / "config.json")
    jobs = _discover_jobs(source)
    if expected_completed is not None and len(jobs) != expected_completed:
        raise ValueError(
            f"Expected {expected_completed} completed jobs, found {len(jobs)}"
        )
    if not jobs:
        raise ValueError("No completed Bilibili jobs were found")
    identities = [_identity(item["bvid"], item["page"]) for item in jobs]
    if len(set(identities)) != len(identities):
        raise ValueError("Completed job source identities are not unique")
    appmsgids = [item["appmsgid"] for item in jobs]
    if len(set(appmsgids)) != len(appmsgids):
        raise ValueError("Draft appmsgids are not unique")

    snapshot = _discover_snapshot(source)
    alias = str(
        snapshot.get("account_profile_alias")
        or configuration.get("opencli_profile")
        or ""
    ).strip()
    if not alias:
        raise ValueError("No non-secret browser profile alias was found")
    snapshot_entries = _normalize_snapshot_entries(snapshot.get("entries") or [])
    snapshot_identities = {
        _identity(item["bvid"], item["page"]) for item in snapshot_entries
    }
    missing = sorted(set(identities) - snapshot_identities)
    if missing:
        raise ValueError(
            f"Completed sources are missing from the Watch Later snapshot: {missing}"
        )
    cache_root = _cache_root(source, configuration)
    warnings = [
        {"bvid": item["bvid"], "page": item["page"], **warning}
        for item in jobs
        for warning in item["warnings"]
    ]
    validated = {
        "completed_jobs": len(jobs),
        "draft_receipts": len(jobs),
        "published_false": sum(item["published"] is False for item in jobs),
        "unique_appmsgids": len(set(appmsgids)),
        "wechat_hosted_images": sum(item["wechat_hosted_images"] for item in jobs),
    }
    if warnings:
        validated["noncritical_reference_warnings"] = len(warnings)
    return {
        "configuration": configuration,
        "jobs": jobs,
        "snapshot_entries": snapshot_entries,
        "profile": {
            "profile_id": PROFILE_ID,
            "account_profile_alias": alias,
            "captured_at": snapshot.get("captured_at"),
            "entry_count": len(snapshot_entries),
        },
        "cache_root": cache_root,
        "validated": validated,
        "warnings": warnings,
    }


def _discover_jobs(source: Path) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for job_path in sorted(source.rglob("job.json")):
        document = _read_object(job_path)
        raw_source = document.get("source")
        if not isinstance(raw_source, dict) or raw_source.get("platform") != "bilibili":
            continue
        if (
            document.get("status") != "completed"
            or document.get("stage") != "completed"
        ):
            continue
        bvid = str(raw_source.get("bvid") or "")
        page = raw_source.get("page", 1)
        if not _BVID.fullmatch(bvid):
            raise ValueError(
                f"Invalid Bilibili source identity in {job_path}: {bvid!r}"
            )
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            raise ValueError(f"Invalid Bilibili page in {job_path}: {page!r}")
        job_dir = job_path.parent
        artifacts = document.get("artifacts")
        if not isinstance(artifacts, dict):
            raise TypeError(f"Completed job has no artifact map: {job_path}")
        reference_warnings: list[dict[str, Any]] = []
        for kind, reference in artifacts.items():
            if not (
                isinstance(reference, dict)
                and reference.get("path")
                and reference.get("sha256")
            ):
                continue
            path = _safe_child(job_dir, str(reference["path"]))
            expected_hash = str(reference["sha256"])
            actual_hash = sha256_file(path)
            if actual_hash == expected_hash:
                continue
            if kind in {"content_binding", "handoff_binding"}:
                raise ValueError(f"Artifact hash mismatch: {path}")
            reference_warnings.append(
                {
                    "kind": str(kind),
                    "path": path.relative_to(source).as_posix(),
                    "expected_sha256": expected_hash,
                    "actual_sha256": actual_hash,
                }
            )
        content_binding_path = _reference_path(
            job_dir,
            artifacts.get("content_binding"),
            "automation-content-binding.json",
        )
        handoff_binding_path = _reference_path(
            job_dir,
            artifacts.get("handoff_binding"),
            "handoff-binding.json",
        )
        content_binding = _read_object(content_binding_path)
        handoff_binding = _read_object(handoff_binding_path)
        project_path = _safe_child(
            job_dir, str(content_binding.get("project_path") or "")
        )
        project_hash = str(content_binding.get("project_sha256") or "")
        if not project_hash or sha256_file(project_path) != project_hash:
            raise ValueError(f"Content project hash mismatch: {project_path}")
        receipt_path = _safe_child(
            job_dir, str(handoff_binding.get("receipt_path") or "")
        )
        receipt_hash = str(handoff_binding.get("receipt_sha256") or "")
        if not receipt_hash or sha256_file(receipt_path) != receipt_hash:
            raise ValueError(f"Draft receipt hash mismatch: {receipt_path}")
        receipt = _read_object(receipt_path)
        if receipt.get("published") is not False or receipt.get(
            "publish_actions_performed"
        ) not in (None, []):
            raise ValueError(
                f"Archived draft receipt must state published=false: {receipt_path}"
            )
        save = receipt.get("save")
        if (
            not isinstance(save, dict)
            or save.get("saved") is not True
            or save.get("saved_page_read_back") is not True
        ):
            raise ValueError(
                f"Archived draft receipt has no verified save/readback: {receipt_path}"
            )
        body_images = receipt.get("body_images")
        if not isinstance(body_images, dict):
            raise TypeError(
                f"Archived draft receipt has no image audit: {receipt_path}"
            )
        intended = _nonnegative_int(body_images.get("intended"), "intended images")
        hosted = _nonnegative_int(body_images.get("wechat_hosted"), "hosted images")
        visible = _nonnegative_int(body_images.get("visible_loaded"), "visible images")
        local_markers = _nonnegative_int(
            body_images.get("local_path_markers_remaining"), "local markers"
        )
        non_hosted = _nonnegative_int(
            body_images.get("non_wechat_hosted"), "non-hosted images"
        )
        if hosted != intended or visible != intended or local_markers or non_hosted:
            raise ValueError(
                f"Archived draft receipt image audit failed: {receipt_path}"
            )
        appmsgid = str(handoff_binding.get("appmsgid") or receipt.get("appmsgid") or "")
        if not _NUMERIC.fullmatch(appmsgid):
            raise ValueError(
                f"Archived draft receipt has no stable appmsgid: {receipt_path}"
            )
        timestamps = (
            document.get("timestamps")
            if isinstance(document.get("timestamps"), dict)
            else {}
        )
        jobs.append(
            {
                "bvid": bvid,
                "page": page,
                "url": str(
                    raw_source.get("url") or f"https://www.bilibili.com/video/{bvid}/"
                ),
                "original_job_id": str(document.get("job_id") or job_dir.name),
                "job_relative": job_dir.relative_to(source).as_posix(),
                "job_sha256": sha256_file(job_path),
                "content_project": {
                    "path": project_path.relative_to(source).as_posix(),
                    "sha256": project_hash,
                },
                "draft_receipt": {
                    "path": receipt_path.relative_to(source).as_posix(),
                    "sha256": receipt_hash,
                },
                "appmsgid": appmsgid,
                "published": False,
                "wechat_hosted_images": hosted,
                "created_at": timestamps.get("created_at"),
                "completed_at": timestamps.get("finished_at")
                or timestamps.get("updated_at"),
                "warnings": reference_warnings,
            }
        )
    return jobs


def _discover_snapshot(source: Path) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for path in source.rglob("watch-later-latest.json"):
        document = _read_object(path)
        if isinstance(document.get("entries"), list):
            candidates.append(document)
    if not candidates:
        raise FileNotFoundError("No Watch Later snapshot was found")
    return max(candidates, key=lambda item: str(item.get("captured_at") or ""))


def _normalize_snapshot_entries(values: list[Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in values:
        if not isinstance(item, dict):
            raise TypeError("Watch Later snapshot entries must be objects")
        bvid = str(item.get("bvid") or "")
        page = item.get("page", 1)
        if (
            not _BVID.fullmatch(bvid)
            or not isinstance(page, int)
            or isinstance(page, bool)
            or page < 1
        ):
            raise ValueError("Watch Later snapshot contains an invalid source identity")
        entries.append({"bvid": bvid, "page": page})
    return entries


def _read_configuration_values(path: Path) -> dict[str, Any]:
    document = _read_object(path)
    reject_secrets(document)
    values = document.get("values", document)
    if not isinstance(values, dict):
        raise TypeError("Previous configuration values must be an object")
    return {
        key: value
        for key, value in values.items()
        if key in CONFIG_ENVIRONMENT and value not in (None, "")
    }


def _translated_configuration(
    values: dict[str, Any],
    *,
    source: Path,
    archive: Path,
    target: Path,
) -> dict[str, str]:
    translated: dict[str, str] = {}
    for field, value in values.items():
        if field == "home":
            translated[field] = str(target)
            continue
        if field == "download_cache":
            translated[field] = str(target / "cache" / "media")
            continue
        selected = str(value)
        path_value = Path(selected).expanduser()
        if path_value.is_absolute():
            resolved = path_value.resolve(strict=False)
            try:
                relative = resolved.relative_to(source)
            except ValueError:
                pass
            else:
                selected = str((archive / relative).resolve(strict=False))
        translated[field] = selected
    translated["home"] = str(target)
    translated["download_cache"] = str(target / "cache" / "media")
    reject_secrets({"values": translated})
    return dict(sorted(translated.items()))


def _cache_root(source: Path, configuration: dict[str, Any]) -> Path | None:
    selected = configuration.get("download_cache")
    if selected:
        candidate = Path(str(selected)).expanduser().resolve(strict=False)
        try:
            candidate.relative_to(source)
        except ValueError as error:
            raise ValueError(
                "Download cache must be inside the archived state"
            ) from error
        if candidate.is_dir():
            return candidate
    fallback = source / "subtitle-home" / "cache" / "media"
    return fallback if fallback.is_dir() else None


def _copy_cache(
    *,
    archive: Path,
    staging: Path,
    cache_root: Path | None,
    original_source: Path,
    inventory_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    destination = staging / "cache" / "media"
    destination.mkdir(parents=True, exist_ok=True)
    if cache_root is None:
        return {"files": 0, "bytes": 0, "mode": "copy", "entries": []}
    cache_relative = cache_root.relative_to(original_source)
    archived_cache = archive / cache_relative
    prefix = cache_relative.as_posix().rstrip("/") + "/"
    expected = {
        item["path"][len(prefix) :]: item
        for item in inventory_entries
        if str(item["path"]).startswith(prefix)
    }
    copied: list[dict[str, Any]] = []
    for relative, item in sorted(expected.items()):
        source_file = archived_cache / Path(*PurePosixPath(relative).parts)
        target_file = destination / Path(*PurePosixPath(relative).parts)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target_file)
        if (
            target_file.stat().st_size != item["bytes"]
            or sha256_file(target_file) != item["sha256"]
        ):
            raise ValueError(f"Copied cache file failed integrity: {relative}")
        copied.append(
            {
                "path": relative,
                "bytes": item["bytes"],
                "sha256": item["sha256"],
            }
        )
    return {
        "files": len(copied),
        "bytes": sum(item["bytes"] for item in copied),
        "mode": "copy",
        "entries": copied,
    }


def _verify_target(
    root: Path,
    receipt: dict[str, Any],
    *,
    expected_completed: int | None,
) -> None:
    reject_secrets(receipt)
    store = Store(root)
    profile_id = str(receipt.get("profile_id") or "")
    profile = store.get_profile(profile_id)
    jobs = store.list_jobs(profile_id=profile_id)
    sources = list(receipt.get("sources") or [])
    expected = expected_completed if expected_completed is not None else len(sources)
    if len(sources) != expected or len(jobs) != expected:
        raise ValueError(
            f"Migrated completed job count mismatch: {len(jobs)} != {expected}"
        )
    expected_keys = {str(item["idempotency_key"]) for item in sources}
    actual_keys = {str(item["idempotency_key"]) for item in jobs}
    if expected_keys != actual_keys:
        raise ValueError("Migrated idempotency index does not match the receipt")
    if any(
        job.get("status") != "completed" or job.get("stage") != "completed"
        for job in jobs
    ):
        raise ValueError("Migrated jobs are not terminal completed jobs")
    source_identities = {
        _identity(str(item["bvid"]), int(item["page"])) for item in sources
    }
    if not source_identities.issubset(
        set(profile.get("baseline", {}).get("seen") or [])
    ):
        raise ValueError("Profile baseline does not include every migrated source")
    for job in jobs:
        records = store.list_artifacts(job["job_id"], kind="archive_record")
        if len(records) != 1:
            raise ValueError(f"Expected one archive record for {job['job_id']}")
        store.read_artifact(job["job_id"], records[0]["artifact_id"])
    for item in receipt.get("cache", {}).get("entries") or []:
        relative = _safe_relative(str(item["path"]))
        path = root / "cache" / "media" / Path(*relative.parts)
        if (
            not path.is_file()
            or path.stat().st_size != item["bytes"]
            or sha256_file(path) != item["sha256"]
        ):
            raise ValueError(f"Migrated cache file failed integrity: {item['path']}")
    config = _read_object(root / "config.json")
    if config.get("schema_version") != "video-content/config-v1":
        raise ValueError("Migrated configuration schema mismatch")
    values = config.get("values") if isinstance(config.get("values"), dict) else {}
    expected_root = Path(str(receipt["state_root"])).expanduser().resolve()
    if Path(str(values.get("home") or "")).expanduser().resolve() != expected_root:
        raise ValueError("Migrated configuration home mismatch")
    expected_cache = expected_root / "cache" / "media"
    if (
        Path(str(values.get("download_cache") or "")).expanduser().resolve()
        != expected_cache
    ):
        raise ValueError("Migrated configuration cache mismatch")


def _build_inventory(root: Path) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for path in _files(root):
        stat_result = path.stat()
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": stat_result.st_size,
                "sha256": sha256_file(path),
            }
        )
    return {
        "files": len(entries),
        "bytes": sum(item["bytes"] for item in entries),
        "entries": entries,
    }


def _verify_inventory(root: Path, entries: list[dict[str, Any]]) -> None:
    for item in entries:
        relative = _safe_relative(str(item.get("path") or ""))
        path = root / Path(*relative.parts)
        if not path.is_file():
            raise FileNotFoundError(f"Archived file is missing: {item.get('path')}")
        if path.stat().st_size != item.get("bytes") or sha256_file(path) != item.get(
            "sha256"
        ):
            raise ValueError(f"Archived file failed integrity: {item.get('path')}")


def _inventory_summary(root: Path) -> dict[str, int]:
    files = _files(root)
    return {
        "files": len(files),
        "bytes": sum(path.stat().st_size for path in files),
    }


def _files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def _protect_archive(root: Path) -> None:
    marker = root / "archive-protection.json"
    write_json_atomic(
        marker,
        {
            "schema_version": "video-content/archive-protection-v1",
            "protected_at": utc_now(),
            "mode": "read_only_files",
        },
    )
    for path in _files(root):
        if os.name == "nt":
            os.chmod(path, stat.S_IREAD)
        else:
            os.chmod(path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)


def _migration_paths(
    source: str | Path,
    archive: str | Path,
    target: str | Path,
) -> tuple[Path, Path, Path]:
    source_path = Path(source).expanduser().resolve()
    archive_path = Path(archive).expanduser().resolve(strict=False)
    target_path = Path(target).expanduser().resolve(strict=False)
    if not source_path.is_dir():
        raise FileNotFoundError(f"Source state directory does not exist: {source_path}")
    if source_path.parent == source_path:
        raise ValueError("Source state cannot be a filesystem root")
    paths = {source_path, archive_path, target_path}
    if len(paths) != 3:
        raise ValueError("Source, archive, and target must be different paths")
    for parent, child in (
        (source_path, archive_path),
        (source_path, target_path),
        (archive_path, source_path),
        (archive_path, target_path),
        (target_path, source_path),
        (target_path, archive_path),
    ):
        try:
            child.relative_to(parent)
        except ValueError:
            continue
        raise ValueError(
            f"Migration paths must not contain each other: {parent} -> {child}"
        )
    if source_path.drive.casefold() != archive_path.drive.casefold():
        raise ValueError(
            "Source and archive must be on the same volume for an atomic move"
        )
    return source_path, archive_path, target_path


def _require_new_destinations(archive: Path, target: Path) -> None:
    if archive.exists():
        raise FileExistsError(f"Archive destination already exists: {archive}")
    if target.exists():
        raise FileExistsError(f"State destination already exists: {target}")


def _validate_reference(root: Path, reference: dict[str, Any]) -> Path:
    path = _safe_child(root, str(reference.get("path") or ""))
    expected = str(reference.get("sha256") or "")
    if not expected or sha256_file(path) != expected:
        raise ValueError(f"Artifact hash mismatch: {path}")
    return path


def _reference_path(root: Path, reference: Any, fallback: str) -> Path:
    if isinstance(reference, dict) and reference.get("path"):
        return _safe_child(root, str(reference["path"]))
    return _safe_child(root, fallback)


def _safe_child(root: Path, value: str) -> Path:
    relative = _safe_relative(value)
    path = (root / Path(*relative.parts)).resolve()
    if root != path and root not in path.parents:
        raise ValueError(f"Path escapes archived job: {value!r}")
    if not path.is_file():
        raise FileNotFoundError(f"Archived file does not exist: {path}")
    return path


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or value.startswith("/")
        or ":" in value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"Unsafe relative path: {value!r}")
    return path


def _read_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"JSON document does not exist: {path}")
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(document, dict):
        raise TypeError(f"JSON document must be an object: {path}")
    return document


def _identity(bvid: str, page: int) -> str:
    return f"{bvid}:p{page}"


def _public_source(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "bvid": item["bvid"],
        "page": item["page"],
        "job_relative": item["job_relative"],
        "appmsgid": item["appmsgid"],
        "published": False,
    }


def _nonnegative_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise TypeError(f"{label} must be a non-negative integer")
    return value


if __name__ == "__main__":
    main()
