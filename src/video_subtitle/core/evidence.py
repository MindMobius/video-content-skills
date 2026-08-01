from __future__ import annotations

from pathlib import Path
from typing import Any

from .srt import format_short_time, parse_srt
from .util import read_json

_CUE_ARTIFACT_KINDS = {
    "subtitle_srt",
    "ocr_primary_srt",
    "ocr_validation_srt",
    "reviewed_subtitle_srt",
}


def list_subtitle_evidence_for_manifest(manifest_path: Path) -> dict[str, Any]:
    """List time-addressable subtitle evidence without choosing for the Agent."""
    manifest_path = manifest_path.resolve()
    manifest = read_json(manifest_path)
    source_by_artifact_source = {
        str(source.get("artifact_source")): source
        for source in manifest.get("sources", [])
        if source.get("artifact_source")
    }
    evidence: list[dict[str, Any]] = []
    for artifact_index, artifact in enumerate(manifest.get("artifacts", []), start=1):
        artifact_kind = str(artifact.get("kind") or "")
        if artifact_kind not in _CUE_ARTIFACT_KINDS:
            continue
        source = str(artifact.get("source") or "")
        source_metadata = source_by_artifact_source.get(source)
        path, path_error = _safe_artifact_path(manifest_path, artifact)
        cue_count = artifact.get("cue_count")
        if cue_count is None and path is not None and path.is_file():
            cue_count = len(parse_srt(path))
        evidence.append(
            {
                "evidence_id": _evidence_id(artifact_index),
                "artifact_kind": artifact_kind,
                "source": source,
                "source_kind": (
                    source_metadata.get("kind")
                    if source_metadata is not None
                    else "derived"
                ),
                "layer": "raw" if source_metadata is not None else "derived",
                "selected": artifact.get("selected") is True,
                "cue_count": cue_count,
                "available": path is not None and path.is_file(),
                "path": str(path) if path is not None else None,
                "path_error": path_error,
                "supports_time_range": True,
            }
        )
    return {
        "schema_version": "video-subtitle/evidence-catalog-v1",
        "job_id": manifest.get("job_id"),
        "job_status": manifest.get("status"),
        "video": _video_summary(manifest.get("video") or {}),
        "selected_source": manifest.get("selected_source"),
        "review": manifest.get("review"),
        "evidence": evidence,
    }


def read_subtitle_evidence_range(
    manifest_path: Path,
    *,
    evidence_id: str,
    start_ms: int = 0,
    end_ms: int | None = None,
    max_cues: int = 120,
) -> dict[str, Any]:
    """Read an arbitrary time range from one SRT evidence artifact."""
    if start_ms < 0:
        raise ValueError("start_ms cannot be negative")
    if end_ms is not None and end_ms <= start_ms:
        raise ValueError("end_ms must be greater than start_ms")
    if not 1 <= max_cues <= 500:
        raise ValueError("max_cues must be between 1 and 500")

    manifest_path = manifest_path.resolve()
    manifest = read_json(manifest_path)
    artifact_index, artifact = _artifact_for_evidence_id(manifest, evidence_id)
    artifact_kind = str(artifact.get("kind") or "")
    if artifact_kind not in _CUE_ARTIFACT_KINDS:
        raise ValueError(f"Evidence {evidence_id} is not a time-addressable SRT")
    path, path_error = _safe_artifact_path(manifest_path, artifact)
    if path is None:
        raise ValueError(path_error or f"Evidence {evidence_id} has an invalid path")
    if not path.is_file():
        raise FileNotFoundError(f"Evidence file does not exist: {path}")

    cues = parse_srt(path)
    matching = [
        (cue_index, cue)
        for cue_index, cue in enumerate(cues, start=1)
        if cue.end_ms > start_ms
        and (end_ms is None or cue.start_ms < end_ms)
    ]
    returned = matching[:max_cues]
    has_more = len(matching) > len(returned)
    return {
        "schema_version": "video-subtitle/evidence-range-v1",
        "job_id": manifest.get("job_id"),
        "evidence": {
            "evidence_id": _evidence_id(artifact_index),
            "artifact_kind": artifact_kind,
            "source": artifact.get("source"),
            "selected": artifact.get("selected") is True,
            "path": str(path),
        },
        "range": {
            "start_ms": start_ms,
            "end_ms": end_ms,
            "start": format_short_time(start_ms),
            "end": format_short_time(end_ms) if end_ms is not None else None,
        },
        "matching_cue_count": len(matching),
        "returned_cue_count": len(returned),
        "has_more": has_more,
        "next_start_ms": matching[len(returned)][1].start_ms if has_more else None,
        "cues": [
            {
                "cue_id": f"{evidence_id}-cue-{cue_index:05d}",
                "index": cue_index,
                "start_ms": cue.start_ms,
                "end_ms": cue.end_ms,
                "start": format_short_time(cue.start_ms),
                "end": format_short_time(cue.end_ms),
                "text": cue.text,
            }
            for cue_index, cue in returned
        ],
    }


def _artifact_for_evidence_id(
    manifest: dict[str, Any],
    evidence_id: str,
) -> tuple[int, dict[str, Any]]:
    for artifact_index, artifact in enumerate(manifest.get("artifacts", []), start=1):
        if _evidence_id(artifact_index) == evidence_id:
            return artifact_index, artifact
    available = [
        _evidence_id(index)
        for index, artifact in enumerate(manifest.get("artifacts", []), start=1)
        if str(artifact.get("kind") or "") in _CUE_ARTIFACT_KINDS
    ]
    raise ValueError(
        f"Unknown evidence_id {evidence_id!r}; call list_subtitle_evidence first. "
        f"Available IDs: {', '.join(available) or 'none'}"
    )


def _safe_artifact_path(
    manifest_path: Path,
    artifact: dict[str, Any],
) -> tuple[Path | None, str | None]:
    raw_path = str(artifact.get("path") or "").strip()
    if not raw_path:
        return None, "Artifact has no path"
    job_directory = manifest_path.parent.resolve()
    path = Path(raw_path)
    if not path.is_absolute():
        path = job_directory / path
    path = path.resolve()
    try:
        path.relative_to(job_directory)
    except ValueError:
        return None, "Refusing to read subtitle evidence outside the job directory"
    return path, None


def _evidence_id(artifact_index: int) -> str:
    return f"ev-{artifact_index:04d}"


def _video_summary(video: dict[str, Any]) -> dict[str, Any]:
    return {
        key: video.get(key)
        for key in (
            "bvid",
            "title",
            "series_title",
            "author",
            "page",
            "duration",
            "duration_seconds",
            "url",
        )
        if video.get(key) not in {None, ""}
    }
