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
