from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / ".agents" / "skills" / "wechat-draft"


def test_wechat_skill_requires_visible_state_and_validated_receipt() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    checklist = (SKILL_ROOT / "references" / "editor-checklist.md").read_text(
        encoding="utf-8"
    )
    contract = f"{skill}\n{checklist}"
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
        "video-content/wechat-editor-observation-v2",
        "supersedes_receipt_id",
        "creationSourceSelector",
        "post-refresh snapshot",
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
