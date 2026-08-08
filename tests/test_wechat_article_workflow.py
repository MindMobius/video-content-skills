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


def test_wechat_article_defaults_to_minimal_edit_image_markers() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    prompt = (SKILL_ROOT / "prompts" / "create-deliverable.md").read_text(
        encoding="utf-8"
    )
    audit = (SKILL_ROOT / "prompts" / "audit-fidelity.md").read_text(encoding="utf-8")
    reference = (SKILL_ROOT / "references" / "wechat-article.md").read_text(
        encoding="utf-8"
    )

    normalized_skill = " ".join(skill.split())
    normalized_prompt = " ".join(prompt.split())
    normalized_audit = " ".join(audit.split())
    normalized_reference = " ".join(reference.split())

    assert "default is a minimal-edit marker" in normalized_skill
    assert "Default to a minimal-edit marker" in normalized_prompt
    assert "default minimal-edit mode" in normalized_audit
    for required_contract in (
        "default to minimal-edit mode",
        "one human-visible line",
        "relative asset path",
        "data-local-image-slot",
        "delete at most one visible element",
        "A descriptive slot is opt-in",
        "do not expose an absolute machine path",
    ):
        assert required_contract in normalized_reference

    assert "boxed placeholder cards" in normalized_audit
    assert (
        "Renderer documentation does not override this handoff rule"
        in normalized_prompt
    )


def test_public_docs_describe_minimal_edit_image_handoff() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    workflow = (ROOT / "docs" / "content-workflow.md").read_text(encoding="utf-8")
    case = (
        ROOT / "docs" / "cases" / "BV1xK3h6fE7a-wechat-minimal-image-handoff.md"
    ).read_text(encoding="utf-8")

    assert "单行相对图片路径" in readme
    assert "单行相对路径标记" in workflow
    assert "机器校验信息放在" in workflow
    assert "机器验证信息与人类编辑界面必须分离" in case
    assert "dlv-001 -> dlv-002" in case
