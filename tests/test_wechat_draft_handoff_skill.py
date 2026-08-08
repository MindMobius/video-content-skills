from pathlib import Path

ROOT = Path(__file__).parents[1]
HANDOFF_ROOT = ROOT / ".agents" / "skills" / "wechat-draft-handoff"
CONTENT_ROOT = ROOT / ".agents" / "skills" / "video-to-content"


def test_wechat_draft_handoff_requires_audited_explicitly_authorized_input() -> None:
    skill = (HANDOFF_ROOT / "SKILL.md").read_text(encoding="utf-8")
    normalized_skill = " ".join(skill.split())

    for contract in (
        "The user explicitly asked",
        "ready_for_delivery=true",
        "already signed in",
        "Saving the draft requires an explicit request",
        "Never ask the user for, extract, copy, export, log, or persist cookies",
    ):
        assert contract in normalized_skill

    assert "../video-to-content/SKILL.md" in skill
    assert "references/wechat-editor-checklist.md" in skill


def test_wechat_draft_handoff_keeps_image_transport_transient() -> None:
    skill = (HANDOFF_ROOT / "SKILL.md").read_text(encoding="utf-8")
    checklist = (HANDOFF_ROOT / "references" / "wechat-editor-checklist.md").read_text(
        encoding="utf-8"
    )
    normalized_contract = " ".join(f"{skill}\n{checklist}".split())

    for contract in (
        "text/html",
        "data:image/...;base64,...",
        "Base64 payload is transport data only",
        "mmbiz.qpic.cn",
        "temporary payload was not written to the delivery package or logs",
        "Visible body-image count equals the intended image count",
    ):
        assert contract in normalized_contract

    assert "Do not save it beside the article" in normalized_contract
    assert (
        "Content fidelity and platform handoff are independent states"
        in normalized_contract
    )


def test_wechat_draft_handoff_never_expands_into_publishing() -> None:
    skill = (HANDOFF_ROOT / "SKILL.md").read_text(encoding="utf-8")
    checklist = (HANDOFF_ROOT / "references" / "wechat-editor-checklist.md").read_text(
        encoding="utf-8"
    )

    assert "Never click publish" in skill
    assert "nothing was published" in skill
    assert "No publish, schedule, mass-send" in checklist


def test_core_content_skill_routes_optional_handoff_after_audit() -> None:
    content_skill = (CONTENT_ROOT / "SKILL.md").read_text(encoding="utf-8")
    article_reference = (CONTENT_ROOT / "references" / "wechat-article.md").read_text(
        encoding="utf-8"
    )
    create_prompt = (CONTENT_ROOT / "prompts" / "create-deliverable.md").read_text(
        encoding="utf-8"
    )
    audit_prompt = (CONTENT_ROOT / "prompts" / "audit-fidelity.md").read_text(
        encoding="utf-8"
    )

    for document in (content_skill, article_reference, create_prompt):
        assert "wechat-draft-handoff" in document

    assert "clipboard-only" in content_skill
    assert "Platform success never changes the content fidelity audit" in " ".join(
        article_reference.split()
    )
    assert "platform state is a separate receipt" in " ".join(audit_prompt.split())


def test_public_docs_discover_the_optional_handoff_and_real_case() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    workflow = (ROOT / "docs" / "content-workflow.md").read_text(encoding="utf-8")
    reproducibility = (ROOT / "docs" / "reproducibility.md").read_text(encoding="utf-8")
    case = (ROOT / "docs" / "cases" / "BV1hK3v6LELB-wechat-draft-handoff.md").read_text(
        encoding="utf-8"
    )

    for document in (readme, agents, workflow, reproducibility):
        assert "wechat-draft-handoff" in document

    assert "mmbiz.qpic.cn" in workflow
    assert "7 张正文图片" in case
    assert "没有发表" in case
