from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_watch_later_automation_skill_encodes_fail_closed_flow() -> None:
    skill_path = (
        ROOT / ".agents" / "skills" / "video-watch-later-automation" / "SKILL.md"
    )
    text = skill_path.read_text(encoding="utf-8")
    assert "scan_bilibili_watch_later" in text
    assert "save_canonical_subtitle" in text
    assert "unprocessable" in text
    assert "paused_auth" in text
    assert "save_wechat_draft" in text
    assert "never publish" in text.lower()
    assert "do not ask the user" in text.lower()
    assert "baseline_if_empty=true" in text


def test_agent_routing_and_dsh_register_automation_skill() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    plugin = (ROOT / "dsh" / "plugin.js").read_text(encoding="utf-8")
    assert "video-watch-later-automation" in agents
    assert "video-watch-later-automation" in plugin


def test_public_docs_explain_the_one_shot_operator_contract() -> None:
    guide_path = ROOT / "docs" / "watch-later-automation.md"
    guide = guide_path.read_text(encoding="utf-8")
    public_docs = [
        (ROOT / "README.md").read_text(encoding="utf-8"),
        (ROOT / "docs" / "environment.md").read_text(encoding="utf-8"),
        (ROOT / "docs" / "reproducibility.md").read_text(encoding="utf-8"),
    ]

    for token in (
        "watch_later_monitor",
        "automation-profile-save",
        "automation-authorize-drafts",
        "--confirm-draft-only-authorization",
        "automation-scan",
        "--baseline-if-empty",
        "BILIBILI_RISK_CONTROL",
        "--store",
        "unprocessable",
        "paused_auth",
        "manual_required",
        "published=false",
    ):
        assert token in guide

    for document in public_docs:
        assert "watch-later-automation.md" in document
