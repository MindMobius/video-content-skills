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
