from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / ".agents" / "skills" / "wechat-draft"


def test_wechat_skill_requires_visible_state_and_validated_receipt() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    checklist = (SKILL_ROOT / "references" / "editor-checklist.md").read_text(
        encoding="utf-8"
    )
    document_import = (SKILL_ROOT / "references" / "document-import.md").read_text(
        encoding="utf-8"
    )
    contract = f"{skill}\n{checklist}\n{document_import}"
    for token in (
        "content_validate.valid=true",
        "scripts/prepare_clipboard.py",
        "scripts/browser-adapter.js",
        "stable numeric `appmsgid`",
        "refresh readback",
        "published=false",
        "zero local-path markers",
        "Never save a second draft",
        "内容由AI生成",
        "video-content/wechat-editor-observation-v3",
        "supersedes_receipt_id",
        "creationSourceSelector",
        "post-refresh snapshot",
        "article-import.docx",
        "document-import.md",
        "opening, middle, and ending",
        "natural_width",
        "natural_height",
        "aspect ratio",
        "wp:extent",
        "setFiles: Not allowed",
        "article-import",
    ):
        assert token in contract
    for secret in ("cookies", "tokens", "browser storage", "clipboard"):
        assert secret in contract


def test_wechat_skill_scripts_use_new_runtime_name() -> None:
    browser = (SKILL_ROOT / "scripts" / "browser-adapter.js").read_text(
        encoding="utf-8"
    )
    clipboard = (SKILL_ROOT / "scripts" / "prepare_clipboard.py").read_text(
        encoding="utf-8"
    )
    assert "video-content/wechat-browser-adapter" in browser
    assert "video_content.wechat_adapter" in clipboard


def test_wechat_skill_has_same_target_recovery_rules() -> None:
    recovery = (SKILL_ROOT / "references" / "recovery-and-readback.md").read_text(
        encoding="utf-8"
    )
    for token in (
        "先观察，再重试",
        "同一目标",
        "稳定数字 `appmsgid`",
        "不要新建第二篇",
        "paused_auth",
        "retryable",
        "刷新或重新打开",
        "内容由AI生成",
        "文档导入",
        "叠加剪贴板",
        "setFiles: Not allowed",
        "同一已登录会话中新开 Agent 控制标签页",
        "wechat-editor-observation-v3",
        "天然宽高",
    ):
        assert token in recovery
