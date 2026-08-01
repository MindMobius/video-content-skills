"""Dependency-free bootstrap for Agents before the package or MCP server exists."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import venv
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create .venv and install this project with MCP support",
    )
    parser.add_argument(
        "--capability",
        action="append",
        default=[],
        help="Capability forwarded to video-subtitle setup after bootstrap",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    root = Path(__file__).resolve().parents[1]
    venv_dir = root / ".venv"
    python = _venv_python(venv_dir)
    actions: list[dict[str, str]] = []

    if not python.is_file():
        actions.append(
            {
                "type": "create_venv",
                "command": f'"{sys.executable}" -m venv "{venv_dir}"',
            }
        )
    if not args.apply:
        installed = python.is_file() and _package_available(python)
        if not installed:
            actions.append(
                {
                    "type": "install_project",
                    "command": (
                        f'"{python}" -m pip install -e "{root}[mcp]"'
                        if python.is_file()
                        else "Rerun this bootstrap with --apply"
                    ),
                }
            )
        _emit(
            {
                "schema_version": "video-subtitle/bootstrap-v1",
                "status": "ready" if installed else "agent_action_required",
                "ready": installed,
                "repo": str(root),
                "venv_python": str(python),
                "requirements": str(root / "src" / "video_subtitle" / "requirements.json"),
                "agent_actions": actions,
                "next_step": (
                    "Run video-subtitle setup for the task capabilities."
                    if installed
                    else "Run python scripts/bootstrap.py --apply, then inspect setup actions."
                ),
            }
        )

    if not python.is_file():
        venv.EnvBuilder(with_pip=True).create(venv_dir)
    install = subprocess.run(
        [str(python), "-m", "pip", "install", "-e", f"{root}[mcp]"],
        cwd=root,
        check=False,
    )
    if install.returncode != 0:
        _emit(
            {
                "schema_version": "video-subtitle/bootstrap-v1",
                "status": "failed",
                "error": f"pip install exited with code {install.returncode}",
            },
            exit_code=1,
        )

    command = [str(python), "-m", "video_subtitle.cli", "setup"]
    for capability in args.capability:
        command += ["--capability", capability]
    completed = subprocess.run(command, cwd=root, check=False)
    raise SystemExit(completed.returncode)


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


def _emit(value: dict[str, object], *, exit_code: int = 0) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
