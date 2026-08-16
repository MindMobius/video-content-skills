from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / ".agents" / "skills"


def _frontmatter_value(content: str, field: str) -> str:
    match = re.search(rf"(?m)^{re.escape(field)}:\s*(.+?)\s*$", content)
    if match is None:
        raise AssertionError(f"SKILL.md is missing {field!r}")
    return match.group(1).strip().strip("\"'")


def _interface_value(content: str, field: str) -> str:
    match = re.search(rf'(?m)^  {re.escape(field)}: "([^"]+)"$', content)
    if match is None:
        raise AssertionError(f"agents/openai.yaml is missing quoted {field!r}")
    return match.group(1)


def test_project_skills_use_the_standard_discovery_directory() -> None:
    assert not (ROOT / "skills").exists()
    assert (ROOT / "AGENTS.md").is_file()

    discovered = sorted(SKILLS_ROOT.glob("*/SKILL.md"))
    assert [path.parent.name for path in discovered] == [
        "video-subtitle",
        "video-to-content",
        "wechat-draft-handoff",
    ]
    for skill_path in discovered:
        content = skill_path.read_text(encoding="utf-8")
        assert _frontmatter_value(content, "name") == skill_path.parent.name
        assert _frontmatter_value(content, "description")


def test_project_skills_include_valid_openai_interface_metadata() -> None:
    for skill_path in sorted(SKILLS_ROOT.glob("*/SKILL.md")):
        skill_name = skill_path.parent.name
        metadata_path = skill_path.parent / "agents" / "openai.yaml"
        assert metadata_path.is_file()
        metadata = metadata_path.read_text(encoding="utf-8")

        assert metadata.startswith("interface:\n")
        assert _interface_value(metadata, "display_name")
        short_description = _interface_value(metadata, "short_description")
        assert 25 <= len(short_description) <= 64
        default_prompt = _interface_value(metadata, "default_prompt")
        assert f"${skill_name}" in default_prompt


def test_skill_markdown_relative_links_resolve() -> None:
    missing: list[str] = []
    for markdown_path in SKILLS_ROOT.rglob("*.md"):
        content = markdown_path.read_text(encoding="utf-8")
        for raw_target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", content):
            target = raw_target.strip().strip("<>")
            if "://" in target or target.startswith("#"):
                continue
            relative_target = target.split("#", 1)[0]
            if not (markdown_path.parent / relative_target).resolve().exists():
                missing.append(f"{markdown_path.relative_to(ROOT)} -> {target}")

    assert missing == []


def test_public_entrypoints_discover_reliability_and_timing_contracts() -> None:
    documents = {
        path: (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "AGENTS.md",
            "README.md",
            "docs/workflow.md",
            "docs/content-workflow.md",
            "docs/environment.md",
            "docs/reproducibility.md",
            ".agents/skills/video-subtitle/SKILL.md",
            ".agents/skills/video-to-content/SKILL.md",
        )
    }
    subtitle_contract = "\n".join(
        documents[path]
        for path in (
            "AGENTS.md",
            "README.md",
            "docs/workflow.md",
            "docs/environment.md",
            ".agents/skills/video-subtitle/SKILL.md",
        )
    )
    content_contract = "\n".join(
        documents[path]
        for path in (
            "AGENTS.md",
            "README.md",
            "docs/content-workflow.md",
            "docs/reproducibility.md",
            ".agents/skills/video-to-content/SKILL.md",
        )
    )

    for token in (
        "plan_hard_subtitle_scout",
        "ocr-scout-plan",
        "opencli_browser_timeout",
        "download_retries",
        "download_retry_backoff",
        "download_cache",
        "actual_bytes",
        "actual_mib",
    ):
        assert token in subtitle_contract

    for token in (
        "start_video_content_phase",
        "finish_video_content_phase",
        "content-phase-start",
        "content-phase-finish",
        "timing_summary",
    ):
        assert token in content_contract


def test_skill_entrypoints_discover_reproducible_runtime_and_handoff_tools() -> None:
    subtitle_skill = (SKILLS_ROOT / "video-subtitle" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    content_skill = (SKILLS_ROOT / "video-to-content" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    handoff_skill = (SKILLS_ROOT / "wechat-draft-handoff" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    public_docs = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "AGENTS.md",
            "README.md",
            "docs/environment.md",
            "docs/reproducibility.md",
            "docs/content-workflow.md",
        )
    )

    for token in (
        "requirements/runtime-lock.json",
        "scripts/runtime_setup.py plan",
        "--confirm-large-download",
        "scripts/repro_check.py",
    ):
        assert token in f"{subtitle_skill}\n{public_docs}"

    for token in (
        "initialize_video_batch",
        "get_video_batch",
        "update_video_batch_item",
        "scripts/render_wechat_article.py",
        "video-content/wechat-manuscript-v1",
        "scripts/project_bundle.py",
        "video-content/portable-bundle-v1",
    ):
        assert token in f"{content_skill}\n{public_docs}"

    for token in (
        "scripts/prepare_clipboard.py",
        "scripts/browser-adapter.js",
        "video-content/wechat-editor-observation-v1",
        "scripts/build_wechat_draft_receipt.py",
    ):
        assert token in handoff_skill

    for schema in (
        "runtime-lock.schema.json",
        "batch-manifest.schema.json",
        "portable-bundle.schema.json",
        "wechat-manuscript.schema.json",
        "wechat-browser-snapshot.schema.json",
        "wechat-editor-observation.schema.json",
    ):
        assert (ROOT / "schemas" / schema).is_file()


def test_mcp_smoke_reports_batch_tool_discovery() -> None:
    smoke = (ROOT / "scripts" / "mcp_smoke.py").read_text(encoding="utf-8")

    assert '"batch_tools_exposed"' in smoke
    for tool_name in (
        "initialize_video_batch",
        "get_video_batch",
        "update_video_batch_item",
    ):
        assert f'"{tool_name}"' in smoke


def test_hard_subtitle_decision_is_independent_of_platform_tracks() -> None:
    skill = (SKILLS_ROOT / "video-subtitle" / "SKILL.md").read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    workflow = (ROOT / "docs" / "workflow.md").read_text(encoding="utf-8")

    assert re.search(r"two\s+independent observations", skill)
    assert "A usable platform track does not permit skipping this decision" in skill
    assert re.search(r"whether or not platform\s+subtitles exist", agents)
    assert "平台字幕是否存在与连续硬字幕是否存在是两个独立问题" in workflow
    assert (
        "When platform subtitles are absent and continuous hard subtitles" not in skill
    )


def test_package_versions_are_synchronized_semver() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    package = (ROOT / "src" / "video_subtitle" / "__init__.py").read_text(
        encoding="utf-8"
    )
    project_version = re.search(r'(?m)^version = "([^"]+)"$', pyproject)
    package_version = re.search(r'(?m)^__version__ = "([^"]+)"$', package)

    assert project_version is not None
    assert package_version is not None
    assert project_version.group(1) == package_version.group(1)
    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", project_version.group(1))
