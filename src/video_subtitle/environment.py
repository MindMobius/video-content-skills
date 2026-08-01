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
    if human_actions:
        status = "human_action_required"
    elif agent_actions or not ready:
        status = "agent_action_required"
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

    python_ready = sys.version_info >= (3, 10)
    opencli_ready = bool(opencli.get("available"))
    bridge_ready = bool(opencli.get("platform_ready"))
    states: dict[str, dict[str, Any]] = {
        "python": {
            "status": "ready" if python_ready else "missing",
            "detected": sys.version.split()[0],
        },
        "node": _node_state(opencli),
        "opencli": {
            "status": "ready" if opencli_ready else "missing",
            "detected": opencli.get("command"),
        },
        "browser_bridge": {
            "status": (
                "ready"
                if bridge_ready
                else "human_action_required"
                if opencli_ready
                else "blocked"
            ),
            "detected": opencli.get("profile"),
            **({"blocked_by": ["opencli"]} if not opencli_ready else {}),
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
    if asr_available and (not runtime_checked or runtime.get("cuda_available")):
        cuda_status = "ready"
    else:
        cuda_status = "human_action_required"
    states["cuda"] = {
        "status": cuda_status,
        "detected": runtime.get("gpu"),
        "runtime_checked": runtime_checked,
    }
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
    if opencli.get("available") and ".js" not in command.lower():
        return {
            "status": "ready",
            "detected": "not required by configured OpenCLI executable",
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
