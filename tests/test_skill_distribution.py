from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / ".agents" / "skills"
EXPECTED = [
    "video-evidence",
    "video-to-content",
    "watch-later-to-wechat",
    "wechat-draft",
]


def _frontmatter(content: str, field: str) -> str:
    match = re.search(rf"(?m)^{re.escape(field)}:\s*(.+?)\s*$", content)
    if match is None:
        raise AssertionError(f"Missing frontmatter field: {field}")
    return match.group(1).strip().strip("\"'")


def test_only_four_canonical_skills_exist() -> None:
    assert not (ROOT / "skills").exists()
    discovered = sorted(path.parent.name for path in SKILLS_ROOT.glob("*/SKILL.md"))
    assert discovered == EXPECTED
    for name in EXPECTED:
        skill = (SKILLS_ROOT / name / "SKILL.md").read_text(encoding="utf-8")
        assert _frontmatter(skill, "name") == name
        assert _frontmatter(skill, "description")
        assert len(skill.splitlines()) <= 180


def test_every_skill_has_agent_metadata_and_valid_local_links() -> None:
    for name in EXPECTED:
        metadata = (SKILLS_ROOT / name / "agents" / "openai.yaml").read_text(
            encoding="utf-8"
        )
        assert metadata.startswith("interface:\n")
        assert f"${name}" in metadata
    missing: list[str] = []
    for markdown in SKILLS_ROOT.rglob("*.md"):
        for target in re.findall(
            r"\[[^\]]+\]\(([^)]+)\)", markdown.read_text(encoding="utf-8")
        ):
            target = target.strip().strip("<>")
            if "://" in target or target.startswith("#"):
                continue
            local = target.split("#", 1)[0]
            if not (markdown.parent / local).resolve().exists():
                missing.append(f"{markdown.relative_to(ROOT)} -> {target}")
    assert missing == []
