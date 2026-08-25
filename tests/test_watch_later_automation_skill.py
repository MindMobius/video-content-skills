from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / ".agents" / "skills" / "watch-later-to-wechat"


def test_watch_later_skill_keeps_operational_failure_policy() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    lifecycle = (SKILL_ROOT / "references" / "job-lifecycle.md").read_text(
        encoding="utf-8"
    )
    contract = f"{skill}\n{lifecycle}"
    for token in (
        "retryable",
        "paused_auth",
        "unprocessable",
        "completed",
        "published=false",
        "run_id",
        "one current validated Draft Receipt",
        "source_faithful_full",
        "minimum_source_frames",
        "内容由AI生成",
        "supersede",
        "raw Transcript passthrough",
    ):
        assert token in contract
    for prohibited in (
        "publish",
        "schedule",
        "mass send",
        "originality",
        "account management",
    ):
        assert prohibited in skill
