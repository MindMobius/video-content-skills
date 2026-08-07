from pathlib import Path

ROOT = Path(__file__).parents[1]
SKILL_ROOT = ROOT / ".agents" / "skills" / "video-to-content"


def test_wechat_article_reference_is_routed_from_skill_and_prompt() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    prompt = (SKILL_ROOT / "prompts" / "create-deliverable.md").read_text(
        encoding="utf-8"
    )

    assert "references/wechat-article.md" in skill
    assert "../references/wechat-article.md" in prompt


def test_wechat_article_reference_preserves_agent_and_renderer_boundaries() -> None:
    reference = (SKILL_ROOT / "references" / "wechat-article.md").read_text(
        encoding="utf-8"
    )

    required_sections = [
        "## Responsibility split",
        "## Build the manuscript first",
        "## Use a renderer as an optional downstream Skill",
        "## Package local images explicitly",
        "## Validate two independent layers",
        "## Final handoff",
    ]
    for section in required_sections:
        assert section in reference

    assert "not a dependency of this repository" in reference
    assert (
        "Renderer validation proves markup compatibility, not semantic fidelity"
        in reference
    )
    assert "skills@1.5.22" in reference
    assert "--list" in reference
    assert "remain outside this project" in reference


def test_wechat_article_reference_defines_local_image_handoff_package() -> None:
    reference = (SKILL_ROOT / "references" / "wechat-article.md").read_text(
        encoding="utf-8"
    )

    for artifact in (
        "article.md",
        "article.html",
        "article-preview.html",
        "cover.jpg",
        "image-import-checklist.md",
    ):
        assert artifact in reference

    for unsupported_source in ("`file:`", "`data:`", "`blob:`"):
        assert unsupported_source in reference

    assert "复制排版正文" in reference
    assert "formatted body was copied" in reference
    assert "manual insertion" in reference
