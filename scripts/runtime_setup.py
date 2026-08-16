"""Plan, install, and verify pinned heavy runtime dependencies.

The default command is read-only. Large downloads and environment creation require
both ``install`` and ``--confirm-large-download``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.request
import venv
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = ROOT / "requirements" / "runtime-lock.json"
RECEIPT_NAME = ".video-subtitle-runtime.json"
INSTALLING_NAME = ".video-subtitle-installing.json"
DEPENDENCIES = (
    "ffmpeg",
    "videocr",
    "asr",
    "qwen_asr_model",
    "qwen_aligner_model",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("plan", "verify", "install"):
        child = commands.add_parser(command)
        child.add_argument("dependency", choices=DEPENDENCIES)
        child.add_argument("--path", type=Path)
        child.add_argument(
            "--variant",
            help="VideOCR platform variant; auto selects the CPU variant",
        )
        child.add_argument(
            "--profile",
            default="nvidia-cu128",
            help="ASR torch profile from runtime-lock.json",
        )
        child.add_argument(
            "--confirm-large-download",
            action="store_true",
            help="Required before VideOCR, ASR, or model installation",
        )
        child.add_argument(
            "--quick",
            action="store_true",
            help="Verify model receipt metadata without rehashing every file",
        )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    lock_path = args.lock.expanduser().resolve()
    lock = _read_lock(lock_path)
    try:
        if args.command == "plan":
            report = _plan(lock, args.dependency, args.path, args.variant, args.profile)
        elif args.command == "verify":
            report = _verify(
                lock,
                args.dependency,
                args.path,
                args.variant,
                args.profile,
                quick=args.quick,
            )
        else:
            report = _install(lock, args)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        report = {
            "schema_version": "video-subtitle/runtime-action-v1",
            "action": args.command,
            "dependency": args.dependency,
            "ok": False,
            "error": str(error),
        }
    report["lock"] = {
        "path": str(lock_path),
        "sha256": _sha256(lock_path),
        "verified_at": lock["verified_at"],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report.get("ok") else 1)


def _read_lock(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != "video-subtitle/runtime-lock-v1":
        raise ValueError("Unsupported runtime lock schema")
    return document


def _plan(
    lock: dict[str, Any],
    dependency: str,
    path: Path | None,
    variant: str | None,
    profile: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": "video-subtitle/runtime-action-v1",
        "action": "plan",
        "dependency": dependency,
        "ok": True,
        "confirmation_required": dependency != "ffmpeg",
    }
    if dependency == "ffmpeg":
        selected = path.expanduser().resolve() if path else _which_path("ffmpeg")
        result["detected"] = _ffmpeg_state(selected, lock["ffmpeg"])
        result["agent_action"] = {
            "type": "package_manager_install",
            "command": lock["ffmpeg"]["install_hints"].get(_platform_name()),
            "requires_os_privilege_maybe": True,
        }
        return result
    if dependency == "videocr":
        selected_variant, asset = _videocr_asset(lock, variant)
        result.update(
            {
                "variant": selected_variant,
                "download": asset,
                "download_mib": round(asset["bytes"] / (1024 * 1024), 1),
                "next_command": [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "install",
                    "videocr",
                    "--variant",
                    selected_variant,
                    "--path",
                    "<download-directory>",
                    "--confirm-large-download",
                ],
                "post_install": (
                    "Extract the verified archive with 7-Zip, locate videocr-cli, "
                    "persist its path, and run video-subtitle doctor."
                ),
            }
        )
        return result
    if dependency == "asr":
        selected_profile = _asr_profile(lock, profile)
        result.update(
            {
                "profile": profile,
                "python": lock["asr"]["python"],
                "packages": {
                    "torch": selected_profile["torch"],
                    "qwen-asr": lock["asr"]["qwen_asr"],
                    "transformers": lock["asr"]["transformers"],
                },
                "torch_index_url": selected_profile["index_url"],
                "warning": (
                    "Inspect the current GPU driver before choosing a CUDA profile. "
                    "CPU is valid for setup checks but is not a throughput promise."
                ),
            }
        )
        return result
    model = lock["models"][dependency]
    result.update(
        {
            "repo_id": model["repo_id"],
            "revision": model["revision"],
            "download_tool": "hf",
            "target": str(path.expanduser().resolve()) if path else None,
        }
    )
    return result


def _verify(
    lock: dict[str, Any],
    dependency: str,
    path: Path | None,
    variant: str | None,
    profile: str,
    *,
    quick: bool,
) -> dict[str, Any]:
    if dependency == "ffmpeg":
        selected = path.expanduser().resolve() if path else _which_path("ffmpeg")
        state = _ffmpeg_state(selected, lock["ffmpeg"])
        return _result("verify", dependency, bool(state.get("valid")), state=state)
    if path is None:
        raise ValueError(f"--path is required to verify {dependency}")
    selected = path.expanduser().resolve()
    if dependency == "videocr":
        selected_variant, asset = _videocr_asset(lock, variant)
        if selected.is_dir():
            selected = selected / asset["asset"]
        actual_sha256 = _sha256(selected)
        actual_bytes = selected.stat().st_size
        valid = actual_sha256 == asset["sha256"] and actual_bytes == asset["bytes"]
        return _result(
            "verify",
            dependency,
            valid,
            variant=selected_variant,
            path=str(selected),
            expected_sha256=asset["sha256"],
            actual_sha256=actual_sha256,
            expected_bytes=asset["bytes"],
            actual_bytes=actual_bytes,
        )
    if dependency == "asr":
        selected_python = _python_in_environment(selected)
        state = _asr_state(selected_python, lock, profile)
        return _result("verify", dependency, bool(state.get("valid")), state=state)
    state = _verify_model(selected, lock["models"][dependency], quick=quick)
    return _result("verify", dependency, bool(state.get("valid")), state=state)


def _install(lock: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    if args.dependency == "ffmpeg":
        raise ValueError(
            "FFmpeg installation remains package-manager owned; run plan, execute the "
            "reported host command, then run verify."
        )
    if not args.confirm_large_download:
        raise ValueError(
            "Large runtime installation requires --confirm-large-download after the "
            "Agent has shown the plan to the user."
        )
    if args.path is None:
        raise ValueError("--path is required for runtime installation")
    target = args.path.expanduser().resolve()
    if args.dependency == "videocr":
        return _download_videocr(lock, target, args.variant)
    if args.dependency == "asr":
        return _install_asr(lock, target, args.profile)
    return _download_model(lock, args.dependency, target)


def _download_videocr(
    lock: dict[str, Any], target: Path, variant: str | None
) -> dict[str, Any]:
    selected_variant, asset = _videocr_asset(lock, variant)
    target.mkdir(parents=True, exist_ok=True)
    archive = target / asset["asset"]
    if archive.exists():
        existing = _verify(lock, "videocr", archive, selected_variant, "", quick=False)
        if existing["ok"]:
            existing["action"] = "install"
            existing["reused"] = True
            return existing
        raise ValueError(f"Existing archive does not match the runtime lock: {archive}")
    partial = archive.with_suffix(archive.suffix + ".part")
    request = urllib.request.Request(
        asset["url"], headers={"User-Agent": "video-subtitle-skill/0.7.0"}
    )
    digest = hashlib.sha256()
    downloaded = 0
    try:
        with (
            urllib.request.urlopen(request, timeout=60) as response,
            partial.open("wb") as output,
        ):
            while block := response.read(1024 * 1024):
                output.write(block)
                digest.update(block)
                downloaded += len(block)
        if downloaded != asset["bytes"] or digest.hexdigest() != asset["sha256"]:
            raise ValueError("Downloaded VideOCR archive failed size or SHA-256 check")
        os.replace(partial, archive)
    finally:
        if partial.exists():
            partial.unlink()
    receipt = {
        "schema_version": "video-subtitle/runtime-install-receipt-v1",
        "dependency": "videocr",
        "version": lock["videocr"]["version"],
        "variant": selected_variant,
        "asset": archive.name,
        "bytes": downloaded,
        "sha256": digest.hexdigest(),
    }
    _write_json(target / f"{archive.name}.receipt.json", receipt)
    return _result(
        "install",
        "videocr",
        True,
        reused=False,
        archive=str(archive),
        receipt=str(target / f"{archive.name}.receipt.json"),
        next_action="Extract the archive, persist videocr-cli, then run doctor.",
    )


def _install_asr(
    lock: dict[str, Any], target: Path, profile_name: str
) -> dict[str, Any]:
    selected_profile = _asr_profile(lock, profile_name)
    receipt_path = target / RECEIPT_NAME
    if receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        state = _asr_state(_python_in_environment(target), lock, profile_name)
        if receipt.get("profile") == profile_name and state.get("valid"):
            (target / INSTALLING_NAME).unlink(missing_ok=True)
            return _result(
                "install",
                "asr",
                True,
                reused=True,
                python=str(_python_in_environment(target)),
                receipt=str(receipt_path),
                state=state,
            )
        raise ValueError("Existing ASR environment does not match the runtime lock")
    environment_python = _python_in_environment(target)
    if (
        not environment_python.is_file()
        and _current_python_series() != lock["asr"]["python"]
    ):
        raise ValueError(
            "Creating the pinned ASR environment requires Python "
            f"{lock['asr']['python']}; current interpreter is "
            f"{_current_python_series()}"
        )
    mode = _prepare_resumable_target(
        target,
        {
            "schema_version": "video-subtitle/runtime-installing-v1",
            "dependency": "asr",
            "profile": profile_name,
            "python": lock["asr"]["python"],
            "packages": {
                "torch": selected_profile["torch"],
                "qwen-asr": lock["asr"]["qwen_asr"],
                "transformers": lock["asr"]["transformers"],
            },
        },
    )
    if not environment_python.is_file():
        venv.EnvBuilder(with_pip=True).create(target)
    python = _python_in_environment(target)
    commands = [
        [
            str(python),
            "-m",
            "pip",
            "install",
            f"torch=={selected_profile['torch']}",
            "--index-url",
            selected_profile["index_url"],
        ],
        [
            str(python),
            "-m",
            "pip",
            "install",
            f"qwen-asr=={lock['asr']['qwen_asr']}",
            f"transformers=={lock['asr']['transformers']}",
        ],
    ]
    for command in commands:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode:
            raise ValueError(
                f"ASR install failed with code {completed.returncode}: "
                f"{(completed.stderr or completed.stdout)[-2000:]}"
            )
    state = _asr_state(python, lock, profile_name)
    if not state.get("valid"):
        raise ValueError("Installed ASR environment failed the pinned version check")
    receipt = {
        "schema_version": "video-subtitle/runtime-install-receipt-v1",
        "dependency": "asr",
        "profile": profile_name,
        "state": state,
    }
    _write_json(receipt_path, receipt)
    (target / INSTALLING_NAME).unlink(missing_ok=True)
    return _result(
        "install",
        "asr",
        True,
        reused=mode == "resume",
        python=str(python),
        receipt=str(target / RECEIPT_NAME),
        state=state,
    )


def _download_model(
    lock: dict[str, Any], dependency: str, target: Path
) -> dict[str, Any]:
    model = lock["models"][dependency]
    receipt_path = target / RECEIPT_NAME
    if receipt_path.is_file():
        state = _verify_model(target, model, quick=False)
        if state.get("valid"):
            (target / INSTALLING_NAME).unlink(missing_ok=True)
            return _result(
                "install",
                dependency,
                True,
                reused=True,
                target=str(target),
                file_count=state["file_count"],
                receipt=str(receipt_path),
            )
        raise ValueError("Existing model directory does not match its pinned receipt")
    hf = shutil.which("hf")
    if not hf:
        raise ValueError("The pinned model downloader requires the `hf` CLI on PATH")
    mode = _prepare_resumable_target(
        target,
        {
            "schema_version": "video-subtitle/runtime-installing-v1",
            "dependency": dependency,
            "repo_id": model["repo_id"],
            "revision": model["revision"],
        },
    )
    command = [
        hf,
        "download",
        model["repo_id"],
        "--revision",
        model["revision"],
        "--local-dir",
        str(target),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode:
        raise ValueError(
            f"Model download failed with code {completed.returncode}: "
            f"{(completed.stderr or completed.stdout)[-2000:]}"
        )
    files = _hash_tree(target)
    receipt = {
        "schema_version": "video-subtitle/runtime-install-receipt-v1",
        "dependency": dependency,
        "repo_id": model["repo_id"],
        "revision": model["revision"],
        "files": files,
    }
    _write_json(receipt_path, receipt)
    (target / INSTALLING_NAME).unlink(missing_ok=True)
    return _result(
        "install",
        dependency,
        True,
        reused=mode == "resume",
        target=str(target),
        file_count=len(files),
        receipt=str(receipt_path),
    )


def _ffmpeg_state(path: Path | None, lock: dict[str, Any]) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"available": False, "valid": False, "path": str(path) if path else None}
    completed = subprocess.run(
        [str(path), lock["verification_argument"]],
        capture_output=True,
        text=True,
        check=False,
    )
    first_line = (completed.stdout or completed.stderr).splitlines()[0:1]
    version_line = first_line[0] if first_line else ""
    match = re.search(r"ffmpeg version\s+([0-9]+(?:\.[0-9]+)?)", version_line)
    major = int(match.group(1).split(".")[0]) if match else None
    valid = (
        completed.returncode == 0
        and major is not None
        and major >= lock["minimum_major"]
    )
    return {
        "available": completed.returncode == 0,
        "valid": valid,
        "path": str(path),
        "version_line": version_line,
        "minimum_major": lock["minimum_major"],
    }


def _asr_state(path: Path, lock: dict[str, Any], profile_name: str) -> dict[str, Any]:
    profile_lock = _asr_profile(lock, profile_name)
    script = (
        "import importlib.metadata as m,json,sys,torch;"
        "print(json.dumps({'torch':m.version('torch'),'qwen_asr':m.version('qwen-asr'),"
        "'transformers':m.version('transformers'),'cuda_available':torch.cuda.is_available(),"
        "'cuda_runtime':torch.version.cuda,"
        "'python_version':'.'.join(map(str,sys.version_info[:2]))}))"
    )
    completed = subprocess.run(
        [str(path), "-c", script], capture_output=True, text=True, check=False
    )
    if completed.returncode:
        return {
            "available": False,
            "valid": False,
            "python": str(path),
            "error": (completed.stderr or completed.stdout)[-2000:],
        }
    versions = json.loads(completed.stdout)
    valid = (
        versions["python_version"] == lock["asr"]["python"]
        and versions["qwen_asr"] == lock["asr"]["qwen_asr"]
        and versions["transformers"] == lock["asr"]["transformers"]
        and versions["torch"].split("+")[0] == profile_lock["torch"]
    )
    return {"available": True, "valid": valid, "python": str(path), **versions}


def _verify_model(
    target: Path, expected: dict[str, Any], *, quick: bool
) -> dict[str, Any]:
    receipt_path = target / RECEIPT_NAME
    if not receipt_path.is_file():
        return {
            "available": target.is_dir(),
            "valid": False,
            "error": "receipt missing",
        }
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    valid = (
        receipt.get("repo_id") == expected["repo_id"]
        and receipt.get("revision") == expected["revision"]
    )
    mismatches: list[str] = []
    if valid and not quick:
        expected_files = {
            item["path"]: item
            for item in receipt.get("files", [])
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        }
        actual_files = {item["path"]: item for item in _hash_tree(target)}
        if not expected_files:
            mismatches.append("receipt:no-files")
        for path, item in expected_files.items():
            candidate = target / path
            actual = actual_files.get(path, {})
            if (
                not candidate.is_file()
                or actual.get("sha256") != item.get("sha256")
                or actual.get("bytes") != item.get("bytes")
            ):
                mismatches.append(path)
        for path in sorted(actual_files.keys() - expected_files.keys()):
            mismatches.append(f"unexpected:{path}")
        valid = not mismatches
    return {
        "available": target.is_dir(),
        "valid": valid,
        "target": str(target),
        "repo_id": receipt.get("repo_id"),
        "revision": receipt.get("revision"),
        "file_count": len(receipt.get("files", [])),
        "hashes_checked": not quick,
        "mismatches": mismatches,
    }


def _videocr_asset(
    lock: dict[str, Any], requested: str | None
) -> tuple[str, dict[str, Any]]:
    variant = requested or f"{_platform_name()}-{_architecture()}-cpu"
    variants = lock["videocr"]["variants"]
    if variant not in variants:
        raise ValueError(
            f"Unsupported VideOCR variant {variant!r}; choose one of {sorted(variants)}"
        )
    return variant, variants[variant]


def _asr_profile(lock: dict[str, Any], name: str) -> dict[str, Any]:
    profiles = lock["asr"]["profiles"]
    if name not in profiles:
        raise ValueError(
            f"Unknown ASR profile {name!r}; choose one of {sorted(profiles)}"
        )
    return profiles[name]


def _platform_name() -> str:
    return {"windows": "windows", "linux": "linux", "darwin": "macos"}.get(
        platform.system().lower(), platform.system().lower()
    )


def _architecture() -> str:
    value = platform.machine().lower()
    return "x86_64" if value in {"amd64", "x86_64"} else value


def _which_path(name: str) -> Path | None:
    value = shutil.which(name)
    return Path(value).resolve() if value else None


def _python_in_environment(root: Path) -> Path:
    if root.is_file():
        return root
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _current_python_series() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def _hash_tree(root: Path) -> list[dict[str, Any]]:
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name in {RECEIPT_NAME, INSTALLING_NAME} or ".cache" in path.parts:
            continue
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return files


def _prepare_resumable_target(target: Path, marker: dict[str, Any]) -> str:
    if target.exists() and not target.is_dir():
        raise ValueError(f"Runtime target is not a directory: {target}")
    target.mkdir(parents=True, exist_ok=True)
    marker_path = target / INSTALLING_NAME
    existing_items = list(target.iterdir())
    if existing_items:
        if not marker_path.is_file():
            raise ValueError(
                "Runtime target is non-empty and has no resumable installation marker"
            )
        existing = json.loads(marker_path.read_text(encoding="utf-8"))
        if existing != marker:
            raise ValueError(
                "Runtime target belongs to a different interrupted installation"
            )
        return "resume"
    _write_json(marker_path, marker)
    return "new"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _result(action: str, dependency: str, ok: bool, **values: Any) -> dict[str, Any]:
    return {
        "schema_version": "video-subtitle/runtime-action-v1",
        "action": action,
        "dependency": dependency,
        "ok": ok,
        **values,
    }


if __name__ == "__main__":
    main()
