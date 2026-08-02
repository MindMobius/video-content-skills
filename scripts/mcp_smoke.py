"""Protocol-level stdio smoke test for the installed MCP server."""

from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters, stdio_client


async def smoke() -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "video_subtitle.mcp_server"],
        env=os.environ.copy(),
    )
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        initialized = await session.initialize()
        tools_result = await session.list_tools()
        tool_documents = [tool.model_dump(by_alias=True) for tool in tools_result.tools]
        start_tool = next(
            tool
            for tool in tools_result.tools
            if tool.name == "start_subtitle_extraction"
        )
        start_schema = start_tool.model_dump(by_alias=True)["inputSchema"]
        submit_tool = next(
            tool
            for tool in tools_result.tools
            if tool.name == "submit_subtitle_review_window"
        )
        submit_schema = submit_tool.model_dump(by_alias=True)["inputSchema"]
        tool_names = [tool.name for tool in tools_result.tools]
        doctor_result = await session.call_tool(
            "video_subtitle_doctor", {"deep": False}
        )
        artifact_job_id = os.getenv("VIDEO_SUBTITLE_SMOKE_JOB_ID")
        artifact_result = None
        if artifact_job_id:
            artifact_result = await session.call_tool(
                "read_subtitle_artifact",
                {
                    "job_id": artifact_job_id,
                    "artifact_kind": "transcript_markdown",
                    "max_chars": 200,
                },
            )
        print(
            json.dumps(
                {
                    "server": initialized.server_info.name,
                    "protocol_version": initialized.protocol_version,
                    "tools": tool_names,
                    "all_tool_descriptions_present": all(
                        bool(document.get("description")) for document in tool_documents
                    ),
                    "server_prefers_atomic_evidence": (
                        "list_subtitle_evidence" in (initialized.instructions or "")
                        and "optional hint" in (initialized.instructions or "")
                    ),
                    "review_tools_exposed": all(
                        name in tool_names
                        for name in (
                            "prepare_subtitle_review",
                            "get_subtitle_review_window",
                            "submit_subtitle_review_window",
                        )
                    ),
                    "setup_tools_exposed": all(
                        name in tool_names
                        for name in (
                            "video_subtitle_setup",
                            "configure_video_subtitle",
                            "video_subtitle_doctor",
                        )
                    ),
                    "atomic_evidence_tools_exposed": all(
                        name in tool_names
                        for name in (
                            "list_subtitle_evidence",
                            "read_subtitle_evidence",
                        )
                    ),
                    "content_engineering_tools_exposed": all(
                        name in tool_names
                        for name in (
                            "initialize_video_content",
                            "get_video_content_project",
                            "save_video_content_document",
                            "save_video_content_deliverable",
                            "read_video_content_artifact",
                            "validate_video_content_project",
                        )
                    ),
                    "typed_review_decisions": (
                        "ReviewDecisionInput" in submit_schema.get("$defs", {})
                        and submit_schema["$defs"]["ReviewDecisionInput"]["properties"][
                            "action"
                        ].get("enum")
                        == ["keep", "replace", "delete", "insert"]
                    ),
                    "consensus_parameter_exposed": (
                        "ocr_consensus_image_max_width"
                        in start_schema.get("properties", {})
                    ),
                    "all_sources_parameter_exposed": (
                        "collect_all_sources" in start_schema.get("properties", {})
                    ),
                    "asr_parameter_exposed": (
                        "asr_backend" in start_schema.get("properties", {})
                    ),
                    "media_execution_parameter_exposed": (
                        "media_execution" in start_schema.get("properties", {})
                    ),
                    "doctor_is_error": doctor_result.is_error,
                    "artifact_is_error": (
                        artifact_result.is_error if artifact_result else None
                    ),
                    "artifact_preserved_unicode": (
                        "♪" in str(artifact_result.model_dump())
                        if artifact_result
                        else None
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    asyncio.run(smoke())
