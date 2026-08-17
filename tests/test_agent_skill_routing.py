from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / ".agents" / "skills"


def test_video_evidence_routes_progressively() -> None:
    skill = (SKILLS / "video-evidence" / "SKILL.md").read_text(encoding="utf-8")
    normalized = " ".join(skill.split())
    for token in (
        "system_setup",
        "setup.ready=true",
        "system_doctor",
        "source_inspect",
        "evidence_start",
        "transcript_save",
        "platform subtitle track and visible hard subtitles as independent facts",
        "unprocessable",
        "paused_auth",
    ):
        assert token in normalized
    assert "references/environment.md" in skill
    assert "references/evidence-decisions.md" in skill


def test_content_and_handoff_are_separate_authorization_stages() -> None:
    content = (SKILLS / "video-to-content" / "SKILL.md").read_text(encoding="utf-8")
    handoff = (SKILLS / "wechat-draft" / "SKILL.md").read_text(encoding="utf-8")
    normalized_content = " ".join(content.split())
    normalized_handoff = " ".join(handoff.split())
    assert (
        "Content validation does not authorize a platform action" in normalized_content
    )
    assert "original cover and timestamped source frames" in normalized_content
    assert "explicitly authorize" in normalized_handoff
    assert "refresh readback" in normalized_handoff
    assert "published=false" in normalized_handoff
    assert "Never click publish" in normalized_handoff


def test_watch_later_skill_orchestrates_without_daemon_or_batch() -> None:
    skill = (SKILLS / "watch-later-to-wechat" / "SKILL.md").read_text(encoding="utf-8")
    for token in (
        "$video-evidence",
        "$video-to-content",
        "$wechat-draft",
        "watch_later_scan",
        "job_list",
        "BVID/page",
        "OCR and ASR share the GPU serially",
        "do not create a hidden daemon",
        "No duplicate Job",
    ):
        assert token in skill
    assert "batch" not in skill.lower()
