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


def test_readme_is_a_short_human_overview() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.startswith("# Video Content Skills\n")
    assert len(readme.splitlines()) <= 100
    for heading in ("## 能做什么", "## 处理管线", "## 目前已经具备", "## 主要组件"):
        assert heading in readme
    assert "```mermaid" in readme
    assert "AGENTS.md" in readme
    assert "高保真" in readme
    assert "不发布" in readme
    assert "按需" in readme
    for removed_heading in (
        "## 六种核心产物",
        "## 渐进式读取",
        "## 新机器入口",
        "## 不变量",
        "## 验证",
        "## CLI",
        "## MCP",
    ):
        assert removed_heading not in readme


def test_agents_is_the_operational_entrypoint() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith("# Repository Instructions\n")
    assert "## Agent entry" in agents
    for token in (
        "git rev-parse --show-toplevel",
        "validate_layout.py",
        "scripts/bootstrap.py",
        "system setup",
        "scripts/runtime_setup.py",
        "system doctor",
        "agent_actions",
        "human_actions",
        "configuration.path",
        "configuration.state_root",
        "config",
        "home",
        "run_id",
        "`.agents/skills/` is the only canonical Skill source",
        "published=false",
        "先判断任务类型",
        "不安装 VideOCR/ASR",
        "platform_subtitle",
        "hard_ocr_url",
        "audio_asr_url",
        "watch_later_monitor",
        "source-aware-expression-audit.md",
    ):
        assert token in agents
    for skill in EXPECTED_SKILLS:
        assert f".agents/skills/{skill}/SKILL.md" in agents


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
        "repository-layout.md",
        "skill-maintenance.md",
    ]
    plans = sorted(path.name for path in (ROOT / "docs" / "plans").glob("*.md"))
    assert plans == [
        "2026-08-17-video-content-clean-slate-design.md",
        "2026-08-17-video-content-clean-slate.md",
        "2026-08-22-source-faithful-adaptation-design.md",
        "2026-08-22-source-faithful-adaptation.md",
        "2026-08-28-source-aware-expression-audit-design.md",
        "2026-08-28-source-aware-expression-audit.md",
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
        "文章很短不等于文章很干净",
        "截图存在不等于截图被使用",
        "平台点击成功不等于平台状态成立",
        "经验沉淀模板",
    ):
        assert token in maintenance


def test_operations_document_separates_content_and_platform_failures() -> None:
    operations = (ROOT / "docs" / "operations.md").read_text(encoding="utf-8")
    architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    for token in (
        "真实运行中的常见假完成",
        "微信交接的重试顺序",
        "完成证据分层",
        "有副作用的重试",
        "保存 Toast",
        "同一数字 `appmsgid`",
    ):
        assert token in f"{operations}\n{architecture}"


def test_repository_routes_source_aware_expression_review() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    maintenance = (ROOT / "docs" / "skill-maintenance.md").read_text(encoding="utf-8")
    contract = f"{readme}\n{agents}\n{architecture}\n{maintenance}"

    assert "来源感知表达审校" in contract
    assert "expression_audit" in contract
    assert "固定公众号文风" in contract
    assert "Agent 新增" in contract


def test_repository_layout_defines_one_runtime_root() -> None:
    layout = (ROOT / "docs" / "repository-layout.md").read_text(encoding="utf-8")
    for token in (
        ".video-content/",
        "config.json",
        "profiles/",
        "jobs/",
        "cache/media/",
        "runs/",
        "archive/",
        "migration-receipt.json",
        "path-relocation.json",
        "state-layout.json",
        "validate_layout.py",
        "historical_path_references",
        "临时 Store",
    ):
        assert token in layout


def test_project_language_covers_viewpoint_and_clean_omissions() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    operations = (ROOT / "docs" / "operations.md").read_text(encoding="utf-8")
    maintenance = (ROOT / "docs" / "skill-maintenance.md").read_text(encoding="utf-8")
    contract = f"{readme}\n{agents}\n{architecture}\n{operations}\n{maintenance}"

    for token in (
        "二手解说",
        "叙述视角",
        "商品推广",
        "占位说明",
        "不是每个 cue",
    ):
        assert token in contract
