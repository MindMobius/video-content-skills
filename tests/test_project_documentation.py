from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SKILLS = (
    "video-subtitle",
    "video-to-content",
    "video-watch-later-automation",
    "wechat-draft-handoff",
)


def test_readme_is_a_concise_agent_router() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert readme.startswith("# Video Content Skills\n")
    assert len(readme.splitlines()) <= 180
    assert "## Agent 任务路由" in readme
    assert "## 渐进式读取" in readme
    assert "docs/skill-maintenance.md" in readme
    for skill_name in EXPECTED_SKILLS:
        assert f".agents/skills/{skill_name}/SKILL.md" in readme

    for former_manual_heading in (
        "## CLI",
        "## MCP",
        "## OCR / ASR 调度",
        "## 多视频任务编排与耗时优化",
    ):
        assert former_manual_heading not in readme
    assert readme.count("```") // 2 <= 2


def test_skill_maintenance_contract_exists() -> None:
    content = (ROOT / "docs" / "skill-maintenance.md").read_text(encoding="utf-8")

    for expected in (
        ".agents/skills/",
        "SKILL.md",
        "references/",
        "agents/openai.yaml",
        "兼容",
        "python -m pytest",
        "npm run pack:check",
    ):
        assert expected in content


def test_active_documents_use_the_new_project_identity() -> None:
    active_documents = [ROOT / "README.md", ROOT / "AGENTS.md"]
    active_documents.extend(sorted((ROOT / "docs").glob("*.md")))
    stale: list[str] = []

    for path in active_documents:
        content = path.read_text(encoding="utf-8")
        if "Video Subtitle Skill" in content:
            stale.append(f"{path.relative_to(ROOT)}: old project title")
        if "MindMobius/video-subtitle-skill" in content:
            stale.append(f"{path.relative_to(ROOT)}: old repository URL")

    assert stale == []


def test_distribution_name_stays_compatible_while_repository_is_rebranded() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert package["name"] == "video-subtitle-skill"
    assert 'name = "video-subtitle-skill"' in pyproject
    assert package["repository"]["url"].endswith("MindMobius/video-content-skills.git")
    expected_description = (
        "Agent-native video evidence and content production skills with auditable "
        "subtitle, automation, and draft handoff workflows."
    )
    assert package["description"] == expected_description
    assert f'description = "{expected_description}"' in pyproject
    assert {"agent-skills", "video-content", "automation", "wechat"} <= set(
        package["keywords"]
    )
    assert "https://github.com/MindMobius/video-content-skills" in pyproject
    assert 'video-subtitle = "video_subtitle.cli:main"' in pyproject
    assert 'video-subtitle-mcp = "video_subtitle.mcp_server:main"' in pyproject
