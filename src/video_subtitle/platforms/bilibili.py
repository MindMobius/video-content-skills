from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import PlatformError


class OpenCliError(PlatformError):
    """Bilibili adapter failure produced by OpenCLI."""


@dataclass(frozen=True)
class OpenCliSettings:
    command: tuple[str, ...]
    profile: str | None = None
    ytdlp_path: str | None = None
    ffmpeg_path: str | None = None

    @classmethod
    def discover(
        cls,
        *,
        opencli: str | None = None,
        profile: str | None = None,
        ytdlp: str | None = None,
        ffmpeg: str | None = None,
        allow_missing: bool = False,
    ) -> OpenCliSettings:
        opencli_value = (
            opencli
            or os.getenv("VIDEO_SUBTITLE_OPENCLI_COMMAND")
            or os.getenv("VIDEO_SUBTITLE_OPENCLI")
            or os.getenv("SUBTITLE_AGENT_OPENCLI_COMMAND")
            or os.getenv("SUBTITLE_AGENT_OPENCLI")
            or ""
        ).strip()
        command = _resolve_opencli_command(
            opencli_value,
            allow_missing=allow_missing,
        )
        selected_profile = (
            profile
            or os.getenv("VIDEO_SUBTITLE_OPENCLI_PROFILE")
            or os.getenv("SUBTITLE_AGENT_OPENCLI_PROFILE")
            or None
        )
        selected_ytdlp = (
            ytdlp
            or os.getenv("VIDEO_SUBTITLE_YTDLP")
            or os.getenv("SUBTITLE_AGENT_YTDLP")
            or None
        )
        selected_ffmpeg = (
            ffmpeg
            or os.getenv("VIDEO_SUBTITLE_FFMPEG")
            or os.getenv("SUBTITLE_AGENT_FFMPEG")
            or None
        )
        return cls(
            command=tuple(command),
            profile=selected_profile,
            ytdlp_path=selected_ytdlp,
            ffmpeg_path=selected_ffmpeg,
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> OpenCliSettings:
        raw_command = value.get("command")
        if not isinstance(raw_command, list) or not all(
            isinstance(item, str) and item for item in raw_command
        ):
            raise ValueError("OpenCLI command must be a non-empty string array")
        return cls(
            command=tuple(raw_command),
            profile=value.get("profile") or None,
            ytdlp_path=value.get("ytdlp_path") or None,
            ffmpeg_path=value.get("ffmpeg_path") or None,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "command": list(self.command),
            "profile": self.profile,
            "ytdlp_path": self.ytdlp_path,
            "ffmpeg_path": self.ffmpeg_path,
        }

    @property
    def display_command(self) -> str:
        return subprocess.list2cmdline(list(self.command))


def _resolve_opencli_command(
    value: str,
    *,
    allow_missing: bool = False,
) -> list[str]:
    if value:
        if value.startswith("["):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as error:
                raise ValueError(
                    "VIDEO_SUBTITLE_OPENCLI_COMMAND must be a JSON string array"
                ) from error
            if (
                not isinstance(parsed, list)
                or not parsed
                or not all(isinstance(item, str) and item for item in parsed)
            ):
                raise ValueError(
                    "OpenCLI command JSON must be a non-empty string array"
                )
            return parsed

        candidate = Path(value).expanduser()
        if candidate.exists():
            resolved = str(candidate.resolve())
            if candidate.suffix.lower() in {".js", ".mjs", ".cjs"}:
                node = shutil.which("node")
                if not node:
                    raise ValueError(
                        "Node.js is required to run the configured OpenCLI script"
                    )
                return [node, resolved]
            return [resolved]

        executable = shutil.which(value)
        if executable:
            return [executable]
        if allow_missing:
            if candidate.suffix.lower() in {".js", ".mjs", ".cjs"}:
                return [shutil.which("node") or "node", str(candidate)]
            return [value]
        raise ValueError(f"Configured OpenCLI executable does not exist: {value}")

    executable = shutil.which("opencli")
    if executable:
        return [executable]
    return ["opencli"]


class OpenCliClient:
    platform = "bilibili"

    def __init__(
        self, settings: OpenCliSettings, *, timeout_seconds: int = 120
    ) -> None:
        self.settings = settings
        self.timeout_seconds = timeout_seconds

    def is_command_available(self) -> bool:
        first = self.settings.command[0]
        if not (Path(first).exists() or shutil.which(first)):
            return False
        if len(self.settings.command) > 1:
            script = Path(self.settings.command[1])
            if script.suffix.lower() in {".js", ".mjs", ".cjs"}:
                return script.is_file()
        return True

    def auth_status(self) -> Any:
        return self._call(
            ["auth", "status", "--site", "bilibili", "--full"], timeout=30
        )

    def video(self, url: str, *, page: int | None = None) -> dict[str, str]:
        args = ["bilibili", "video", url]
        if page is not None:
            args += ["--page", str(page)]
        payload = self._call(args)
        if not isinstance(payload, list):
            raise OpenCliError(
                "MALFORMED_RESULT",
                "OpenCLI bilibili video did not return a row array",
            )
        result: dict[str, str] = {}
        for row in payload:
            if not isinstance(row, dict) or "field" not in row:
                continue
            result[str(row["field"])] = str(row.get("value", ""))
        if not result.get("bvid"):
            raise OpenCliError(
                "MALFORMED_RESULT",
                "OpenCLI bilibili video result did not contain a bvid",
            )
        return result

    def subtitles(
        self,
        url: str,
        *,
        lang: str = "ai-zh",
        page: int | None = None,
    ) -> list[dict[str, Any]]:
        args = ["bilibili", "subtitle", url, "--lang", lang]
        if page is not None:
            args += ["--page", str(page)]
        payload = self._call(args)
        if not isinstance(payload, list):
            raise OpenCliError(
                "MALFORMED_RESULT",
                "OpenCLI bilibili subtitle did not return a cue array",
            )
        for row in payload:
            if not isinstance(row, dict):
                raise OpenCliError(
                    "MALFORMED_RESULT",
                    "OpenCLI bilibili subtitle contained a non-object cue",
                )
        return payload

    def download(
        self,
        url: str,
        output_dir: Path,
        *,
        quality: str = "1080p",
        page: int | None = None,
    ) -> tuple[Path, Any]:
        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        before = _media_snapshot(output_dir)

        args = [
            "bilibili",
            "download",
            url,
            "--output",
            str(output_dir),
            "--quality",
            quality,
        ]
        if page is not None:
            args += ["--page", str(page)]
        payload = self._call(args, timeout=None)

        if isinstance(payload, list) and payload:
            status = str(payload[0].get("status", "")).lower()
            if status in {"failed", "error"}:
                raise OpenCliError(
                    "DOWNLOAD_FAILED",
                    str(payload[0].get("size") or "OpenCLI reported a failed download"),
                )

        after = _media_snapshot(output_dir)
        changed = [
            path
            for path, signature in after.items()
            if path not in before or before[path] != signature
        ]
        candidates = changed or list(after)
        if not candidates:
            raise OpenCliError(
                "DOWNLOAD_ARTIFACT_NOT_FOUND",
                "OpenCLI completed but no downloaded video file was found",
                help_text=f"Inspect the output directory: {output_dir}",
            )
        candidates.sort(key=lambda item: after[item][0], reverse=True)
        return candidates[0], payload

    def _call(
        self,
        args: Sequence[str],
        *,
        timeout: int | None | object = ...,
    ) -> Any:
        command = list(self.settings.command)
        if self.settings.profile:
            command += ["--profile", self.settings.profile]
        command += list(args)
        command += ["-f", "json"]

        environment = os.environ.copy()
        tool_directories: list[str] = []
        for tool_path in (
            self.settings.ytdlp_path,
            self.settings.ffmpeg_path,
        ):
            if tool_path:
                tool_directories.append(
                    str(Path(tool_path).expanduser().resolve().parent)
                )
        if tool_directories:
            environment["PATH"] = (
                os.pathsep.join(dict.fromkeys(tool_directories))
                + os.pathsep
                + environment.get("PATH", "")
            )

        actual_timeout: int | None
        if timeout is ...:
            actual_timeout = self.timeout_seconds
        else:
            actual_timeout = timeout  # type: ignore[assignment]

        try:
            process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=actual_timeout,
                check=False,
            )
        except FileNotFoundError as error:
            raise OpenCliError(
                "OPENCLI_NOT_FOUND",
                f"OpenCLI executable was not found: {self.settings.display_command}",
                help_text="Set VIDEO_SUBTITLE_OPENCLI to opencli or the built OpenCLI main.js path.",
            ) from error
        except subprocess.TimeoutExpired as error:
            raise OpenCliError(
                "OPENCLI_TIMEOUT",
                f"OpenCLI did not finish within {actual_timeout} seconds",
            ) from error

        stdout = process.stdout.strip()
        stderr = process.stderr.strip()
        combined = "\n".join(item for item in (stdout, stderr) if item)
        if process.returncode != 0:
            raise _parse_opencli_error(combined, process.returncode)

        try:
            payload = _decode_json_output(stdout)
        except ValueError as error:
            raise OpenCliError(
                "MALFORMED_RESULT",
                "OpenCLI succeeded but did not emit valid JSON",
                raw_output=combined,
            ) from error
        payload = _repair_payload_text(payload)

        if isinstance(payload, dict) and payload.get("ok") is False:
            error_value = (
                payload.get("error") if isinstance(payload.get("error"), dict) else {}
            )
            raise OpenCliError(
                str(error_value.get("code") or "OPENCLI_ERROR"),
                str(error_value.get("message") or "OpenCLI returned an error envelope"),
                help_text=str(error_value.get("help") or error_value.get("hint") or ""),
                exit_code=_optional_int(error_value.get("exitCode")),
                raw_output=combined,
            )
        return payload


def bilibili_auth_ready(payload: Any) -> bool:
    if isinstance(payload, list):
        rows = [row for row in payload if isinstance(row, dict)]
        bilibili_rows = [
            row for row in rows if str(row.get("site", "")).lower() == "bilibili"
        ]
        candidates = bilibili_rows or rows
        return any(
            row.get("logged_in") is True
            or str(row.get("status", "")).lower() == "logged_in"
            for row in candidates
        )
    if isinstance(payload, dict):
        return (
            payload.get("logged_in") is True
            or str(payload.get("status", "")).lower() == "logged_in"
        )
    return False


def executable_status(
    configured: str | None,
    fallback_command: str,
) -> dict[str, Any]:
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file():
            return {
                "available": True,
                "path": str(candidate.resolve()),
                "configured": True,
            }
        resolved = shutil.which(configured)
        return {
            "available": bool(resolved),
            "path": str(Path(resolved).resolve()) if resolved else None,
            "configured": True,
        }
    resolved = shutil.which(fallback_command)
    return {
        "available": bool(resolved),
        "path": str(Path(resolved).resolve()) if resolved else None,
        "configured": False,
    }


def _decode_json_output(value: str) -> Any:
    if not value:
        raise ValueError("empty output")
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    decoded: list[tuple[int, Any]] = []
    for index, character in enumerate(value):
        if character not in "[{":
            continue
        try:
            item, end = decoder.raw_decode(value[index:])
        except json.JSONDecodeError:
            continue
        if not value[index + end :].strip():
            decoded.append((index, item))
    if not decoded:
        raise ValueError("no JSON document found")
    return decoded[-1][1]


def _repair_payload_text(value: Any) -> Any:
    if isinstance(value, str):
        return _repair_gb18030_mojibake(value)
    if isinstance(value, list):
        return [_repair_payload_text(item) for item in value]
    if isinstance(value, dict):
        return {
            _repair_payload_text(key): _repair_payload_text(item)
            for key, item in value.items()
        }
    return value


def _repair_gb18030_mojibake(value: str) -> str:
    """Recover Chinese text decoded as Latin-1 by a Windows subprocess bridge."""
    try:
        candidate = value.encode("latin-1").decode("gb18030")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value
    if candidate == value:
        return value

    original_cjk = _count_cjk(value)
    candidate_cjk = _count_cjk(candidate)
    if candidate_cjk >= original_cjk + 2:
        return candidate
    return value


def _count_cjk(value: str) -> int:
    return sum(
        "\u3400" <= character <= "\u4dbf" or "\u4e00" <= character <= "\u9fff"
        for character in value
    )


def _parse_opencli_error(value: str, return_code: int) -> OpenCliError:
    try:
        payload = _decode_json_output(value)
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        error_value = payload.get("error")
        if isinstance(error_value, dict):
            return OpenCliError(
                str(error_value.get("code") or "OPENCLI_ERROR"),
                str(error_value.get("message") or value or "OpenCLI failed"),
                help_text=str(error_value.get("help") or error_value.get("hint") or ""),
                exit_code=_optional_int(error_value.get("exitCode")) or return_code,
                raw_output=value,
            )

    fields: dict[str, str] = {}
    for match in re.finditer(
        r"(?m)^\s*(code|message|help|hint|exitCode):\s*(.*?)\s*$",
        value,
    ):
        fields[match.group(1)] = match.group(2).strip("\"'")
    return OpenCliError(
        fields.get("code", "OPENCLI_ERROR"),
        fields.get("message") or value or f"OpenCLI exited with code {return_code}",
        help_text=fields.get("help") or fields.get("hint", ""),
        exit_code=_optional_int(fields.get("exitCode")) or return_code,
        raw_output=value,
    )


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _media_snapshot(directory: Path) -> dict[Path, tuple[int, int]]:
    extensions = {".mp4", ".mkv", ".webm", ".flv", ".mov", ".m4v"}
    result: dict[Path, tuple[int, int]] = {}
    for path in directory.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in extensions:
            continue
        stat = path.stat()
        result[path.resolve()] = (stat.st_mtime_ns, stat.st_size)
    return result
