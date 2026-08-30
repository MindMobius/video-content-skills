from __future__ import annotations

import asyncio
from pathlib import Path

from video_content.mcp_server import TOOL_NAMES, mcp

EXPECTED_TOOLS = {
    "system_setup",
    "system_configure",
    "system_doctor",
    "source_inspect",
    "evidence_start",
    "job_get",
    "artifact_list",
    "artifact_read",
    "source_frame_extract",
    "transcript_save",
    "content_save",
    "content_validate",
    "watch_later_scan",
    "job_list",
    "job_update",
    "wechat_prepare",
    "wechat_bind",
}


def test_mcp_registers_exact_minimal_tool_surface() -> None:
    assert set(TOOL_NAMES) == EXPECTED_TOOLS
    tools = asyncio.run(mcp.list_tools())
    assert {tool.name for tool in tools} == EXPECTED_TOOLS


def test_mcp_job_list_calls_shared_service(tmp_path: Path) -> None:
    result = asyncio.run(mcp.call_tool("job_list", {"home": str(tmp_path)}))
    payload = result.model_dump()
    assert payload["is_error"] is False
    structured = payload.get("structured_content")
    assert structured["count"] == 0
    assert structured["schema_version"] == "video-content/job-list-v1"
