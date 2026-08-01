from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .srt import (
    Cue,
    format_short_time,
    parse_srt,
    write_cues_json,
    write_srt,
    write_transcript_markdown,
)
from .util import read_json, utc_now, write_json_atomic

REVIEW_ALGORITHM_VERSION = "time-window-cross-language-v2"


@dataclass(frozen=True)
class ReviewOptions:
    window_seconds: int = 30
    context_seconds: float = 2.0
    repeated_phrase_min_cues: int = 3
    cross_scale_warning_threshold: float = 0.72

    def __post_init__(self) -> None:
        if not 10 <= self.window_seconds <= 180:
            raise ValueError("review window_seconds must be between 10 and 180")
        if not 0 <= self.context_seconds <= 15:
            raise ValueError("review context_seconds must be between 0 and 15")
        if self.repeated_phrase_min_cues < 2:
            raise ValueError("repeated_phrase_min_cues must be at least 2")
        if not 0 <= self.cross_scale_warning_threshold <= 1:
            raise ValueError("cross_scale_warning_threshold must be between 0 and 1")

    def as_dict(self) -> dict[str, Any]:
        return {
            "window_seconds": self.window_seconds,
            "context_seconds": self.context_seconds,
            "repeated_phrase_min_cues": self.repeated_phrase_min_cues,
            "cross_scale_warning_threshold": self.cross_scale_warning_threshold,
        }


def prepare_review_packet(
    manifest: dict[str, Any],
    output_dir: Path,
    *,
    options: ReviewOptions | None = None,
) -> dict[str, Any] | None:
    """Build an agent-readable OCR/ASR review packet without mutating raw evidence."""
    options = options or ReviewOptions()
    output_dir = output_dir.resolve()
    hard_ocr = _source_by_kind(manifest, "hard_ocr")
    audio_asr = _source_by_kind(manifest, "audio_asr")
    if hard_ocr is None or audio_asr is None:
        return None

    ocr_source = str(hard_ocr["artifact_source"])
    asr_source = str(audio_asr["artifact_source"])
    ocr_path = _artifact_path(
        manifest,
        kind="subtitle_srt",
        source=ocr_source,
    )
    asr_path = _artifact_path(
        manifest,
        kind="subtitle_srt",
        source=asr_source,
    )
    if ocr_path is None or asr_path is None:
        return None

    ocr_cues = parse_srt(ocr_path)
    asr_cues = parse_srt(asr_path)
    if not ocr_cues or not asr_cues:
        return None

    primary_path = _artifact_path(
        manifest,
        kind="ocr_primary_srt",
        source=ocr_source,
    )
    validation_path = _artifact_path(
        manifest,
        kind="ocr_validation_srt",
        source=ocr_source,
    )
    primary_cues = parse_srt(primary_path) if primary_path else []
    validation_cues = parse_srt(validation_path) if validation_path else []

    ocr_language = _ocr_source_language(manifest, ocr_cues)
    asr_language = _source_language(audio_asr, asr_cues)
    review_mode = (
        "cross_language"
        if _language_family(ocr_language) != _language_family(asr_language)
        else "same_language"
    )
    repeated_phrases = _repeated_latin_phrases(
        ocr_cues,
        minimum_cues=options.repeated_phrase_min_cues,
    )
    ocr_records = _build_ocr_records(
        ocr_cues,
        primary_cues=primary_cues,
        validation_cues=validation_cues,
        repeated_phrases=repeated_phrases,
        target_language=ocr_language,
        cross_scale_warning_threshold=options.cross_scale_warning_threshold,
    )
    asr_records = [
        _cue_record(cue, f"asr-{index:04d}")
        for index, cue in enumerate(asr_cues, start=1)
    ]
    windows = _build_windows(
        ocr_records,
        asr_records,
        mode=review_mode,
        window_ms=options.window_seconds * 1000,
        context_ms=round(options.context_seconds * 1000),
    )

    video_context = _review_video_context(manifest.get("video") or {})
    fingerprint = hashlib.sha256()
    fingerprint.update(REVIEW_ALGORITHM_VERSION.encode("utf-8"))
    fingerprint.update(ocr_path.read_bytes())
    fingerprint.update(asr_path.read_bytes())
    for supporting_path in (primary_path, validation_path):
        if supporting_path is not None:
            fingerprint.update(supporting_path.read_bytes())
    fingerprint.update(json.dumps(options.as_dict(), sort_keys=True).encode("utf-8"))
    fingerprint.update(
        json.dumps(
            video_context,
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    )
    packet_id = f"review_{fingerprint.hexdigest()[:16]}"
    flagged_cues = sum(bool(record["flags"]) for record in ocr_records)
    high_priority_windows = sum(window["priority"] == "high" for window in windows)
    packet: dict[str, Any] = {
        "schema_version": "video-subtitle/review-packet-v1",
        "packet_id": packet_id,
        "algorithm_version": REVIEW_ALGORITHM_VERSION,
        "job_id": manifest.get("job_id"),
        "created_at": utc_now(),
        "status": "awaiting_agent_review",
        "mode": review_mode,
        "options": options.as_dict(),
        "video": video_context,
        "primary": {
            "kind": "hard_ocr",
            "source": ocr_source,
            "language": ocr_language,
            "path": str(ocr_path),
            "cue_count": len(ocr_records),
        },
        "corroborating": {
            "kind": "audio_asr",
            "source": asr_source,
            "language": asr_language,
            "path": str(asr_path),
            "cue_count": len(asr_records),
        },
        "statistics": {
            "window_count": len(windows),
            "high_priority_window_count": high_priority_windows,
            "flagged_ocr_cue_count": flagged_cues,
            "repeated_visual_phrase_count": len(repeated_phrases),
            "repeated_visual_phrases": repeated_phrases,
        },
        "instructions": _review_instructions(review_mode),
        "windows": windows,
    }
    packet_json = output_dir / "review.packet.json"
    packet_markdown = output_dir / "review.packet.md"
    write_json_atomic(packet_json, packet)
    packet_markdown.write_text(
        _packet_markdown(packet),
        encoding="utf-8",
    )
    return {
        "packet": packet,
        "review": {
            "status": "ready_for_agent_review",
            "mode": review_mode,
            "packet_id": packet_id,
            "window_count": len(windows),
            "reviewed_window_count": 0,
            "high_priority_window_count": high_priority_windows,
            "flagged_ocr_cue_count": flagged_cues,
            "packet_path": str(packet_json),
        },
        "artifacts": [
            _artifact("review_packet_json", packet_json),
            _artifact("review_packet_markdown", packet_markdown),
        ],
    }


def prepare_review_for_manifest(
    manifest_path: Path,
    *,
    options: ReviewOptions | None = None,
) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    manifest = read_json(manifest_path)
    existing_packet = _artifact_path(manifest, kind="review_packet_json")
    existing_decisions = _artifact_path(manifest, kind="review_decisions_json")
    if existing_packet is not None and existing_decisions is not None:
        return {
            "schema_version": "video-subtitle/review-operation-v1",
            "job_id": manifest.get("job_id"),
            "review": manifest.get("review"),
            "artifacts": [],
            "reused_existing_review": True,
        }
    result = prepare_review_packet(
        manifest,
        manifest_path.parent,
        options=options,
    )
    if result is None:
        raise ValueError(
            "A review packet requires both hard_ocr and audio_asr SRT evidence"
        )
    _upsert_artifacts(manifest, result["artifacts"])
    manifest["review"] = result["review"]
    _set_fusion_status(manifest, "ready_for_agent_review")
    manifest["updated_at"] = utc_now()
    write_json_atomic(manifest_path, manifest)
    _update_evidence_index(manifest, manifest_path.parent)
    return {
        "schema_version": "video-subtitle/review-operation-v1",
        "job_id": manifest.get("job_id"),
        "review": result["review"],
        "artifacts": result["artifacts"],
    }


def get_review_window(
    manifest_path: Path,
    window_id: str | None = None,
) -> dict[str, Any]:
    manifest = read_json(manifest_path.resolve())
    packet_path = _artifact_path(manifest, kind="review_packet_json")
    if packet_path is None:
        raise FileNotFoundError("The manifest has no review_packet_json artifact")
    packet = read_json(packet_path)
    windows = list(packet.get("windows") or [])
    if window_id:
        window = next(
            (item for item in windows if item.get("window_id") == window_id),
            None,
        )
        if window is None:
            raise ValueError(f"Unknown review window: {window_id}")
        return {
            "schema_version": "video-subtitle/review-window-v1",
            "packet_id": packet.get("packet_id"),
            "mode": packet.get("mode"),
            "video": packet.get("video"),
            "instructions": packet.get("instructions"),
            "window": window,
        }
    return {
        "schema_version": "video-subtitle/review-window-index-v1",
        "packet_id": packet.get("packet_id"),
        "mode": packet.get("mode"),
        "statistics": packet.get("statistics"),
        "windows": [
            {
                "window_id": item.get("window_id"),
                "start_ms": item.get("start_ms"),
                "end_ms": item.get("end_ms"),
                "priority": item.get("priority"),
                "reasons": item.get("reasons"),
                "primary_cue_count": len(item.get("primary_cues") or []),
                "corroborating_cue_count": len(item.get("corroborating_cues") or []),
            }
            for item in windows
        ],
    }


def submit_review_window(
    manifest_path: Path,
    *,
    window_id: str,
    decisions: list[dict[str, Any]],
    unresolved: list[dict[str, Any]] | None = None,
    notes: str = "",
    reviewer: str = "agent",
) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    manifest = read_json(manifest_path)
    packet_path = _artifact_path(manifest, kind="review_packet_json")
    if packet_path is None:
        raise FileNotFoundError("The manifest has no review_packet_json artifact")
    packet = read_json(packet_path)
    window = next(
        (
            item
            for item in packet.get("windows") or []
            if item.get("window_id") == window_id
        ),
        None,
    )
    if window is None:
        raise ValueError(f"Unknown review window: {window_id}")

    normalized_decisions = _validate_decisions(window, decisions)
    normalized_unresolved = _validate_unresolved(window, unresolved or [])
    decisions_path = manifest_path.parent / "review.decisions.json"
    if decisions_path.is_file():
        document = read_json(decisions_path)
        if document.get("packet_id") != packet.get("packet_id"):
            raise ValueError("Existing review decisions belong to another packet")
    else:
        document = {
            "schema_version": "video-subtitle/review-decisions-v1",
            "packet_id": packet.get("packet_id"),
            "job_id": manifest.get("job_id"),
            "created_at": utc_now(),
            "windows": {},
        }
    document["updated_at"] = utc_now()
    document["windows"][window_id] = {
        "reviewer": reviewer,
        "reviewed_at": utc_now(),
        "notes": notes.strip(),
        "decisions": normalized_decisions,
        "unresolved": normalized_unresolved,
    }
    write_json_atomic(decisions_path, document)
    return _render_review_outputs(
        manifest,
        manifest_path,
        packet,
        document,
        decisions_path,
    )


def apply_review_document(
    manifest_path: Path,
    document: dict[str, Any],
) -> dict[str, Any]:
    windows = document.get("windows")
    if not isinstance(windows, list) or not windows:
        raise ValueError("Review document windows must be a non-empty array")
    result: dict[str, Any] | None = None
    reviewer = str(document.get("reviewer") or "agent")
    for submission in windows:
        if not isinstance(submission, dict):
            raise TypeError("Each review window submission must be an object")
        result = submit_review_window(
            manifest_path,
            window_id=str(submission.get("window_id") or ""),
            decisions=list(submission.get("decisions") or []),
            unresolved=list(submission.get("unresolved") or []),
            notes=str(submission.get("notes") or ""),
            reviewer=str(submission.get("reviewer") or reviewer),
        )
    if result is None:  # pragma: no cover - guarded by the non-empty check
        raise ValueError("No review windows were applied")
    return result


def _render_review_outputs(
    manifest: dict[str, Any],
    manifest_path: Path,
    packet: dict[str, Any],
    decisions_document: dict[str, Any],
    decisions_path: Path,
) -> dict[str, Any]:
    windows = list(packet.get("windows") or [])
    submitted = decisions_document.get("windows") or {}
    primary_records = [
        cue for window in windows for cue in window.get("primary_cues") or []
    ]
    primary_records.sort(key=lambda item: (item["start_ms"], item["end_ms"]))
    decision_by_cue: dict[str, dict[str, Any]] = {}
    insertion_decisions: list[dict[str, Any]] = []
    explicit_unresolved: list[dict[str, Any]] = []
    for window_id, submission in submitted.items():
        for decision in submission.get("decisions") or []:
            normalized = {
                **decision,
                "window_id": window_id,
            }
            if decision["action"] == "insert":
                insertion_decisions.append(normalized)
            else:
                decision_by_cue[str(decision["cue_id"])] = normalized
        for item in submission.get("unresolved") or []:
            explicit_unresolved.append({**item, "window_id": window_id})

    reviewed_cues: list[Cue] = []
    changes: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for record in primary_records:
        cue_id = str(record["cue_id"])
        decision = decision_by_cue.get(cue_id)
        text = str(record["text"])
        if decision is None or decision["action"] == "keep":
            reviewed_cues.append(Cue(record["start_ms"], record["end_ms"], text))
            continue
        if decision["confidence"] != "high":
            reviewed_cues.append(Cue(record["start_ms"], record["end_ms"], text))
            deferred.append(
                {
                    "cue_id": cue_id,
                    "window_id": decision["window_id"],
                    "issue": "Non-high-confidence change was recorded but not applied",
                    "proposed_action": decision["action"],
                    "proposed_text": decision.get("reviewed_text"),
                }
            )
            continue
        if decision["action"] == "delete":
            changes.append(
                {
                    "cue_id": cue_id,
                    "window_id": decision["window_id"],
                    "action": "delete",
                    "original_text": text,
                    "reviewed_text": "",
                    "reason": decision["reason"],
                    "evidence": decision["evidence"],
                }
            )
            continue
        reviewed_text = str(decision["reviewed_text"])
        reviewed_cues.append(Cue(record["start_ms"], record["end_ms"], reviewed_text))
        changes.append(
            {
                "cue_id": cue_id,
                "window_id": decision["window_id"],
                "action": "replace",
                "original_text": text,
                "reviewed_text": reviewed_text,
                "reason": decision["reason"],
                "evidence": decision["evidence"],
            }
        )

    for decision in insertion_decisions:
        if decision["confidence"] != "high":
            deferred.append(
                {
                    "cue_id": decision["cue_id"],
                    "window_id": decision["window_id"],
                    "issue": "Non-high-confidence insertion was recorded but not applied",
                    "proposed_action": "insert",
                    "proposed_text": decision["reviewed_text"],
                }
            )
            continue
        reviewed_cues.append(
            Cue(
                int(decision["start_ms"]),
                int(decision["end_ms"]),
                str(decision["reviewed_text"]),
            )
        )
        changes.append(
            {
                "cue_id": decision["cue_id"],
                "window_id": decision["window_id"],
                "action": "insert",
                "start_ms": decision["start_ms"],
                "end_ms": decision["end_ms"],
                "original_text": "",
                "reviewed_text": decision["reviewed_text"],
                "reason": decision["reason"],
                "evidence": decision["evidence"],
            }
        )
    reviewed_cues.sort(key=lambda cue: (cue.start_ms, cue.end_ms))

    unresolved = explicit_unresolved + deferred
    reviewed_window_count = len(submitted)
    if reviewed_window_count < len(windows):
        status = "in_progress"
    elif unresolved:
        status = "complete_with_unresolved"
    else:
        status = "complete"

    output_dir = manifest_path.parent
    reviewed_srt = output_dir / "subtitle.reviewed.srt"
    reviewed_json = output_dir / "subtitle.reviewed.json"
    reviewed_markdown = output_dir / "subtitle.reviewed.md"
    report_json = output_dir / "review.report.json"
    report_markdown = output_dir / "review.report.md"
    write_srt(reviewed_srt, reviewed_cues)
    write_cues_json(reviewed_json, reviewed_cues)
    write_transcript_markdown(
        reviewed_markdown,
        reviewed_cues,
        title=str((manifest.get("video") or {}).get("series_title") or "审阅字幕"),
        source=f"agent_review:{packet.get('packet_id')}",
    )
    report = {
        "schema_version": "video-subtitle/review-report-v1",
        "packet_id": packet.get("packet_id"),
        "job_id": manifest.get("job_id"),
        "updated_at": utc_now(),
        "status": status,
        "window_count": len(windows),
        "reviewed_window_count": reviewed_window_count,
        "original_cue_count": len(primary_records),
        "reviewed_cue_count": len(reviewed_cues),
        "applied_change_count": len(changes),
        "unresolved_count": len(unresolved),
        "changes": changes,
        "unresolved": unresolved,
    }
    write_json_atomic(report_json, report)
    report_markdown.write_text(_report_markdown(report), encoding="utf-8")

    artifacts = [
        _artifact("review_decisions_json", decisions_path),
        _artifact("reviewed_subtitle_srt", reviewed_srt, len(reviewed_cues)),
        _artifact("reviewed_subtitle_json", reviewed_json, len(reviewed_cues)),
        _artifact(
            "reviewed_transcript_markdown",
            reviewed_markdown,
            len(reviewed_cues),
        ),
        _artifact("review_report_json", report_json),
        _artifact("review_report_markdown", report_markdown),
    ]
    _upsert_artifacts(manifest, artifacts)
    manifest["review"] = {
        "status": status,
        "mode": packet.get("mode"),
        "packet_id": packet.get("packet_id"),
        "window_count": len(windows),
        "reviewed_window_count": reviewed_window_count,
        "applied_change_count": len(changes),
        "unresolved_count": len(unresolved),
        "packet_path": str(_artifact_path(manifest, kind="review_packet_json")),
        "report_path": str(report_json),
    }
    fusion_status = {
        "in_progress": "agent_review_in_progress",
        "complete": "agent_review_complete",
        "complete_with_unresolved": "agent_review_complete_with_unresolved",
    }[status]
    _set_fusion_status(manifest, fusion_status)
    if status == "complete" and _selected_primary_kind(manifest) == "hard_ocr":
        for artifact in manifest.get("artifacts") or []:
            if artifact.get("kind") in {
                "subtitle_srt",
                "subtitle_json",
                "transcript_markdown",
            }:
                artifact.pop("selected", None)
            if artifact.get("kind") in {
                "reviewed_subtitle_srt",
                "reviewed_subtitle_json",
                "reviewed_transcript_markdown",
            }:
                artifact["selected"] = True
    manifest["updated_at"] = utc_now()
    write_json_atomic(manifest_path, manifest)
    _update_evidence_index(manifest, output_dir)
    return {
        "schema_version": "video-subtitle/review-operation-v1",
        "job_id": manifest.get("job_id"),
        "review": manifest["review"],
        "artifacts": artifacts,
    }


def _build_ocr_records(
    cues: list[Cue],
    *,
    primary_cues: list[Cue],
    validation_cues: list[Cue],
    repeated_phrases: list[dict[str, Any]],
    target_language: str,
    cross_scale_warning_threshold: float,
) -> list[dict[str, Any]]:
    repeated_values = [str(item["phrase"]) for item in repeated_phrases]
    records: list[dict[str, Any]] = []
    for index, cue in enumerate(cues, start=1):
        record = _cue_record(cue, f"ocr-{index:04d}")
        flags: list[dict[str, Any]] = []
        cjk_count, latin_count = _script_counts(cue.text)
        if _language_family(target_language) == "cjk":
            total_letters = cjk_count + latin_count
            if latin_count >= 5 and (
                not cjk_count or latin_count / max(1, total_letters) >= 0.35
            ):
                flags.append({"code": "latin_dominant_in_cjk_ocr"})
        if cjk_count and cjk_count <= 2 and len(cue.text.strip()) <= 5:
            flags.append({"code": "very_short_ocr_fragment"})
        normalized_latin = " ".join(_latin_tokens(cue.text))
        cue_repeated = [
            phrase for phrase in repeated_values if phrase in normalized_latin
        ]
        if cue_repeated:
            flags.append(
                {
                    "code": "repeated_latin_scene_text",
                    "phrases": cue_repeated,
                }
            )

        primary_match = _best_overlapping_cue(cue, primary_cues)
        validation_match = _best_overlapping_cue(cue, validation_cues)
        cross_scale_similarity: float | None = None
        if primary_match and validation_match:
            cross_scale_similarity = _text_similarity(
                primary_match.text,
                validation_match.text,
            )
            if cross_scale_similarity < cross_scale_warning_threshold:
                flags.append(
                    {
                        "code": "cross_scale_disagreement",
                        "similarity": round(cross_scale_similarity, 4),
                    }
                )
        elif primary_cues or validation_cues:
            flags.append({"code": "cross_scale_evidence_missing"})

        record["flags"] = flags
        record["ocr_evidence"] = {
            "primary": _optional_cue_evidence(primary_match),
            "validation": _optional_cue_evidence(validation_match),
            "primary_validation_similarity": (
                round(cross_scale_similarity, 4)
                if cross_scale_similarity is not None
                else None
            ),
        }
        records.append(record)
    return records


def _build_windows(
    primary_records: list[dict[str, Any]],
    corroborating_records: list[dict[str, Any]],
    *,
    mode: str,
    window_ms: int,
    context_ms: int,
) -> list[dict[str, Any]]:
    duration_ms = max(
        [record["end_ms"] for record in primary_records + corroborating_records],
        default=0,
    )
    windows: list[dict[str, Any]] = []
    for index in range(math.ceil(duration_ms / window_ms)):
        start_ms = index * window_ms
        end_ms = min(duration_ms, (index + 1) * window_ms)
        primary = [
            record
            for record in primary_records
            if start_ms <= record["start_ms"] < end_ms
        ]
        corroborating_matches = [
            record
            for record in corroborating_records
            if record["start_ms"] < end_ms + context_ms
            and record["end_ms"] > max(0, start_ms - context_ms)
        ]
        if not primary and not corroborating_matches:
            continue
        corroborating: list[dict[str, Any]] = []
        for record in corroborating_matches:
            duration = max(1, record["end_ms"] - record["start_ms"])
            overlap = sum(
                max(
                    0,
                    min(record["end_ms"], cue["end_ms"])
                    - max(record["start_ms"], cue["start_ms"]),
                )
                for cue in primary_records
            )
            overlap_ratio = min(1.0, overlap / duration)
            annotated = dict(record)
            annotated["primary_overlap_ratio"] = round(overlap_ratio, 4)
            annotated["flags"] = (
                [{"code": "asr_speech_low_ocr_coverage"}] if overlap_ratio < 0.5 else []
            )
            corroborating.append(annotated)
        reasons: set[str] = set()
        if mode == "cross_language":
            reasons.add("cross_language_semantic_review")
        if corroborating and not primary:
            reasons.add("ocr_gap_with_asr_speech")
        if any(record["flags"] for record in corroborating):
            reasons.add("asr_speech_low_ocr_coverage")
        for record in primary:
            reasons.update(flag["code"] for flag in record.get("flags") or [])
        high_codes = {
            "ocr_gap_with_asr_speech",
            "repeated_latin_scene_text",
            "cross_scale_disagreement",
            "cross_scale_evidence_missing",
            "asr_speech_low_ocr_coverage",
        }
        priority = "high" if reasons.intersection(high_codes) else "normal"
        windows.append(
            {
                "window_id": f"rw-{len(windows) + 1:04d}",
                "start_ms": start_ms,
                "end_ms": end_ms,
                "start": format_short_time(start_ms),
                "end": format_short_time(end_ms),
                "priority": priority,
                "reasons": sorted(reasons),
                "primary_cues": primary,
                "corroborating_cues": corroborating,
            }
        )
    return windows


def _validate_decisions(
    window: dict[str, Any],
    decisions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    available = {str(cue["cue_id"]): cue for cue in window.get("primary_cues") or []}
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for decision_index, decision in enumerate(decisions, start=1):
        if not isinstance(decision, dict):
            raise TypeError("Each review decision must be an object")
        action = str(decision.get("action") or "")
        if action not in {"keep", "replace", "delete", "insert"}:
            raise ValueError("Review action must be keep, replace, delete, or insert")
        cue_id = str(decision.get("cue_id") or "")
        if action == "insert" and not cue_id:
            cue_id = f"insert-{window['window_id']}-{decision_index:02d}"
        if action != "insert" and cue_id not in available:
            raise ValueError(
                f"Cue {cue_id!r} does not belong to window {window['window_id']}"
            )
        if cue_id in seen:
            raise ValueError(f"Duplicate review decision for cue {cue_id}")
        seen.add(cue_id)
        confidence = str(decision.get("confidence") or "high")
        if confidence not in {"high", "medium", "low"}:
            raise ValueError("Review confidence must be high, medium, or low")
        original_text = decision.get("original_text")
        if (
            action != "insert"
            and original_text is not None
            and str(original_text) != available[cue_id]["text"]
        ):
            raise ValueError(f"Original text no longer matches cue {cue_id}")
        reviewed_text = str(
            decision.get("reviewed_text", decision.get("text", ""))
        ).strip()
        reason = str(decision.get("reason") or "").strip()
        if action in {"replace", "insert"} and not reviewed_text:
            raise ValueError("replace/insert decisions require reviewed_text")
        if action in {"replace", "delete", "insert"} and not reason:
            raise ValueError("replace/delete/insert decisions require a reason")
        start_ms: int | None = None
        end_ms: int | None = None
        if action == "insert":
            try:
                start_ms = int(decision["start_ms"])
                end_ms = int(decision["end_ms"])
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(
                    "insert decisions require integer start_ms and end_ms"
                ) from error
            if start_ms < window["start_ms"] or end_ms > window["end_ms"]:
                raise ValueError("Inserted cue must stay inside its review window")
            if end_ms <= start_ms:
                raise ValueError("Inserted cue end_ms must be after start_ms")
        evidence_value = decision.get("evidence") or []
        if not isinstance(evidence_value, list):
            raise TypeError("Review evidence must be an array of source references")
        normalized.append(
            {
                "cue_id": cue_id,
                "action": action,
                "confidence": confidence,
                "original_text": (
                    available[cue_id]["text"] if action != "insert" else ""
                ),
                "reviewed_text": (
                    reviewed_text if action in {"replace", "insert"} else ""
                ),
                "start_ms": start_ms,
                "end_ms": end_ms,
                "reason": reason,
                "evidence": [str(item) for item in evidence_value],
            }
        )
    deleted_ids = {
        decision["cue_id"] for decision in normalized if decision["action"] == "delete"
    }
    occupied = [
        (int(cue["start_ms"]), int(cue["end_ms"]), cue_id)
        for cue_id, cue in available.items()
        if cue_id not in deleted_ids
    ]
    for decision in normalized:
        if decision["action"] != "insert":
            continue
        start_ms = int(decision["start_ms"])
        end_ms = int(decision["end_ms"])
        conflict = next(
            (
                cue_id
                for occupied_start, occupied_end, cue_id in occupied
                if start_ms < occupied_end and end_ms > occupied_start
            ),
            None,
        )
        if conflict:
            raise ValueError(
                f"Inserted cue {decision['cue_id']} overlaps retained cue {conflict}"
            )
        occupied.append((start_ms, end_ms, str(decision["cue_id"])))
    return normalized


def _validate_unresolved(
    window: dict[str, Any],
    unresolved: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    available = {str(cue["cue_id"]) for cue in window.get("primary_cues") or []}
    normalized: list[dict[str, Any]] = []
    for item in unresolved:
        if not isinstance(item, dict):
            raise TypeError("Each unresolved review item must be an object")
        cue_id = str(item.get("cue_id") or "")
        if cue_id and cue_id not in available:
            raise ValueError(f"Unknown unresolved cue: {cue_id}")
        issue = str(item.get("issue") or item.get("reason") or "").strip()
        if not issue:
            raise ValueError("Unresolved review items require an issue")
        normalized.append(
            {
                "cue_id": cue_id or None,
                "issue": issue,
                "evidence": [str(value) for value in item.get("evidence") or []],
            }
        )
    return normalized


def _source_by_kind(
    manifest: dict[str, Any],
    kind: str,
) -> dict[str, Any] | None:
    return next(
        (
            source
            for source in manifest.get("sources") or []
            if source.get("kind") == kind
        ),
        None,
    )


def _artifact_path(
    manifest: dict[str, Any],
    *,
    kind: str,
    source: str | None = None,
) -> Path | None:
    matches = [
        artifact
        for artifact in manifest.get("artifacts") or []
        if artifact.get("kind") == kind
        and (source is None or artifact.get("source") == source)
    ]
    if not matches:
        return None
    path = Path(str(matches[-1]["path"])).resolve()
    return path if path.is_file() else None


def _source_language(source: dict[str, Any], cues: list[Cue]) -> str:
    languages = source.get("detected_languages") or []
    if languages:
        return str(languages[0]).casefold()
    return _detect_script_language(cue.text for cue in cues)


def _ocr_source_language(manifest: dict[str, Any], cues: list[Cue]) -> str:
    request = manifest.get("request") or {}
    videocr = request.get("videocr") or {}
    requested = str(videocr.get("language") or request.get("language") or "")
    normalized = requested.casefold()
    if normalized.startswith(("ch", "zh")) or normalized in {"ai-zh", "cjk"}:
        return "zh"
    if normalized.startswith("en"):
        return "english"
    return _detect_script_language(cue.text for cue in cues)


def _detect_script_language(values: Any) -> str:
    text = "\n".join(str(value) for value in values)
    cjk_count, latin_count = _script_counts(text)
    if cjk_count > latin_count * 0.25:
        return "zh"
    if latin_count:
        return "latin"
    return "unknown"


def _language_family(value: str) -> str:
    normalized = value.casefold()
    if normalized in {"zh", "chinese", "cjk", "ja", "japanese", "ko", "korean"}:
        return "cjk"
    if normalized in {
        "en",
        "english",
        "latin",
        "fr",
        "french",
        "de",
        "german",
        "es",
        "spanish",
    }:
        return "latin"
    return normalized or "unknown"


def _script_counts(value: str) -> tuple[int, int]:
    cjk = sum("\u3400" <= character <= "\u9fff" for character in value)
    latin = sum(
        ("a" <= character.casefold() <= "z")
        for character in value
        if len(character.casefold()) == 1
    )
    return cjk, latin


def _latin_tokens(value: str) -> list[str]:
    return [
        token.casefold().strip("'-")
        for token in re.findall(r"[A-Za-z][A-Za-z'-]*", value)
        if token.strip("'-")
    ]


def _repeated_latin_phrases(
    cues: list[Cue],
    *,
    minimum_cues: int,
) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for cue in cues:
        tokens = _latin_tokens(cue.text)
        phrases = dict.fromkeys(
            " ".join(tokens[index : index + 2])
            for index in range(max(0, len(tokens) - 1))
        )
        counts.update(phrases.keys())
    return [
        {"phrase": phrase, "cue_count": count}
        for phrase, count in counts.most_common()
        if count >= minimum_cues
    ]


def _cue_record(cue: Cue, cue_id: str) -> dict[str, Any]:
    return {
        "cue_id": cue_id,
        "start_ms": cue.start_ms,
        "end_ms": cue.end_ms,
        "start": format_short_time(cue.start_ms),
        "end": format_short_time(cue.end_ms),
        "text": cue.text,
    }


def _best_overlapping_cue(cue: Cue, candidates: list[Cue]) -> Cue | None:
    best: tuple[int, float, Cue] | None = None
    for candidate in candidates:
        overlap = max(
            0,
            min(cue.end_ms, candidate.end_ms) - max(cue.start_ms, candidate.start_ms),
        )
        if overlap <= 0:
            continue
        scored = (overlap, _text_similarity(cue.text, candidate.text), candidate)
        if best is None or scored[:2] > best[:2]:
            best = scored
    return best[2] if best else None


def _text_similarity(left: str, right: str) -> float:
    return SequenceMatcher(
        None,
        _normalize_text(left),
        _normalize_text(right),
        autojunk=False,
    ).ratio()


def _normalize_text(value: str) -> str:
    return "".join(character.casefold() for character in value if character.isalnum())


def _optional_cue_evidence(cue: Cue | None) -> dict[str, Any] | None:
    if cue is None:
        return None
    return {
        "start_ms": cue.start_ms,
        "end_ms": cue.end_ms,
        "text": cue.text,
    }


def _review_video_context(video: dict[str, Any]) -> dict[str, Any]:
    description = str(video.get("description") or "")
    return {
        key: video.get(key)
        for key in ("bvid", "title", "series_title", "author", "page", "duration")
        if video.get(key) not in {None, ""}
    } | {
        "description_excerpt": description[:4000],
        "description_truncated": len(description) > 4000,
    }


def _review_instructions(mode: str) -> list[str]:
    instructions = [
        "Keep the hard-subtitle OCR as the primary evidence and never rewrite raw artifacts.",
        "Use ASR to detect omissions or semantic conflicts, not as an authority for names, numbers, or terminology.",
        "Only submit replace/delete decisions when confidence is high; record uncertain cases as unresolved.",
        "Use a high-confidence insert decision with explicit timestamps when ASR proves that OCR missed a complete subtitle.",
        "Preserve the original timestamps and the publisher's translation style.",
    ]
    if mode == "cross_language":
        instructions.insert(
            1,
            "Compare meaning within the time window; do not expect word-for-word agreement across languages.",
        )
    return instructions


def _packet_markdown(packet: dict[str, Any]) -> str:
    lines = [
        "# 字幕 Agent 审阅包",
        "",
        f"- Packet：`{packet.get('packet_id')}`",
        f"- 模式：`{packet.get('mode')}`",
        f"- 主证据：`{packet['primary']['source']}` / {packet['primary']['language']}",
        (
            f"- 佐证：`{packet['corroborating']['source']}` / "
            f"{packet['corroborating']['language']}"
        ),
        f"- 时间窗：{packet['statistics']['window_count']}",
        f"- 高优先级：{packet['statistics']['high_priority_window_count']}",
        "",
        "原始 OCR/ASR 不会被修改。Agent 应逐窗提交高置信修改和未决冲突。",
        "",
    ]
    for window in packet.get("windows") or []:
        lines.extend(
            [
                f"## {window['window_id']} {window['start']}–{window['end']}",
                "",
                f"- 优先级：`{window['priority']}`",
                "- 原因：" + ", ".join(window.get("reasons") or ["routine_review"]),
                "",
                "### OCR",
                "",
            ]
        )
        if window.get("primary_cues"):
            for cue in window["primary_cues"]:
                flags = ",".join(flag["code"] for flag in cue.get("flags") or [])
                suffix = f" `{flags}`" if flags else ""
                lines.append(
                    f"- `{cue['cue_id']}` [{cue['start']}–{cue['end']}] "
                    f"{cue['text']}{suffix}"
                )
        else:
            lines.append("- （本时间窗没有 OCR 字幕）")
        lines.extend(["", "### ASR", ""])
        for cue in window.get("corroborating_cues") or []:
            lines.append(
                f"- `{cue['cue_id']}` [{cue['start']}–{cue['end']}] {cue['text']}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _report_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 字幕 Agent 审阅报告",
        "",
        f"- 状态：`{report['status']}`",
        (
            f"- 已审阅时间窗：{report['reviewed_window_count']} / "
            f"{report['window_count']}"
        ),
        f"- 已应用高置信修改：{report['applied_change_count']}",
        f"- 未决：{report['unresolved_count']}",
        "",
        "## 已应用修改",
        "",
    ]
    if not report["changes"]:
        lines.append("- 暂无")
    for change in report["changes"]:
        lines.append(
            f"- `{change['cue_id']}` {change['action']}："
            f"{change['original_text']} → {change['reviewed_text']}；"
            f"原因：{change['reason']}"
        )
    lines.extend(["", "## 未决", ""])
    if not report["unresolved"]:
        lines.append("- 暂无")
    for item in report["unresolved"]:
        lines.append(
            f"- `{item.get('cue_id') or item.get('window_id')}`：{item['issue']}"
        )
    return "\n".join(lines).rstrip() + "\n"


def _artifact(kind: str, path: Path, cue_count: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "kind": kind,
        "path": str(path.resolve()),
        "source": "video_subtitle:review",
        "owned_by_job": True,
        "bytes": path.stat().st_size,
    }
    if cue_count is not None:
        result["cue_count"] = cue_count
    return result


def _upsert_artifacts(
    manifest: dict[str, Any],
    artifacts: list[dict[str, Any]],
) -> None:
    existing = manifest.setdefault("artifacts", [])
    for artifact in artifacts:
        existing[:] = [
            item
            for item in existing
            if not (
                item.get("kind") == artifact.get("kind")
                and item.get("source") == artifact.get("source")
            )
        ]
        existing.append(artifact)


def _set_fusion_status(manifest: dict[str, Any], status: str) -> None:
    selected = manifest.get("selected_source")
    if isinstance(selected, dict) and selected.get("kind") == "evidence_bundle":
        selected["fusion_status"] = status


def _selected_primary_kind(manifest: dict[str, Any]) -> str:
    selected = manifest.get("selected_source") or {}
    if selected.get("kind") == "evidence_bundle":
        return str((selected.get("primary") or {}).get("kind") or "")
    return str(selected.get("kind") or "")


def _update_evidence_index(
    manifest: dict[str, Any],
    output_dir: Path,
) -> None:
    review = manifest.get("review") or {}
    selected = manifest.get("selected_source") or {}
    fusion_status = selected.get("fusion_status") or "not_required"
    evidence_json = output_dir / "evidence.index.json"
    if evidence_json.is_file():
        evidence = read_json(evidence_json)
        evidence["fusion_status"] = fusion_status
        evidence["review"] = review
        write_json_atomic(evidence_json, evidence)
    evidence_markdown = output_dir / "evidence.index.md"
    if evidence_markdown.is_file():
        content = evidence_markdown.read_text(encoding="utf-8", errors="replace")
        marker = "\n## Agent 审阅状态\n"
        content = content.split(marker, 1)[0].rstrip()
        content += (
            marker
            + "\n"
            + f"- 状态：`{review.get('status') or fusion_status}`\n"
            + f"- 时间窗：{review.get('reviewed_window_count', 0)} / "
            + f"{review.get('window_count', 0)}\n"
            + f"- 已应用修改：{review.get('applied_change_count', 0)}\n"
            + f"- 未决：{review.get('unresolved_count', 0)}\n"
        )
        evidence_markdown.write_text(content, encoding="utf-8")
