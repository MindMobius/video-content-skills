from __future__ import annotations

from pathlib import Path

from scripts.repro_check import _check_watch_later_to_draft_contract

ROOT = Path(__file__).resolve().parents[1]


def test_watch_later_to_draft_fixture_is_idempotent_and_fail_closed(
    tmp_path: Path,
) -> None:
    fixture = ROOT / "tests" / "fixtures" / "automation" / "fixture.json"
    result = _check_watch_later_to_draft_contract(tmp_path, fixture_path=fixture)

    assert result["jobs_created"] == 1
    assert result["completed_jobs"] == 1
    assert result["draft_bindings"] == 1
    assert result["duplicate_jobs"] == 0
    assert result["duplicate_drafts"] == 0
    assert result["unprocessable_jobs"] == 1
    assert result["content_created_for_unprocessable"] is False
    assert result["raw_evidence_hashes_preserved"] is True
    assert result["published"] is False
    assert result["publish_actions_performed"] == []
