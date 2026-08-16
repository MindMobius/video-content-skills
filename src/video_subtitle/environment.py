from __future__ import annotations

import json
import os
import shutil
import sys
from importlib.resources import files
from pathlib import Path
from typing import Any

from .config import CONFIG_ENVIRONMENT, read_configuration

DEFAULT_CAPABILITIES = ["platform_subtitle", "hard_ocr_url"]


def read_requirements() -> dict[str, Any]:
    resource = files("video_subtitle").joinpath("requirements.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "video-subtitle/requirements-v1":
        raise ValueError("Unsupported video subtitle requirements schema")
    return payload


def normalize_capabilities(values: list[str] | None) -> list[str]:
    requirements = read_requirements()
    available = set(requirements["capabilities"])
    selected = list(values or DEFAULT_CAPABILITIES)
    if "all" in selected:
        selected = list(requirements["capabilities"])
    unknown = [item for item in selected if item not in available]
    if unknown:
        raise ValueError(f"Unknown subtitle capabilities: {', '.join(unknown)}")
    return list(dict.fromkeys(selected))


def build_setup_report(
    diagnostics: dict[str, Any],
    *,
    capabilities: list[str] | None = None,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    requirements = read_requirements()
    selected = normalize_capabilities(capabilities)
    required_by: dict[str, list[str]] = {}
    for capability in selected:
        for dependency in requirements["capabilities"][capability]["requires"]:
            required_by.setdefault(dependency, []).append(capability)

    states = _dependency_states(diagnostics)
    dependencies: list[dict[str, Any]] = []
    agent_actions: list[dict[str, Any]] = []
    human_actions: list[dict[str, Any]] = []
    for dependency_id, capability_ids in required_by.items():
        definition = requirements["dependencies"][dependency_id]
        state = dict(states.get(dependency_id) or {"status": "missing"})
        item = {
            "dependency_id": dependency_id,
            "kind": definition["kind"],
            "description": definition["description"],
            "required_by": capability_ids,
            **{
                key: definition[key]
                for key in ("tested_version", "tested_revision")
                if key in definition
            },
            **state,
        }
        dependencies.append(item)
        if state["status"] == "ready" or state["status"] == "blocked":
            continue
        if state["status"] == "human_action_required":
            action = {
                "dependency_id": dependency_id,
                **definition["human_action"],
            }
            human_actions.append(action)
            continue
        action = definition.get("agent_action")
        if action:
            agent_actions.append({"dependency_id": dependency_id, **action})

    ready = all(item["status"] == "ready" for item in dependencies)
    if agent_actions or (not ready and not human_actions):
        status = "agent_action_required"
    elif human_actions:
        status = "human_action_required"
    else:
        status = "ready"
    config = read_configuration(config_path)
    return {
        "schema_version": "video-subtitle/setup-v1",
        "status": status,
        "ready": ready,
        "requested_capabilities": selected,
        "configuration": {
            "path": config["path"],
            "exists": config["exists"],
            "configured_fields": sorted(config["values"]),
            "precedence": ["CLI arguments", "environment", "config file", "PATH"],
        },
        "dependencies": dependencies,
        "agent_actions": agent_actions,
        "human_actions": human_actions,
        "next_step": _next_step(status, deep=bool(diagnostics.get("deep"))),
    }


def _dependency_states(diagnostics: dict[str, Any]) -> dict[str, dict[str, Any]]:
    opencli = diagnostics.get("opencli") or {}
    downloads = diagnostics.get("download_tools") or {}
    ocr = diagnostics.get("hard_ocr") or {}
    asr = diagnostics.get("audio_asr") or {}
    watch_later = diagnostics.get("watch_later_adapter") or {}
    watch_later_required = "watch_later_monitor" in set(
        diagnostics.get("requested_capabilities") or []
    )

    python_ready = sys.version_info >= (3, 10)
    opencli_detected = bool(opencli.get("available"))
    node_state = _node_state(opencli)
    node_ready = node_state["status"] == "ready"
    opencli_ready = opencli_detected and node_ready
    watch_later_ready = bool(watch_later.get("available")) and opencli_ready
    bridge_blockers: list[str] = []
    if not opencli_ready:
        bridge_blockers.append("opencli")
    elif watch_later_required and not watch_later_ready:
        bridge_blockers.append("watch_later_adapter")
    bridge_ready = (
        bool(opencli.get("platform_ready")) and opencli_ready and not bridge_blockers
    )
    opencli_state: dict[str, Any] = {
        "status": (
            "ready" if opencli_ready else "blocked" if not node_ready else "missing"
        ),
        "detected": opencli.get("command"),
    }
    if not node_ready:
        opencli_state["blocked_by"] = ["node"]
    states: dict[str, dict[str, Any]] = {
        "python": {
            "status": "ready" if python_ready else "missing",
            "detected": sys.version.split()[0],
        },
        "node": node_state,
        "opencli": opencli_state,
        "watch_later_adapter": {
            "status": (
                "ready"
                if watch_later_ready
                else "blocked"
                if not opencli_ready
                else "missing"
            ),
            "detected": watch_later.get("command"),
            **({"blocked_by": ["opencli"]} if not opencli_ready else {}),
        },
        "browser_bridge": {
            "status": (
                "ready"
                if bridge_ready
                else "blocked"
                if bridge_blockers
                else "human_action_required"
            ),
            "detected": opencli.get("profile"),
            **({"blocked_by": bridge_blockers} if bridge_blockers else {}),
        },
        "yt_dlp": _tool_state(downloads.get("yt_dlp")),
        "ffmpeg": _tool_state(downloads.get("ffmpeg")),
        "videocr": {
            "status": "ready" if ocr.get("available") else "missing",
            "detected": ocr.get("executable"),
        },
    }

    asr_available = bool(asr.get("available"))
    states["asr_python"] = _configured_path_state(
        "asr_python", ready=asr_available, detected=asr.get("python")
    )
    states["qwen_asr_model"] = _configured_model_state(
        "qwen_asr_model", detected=asr.get("model")
    )
    states["qwen_aligner_model"] = _configured_model_state(
        "qwen_aligner_model", detected=asr.get("aligner")
    )
    runtime = asr.get("runtime") or {}
    runtime_checked = bool(asr.get("runtime_checked", bool(runtime)))
    cuda_prerequisites = [
        "ffmpeg",
        "asr_python",
        "qwen_asr_model",
        "qwen_aligner_model",
    ]
    cuda_blockers = [
        dependency_id
        for dependency_id in cuda_prerequisites
        if states[dependency_id]["status"] != "ready"
    ]
    if (
        diagnostics.get("deep")
        and not cuda_blockers
        and not asr_available
        and not runtime_checked
    ):
        states["asr_python"]["status"] = "missing"
        states["asr_python"]["detail"] = (
            asr.get("error") or "The deep ASR runtime probe did not complete."
        )
        cuda_blockers.append("asr_python")

    if cuda_blockers:
        cuda_state: dict[str, Any] = {
            "status": "blocked",
            "detected": runtime.get("gpu"),
            "runtime_checked": runtime_checked,
            "blocked_by": cuda_blockers,
        }
    elif asr_available and (not runtime_checked or bool(runtime.get("cuda_available"))):
        cuda_state = {
            "status": "ready",
            "detected": runtime.get("gpu"),
            "runtime_checked": runtime_checked,
        }
    else:
        cuda_state = {
            "status": "human_action_required",
            "detected": runtime.get("gpu"),
            "runtime_checked": runtime_checked,
        }
    states["cuda"] = cuda_state
    return states


def _tool_state(value: Any) -> dict[str, Any]:
    item = value if isinstance(value, dict) else {}
    return {
        "status": "ready" if item.get("available") else "missing",
        "detected": item.get("path"),
    }


def _executable_state(command: str) -> dict[str, Any]:
    detected = shutil.which(command)
    return {
        "status": "ready" if detected else "missing",
        "detected": detected,
    }


def _node_state(opencli: dict[str, Any]) -> dict[str, Any]:
    command = str(opencli.get("command") or "")
    executable = command.strip().strip('"')
    if opencli.get("available") and executable.lower().endswith(".exe"):
        return {
            "status": "ready",
            "detected": "not required by standalone OpenCLI executable",
        }
    return _executable_state("node")


def _configured_path_state(
    field: str,
    *,
    ready: bool,
    detected: str | None,
) -> dict[str, Any]:
    configured = detected or os.getenv(CONFIG_ENVIRONMENT[field])
    available = bool(configured and (Path(configured).expanduser().is_file() or ready))
    return {
        "status": "ready" if available else "missing",
        "detected": configured,
    }


def _configured_model_state(
    field: str,
    *,
    detected: str | None,
) -> dict[str, Any]:
    configured = detected or os.getenv(CONFIG_ENVIRONMENT[field])
    local_directory = bool(
        configured and Path(configured).expanduser().resolve().is_dir()
    )
    return {
        "status": "ready" if local_directory else "missing",
        "detected": configured,
        **(
            {
                "detail": (
                    "Setup requires a local model directory so extraction cannot "
                    "trigger an unconfirmed model download."
                )
            }
            if configured and not local_directory
            else {}
        ),
    }


def _next_step(status: str, *, deep: bool) -> str:
    if status == "ready":
        if deep:
            return "Start the subtitle task with the verified capabilities."
        return "Run video_subtitle_doctor with deep=true, then start the task."
    if status == "human_action_required":
        return (
            "Complete agent_actions first where possible, ask the user only for the "
            "listed human_actions, persist discovered paths, then rerun setup."
        )
    return (
        "Execute the listed agent_actions, persist paths with configure, then rerun "
        "setup before asking the user for help."
    )
