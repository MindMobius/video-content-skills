from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from .evidence import list_subtitle_evidence_for_manifest
from .util import read_json, utc_now, write_json_atomic, write_text_atomic

ContentDocumentKind = Literal["content_map", "media_plan", "fidelity_audit"]
ContentMedium = Literal[
    "article",
    "one_page",
    "card_series",
    "brief",
    "script",
    "custom",
]
ContentFormat = Literal["markdown", "html", "svg", "json", "text"]

_DOCUMENT_VERSIONS = {
    "content_map": "video-content/content-map-v1",
    "media_plan": "video-content/media-plan-v1",
    "fidelity_audit": "video-content/fidelity-audit-v1",
}
_DOCUMENT_PREFIXES = {
    "content_map": "cmap",
    "media_plan": "mplan",
    "fidelity_audit": "audit",
}
_DOCUMENT_DIRECTORIES = {
    "content_map": "maps",
    "media_plan": "plans",
    "fidelity_audit": "audits",
}
_FORMAT_EXTENSIONS = {
    "markdown": "md",
    "html": "html",
    "svg": "svg",
    "json": "json",
    "text": "txt",
}
_ARTIFACT_COLLECTIONS = {
    "content_map": "content_maps",
    "media_plan": "media_plans",
    "fidelity_audit": "fidelity_audits",
}


def initialize_content_project(
    manifest_path: Path,
    *,
    objective: str = "faithful_information_transfer",
    audience: str = "",
    output_language: str = "zh-CN",
) -> dict[str, Any]:
    """Create an idempotent content workspace pinned to subtitle evidence hashes."""
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Subtitle manifest does not exist: {manifest_path}")
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        raise TypeError("Subtitle manifest must be a JSON object")
    if manifest.get("status") != "completed":
        raise ValueError(
            "Content work requires a completed subtitle job; "
            f"current status is {manifest.get('status')!r}"
        )

    objective = objective.strip()
    output_language = output_language.strip()
    if not objective:
        raise ValueError("objective cannot be empty")
    if not output_language:
        raise ValueError("output_language cannot be empty")

    catalog = list_subtitle_evidence_for_manifest(manifest_path)
    available = [item for item in catalog["evidence"] if item.get("available")]
    if not available:
        raise ValueError(
            "Content work requires at least one readable subtitle evidence source"
        )

    manifest_sha256 = _sha256_file(manifest_path)
    identity = {
        "manifest_sha256": manifest_sha256,
        "objective": objective,
        "audience": audience.strip(),
        "output_language": output_language,
    }
    identity_hash = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    project_id = f"content_{identity_hash[:16]}"
    project_root = manifest_path.parent / "content" / project_id
    project_path = project_root / "project.json"
    if project_path.exists():
        result = get_content_project(project_path)
        result["reused_existing_project"] = True
        return result

    project_root.mkdir(parents=True, exist_ok=False)
    for directory in ("maps", "plans", "deliverables", "audits"):
        (project_root / directory).mkdir()

    evidence_snapshot = []
    for item in available:
        evidence_path = Path(str(item["path"])).resolve()
        evidence_snapshot.append(
            {
                "evidence_id": item["evidence_id"],
                "artifact_kind": item["artifact_kind"],
                "source": item.get("source"),
                "source_kind": item.get("source_kind"),
                "layer": item.get("layer"),
                "selected": item.get("selected") is True,
                "cue_count": item.get("cue_count"),
                "path": _relative_path(evidence_path, project_root),
                "sha256": _sha256_file(evidence_path),
            }
        )

    project: dict[str, Any] = {
        "schema_version": "video-content/project-v1",
        "project_id": project_id,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "status": "initialized",
        "intent": {
            "objective": objective,
            "audience": audience.strip(),
            "output_language": output_language,
        },
        "source": {
            "manifest_path": _relative_path(manifest_path, project_root),
            "manifest_sha256": manifest_sha256,
            "job_id": manifest.get("job_id"),
            "video": catalog.get("video") or {},
            "selected_source": catalog.get("selected_source"),
            "review": catalog.get("review"),
            "evidence": evidence_snapshot,
        },
        "artifacts": {
            "content_maps": [],
            "media_plans": [],
            "deliverables": [],
            "fidelity_audits": [],
        },
        "current": {
            "content_map_id": None,
            "media_plan_id": None,
            "deliverable_id": None,
            "fidelity_audit_id": None,
        },
        "next_action": {
            "code": "BUILD_CONTENT_MAP",
            "message": (
                "Read the pinned evidence in bounded time ranges, then author a "
                "video-content/content-map-v1 document."
            ),
        },
    }
    write_json_atomic(project_path, project)
    result = get_content_project(project_path)
    result["reused_existing_project"] = False
    return result


def get_content_project(project_path: Path) -> dict[str, Any]:
    """Read project state and attach a deterministic integrity summary."""
    project_path = _require_project_path(project_path)
    project = read_json(project_path)
    if not isinstance(project, dict):
        raise TypeError("Content project must be a JSON object")
    _validate_project_identity(project, project_path)
    return {
        **project,
        "project_path": str(project_path),
        "integrity": validate_content_project(project_path),
    }


def save_content_document(
    project_path: Path,
    *,
    kind: ContentDocumentKind,
    document: dict[str, Any],
) -> dict[str, Any]:
    """Validate and version an Agent-authored semantic document without rewriting it."""
    project_path = _require_project_path(project_path)
    project = read_json(project_path)
    _validate_project_identity(project, project_path)
    if kind not in _DOCUMENT_VERSIONS:
        raise ValueError(f"Unsupported content document kind: {kind}")
    if not isinstance(document, dict):
        raise TypeError("Content document must be a JSON object")
    project["_project_path"] = str(project_path)
    try:
        _validate_content_document(project, kind, document)
    finally:
        project.pop("_project_path", None)

    collection_name = _ARTIFACT_COLLECTIONS[kind]
    collection = project["artifacts"][collection_name]
    revision = len(collection) + 1
    artifact_id = f"{_DOCUMENT_PREFIXES[kind]}-{revision:03d}"
    relative_path = (
        Path(_DOCUMENT_DIRECTORIES[kind])
        / f"{artifact_id}.{kind.replace('_', '-')}.json"
    )
    artifact_path = project_path.parent / relative_path
    write_json_atomic(artifact_path, document)
    metadata = {
        "artifact_id": artifact_id,
        "kind": kind,
        "revision": revision,
        "path": relative_path.as_posix(),
        "sha256": _sha256_file(artifact_path),
        "created_at": utc_now(),
    }
    if kind == "fidelity_audit":
        metadata["deliverable_id"] = document["target"]["deliverable_id"]
        metadata["audit_status"] = document["status"]
    collection.append(metadata)
    project["current"][f"{kind}_id"] = artifact_id

    if kind == "content_map":
        project["current"]["media_plan_id"] = None
        project["current"]["deliverable_id"] = None
        project["current"]["fidelity_audit_id"] = None
        project["status"] = "mapped"
        next_action = "RESOLVE_MEDIUM_DECISION"
        next_message = (
            "Use the user's explicit carrier request or delegation; otherwise "
            "pause and ask before saving a media plan."
        )
    elif kind == "media_plan":
        project["current"]["deliverable_id"] = None
        project["current"]["fidelity_audit_id"] = None
        project["status"] = "planned"
        next_action = "CREATE_DELIVERABLE"
        next_message = (
            "Create only the selected deliverable and declare its used claims."
        )
    else:
        audit_status = document["status"]
        project["status"] = "complete" if audit_status != "fail" else "needs_revision"
        next_action = "DELIVER" if audit_status != "fail" else "REVISE_DELIVERABLE"
        next_message = (
            "Deliver the audited artifact with warnings disclosed."
            if audit_status != "fail"
            else "Revise the deliverable from the audit findings, then audit the new revision."
        )
    project["next_action"] = {"code": next_action, "message": next_message}
    project["updated_at"] = utc_now()
    write_json_atomic(project_path, project)
    return {
        "schema_version": "video-content/save-result-v1",
        "project_id": project["project_id"],
        "artifact": metadata,
        "project_status": project["status"],
        "next_action": project["next_action"],
    }


def save_content_deliverable(
    project_path: Path,
    *,
    medium: ContentMedium,
    format: ContentFormat,
    content: str,
    title: str,
    used_claim_ids: list[str],
    used_caveat_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Version an Agent-authored deliverable and bind it to its semantic sources."""
    project_path = _require_project_path(project_path)
    project = read_json(project_path)
    _validate_project_identity(project, project_path)
    if medium not in {
        "article",
        "one_page",
        "card_series",
        "brief",
        "script",
        "custom",
    }:
        raise ValueError(f"Unsupported medium: {medium}")
    if format not in _FORMAT_EXTENSIONS:
        raise ValueError(f"Unsupported deliverable format: {format}")
    if not title.strip():
        raise ValueError("Deliverable title cannot be empty")
    if not content.strip():
        raise ValueError("Deliverable content cannot be empty")
    if len(content) > 2_000_000:
        raise ValueError("Deliverable content exceeds the 2,000,000 character limit")
    if format == "json":
        try:
            json.loads(content)
        except json.JSONDecodeError as error:
            raise ValueError("JSON deliverable content is invalid") from error

    content_map, map_metadata = _current_document(project_path, project, "content_map")
    media_plan, plan_metadata = _current_document(project_path, project, "media_plan")
    if media_plan.get("content_map_sha256") != map_metadata["sha256"]:
        raise ValueError("Current media plan targets an older content map")
    rendering_format = (media_plan.get("rendering_contract") or {}).get("format")
    if rendering_format != format:
        raise ValueError(
            "Deliverable format must match media_plan.rendering_contract.format; "
            f"expected {rendering_format!r}"
        )
    if media_plan.get("selected_medium") != medium:
        raise ValueError(
            "Deliverable medium must match media_plan.selected_medium; "
            f"expected {media_plan.get('selected_medium')!r}"
        )
    claim_ids = _ids(content_map.get("claims", []), "claim_id")
    caveat_ids = _ids(content_map.get("caveats", []), "caveat_id")
    used_claim_ids = _unique_strings(used_claim_ids, "used_claim_ids")
    used_caveat_ids = _unique_strings(used_caveat_ids or [], "used_caveat_ids")
    _require_known_refs(used_claim_ids, claim_ids, "used_claim_ids")
    _require_known_refs(used_caveat_ids, caveat_ids, "used_caveat_ids")
    _require_included(
        media_plan.get("required_claim_ids", []),
        used_claim_ids,
        "required claim",
    )
    _require_included(
        media_plan.get("required_caveat_ids", []),
        used_caveat_ids,
        "required caveat",
    )

    collection = project["artifacts"]["deliverables"]
    revision = len(collection) + 1
    deliverable_id = f"dlv-{revision:03d}"
    extension = _FORMAT_EXTENSIONS[format]
    relative_path = Path("deliverables") / f"{deliverable_id}.{medium}.{extension}"
    artifact_path = project_path.parent / relative_path
    write_text_atomic(artifact_path, content)
    metadata = {
        "artifact_id": deliverable_id,
        "kind": "deliverable",
        "revision": revision,
        "medium": medium,
        "format": format,
        "title": title.strip(),
        "path": relative_path.as_posix(),
        "sha256": _sha256_file(artifact_path),
        "content_map_id": map_metadata["artifact_id"],
        "content_map_sha256": map_metadata["sha256"],
        "media_plan_id": plan_metadata["artifact_id"],
        "media_plan_sha256": plan_metadata["sha256"],
        "used_claim_ids": used_claim_ids,
        "used_caveat_ids": used_caveat_ids,
        "created_at": utc_now(),
    }
    collection.append(metadata)
    project["current"]["deliverable_id"] = deliverable_id
    project["current"]["fidelity_audit_id"] = None
    project["status"] = "drafted"
    project["next_action"] = {
        "code": "AUDIT_FIDELITY",
        "message": (
            "Compare every material statement in the deliverable with the content map "
            "and pinned subtitle evidence, then save a fidelity audit."
        ),
    }
    project["updated_at"] = utc_now()
    write_json_atomic(project_path, project)
    return {
        "schema_version": "video-content/deliverable-result-v1",
        "project_id": project["project_id"],
        "deliverable": metadata,
        "project_status": project["status"],
        "next_action": project["next_action"],
    }


def read_content_artifact(
    project_path: Path,
    *,
    artifact: str = "latest_deliverable",
    artifact_id: str = "",
    offset: int = 0,
    max_chars: int = 20_000,
) -> dict[str, Any]:
    """Read a bounded chunk from one registered content artifact."""
    if offset < 0:
        raise ValueError("offset cannot be negative")
    if not 1 <= max_chars <= 100_000:
        raise ValueError("max_chars must be between 1 and 100000")
    project_path = _require_project_path(project_path)
    project = read_json(project_path)
    _validate_project_identity(project, project_path)
    metadata = _select_artifact(project, artifact, artifact_id)
    path = project_path if metadata is None else _artifact_path(project_path, metadata)
    content = path.read_text(encoding="utf-8", errors="replace")
    chunk = content[offset : offset + max_chars]
    return {
        "schema_version": "video-content/artifact-read-v1",
        "project_id": project["project_id"],
        "artifact": artifact,
        "artifact_id": metadata.get("artifact_id") if metadata else "project",
        "path": str(path),
        "offset": offset,
        "next_offset": offset + len(chunk),
        "total_chars": len(content),
        "has_more": offset + len(chunk) < len(content),
        "content": chunk,
    }


def validate_content_project(project_path: Path) -> dict[str, Any]:
    """Verify source and artifact immutability plus completion bookkeeping."""
    project_path = _require_project_path(project_path)
    project = read_json(project_path)
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    try:
        _validate_project_identity(project, project_path)
    except (TypeError, ValueError) as error:
        errors.append({"code": "INVALID_PROJECT", "message": str(error)})
        return _validation_result(project, errors, warnings, ready=False)

    try:
        manifest_path = _resolve_source_path(
            project_path, str(project["source"]["manifest_path"])
        )
    except ValueError as error:
        errors.append({"code": "INVALID_SOURCE_MANIFEST_PATH", "message": str(error)})
    else:
        _check_file_hash(
            manifest_path,
            str(project["source"]["manifest_sha256"]),
            "SOURCE_MANIFEST",
            errors,
        )
    for evidence in project["source"]["evidence"]:
        try:
            evidence_path = _resolve_source_path(project_path, str(evidence["path"]))
        except (KeyError, ValueError) as error:
            errors.append(
                {
                    "code": "INVALID_EVIDENCE_PATH",
                    "message": str(error),
                }
            )
            continue
        _check_file_hash(
            evidence_path,
            str(evidence.get("sha256") or ""),
            f"EVIDENCE_{evidence.get('evidence_id', 'unknown')}",
            errors,
        )

    for collection_name, entries in project["artifacts"].items():
        if not isinstance(entries, list):
            errors.append(
                {
                    "code": "INVALID_ARTIFACT_COLLECTION",
                    "message": f"artifacts.{collection_name} must be a list",
                }
            )
            continue
        for entry in entries:
            try:
                artifact_path = _artifact_path(project_path, entry)
            except (TypeError, ValueError) as error:
                errors.append(
                    {
                        "code": "INVALID_ARTIFACT_PATH",
                        "message": str(error),
                    }
                )
                continue
            _check_file_hash(
                artifact_path,
                str(entry.get("sha256") or ""),
                f"ARTIFACT_{entry.get('artifact_id', 'unknown')}",
                errors,
            )

    current_deliverable = _metadata_by_id(
        project["artifacts"]["deliverables"],
        project["current"].get("deliverable_id"),
    )
    current_audit = _metadata_by_id(
        project["artifacts"]["fidelity_audits"],
        project["current"].get("fidelity_audit_id"),
    )
    ready = False
    if current_deliverable is None:
        warnings.append(
            {"code": "NO_DELIVERABLE", "message": "No deliverable has been saved yet"}
        )
    elif current_audit is None:
        warnings.append(
            {
                "code": "UNAUDITED_DELIVERABLE",
                "message": "The current deliverable has no fidelity audit",
            }
        )
    elif current_audit.get("deliverable_id") != current_deliverable.get("artifact_id"):
        warnings.append(
            {
                "code": "STALE_FIDELITY_AUDIT",
                "message": "The current fidelity audit targets an older deliverable",
            }
        )
    elif current_audit.get("audit_status") in {"pass", "pass_with_warnings"}:
        ready = not errors
        if current_audit.get("audit_status") == "pass_with_warnings":
            warnings.append(
                {
                    "code": "FIDELITY_AUDIT_WARNINGS",
                    "message": (
                        "The current deliverable passed with warnings; read and "
                        "disclose the current fidelity audit before delivery"
                    ),
                    "artifact_id": str(current_audit.get("artifact_id") or ""),
                }
            )

    return _validation_result(project, errors, warnings, ready=ready)


def safe_content_project_id(value: str) -> str:
    if not re.fullmatch(r"content_[a-f0-9]{16}", value):
        raise ValueError("Invalid content project id")
    return value


def _validate_project_identity(project: Any, project_path: Path) -> None:
    if not isinstance(project, dict):
        raise TypeError("Content project must be a JSON object")
    if project.get("schema_version") != "video-content/project-v1":
        raise ValueError("Unsupported content project schema_version")
    project_id = safe_content_project_id(str(project.get("project_id") or ""))
    if project_path.parent.name != project_id:
        raise ValueError("Content project id does not match its directory")
    if not isinstance(project.get("source"), dict):
        raise TypeError("Content project source must be an object")
    if not isinstance(project["source"].get("evidence"), list):
        raise TypeError("Content project source.evidence must be a list")
    _require_fields(
        project["source"],
        ("manifest_path", "manifest_sha256", "evidence"),
        "Content project source",
    )
    if not isinstance(project.get("artifacts"), dict):
        raise TypeError("Content project artifacts must be an object")
    _require_fields(
        project["artifacts"],
        ("content_maps", "media_plans", "deliverables", "fidelity_audits"),
        "Content project artifacts",
    )
    if not isinstance(project.get("current"), dict):
        raise TypeError("Content project current must be an object")
    _require_fields(
        project["current"],
        ("content_map_id", "media_plan_id", "deliverable_id", "fidelity_audit_id"),
        "Content project current",
    )


def _validate_content_document(
    project: dict[str, Any],
    kind: ContentDocumentKind,
    document: dict[str, Any],
) -> None:
    expected_version = _DOCUMENT_VERSIONS[kind]
    if document.get("schema_version") != expected_version:
        raise ValueError(f"{kind}.schema_version must be {expected_version!r}")
    if document.get("project_id") != project["project_id"]:
        raise ValueError(f"{kind}.project_id does not match the content project")
    if document.get("source_manifest_sha256") != project["source"]["manifest_sha256"]:
        raise ValueError(f"{kind}.source_manifest_sha256 does not match the project")
    if kind == "content_map":
        _validate_content_map(project, document)
    elif kind == "media_plan":
        _validate_media_plan(project, document)
    else:
        _validate_fidelity_audit(project, document)


def _validate_content_map(project: dict[str, Any], document: dict[str, Any]) -> None:
    required = (
        "content_type",
        "summary",
        "coverage",
        "evidence_refs",
        "claims",
        "caveats",
        "uncertainties",
        "agent_inferences",
        "sections",
    )
    _require_fields(document, required, "content_map")
    if document["content_type"] not in {
        "argument",
        "explanation",
        "tutorial",
        "interview",
        "narrative",
        "mixed",
    }:
        raise ValueError("content_map.content_type is unsupported")
    if not str(document["summary"]).strip():
        raise ValueError("content_map.summary cannot be empty")
    evidence_ids = {str(item["evidence_id"]) for item in project["source"]["evidence"]}
    evidence_refs = _unique_id_map(
        document["evidence_refs"], "evidence_ref_id", "content_map.evidence_refs"
    )
    for item in evidence_refs.values():
        if item.get("evidence_id") not in evidence_ids:
            raise ValueError(
                "content_map evidence_ref uses an unknown evidence_id: "
                f"{item.get('evidence_id')!r}"
            )
        _validate_range(item, "content_map.evidence_refs")
        if item.get("relationship") not in {"supports", "context", "conflicts"}:
            raise ValueError("content_map evidence_ref relationship is unsupported")
        if not str(item.get("text") or "").strip():
            raise ValueError("content_map evidence_ref text cannot be empty")

    claims = _unique_id_map(document["claims"], "claim_id", "content_map.claims")
    if not claims:
        raise ValueError("content_map.claims must contain at least one claim")
    for claim in claims.values():
        _require_fields(claim, ("text", "kind", "evidence_refs"), "claim")
        if claim["kind"] not in {
            "fact",
            "definition",
            "explanation",
            "opinion",
            "prediction",
            "recommendation",
            "instruction",
            "example",
        }:
            raise ValueError("claim.kind is unsupported")
        _require_known_refs(
            claim["evidence_refs"], evidence_refs.keys(), "claim.evidence_refs"
        )

    coverage = document["coverage"]
    _require_fields(coverage, ("mode", "evidence_ids", "analyzed_ranges"), "coverage")
    if coverage["mode"] not in {"full", "partial"}:
        raise ValueError("coverage.mode must be full or partial")
    _require_known_refs(coverage["evidence_ids"], evidence_ids, "coverage.evidence_ids")
    if not coverage["analyzed_ranges"]:
        raise ValueError("coverage.analyzed_ranges must not be empty")
    for item in coverage["analyzed_ranges"]:
        _validate_range(item, "coverage.analyzed_ranges")

    caveats = _unique_id_map(document["caveats"], "caveat_id", "content_map.caveats")
    uncertainties = _unique_id_map(
        document["uncertainties"], "uncertainty_id", "content_map.uncertainties"
    )
    for caveat in caveats.values():
        _require_known_refs(
            caveat.get("claim_ids", []), claims.keys(), "caveat.claim_ids"
        )
        _require_known_refs(
            caveat.get("evidence_refs", []),
            evidence_refs.keys(),
            "caveat.evidence_refs",
        )
    for uncertainty in uncertainties.values():
        _require_known_refs(
            uncertainty.get("claim_ids", []),
            claims.keys(),
            "uncertainty.claim_ids",
        )
        _require_known_refs(
            uncertainty.get("evidence_refs", []),
            evidence_refs.keys(),
            "uncertainty.evidence_refs",
        )
    for inference in document["agent_inferences"]:
        _require_known_refs(
            inference.get("evidence_refs", []),
            evidence_refs.keys(),
            "agent_inference.evidence_refs",
        )
    for section in document["sections"]:
        _require_known_refs(
            section.get("claim_ids", []), claims.keys(), "section.claim_ids"
        )
    thesis = document.get("thesis")
    if thesis is not None:
        if not isinstance(thesis, dict):
            raise TypeError("content_map.thesis must be an object or null")
        _require_known_refs(
            thesis.get("claim_ids", []), claims.keys(), "thesis.claim_ids"
        )


def _validate_media_plan(project: dict[str, Any], document: dict[str, Any]) -> None:
    required = (
        "content_map_sha256",
        "communication_goal",
        "audience",
        "selected_medium",
        "selection_authority",
        "selection_reason",
        "adaptation_strategy",
        "narrative_voice",
        "required_claim_ids",
        "required_caveat_ids",
        "omissions",
        "structure",
        "rendering_contract",
        "fidelity_rules",
    )
    _require_fields(document, required, "media_plan")
    content_map, metadata = _current_document_by_project(project, "content_map")
    if document["content_map_sha256"] != metadata["sha256"]:
        raise ValueError("media_plan.content_map_sha256 does not match the current map")
    if document["selected_medium"] not in {
        "article",
        "one_page",
        "card_series",
        "brief",
        "script",
        "custom",
    }:
        raise ValueError("media_plan.selected_medium is unsupported")
    if document["selection_authority"] not in {
        "user_selected",
        "user_delegated",
    }:
        raise ValueError("media_plan.selection_authority is unsupported")
    claims = _ids(content_map["claims"], "claim_id")
    caveats = _ids(content_map["caveats"], "caveat_id")
    speakers = _ids(content_map.get("speakers", []), "speaker_id")
    adaptation = document["adaptation_strategy"]
    _require_fields(
        adaptation,
        ("relationship_to_source", "rationale", "transformations"),
        "adaptation_strategy",
    )
    if adaptation["relationship_to_source"] not in {
        "reconstructed_for_medium",
        "preserve_source_order",
    }:
        raise ValueError("adaptation_strategy.relationship_to_source is unsupported")
    if not str(adaptation["rationale"]).strip():
        raise ValueError("adaptation_strategy.rationale cannot be empty")
    if not adaptation["transformations"]:
        raise ValueError("adaptation_strategy.transformations must not be empty")

    narrative_voice = document["narrative_voice"]
    _require_fields(
        narrative_voice,
        ("mode", "speaker_ids", "description", "prohibited_wrappers"),
        "narrative_voice",
    )
    if narrative_voice["mode"] not in {
        "source_author",
        "preserve_speakers",
        "editorial",
    }:
        raise ValueError("narrative_voice.mode is unsupported")
    _require_known_refs(
        narrative_voice["speaker_ids"], speakers, "narrative_voice.speaker_ids"
    )
    if (
        narrative_voice["mode"] == "source_author"
        and not narrative_voice["speaker_ids"]
    ):
        raise ValueError("source_author narrative voice requires source speakers")
    if (
        narrative_voice["mode"] == "preserve_speakers"
        and not narrative_voice["speaker_ids"]
    ):
        raise ValueError("preserve_speakers narrative voice requires speakers")
    if not str(narrative_voice["description"]).strip():
        raise ValueError("narrative_voice.description cannot be empty")
    if not document["required_claim_ids"]:
        raise ValueError("media_plan.required_claim_ids must not be empty")
    _require_known_refs(document["required_claim_ids"], claims, "required_claim_ids")
    _require_known_refs(document["required_caveat_ids"], caveats, "required_caveat_ids")
    omitted_claim_ids = []
    for omission in document["omissions"]:
        _require_fields(omission, ("claim_id", "reason"), "omission")
        omitted_claim_ids.append(omission["claim_id"])
    _require_known_refs(omitted_claim_ids, claims, "omissions.claim_id")
    overlap = set(document["required_claim_ids"]) & set(omitted_claim_ids)
    if overlap:
        raise ValueError(f"Required claims cannot also be omitted: {sorted(overlap)}")
    for unit in document["structure"]:
        _require_known_refs(unit.get("claim_ids", []), claims, "structure.claim_ids")
        _require_known_refs(unit.get("caveat_ids", []), caveats, "structure.caveat_ids")


def _validate_fidelity_audit(project: dict[str, Any], document: dict[str, Any]) -> None:
    required = (
        "content_map_sha256",
        "target",
        "status",
        "claim_checks",
        "required_element_checks",
        "findings",
        "repair_actions",
    )
    _require_fields(document, required, "fidelity_audit")
    content_map, map_metadata = _current_document_by_project(project, "content_map")
    if document["content_map_sha256"] != map_metadata["sha256"]:
        raise ValueError("fidelity_audit.content_map_sha256 does not match current map")
    target = document["target"]
    _require_fields(target, ("deliverable_id", "sha256"), "fidelity_audit.target")
    deliverable = _metadata_by_id(
        project["artifacts"]["deliverables"], target["deliverable_id"]
    )
    if deliverable is None:
        raise ValueError("fidelity_audit targets an unknown deliverable")
    if target["deliverable_id"] != project["current"].get("deliverable_id"):
        raise ValueError("fidelity_audit must target the current deliverable")
    if target["sha256"] != deliverable["sha256"]:
        raise ValueError("fidelity_audit target hash does not match the deliverable")
    if document["status"] not in {"pass", "pass_with_warnings", "fail"}:
        raise ValueError("fidelity_audit.status is unsupported")
    claims = _ids(content_map["claims"], "claim_id")
    caveats = _ids(content_map["caveats"], "caveat_id")
    media_plan, _ = _current_document_by_project(project, "media_plan")
    error_findings = 0
    checked_claim_ids: set[str] = set()
    for check in document["claim_checks"]:
        _require_fields(check, ("statement", "claim_ids", "verdict"), "claim_check")
        _require_known_refs(check["claim_ids"], claims, "claim_check.claim_ids")
        checked_claim_ids.update(check["claim_ids"])
        if check["verdict"] not in {
            "faithful",
            "compressed_but_faithful",
            "distorted",
            "unsupported",
        }:
            raise ValueError("claim_check.verdict is unsupported")
        if check["verdict"] in {"distorted", "unsupported"}:
            error_findings += 1
        elif not check["claim_ids"]:
            raise ValueError(
                "A supported claim_check must reference at least one claim"
            )
    checked_required_elements: set[tuple[str, str]] = set()
    for check in document["required_element_checks"]:
        _require_fields(check, ("element_type", "element_id", "present"), "element")
        if check["element_type"] not in {"claim", "caveat"}:
            raise ValueError("required_element.element_type is unsupported")
        known = claims if check["element_type"] == "claim" else caveats
        _require_known_refs([check["element_id"]], known, "required_element.element_id")
        key = (check["element_type"], check["element_id"])
        if key in checked_required_elements:
            raise ValueError(f"Duplicate required_element_check: {key}")
        checked_required_elements.add(key)
        if check["present"] is not True:
            error_findings += 1
    missing_claim_checks = sorted(
        set(deliverable["used_claim_ids"]) - checked_claim_ids
    )
    if missing_claim_checks:
        raise ValueError(
            "fidelity_audit.claim_checks does not cover used claims: "
            f"{missing_claim_checks}"
        )
    expected_required_elements = {
        *(("claim", item) for item in media_plan["required_claim_ids"]),
        *(("caveat", item) for item in media_plan["required_caveat_ids"]),
    }
    missing_required_checks = sorted(
        expected_required_elements - checked_required_elements
    )
    if missing_required_checks:
        raise ValueError(
            "fidelity_audit.required_element_checks is incomplete: "
            f"{missing_required_checks}"
        )
    for finding in document["findings"]:
        if finding.get("severity") == "error":
            error_findings += 1
    if document["status"] in {"pass", "pass_with_warnings"} and error_findings:
        raise ValueError("A passing fidelity audit cannot contain semantic errors")
    if document["status"] == "fail" and error_findings == 0:
        raise ValueError(
            "A failed fidelity audit must record at least one semantic error"
        )


def _current_document(
    project_path: Path,
    project: dict[str, Any],
    kind: Literal["content_map", "media_plan"],
) -> tuple[dict[str, Any], dict[str, Any]]:
    collection_name = _ARTIFACT_COLLECTIONS[kind]
    artifact_id = project["current"].get(f"{kind}_id")
    metadata = _metadata_by_id(project["artifacts"][collection_name], artifact_id)
    if metadata is None:
        raise ValueError(f"A current {kind} is required first")
    path = _artifact_path(project_path, metadata)
    document = read_json(path)
    if not isinstance(document, dict):
        raise TypeError(f"Current {kind} must be a JSON object")
    return document, metadata


def _current_document_by_project(
    project: dict[str, Any],
    kind: Literal["content_map", "media_plan"],
) -> tuple[dict[str, Any], dict[str, Any]]:
    collection_name = _ARTIFACT_COLLECTIONS[kind]
    artifact_id = project["current"].get(f"{kind}_id")
    metadata = _metadata_by_id(project["artifacts"][collection_name], artifact_id)
    if metadata is None:
        raise ValueError(f"A current {kind} is required first")
    project_path_value = project.get("_project_path")
    if project_path_value:
        path = _artifact_path(Path(project_path_value), metadata)
    else:
        path = Path(str(metadata.get("_resolved_path") or metadata["path"]))
    if not path.is_absolute() or not path.is_file():
        raise ValueError(f"Current {kind} artifact is unavailable")
    document = read_json(path)
    if not isinstance(document, dict):
        raise TypeError(f"Current {kind} must be a JSON object")
    return document, metadata


def _select_artifact(
    project: dict[str, Any], artifact: str, artifact_id: str
) -> dict[str, Any] | None:
    if artifact == "project":
        return None
    selector = {
        "latest_content_map": ("content_maps", "content_map_id"),
        "latest_media_plan": ("media_plans", "media_plan_id"),
        "latest_deliverable": ("deliverables", "deliverable_id"),
        "latest_fidelity_audit": ("fidelity_audits", "fidelity_audit_id"),
    }
    if artifact == "artifact_id":
        if not artifact_id:
            raise ValueError("artifact_id is required when artifact=artifact_id")
        for collection in project["artifacts"].values():
            match = _metadata_by_id(collection, artifact_id)
            if match is not None:
                return match
        raise ValueError(f"Unknown content artifact id: {artifact_id}")
    if artifact not in selector:
        raise ValueError(f"Unsupported content artifact selector: {artifact}")
    collection_name, current_key = selector[artifact]
    metadata = _metadata_by_id(
        project["artifacts"][collection_name], project["current"].get(current_key)
    )
    if metadata is None:
        raise FileNotFoundError(f"Content project has no {artifact}")
    return metadata


def _require_project_path(project_path: Path) -> Path:
    project_path = project_path.resolve()
    if not project_path.is_file():
        raise FileNotFoundError(f"Content project does not exist: {project_path}")
    return project_path


def _artifact_path(project_path: Path, metadata: dict[str, Any]) -> Path:
    raw_path = str(metadata.get("path") or "")
    if not raw_path:
        raise ValueError("Content artifact has no path")
    root = project_path.parent.resolve()
    path = (root / raw_path).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError(
            "Refusing to read a content artifact outside the project"
        ) from error
    return path


def _resolve_source_path(project_path: Path, raw_path: str) -> Path:
    project_root = project_path.parent.resolve()
    job_root = project_root.parent.parent.resolve()
    path = (project_root / raw_path).resolve()
    try:
        path.relative_to(job_root)
    except ValueError as error:
        raise ValueError(
            "Refusing to read source evidence outside the subtitle job"
        ) from error
    return path


def _relative_path(path: Path, root: Path) -> str:
    return Path(_relative_path_string(path.resolve(), root.resolve())).as_posix()


def _relative_path_string(path: Path, root: Path) -> str:
    import os

    return os.path.relpath(path, root)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_file_hash(
    path: Path,
    expected: str,
    label: str,
    errors: list[dict[str, str]],
) -> None:
    if not path.is_file():
        errors.append({"code": f"{label}_MISSING", "message": f"Missing file: {path}"})
        return
    actual = _sha256_file(path)
    if actual != expected:
        errors.append(
            {
                "code": f"{label}_CHANGED",
                "message": f"Hash mismatch for {path}",
            }
        )


def _validation_result(
    project: dict[str, Any],
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
    *,
    ready: bool,
) -> dict[str, Any]:
    return {
        "schema_version": "video-content/validation-v1",
        "project_id": project.get("project_id") if isinstance(project, dict) else None,
        "valid": not errors,
        "ready_for_delivery": ready and not errors,
        "errors": errors,
        "warnings": warnings,
    }


def _require_fields(value: dict[str, Any], names: tuple[str, ...], label: str) -> None:
    missing = [name for name in names if name not in value]
    if missing:
        raise ValueError(f"{label} is missing required fields: {', '.join(missing)}")


def _validate_range(value: dict[str, Any], label: str) -> None:
    _require_fields(value, ("start_ms", "end_ms"), label)
    start_ms = value["start_ms"]
    end_ms = value["end_ms"]
    if not isinstance(start_ms, int) or not isinstance(end_ms, int):
        raise TypeError(f"{label} start_ms/end_ms must be integers")
    if start_ms < 0 or end_ms <= start_ms:
        raise ValueError(f"{label} requires 0 <= start_ms < end_ms")


def _unique_id_map(values: Any, field: str, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(values, list):
        raise TypeError(f"{label} must be a list")
    result: dict[str, dict[str, Any]] = {}
    for item in values:
        if not isinstance(item, dict):
            raise TypeError(f"{label} items must be objects")
        value = str(item.get(field) or "")
        if not value:
            raise ValueError(f"{label} item is missing {field}")
        if value in result:
            raise ValueError(f"{label} contains duplicate {field}: {value}")
        result[value] = item
    return result


def _ids(values: list[dict[str, Any]], field: str) -> set[str]:
    return set(_unique_id_map(values, field, field))


def _require_known_refs(values: Any, known: Any, label: str) -> None:
    if not isinstance(values, list):
        raise TypeError(f"{label} must be a list")
    known_set = set(known)
    unknown = sorted({str(value) for value in values} - known_set)
    if unknown:
        raise ValueError(f"{label} contains unknown references: {unknown}")


def _require_included(required: Any, actual: list[str], label: str) -> None:
    if not isinstance(required, list):
        raise TypeError(f"media plan {label} list is invalid")
    missing = sorted(set(required) - set(actual))
    if missing:
        raise ValueError(f"Deliverable is missing {label} ids: {missing}")


def _unique_strings(values: list[str], label: str) -> list[str]:
    result = []
    seen = set()
    for value in values:
        text = str(value).strip()
        if not text:
            raise ValueError(f"{label} cannot contain empty values")
        if text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _metadata_by_id(
    collection: list[dict[str, Any]], artifact_id: Any
) -> dict[str, Any] | None:
    if not artifact_id:
        return None
    return next(
        (item for item in collection if item.get("artifact_id") == artifact_id),
        None,
    )
