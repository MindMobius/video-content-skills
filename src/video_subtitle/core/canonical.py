"""Agent-authored canonical subtitles derived from immutable evidence."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from .evidence import list_subtitle_evidence_for_manifest
from .locking import exclusive_file_lock
from .srt import Cue, parse_srt, write_cues_json, write_srt, write_transcript_markdown
from .util import read_json, utc_now, write_json_atomic

SCHEMA_VERSION = "video-subtitle/canonical-v1"
SOURCE = "canonical_subtitle:agent"


def save_canonical_subtitle(
    manifest_path: Path,
    *,
    document: dict[str, Any],
) -> dict[str, Any]:
    """Validate and persist one canonical subtitle without modifying raw evidence."""
    manifest_path = _require_manifest(manifest_path)
    if not isinstance(document, dict):
        raise TypeError("Canonical subtitle document must be a JSON object")
    current_hash = _sha256_file(manifest_path)
    if str(document.get("manifest_sha256") or "") != current_hash:
        raise ValueError(
            "Canonical subtitle manifest hash does not match current manifest"
        )
    status = str(document.get("status") or "").strip()
    if status not in {"usable", "unusable"}:
        raise ValueError("Canonical subtitle status must be usable or unusable")
    catalog = list_subtitle_evidence_for_manifest(manifest_path)
    evidence_by_id = {item["evidence_id"]: item for item in catalog["evidence"]}
    evidence = _validate_evidence(document.get("evidence"), evidence_by_id)
    unresolved = _validate_unresolved(document.get("unresolved"))
    decisions = copy.deepcopy(document.get("decisions") or [])
    if not isinstance(decisions, list):
        raise TypeError("Canonical subtitle decisions must be an array")
    termination = copy.deepcopy(document.get("termination"))
    if status == "usable":
        if any(item["blocking"] for item in unresolved):
            raise ValueError(
                "A usable canonical subtitle cannot contain blocking issues"
            )
        if termination is not None:
            raise ValueError("A usable canonical subtitle cannot contain termination")
        cues = _validate_cues(document.get("cues"), evidence_by_id)
        if not cues:
            raise ValueError("A usable canonical subtitle requires at least one cue")
    else:
        cues = _validate_cues(document.get("cues") or [], evidence_by_id)
        if cues:
            raise ValueError(
                "An unusable canonical subtitle cannot contain usable cues"
            )
        if (
            not isinstance(termination, dict)
            or not str(termination.get("code") or "").strip()
        ):
            raise ValueError("An unusable canonical subtitle requires termination")

    identity = {
        "manifest_sha256": current_hash,
        "status": status,
        "evidence": evidence,
        "cues": [item for item in cues],
        "decisions": decisions,
        "unresolved": unresolved,
        "termination": termination,
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    canonical_id = f"canonical_{digest[:16]}"
    output_dir = manifest_path.parent
    srt_path = output_dir / "subtitle.canonical.srt"
    json_path = output_dir / "subtitle.canonical.json"
    markdown_path = output_dir / "subtitle.canonical.md"
    report_path = output_dir / "subtitle.canonical.report.json"
    if status == "usable":
        cue_objects = [
            Cue(item["start_ms"], item["end_ms"], item["text"]) for item in cues
        ]
        write_srt(srt_path, cue_objects)
        write_cues_json(json_path, cue_objects)
        title = str(
            (read_json(manifest_path).get("video") or {}).get("title") or "最佳字幕"
        )
        write_transcript_markdown(
            markdown_path, cue_objects, title=title, source=SOURCE
        )
        artifacts = {
            "srt": str(srt_path.resolve()),
            "json": str(json_path.resolve()),
            "markdown": str(markdown_path.resolve()),
            "report": str(report_path.resolve()),
        }
    else:
        for path in (srt_path, json_path, markdown_path):
            path.unlink(missing_ok=True)
        artifacts = {
            "srt": None,
            "json": None,
            "markdown": None,
            "report": str(report_path.resolve()),
        }
    result = {
        "schema_version": SCHEMA_VERSION,
        "canonical_id": canonical_id,
        "manifest_sha256": current_hash,
        "status": status,
        "evidence": evidence,
        "cues": [
            {"cue_id": f"canonical-cue-{index:05d}", **item}
            for index, item in enumerate(cues, start=1)
        ],
        "decisions": decisions,
        "unresolved": unresolved,
        "artifacts": artifacts,
        "termination": termination,
        "created_at": utc_now(),
    }
    write_json_atomic(report_path, result)
    with exclusive_file_lock(manifest_path):
        manifest = read_json(manifest_path)
        if _sha256_file(manifest_path) != current_hash:
            raise ValueError(
                "Subtitle manifest changed while canonical subtitle was written"
            )
        _remove_previous_canonical(manifest)
        report_artifact = _artifact(
            "canonical_subtitle_report",
            report_path,
            source=SOURCE,
        )
        manifest.setdefault("artifacts", []).append(report_artifact)
        if status == "usable":
            manifest.setdefault("sources", []).append(
                {
                    "kind": "canonical_subtitle",
                    "artifact_source": SOURCE,
                    "cue_count": len(cues),
                    "derived_from": [item["evidence_id"] for item in evidence],
                    "provenance_note": (
                        "Agent-authored canonical subtitle derived from immutable evidence; "
                        "raw sources remain unchanged."
                    ),
                }
            )
            manifest["artifacts"].extend(
                [
                    _artifact(
                        "canonical_subtitle_srt",
                        srt_path,
                        source=SOURCE,
                        cue_count=len(cues),
                        selected=True,
                    ),
                    _artifact("canonical_subtitle_json", json_path, source=SOURCE),
                    _artifact(
                        "canonical_transcript_markdown",
                        markdown_path,
                        source=SOURCE,
                    ),
                ]
            )
        manifest["canonical_subtitle"] = {
            "canonical_id": canonical_id,
            "status": status,
            "report_path": str(report_path.resolve()),
            "report_sha256": _sha256_file(report_path),
            "source_manifest_sha256": current_hash,
        }
        write_json_atomic(manifest_path, manifest)
    return get_canonical_subtitle(manifest_path)


def get_canonical_subtitle(manifest_path: Path) -> dict[str, Any]:
    manifest_path = _require_manifest(manifest_path)
    manifest = read_json(manifest_path)
    metadata = manifest.get("canonical_subtitle")
    if not isinstance(metadata, dict):
        raise FileNotFoundError("Canonical subtitle has not been created")
    report_path = Path(str(metadata.get("report_path") or "")).expanduser().resolve()
    try:
        report_path.relative_to(manifest_path.parent)
    except ValueError as error:
        raise ValueError(
            "Canonical report is outside the subtitle job directory"
        ) from error
    if not report_path.is_file():
        raise FileNotFoundError(f"Canonical report does not exist: {report_path}")
    if _sha256_file(report_path) != metadata.get("report_sha256"):
        raise ValueError("Canonical subtitle report hash changed")
    document = read_json(report_path)
    return {**document, "manifest_path": str(manifest_path)}


def require_usable_canonical_subtitle(manifest_path: Path) -> dict[str, Any]:
    document = get_canonical_subtitle(manifest_path)
    if document.get("status") != "usable":
        raise ValueError("Automation requires a usable canonical subtitle")
    srt_path = Path(str(document.get("artifacts", {}).get("srt") or ""))
    if not srt_path.is_file():
        raise FileNotFoundError("Usable canonical subtitle SRT is missing")
    return document


def _validate_evidence(
    value: Any, catalog: dict[str, dict[str, Any]]
) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ValueError("Canonical subtitle requires evidence references")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            raise TypeError("Canonical evidence reference must be an object")
        evidence_id = str(item.get("evidence_id") or "")
        if evidence_id in seen:
            raise ValueError(f"Duplicate canonical evidence reference: {evidence_id}")
        evidence = catalog.get(evidence_id)
        if evidence is None or not evidence.get("available"):
            raise ValueError(
                f"Unknown or unavailable canonical evidence: {evidence_id}"
            )
        path = Path(str(evidence["path"]))
        sha256 = str(item.get("sha256") or "")
        if sha256 != _sha256_file(path):
            raise ValueError(f"Canonical evidence hash changed: {evidence_id}")
        role = str(item.get("role") or "")
        if role not in {"primary", "corroborating"}:
            raise ValueError("Canonical evidence role is invalid")
        result.append({"evidence_id": evidence_id, "sha256": sha256, "role": role})
        seen.add(evidence_id)
    if not any(item["role"] == "primary" for item in result):
        raise ValueError("Canonical subtitle requires one primary evidence source")
    return result


def _validate_cues(
    value: Any, catalog: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise TypeError("Canonical subtitle cues must be an array")
    known_refs: set[str] = set()
    for evidence_id, evidence in catalog.items():
        path = Path(str(evidence.get("path") or ""))
        if not path.is_file():
            continue
        for index, _cue in enumerate(parse_srt(path), start=1):
            known_refs.add(f"{evidence_id}-cue-{index:05d}")
    result: list[dict[str, Any]] = []
    previous_end = 0
    for item in value:
        if not isinstance(item, dict):
            raise TypeError("Canonical cue must be an object")
        start_ms = item.get("start_ms")
        end_ms = item.get("end_ms")
        if not isinstance(start_ms, int) or isinstance(start_ms, bool) or start_ms < 0:
            raise ValueError("Canonical cue start_ms is invalid")
        if (
            not isinstance(end_ms, int)
            or isinstance(end_ms, bool)
            or end_ms <= start_ms
        ):
            raise ValueError("Canonical cue end_ms is invalid")
        if start_ms < previous_end:
            raise ValueError("Canonical cues must not overlap or move backwards")
        text = str(item.get("text") or "").strip()
        if not text:
            raise ValueError("Canonical cue text cannot be empty")
        evidence_refs = list(item.get("evidence_refs") or [])
        if not evidence_refs:
            raise ValueError("Canonical cue requires evidence references")
        unknown = [ref for ref in evidence_refs if ref not in known_refs]
        if unknown:
            raise ValueError(f"Canonical cue references unknown evidence: {unknown}")
        result.append(
            {
                "start_ms": start_ms,
                "end_ms": end_ms,
                "text": text,
                "evidence_refs": evidence_refs,
            }
        )
        previous_end = end_ms
    return result


def _validate_unresolved(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError("Canonical unresolved issues must be an array")
    result = []
    for item in value:
        if not isinstance(item, dict):
            raise TypeError("Canonical unresolved issue must be an object")
        issue = str(item.get("issue") or "").strip()
        if not issue:
            raise ValueError("Canonical unresolved issue cannot be empty")
        result.append(
            {
                "issue": issue,
                "blocking": bool(item.get("blocking")),
                **(
                    {"evidence_refs": list(item.get("evidence_refs") or [])}
                    if item.get("evidence_refs") is not None
                    else {}
                ),
            }
        )
    return result


def _remove_previous_canonical(manifest: dict[str, Any]) -> None:
    manifest["sources"] = [
        item
        for item in manifest.get("sources", [])
        if item.get("kind") != "canonical_subtitle"
    ]
    manifest["artifacts"] = [
        item
        for item in manifest.get("artifacts", [])
        if not str(item.get("kind") or "").startswith("canonical_")
        and item.get("kind") != "canonical_subtitle_srt"
    ]


def _artifact(
    kind: str,
    path: Path,
    *,
    source: str,
    cue_count: int | None = None,
    selected: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "kind": kind,
        "path": str(path.resolve()),
        "source": source,
        "owned_by_job": True,
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }
    if cue_count is not None:
        result["cue_count"] = cue_count
    if selected:
        result["selected"] = True
    return result


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_manifest(path: Path) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Subtitle manifest does not exist: {path}")
    manifest = read_json(path)
    if manifest.get("status") != "completed":
        raise ValueError("Canonical subtitle requires a completed subtitle manifest")
    return path
