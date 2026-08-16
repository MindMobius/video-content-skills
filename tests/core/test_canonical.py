from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from video_subtitle.core.canonical import (
    get_canonical_subtitle,
    require_usable_canonical_subtitle,
    save_canonical_subtitle,
)
from video_subtitle.core.evidence import list_subtitle_evidence_for_manifest
from video_subtitle.core.srt import Cue, write_srt
from video_subtitle.core.util import write_json_atomic


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(tmp_path: Path) -> Path:
    subtitle = tmp_path / "subtitle.platform.srt"
    write_srt(
        subtitle,
        [Cue(0, 1000, "第一句"), Cue(1000, 2000, "第二句")],
    )
    manifest = tmp_path / "manifest.json"
    write_json_atomic(
        manifest,
        {
            "schema_version": "video-subtitle/v1",
            "job_id": "sub_canonical",
            "status": "completed",
            "video": {"bvid": "BV1canonical", "duration_seconds": 2},
            "selected_source": {"kind": "platform_subtitle"},
            "sources": [
                {
                    "kind": "platform_subtitle",
                    "artifact_source": "platform_subtitle:bilibili",
                    "cue_count": 2,
                }
            ],
            "review": None,
            "artifacts": [
                {
                    "kind": "subtitle_srt",
                    "source": "platform_subtitle:bilibili",
                    "path": str(subtitle),
                    "owned_by_job": True,
                    "selected": True,
                    "cue_count": 2,
                }
            ],
        },
    )
    return manifest


def _usable_document(manifest: Path) -> dict:
    catalog = list_subtitle_evidence_for_manifest(manifest)
    evidence = catalog["evidence"][0]
    return {
        "manifest_sha256": _sha(manifest),
        "status": "usable",
        "evidence": [
            {
                "evidence_id": evidence["evidence_id"],
                "sha256": _sha(Path(evidence["path"])),
                "role": "primary",
            }
        ],
        "cues": [
            {
                "start_ms": 0,
                "end_ms": 1000,
                "text": "第一句",
                "evidence_refs": ["ev-0001-cue-00001"],
            },
            {
                "start_ms": 1000,
                "end_ms": 2000,
                "text": "第二句",
                "evidence_refs": ["ev-0001-cue-00002"],
            },
        ],
        "decisions": [],
        "unresolved": [],
        "termination": None,
    }


def test_usable_canonical_is_added_as_derived_evidence(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    raw_path = tmp_path / "subtitle.platform.srt"
    raw_bytes = raw_path.read_bytes()
    result = save_canonical_subtitle(manifest, document=_usable_document(manifest))
    assert result["status"] == "usable"
    assert Path(result["artifacts"]["srt"]).is_file()
    assert raw_path.read_bytes() == raw_bytes
    catalog = list_subtitle_evidence_for_manifest(manifest)
    canonical = next(
        item
        for item in catalog["evidence"]
        if item["source_kind"] == "canonical_subtitle"
    )
    assert canonical["layer"] == "derived"
    assert canonical["selected"] is True
    assert (
        require_usable_canonical_subtitle(manifest)["canonical_id"]
        == result["canonical_id"]
    )


def test_canonical_rejects_stale_hash_and_blocking_issue(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    stale = _usable_document(manifest)
    stale["manifest_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="manifest"):
        save_canonical_subtitle(manifest, document=stale)

    blocked = _usable_document(manifest)
    blocked["unresolved"] = [{"issue": "关键人名无法确认", "blocking": True}]
    with pytest.raises(ValueError, match="blocking"):
        save_canonical_subtitle(manifest, document=blocked)


def test_unusable_canonical_writes_report_without_evidence(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    document = _usable_document(manifest)
    document.update(
        {
            "status": "unusable",
            "cues": [],
            "unresolved": [{"issue": "音频不可辨认", "blocking": True}],
            "termination": {
                "code": "INSUFFICIENT_EVIDENCE",
                "message": "No reliable transcript can be produced.",
            },
        }
    )
    result = save_canonical_subtitle(manifest, document=document)
    assert result["status"] == "unusable"
    assert result["artifacts"]["srt"] is None
    assert Path(result["artifacts"]["report"]).is_file()
    assert not any(
        item["source_kind"] == "canonical_subtitle"
        for item in list_subtitle_evidence_for_manifest(manifest)["evidence"]
    )
    with pytest.raises(ValueError, match="usable"):
        require_usable_canonical_subtitle(manifest)
    assert get_canonical_subtitle(manifest)["termination"]["code"] == (
        "INSUFFICIENT_EVIDENCE"
    )
