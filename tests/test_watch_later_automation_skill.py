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


def test_agent_routing_and_dsh_register_automation_skill() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    plugin = (ROOT / "dsh" / "plugin.js").read_text(encoding="utf-8")
    assert "video-watch-later-automation" in agents
    assert "video-watch-later-automation" in plugin
