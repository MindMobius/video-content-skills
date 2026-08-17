from __future__ import annotations

from typing import Any

from . import api

try:
    from mcp.server import MCPServer as McpServer
except ImportError:  # pragma: no cover
    McpServer = None  # type: ignore[assignment,misc]

TOOL_NAMES = (
    "system_setup",
    "system_configure",
    "system_doctor",
    "source_inspect",
    "evidence_start",
    "job_get",
    "artifact_list",
    "artifact_read",
    "transcript_save",
    "content_save",
    "content_validate",
    "watch_later_scan",
    "job_list",
    "job_update",
    "wechat_prepare",
    "wechat_bind",
)


def system_setup(
    capabilities: list[str] | None = None, config_path: str | None = None
) -> dict[str, Any]:
    return api.system_setup(capabilities, config_path=config_path)


def system_configure(
    values: dict[str, str | None],
    clear: list[str] | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    return api.system_configure(values, clear=clear, config_path=config_path)


def system_doctor(
    capabilities: list[str] | None = None,
    deep: bool = True,
    config_path: str | None = None,
) -> dict[str, Any]:
    return api.system_doctor(capabilities, deep=deep, config_path=config_path)


def source_inspect(
    url: str, page: int | None = None, config_path: str | None = None
) -> dict[str, Any]:
    return api.source_inspect(url, page, config_path=config_path)


def evidence_start(
    url: str,
    home: str | None = None,
    page: int | None = None,
    run_id: str | None = None,
    profile_id: str | None = None,
    language: str = "ai-zh",
    ocr_backend: str = "auto",
    asr_backend: str = "none",
    video_path: str | None = None,
    download_if_needed: bool = True,
    collect_all_sources: bool = False,
    media_execution: str = "auto",
    hard_subtitle_visual_decision: str = "not_assessed",
    visual_assessment: dict[str, Any] | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    return api.evidence_start(
        url,
        home=home,
        page=page,
        run_id=run_id,
        profile_id=profile_id,
        language=language,
        ocr_backend=ocr_backend,
        asr_backend=asr_backend,
        video_path=video_path,
        download_if_needed=download_if_needed,
        collect_all_sources=collect_all_sources,
        media_execution=media_execution,
        hard_subtitle_visual_decision=hard_subtitle_visual_decision,
        visual_assessment=visual_assessment,
        config_path=config_path,
    )


def job_get(job_id: str, home: str | None = None) -> dict[str, Any]:
    return api.job_get(job_id, home=home)


def artifact_list(
    job_id: str, home: str | None = None, kind: str | None = None
) -> dict[str, Any]:
    return api.artifact_list(job_id, home=home, kind=kind)


def artifact_read(
    job_id: str, artifact_id: str, home: str | None = None, text: bool = True
) -> dict[str, Any]:
    return api.artifact_read(job_id, artifact_id, home=home, text=text)


def transcript_save(
    job_id: str,
    evidence_ids: list[str],
    cues: list[dict[str, Any]],
    text: str,
    home: str | None = None,
    corrections: list[dict[str, Any]] | None = None,
    uncertainties: list[dict[str, Any]] | None = None,
    quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return api.transcript_save(
        job_id,
        evidence_ids,
        cues,
        text,
        home=home,
        corrections=corrections,
        uncertainties=uncertainties,
        quality=quality,
    )


def content_save(
    job_id: str,
    transcript_id: str,
    carrier: str,
    document: dict[str, Any],
    home: str | None = None,
    media: list[dict[str, Any]] | None = None,
    audit: dict[str, Any] | None = None,
    render: bool = True,
) -> dict[str, Any]:
    return api.content_save(
        job_id,
        transcript_id,
        carrier,
        document,
        home=home,
        media=media,
        audit=audit,
        render=render,
    )


def content_validate(
    job_id: str, content_id: str, home: str | None = None
) -> dict[str, Any]:
    return api.content_validate(job_id, content_id, home=home)


def watch_later_scan(
    profile_id: str,
    home: str | None = None,
    account_profile_alias: str | None = None,
    carrier: str = "wechat_article",
    limit: int | None = None,
    baseline_if_empty: bool = False,
    config_path: str | None = None,
) -> dict[str, Any]:
    return api.watch_later_scan(
        profile_id,
        home=home,
        account_profile_alias=account_profile_alias,
        carrier=carrier,
        limit=limit,
        baseline_if_empty=baseline_if_empty,
        config_path=config_path,
    )


def job_list(
    home: str | None = None,
    run_id: str | None = None,
    status: str | None = None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    return api.job_list(home=home, run_id=run_id, status=status, profile_id=profile_id)


def job_update(
    job_id: str,
    home: str | None = None,
    stage: str | None = None,
    status: str | None = None,
    error: dict[str, Any] | None = None,
    retry_at: str | None = None,
    increment_attempts: bool = False,
) -> dict[str, Any]:
    return api.job_update(
        job_id,
        home=home,
        stage=stage,
        status=status,
        error=error,
        retry_at=retry_at,
        increment_attempts=increment_attempts,
    )


def wechat_prepare(
    job_id: str,
    content_id: str,
    authorized: bool,
    save_draft: bool,
    home: str | None = None,
    copy_to_clipboard: bool = False,
) -> dict[str, Any]:
    return api.wechat_prepare(
        job_id,
        content_id,
        home=home,
        authorized=authorized,
        save_draft=save_draft,
        copy_to_clipboard=copy_to_clipboard,
    )


def wechat_bind(
    job_id: str, content_id: str, observation: dict[str, Any], home: str | None = None
) -> dict[str, Any]:
    return api.wechat_bind(job_id, content_id, observation, home=home)


if McpServer is not None:
    mcp = McpServer(
        "video_content",
        version="1.0.0",
        instructions=(
            "Use source and evidence tools first. Preserve platform, OCR, ASR, and Agent-reviewed evidence independently. "
            "Save a Transcript before Content. Watch Later scans are one-shot and idempotent; the caller owns recurrence. "
            "WeChat tools require explicit draft authorization, validate refresh readback, and never publish."
        ),
    )
    for _name in TOOL_NAMES:
        mcp.tool(name=_name)(globals()[_name])
else:  # pragma: no cover
    mcp = None


def main() -> None:
    if mcp is None:
        raise SystemExit(
            'MCP dependency is missing. Install with: pip install -e ".[mcp]"'
        )
    mcp.run(transport="stdio")
