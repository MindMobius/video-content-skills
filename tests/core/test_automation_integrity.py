from __future__ import annotations

import hashlib
from pathlib import Path

from video_subtitle.core.automation_integrity import (
    audit_automation_job,
    audit_automation_store,
)
from video_subtitle.core.automation_job import (
    get_automation_job,
    initialize_automation_job,
)
from video_subtitle.core.util import read_json, write_json_atomic


def _profile() -> dict:
    return {
        "profile_id": "profile-integrity",
        "version": 1,
        "retry_policy": {
            "max_technical_attempts": 2,
            "max_content_repairs": 1,
            "backoff_seconds": 1,
        },
    }


def _source(bvid: str) -> dict:
    return {
        "platform": "bilibili",
        "bvid": bvid,
        "page": 1,
        "title": bvid,
        "url": f"https://www.bilibili.com/video/{bvid}/",
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _job(tmp_path: Path, bvid: str = "BV1integrity") -> Path:
    return Path(
        initialize_automation_job(tmp_path, _source(bvid), _profile())["job_path"]
    )


def _set_artifact(
    job_path: Path,
    *,
    kind: str,
    path: str,
    sha256: str | None = None,
    status: str | None = None,
) -> None:
    document = read_json(job_path)
    metadata: dict[str, str] = {"path": path}
    if sha256 is not None:
        metadata["sha256"] = sha256
    if status is not None:
        metadata["status"] = status
    document["artifacts"][kind] = metadata
    write_json_atomic(job_path, document)


def _complete_job(job_path: Path, *, appmsgid: str) -> None:
    root = job_path.parent
    receipt = root / "wechat-draft-receipt.json"
    write_json_atomic(
        receipt,
        {
            "schema_version": "video-content/wechat-draft-receipt-v1",
            "project_id": "content_0123456789abcdef",
            "deliverable_id": "dlv-001",
            "fidelity_audit_id": "audit-001",
            "appmsgid": appmsgid,
            "published": False,
            "publish_actions_performed": [],
        },
    )
    binding = root / "handoff-binding.json"
    job = read_json(job_path)
    write_json_atomic(
        binding,
        {
            "schema_version": "video-automation/handoff-binding-v1",
            "binding_id": f"binding_{job['job_id'][-16:]}",
            "job_id": job["job_id"],
            "authorization_id": "auth-watch-later",
            "project_id": "content_0123456789abcdef",
            "deliverable_id": "dlv-001",
            "fidelity_audit_id": "audit-001",
            "receipt_path": "wechat-draft-receipt.json",
            "receipt_sha256": _sha256(receipt),
            "appmsgid": appmsgid,
            "created_at": "2026-08-17T00:00:00Z",
        },
    )
    job["status"] = "completed"
    job["stage"] = "completed"
    job["artifacts"]["handoff_binding"] = {
        "path": "handoff-binding.json",
        "sha256": _sha256(binding),
        "status": "valid",
    }
    job["timestamps"]["finished_at"] = "2026-08-17T00:00:00Z"
    job["timestamps"]["updated_at"] = "2026-08-17T00:00:00Z"
    write_json_atomic(job_path, job)


def test_job_audit_detects_missing_and_hash_mismatch(tmp_path: Path) -> None:
    job_path = _job(tmp_path)
    valid = job_path.parent / "valid.json"
    valid.write_text("valid", encoding="utf-8")
    changed = job_path.parent / "changed.json"
    changed.write_text("changed", encoding="utf-8")
    _set_artifact(
        job_path,
        kind="valid",
        path="valid.json",
        sha256=_sha256(valid),
    )
    _set_artifact(
        job_path,
        kind="changed",
        path="changed.json",
        sha256="0" * 64,
    )
    _set_artifact(
        job_path,
        kind="missing",
        path="missing.json",
        sha256="1" * 64,
    )

    report = audit_automation_job(job_path)
    by_kind = {item["kind"]: item for item in report["artifacts"]}

    assert report["valid"] is False
    assert by_kind["valid"]["hash_status"] == "match"
    assert by_kind["changed"]["hash_status"] == "mismatch"
    assert by_kind["missing"]["exists"] is False


def test_legacy_nested_path_is_repaired_by_hash_without_moving_files(
    tmp_path: Path,
) -> None:
    job_path = _job(tmp_path)
    root = job_path.parent
    canonical = root / "evidence" / "audit.json"
    canonical.parent.mkdir()
    canonical.write_text("same", encoding="utf-8")
    legacy_relative = (
        Path(".video-subtitle-local")
        / "automation-store"
        / "jobs"
        / read_json(job_path)["job_id"]
        / "evidence"
        / "audit.json"
    )
    nested = root / legacy_relative
    nested.parent.mkdir(parents=True)
    nested.write_text("same", encoding="utf-8")
    _set_artifact(
        job_path,
        kind="fidelity_audit",
        path=legacy_relative.as_posix(),
        sha256=_sha256(canonical),
        status="pass",
    )

    before = audit_automation_job(job_path)
    assert before["valid"] is False
    assert before["artifacts"][0]["noncanonical"] is True
    assert before["artifacts"][0]["repairable"] is True

    repaired = audit_automation_job(job_path, repair_paths=True)

    assert repaired["valid"] is True
    assert repaired["repairs"][0]["new_path"] == "evidence/audit.json"
    assert get_automation_job(job_path)["artifacts"]["fidelity_audit"]["path"] == (
        "evidence/audit.json"
    )
    assert canonical.is_file()
    assert nested.is_file()


def test_manifest_hash_can_be_a_verified_historical_canonical_pin(
    tmp_path: Path,
) -> None:
    job_path = _job(tmp_path)
    root = job_path.parent
    manifest = root / "evidence" / "manifest.json"
    manifest.parent.mkdir()
    write_json_atomic(
        manifest,
        {
            "schema_version": "video-subtitle/v1",
            "status": "completed",
            "artifacts": [],
            "sources": [],
        },
    )
    source_sha256 = _sha256(manifest)
    report = root / "evidence" / "subtitle.canonical.report.json"
    write_json_atomic(
        report,
        {
            "schema_version": "video-subtitle/canonical-v1",
            "canonical_id": "canonical_0123456789abcdef",
            "manifest_sha256": source_sha256,
            "status": "usable",
        },
    )
    report_sha256 = _sha256(report)
    manifest_document = read_json(manifest)
    manifest_document["canonical_subtitle"] = {
        "canonical_id": "canonical_0123456789abcdef",
        "status": "usable",
        "report_path": str(report),
        "report_sha256": report_sha256,
        "source_manifest_sha256": source_sha256,
    }
    write_json_atomic(manifest, manifest_document)
    _set_artifact(
        job_path,
        kind="subtitle_manifest",
        path="evidence/manifest.json",
        sha256=source_sha256,
        status="completed",
    )
    _set_artifact(
        job_path,
        kind="canonical_subtitle",
        path="evidence/subtitle.canonical.report.json",
        sha256=report_sha256,
        status="usable",
    )

    report_result = audit_automation_job(job_path)
    by_kind = {item["kind"]: item for item in report_result["artifacts"]}

    assert report_result["valid"] is True
    assert by_kind["subtitle_manifest"]["hash_status"] == "historical_pin"


def test_completed_job_requires_valid_binding_and_receipt(tmp_path: Path) -> None:
    job_path = _job(tmp_path)
    job = read_json(job_path)
    job["status"] = "completed"
    job["stage"] = "completed"
    job["timestamps"]["finished_at"] = "2026-08-17T00:00:00Z"
    write_json_atomic(job_path, job)

    report = audit_automation_job(job_path)

    assert report["valid"] is False
    assert "COMPLETED_WITHOUT_HANDOFF_BINDING" in report["errors"]


def test_store_audit_detects_duplicate_appmsgid(tmp_path: Path) -> None:
    first = _job(tmp_path, "BV1integrityA")
    second = _job(tmp_path, "BV1integrityB")
    _complete_job(first, appmsgid="123456789")
    _complete_job(second, appmsgid="123456789")

    report = audit_automation_store(tmp_path)

    assert report["valid"] is False
    assert report["summary"]["by_status"] == {"completed": 2}
    assert report["duplicate_appmsgids"] == ["123456789"]
    assert len(report["drafts"]) == 2
