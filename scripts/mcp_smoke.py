"""Offline smoke test for the Video Content MCP registration and shared service."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from video_content.mcp_server import TOOL_NAMES, mcp


async def smoke() -> dict[str, object]:
    tools = await mcp.list_tools()
    with tempfile.TemporaryDirectory(prefix="video-content-mcp-") as directory:
        result = await mcp.call_tool("job_list", {"home": str(Path(directory))})
    payload = result.model_dump()
    structured = payload.get("structured_content")
    return {
        "schema_version": "video-content/mcp-smoke-v1",
        "ok": (
            {tool.name for tool in tools} == set(TOOL_NAMES)
            and payload.get("is_error") is False
            and structured.get("count") == 0
        ),
        "tool_count": len(tools),
        "tools": [tool.name for tool in tools],
        "job_list_count": structured.get("count"),
    }


def main() -> None:
    report = asyncio.run(smoke())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
