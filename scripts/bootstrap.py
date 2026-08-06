"""Dependency-free bootstrap for Agents before the package or MCP server exists."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import venv
from pathlib import Path
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create .venv when needed, install this project, and run setup",
    )
    parser.add_argument(
        "--force-reinstall",
        action="store_true",
        help="Reinstall the project even when the repository .venv is ready",
    )
    parser.add_argument(
        "--capability",
        action="append",
        default=[],
        help="Capability forwarded to video-subtitle setup after bootstrap",
    )
    parser.add_argument(
        "--config",
        help=(
            "Configuration path forwarded to setup; use an explicit path for "
            "isolated or reproducibility checks"
        ),
    )
    parser.add_argument(
        "--deep",
        action="store_true",
        help="Forward the deep runtime probe to setup",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    root = Path(__file__).resolve().parents[1]
    venv_dir = root / ".venv"
    python = _venv_python(venv_dir)
    installed = python.is_file() and _package_available(python)

    if args.apply:
        if not python.is_file():
            try:
                venv.EnvBuilder(with_pip=True).create(venv_dir)
            except (OSError, subprocess.SubprocessError) as error:  # pragma: no cover
                _emit(
                    _bootstrap_report(
                        root,
                        python,
                        installed=False,
                        status="failed",
                        error={"stage": "create_venv", "message": str(error)},
                    ),
                    exit_code=1,
                )
        if not installed or args.force_reinstall:
            install = _run(
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "-e",
                    f"{root}[mcp]",
                ],
                cwd=root,
            )
            if install.returncode != 0:
                _emit(
                    _bootstrap_report(
                        root,
                        python,
                        installed=False,
                        status="failed",
                        error={
                            "stage": "install_project",
                            "message": f"pip install exited with code {install.returncode}",
                            "details": _bounded_process_error(install),
                        },
                    ),
                    exit_code=1,
                )
            installed = _package_available(python)

    if not installed:
        command = [sys.executable, str(Path(__file__).resolve()), "--apply"]
        for capability in args.capability:
            command += ["--capability", capability]
        if args.config:
            command += ["--config", args.config]
        if args.deep:
            command.append("--deep")
        _emit(
            _bootstrap_report(
                root,
                python,
                installed=False,
                status="agent_action_required",
                agent_actions=[
                    {
                        "action_id": "install_core",
                        "type": "command",
                        "command": _display_command(command),
                        "description": (
                            "Create the repository .venv, install the core package "
                            "plus MCP support, and continue into capability setup."
                        ),
                    }
                ],
                next_step="Execute install_core, then follow the returned setup actions.",
            )
        )

    setup_process = _run(_setup_command(python, args), cwd=root)
    if setup_process.returncode != 0:
        _emit(
            _bootstrap_report(
                root,
                python,
                installed=True,
                status="failed",
                error={
                    "stage": "capability_setup",
                    "message": (
                        "video-subtitle setup exited with code "
                        f"{setup_process.returncode}"
                    ),
                    "details": _bounded_process_error(setup_process),
                },
            ),
            exit_code=1,
        )
    try:
        setup = json.loads(setup_process.stdout)
    except json.JSONDecodeError as error:
        _emit(
            _bootstrap_report(
                root,
                python,
                installed=True,
                status="failed",
                error={
                    "stage": "capability_setup",
                    "message": f"setup returned invalid JSON: {error}",
                    "details": _bounded_process_error(setup_process),
                },
            ),
            exit_code=1,
        )

    _emit(
        _bootstrap_report(
            root,
            python,
            installed=True,
            status=str(setup["status"]),
            setup=setup,
            agent_actions=list(setup.get("agent_actions") or []),
            human_actions=list(setup.get("human_actions") or []),
            next_step=str(setup["next_step"]),
        )
    )


def _bootstrap_report(
    root: Path,
    python: Path,
    *,
    installed: bool,
    status: str,
    setup: dict[str, Any] | None = None,
    agent_actions: list[dict[str, Any]] | None = None,
    human_actions: list[dict[str, Any]] | None = None,
    next_step: str | None = None,
    error: dict[str, str] | None = None,
) -> dict[str, Any]:
    skills_root = root / ".agents" / "skills"
    skills = [
        {
            "name": skill_path.parent.name,
            "path": str(skill_path.resolve()),
        }
        for skill_path in sorted(skills_root.glob("*/SKILL.md"))
    ]
    cli_command = [str(python), "-m", "video_subtitle.cli"]
    mcp_args = ["-m", "video_subtitle.mcp_server"]
    report: dict[str, Any] = {
        "schema_version": "video-subtitle/bootstrap-v2",
        "status": status,
        "ready": bool(installed and setup and setup.get("ready")),
        "repo": str(root),
        "installation": {
            "ready": installed,
            "venv_python": str(python),
            "requirements": str(root / "src" / "video_subtitle" / "requirements.json"),
        },
        "skills": {
            "discovery_root": str(skills_root),
            "available": skills,
        },
        "cli": {
            "transport": "process",
            "command": cli_command,
        },
        "mcp": {
            "server_name": "video_subtitle",
            "transport": "stdio",
            "command": str(python),
            "args": mcp_args,
            "registration_required": True,
            "registration_owner": "calling_agent",
            "fallback_command": cli_command,
        },
        "setup": setup,
        "agent_actions": list(agent_actions or []),
        "human_actions": list(human_actions or []),
        "next_step": next_step or "Inspect the reported failure before retrying.",
    }
    if error:
        report["error"] = error
    return report


def _setup_command(python: Path, args: argparse.Namespace) -> list[str]:
    command = [str(python), "-m", "video_subtitle.cli"]
    if args.config:
        command += ["--config", args.config]
    command.append("setup")
    for capability in args.capability:
        command += ["--capability", capability]
    if args.deep:
        command.append("--deep")
    return command


def _venv_python(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _package_available(python: Path) -> bool:
    completed = subprocess.run(
        [str(python), "-c", "import video_subtitle"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode == 0


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _bounded_process_error(process: subprocess.CompletedProcess[str]) -> str:
    details = (process.stderr or process.stdout or "").strip()
    return details[-4000:]


def _display_command(command: list[str]) -> str:
    if sys.platform == "win32":
        return subprocess.list2cmdline(command)
    return shlex.join(command)


def _emit(value: dict[str, Any], *, exit_code: int = 0) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
