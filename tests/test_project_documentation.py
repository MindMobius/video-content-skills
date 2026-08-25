from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SKILLS = (
    "video-evidence",
    "video-to-content",
    "watch-later-to-wechat",
    "wechat-draft",
)


def test_readme_is_a_concise_agent_router() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.startswith("# Video Content Skills\n")
    assert len(readme.splitlines()) <= 160
    assert "## Agent 任务路由" in readme
    assert "## 渐进式读取" in readme
    assert "docs/skill-maintenance.md" in readme
    for skill in EXPECTED_SKILLS:
        assert f".agents/skills/{skill}/SKILL.md" in readme
    for removed_heading in ("## CLI", "## MCP", "## 多视频任务编排与耗时优化"):
        assert removed_heading not in readme


def test_active_documents_define_the_six_product_clean_surface() -> None:
    active = [
        ROOT / "README.md",
        ROOT / "AGENTS.md",
        *sorted((ROOT / "docs").glob("*.md")),
    ]
    contract = "\n".join(path.read_text(encoding="utf-8") for path in active)
    for product in (
        "Profile",
        "Job",
        "Evidence",
        "Transcript",
        "Content",
        "Draft Receipt",
    ):
        assert product in contract

    operations = (ROOT / "docs" / "operations.md").read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "scripts/migrate_legacy_state.py" in operations
    assert "scripts/migrate_legacy_state.py" in agents


def test_metadata_uses_the_1_0_identity() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert package["name"] == "video-content-skills"
    assert package["version"] == "1.0.0"
    assert package["private"] is True
    assert 'name = "video-content-skills"' in pyproject
    assert 'version = "1.0.0"' in pyproject
    assert 'video-content = "video_content.cli:main"' in pyproject
    assert 'video-content-mcp = "video_content.mcp_server:main"' in pyproject


def test_docs_are_progressive_not_historical_dump() -> None:
    assert sorted(path.name for path in (ROOT / "docs").glob("*.md")) == [
        "architecture.md",
        "operations.md",
        "skill-maintenance.md",
    ]
    plans = sorted(path.name for path in (ROOT / "docs" / "plans").glob("*.md"))
    assert plans == [
        "2026-08-17-video-content-clean-slate-design.md",
        "2026-08-17-video-content-clean-slate.md",
        "2026-08-22-source-faithful-adaptation-design.md",
        "2026-08-22-source-faithful-adaptation.md",
    ]
    assert not (ROOT / "docs" / "cases").exists()


def test_skill_maintenance_turns_real_failures_into_enforced_contracts() -> None:
    maintenance = (ROOT / "docs" / "skill-maintenance.md").read_text(encoding="utf-8")
    for token in (
        "流程完成不等于内容完成",
        "先写失败测试",
        "Agent 语义判断",
        "确定性验收",
        "真实输出",
        "字幕直贴",
    ):
        assert token in maintenance
