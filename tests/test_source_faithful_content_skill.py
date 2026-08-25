from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / ".agents" / "skills"
CONTENT_SKILL = SKILLS / "video-to-content"


def test_video_to_content_defaults_to_source_faithful_adaptation() -> None:
    skill = (CONTENT_SKILL / "SKILL.md").read_text(encoding="utf-8")
    prompt = (CONTENT_SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")
    normalized = " ".join(skill.split())

    assert "references/source-faithful-adaptation.md" in skill
    assert "source structure" in normalized
    assert "explicitly requested" in normalized
    assert "source-faithful" in prompt


def test_source_faithful_reference_defines_editorial_boundaries() -> None:
    reference = CONTENT_SKILL / "references" / "source-faithful-adaptation.md"
    assert reference.exists()
    content = reference.read_text(encoding="utf-8")

    for token in (
        "ephemeral source map",
        "新增比喻",
        "人物身份",
        "原有顺序",
        "明确要求",
        "机械拼接",
        "逐条字幕",
    ):
        assert token in content


def test_traceability_and_wechat_preserve_source_authorship() -> None:
    traceability = (CONTENT_SKILL / "references" / "traceability.md").read_text(
        encoding="utf-8"
    )
    wechat = (CONTENT_SKILL / "references" / "wechat-article.md").read_text(
        encoding="utf-8"
    )

    assert "人物身份" in traceability
    assert "来源顺序" in traceability
    assert "不是新的作者" in wechat


def test_repository_promises_high_fidelity_carrier_migration() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "来源忠实" in agents
    assert "高保真" in readme


def test_full_fidelity_audit_maps_sections_and_frames_to_output_blocks() -> None:
    skill = (CONTENT_SKILL / "SKILL.md").read_text(encoding="utf-8")
    traceability = (CONTENT_SKILL / "references" / "traceability.md").read_text(
        encoding="utf-8"
    )
    frames = (CONTENT_SKILL / "references" / "source-frame-selection.md").read_text(
        encoding="utf-8"
    )

    assert "material_sections.items" in skill
    assert "source_cue_indices" in traceability
    assert "output_block_indices" in traceability
    assert "block_index" in frames
    assert "media 列表" in frames
    assert "raw Transcript passthrough" in skill
