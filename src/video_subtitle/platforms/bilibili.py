from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
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
    browser_command_timeout_seconds: int = 180
    download_retries: int = 2
    download_retry_backoff_seconds: float = 2.0

    @classmethod
    def discover(
        cls,
        *,
        opencli: str | None = None,
        profile: str | None = None,
        ytdlp: str | None = None,
        ffmpeg: str | None = None,
        browser_command_timeout_seconds: int | None = None,
        download_retries: int | None = None,
        download_retry_backoff_seconds: float | None = None,
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
        selected_browser_timeout = _positive_int_setting(
            browser_command_timeout_seconds,
            os.getenv("VIDEO_SUBTITLE_OPENCLI_BROWSER_TIMEOUT"),
            default=180,
            label="OpenCLI browser command timeout",
        )
        selected_download_retries = _nonnegative_int_setting(
            download_retries,
            os.getenv("VIDEO_SUBTITLE_DOWNLOAD_RETRIES"),
            default=2,
            label="download retries",
        )
        selected_retry_backoff = _nonnegative_float_setting(
            download_retry_backoff_seconds,
            os.getenv("VIDEO_SUBTITLE_DOWNLOAD_RETRY_BACKOFF"),
            default=2.0,
            label="download retry backoff",
        )
        return cls(
            command=tuple(command),
            profile=selected_profile,
            ytdlp_path=selected_ytdlp,
            ffmpeg_path=selected_ffmpeg,
            browser_command_timeout_seconds=selected_browser_timeout,
            download_retries=selected_download_retries,
            download_retry_backoff_seconds=selected_retry_backoff,
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
            browser_command_timeout_seconds=_positive_int_setting(
                value.get("browser_command_timeout_seconds"),
                default=180,
                label="OpenCLI browser command timeout",
            ),
            download_retries=_nonnegative_int_setting(
                value.get("download_retries"),
                default=2,
                label="download retries",
            ),
            download_retry_backoff_seconds=_nonnegative_float_setting(
                value.get("download_retry_backoff_seconds"),
                default=2.0,
                label="download retry backoff",
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "command": list(self.command),
            "profile": self.profile,
            "ytdlp_path": self.ytdlp_path,
            "ffmpeg_path": self.ffmpeg_path,
            "browser_command_timeout_seconds": self.browser_command_timeout_seconds,
            "download_retries": self.download_retries,
            "download_retry_backoff_seconds": self.download_retry_backoff_seconds,
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
        cache_dir: Path | None = None,
        cache_key: str | None = None,
    ) -> tuple[Path, Any]:
        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        resolved_cache_key = _download_cache_key(
            url,
            quality=quality,
            page=page,
            identity=cache_key,
        )
        target_dir = output_dir
        cache_entry: Path | None = None
        if cache_dir is not None:
            cache_entry = (
                cache_dir.expanduser().resolve() / self.platform / resolved_cache_key
            )
            cache_entry.mkdir(parents=True, exist_ok=True)
            target_dir = cache_entry
            cached = _read_download_cache(cache_entry, resolved_cache_key)
            if cached is not None:
                return cached, _download_result(
                    cached,
                    raw_result=None,
                    cache_key=resolved_cache_key,
                    cache_hit=True,
                    cache_state="complete",
                    retry_index=0,
                    attempt_count=0,
                )

        before = _media_snapshot(target_dir)
        last_error: OpenCliError | None = None
        for retry_index in range(self.settings.download_retries + 1):
            if retry_index:
                recovered = _latest_media(target_dir)
                if recovered is not None:
                    if cache_entry is not None:
                        _write_download_cache(
                            cache_entry,
                            resolved_cache_key,
                            recovered,
                        )
                    return recovered, _download_result(
                        recovered,
                        raw_result=None,
                        cache_key=resolved_cache_key,
                        cache_hit=True,
                        cache_state="recovered_after_error",
                        retry_index=retry_index,
                        attempt_count=retry_index,
                    )
                backoff = self.settings.download_retry_backoff_seconds * retry_index
                if backoff:
                    time.sleep(backoff)

            args = [
                "bilibili",
                "download",
                url,
                "--output",
                str(target_dir),
                "--quality",
                quality,
            ]
            if page is not None:
                args += ["--page", str(page)]
            try:
                payload = self._call(args, timeout=None)
                _raise_for_download_status(payload)
            except OpenCliError as error:
                last_error = error
                if not _is_retryable_download_error(error):
                    raise
                continue

            candidate = _latest_media(target_dir, before=before)
            if candidate is None:
                last_error = OpenCliError(
                    "DOWNLOAD_ARTIFACT_NOT_FOUND",
                    "OpenCLI completed but no downloaded video file was found",
                    help_text=f"Inspect the output directory: {target_dir}",
                )
                continue
            if cache_entry is not None:
                _write_download_cache(
                    cache_entry,
                    resolved_cache_key,
                    candidate,
                )
            return candidate, _download_result(
                candidate,
                raw_result=payload,
                cache_key=resolved_cache_key,
                cache_hit=False,
                cache_state="written" if cache_entry is not None else "disabled",
                retry_index=retry_index,
                attempt_count=retry_index + 1,
            )

        assert last_error is not None
        raise last_error

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
        environment.setdefault(
            "OPENCLI_BROWSER_COMMAND_TIMEOUT",
            str(self.settings.browser_command_timeout_seconds),
        )
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


_DOWNLOAD_CACHE_FILENAME = "download-cache.json"


def _download_cache_key(
    url: str,
    *,
    quality: str,
    page: int | None,
    identity: str | None,
) -> str:
    source_identity = (identity or "").strip()
    if not source_identity:
        match = re.search(r"(?i)\b(BV[0-9A-Za-z]+)\b", url)
        source_identity = match.group(1) if match else url
    normalized_page = page or 1
    digest_source = f"bilibili|{source_identity}|p{normalized_page}|{quality}"
    digest = sha256(digest_source.encode("utf-8")).hexdigest()[:12]
    identity_label = re.sub(r"[^0-9A-Za-z._-]+", "-", source_identity).strip("-._")
    quality_label = re.sub(r"[^0-9A-Za-z._-]+", "-", quality).strip("-._")
    identity_label = (identity_label or "video")[:48]
    quality_label = (quality_label or "quality")[:24]
    return f"{identity_label}-p{normalized_page}-{quality_label}-{digest}"


def _read_download_cache(cache_entry: Path, cache_key: str) -> Path | None:
    marker_path = cache_entry / _DOWNLOAD_CACHE_FILENAME
    if not marker_path.is_file():
        return None
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("cache_key") != cache_key:
        return None
    raw_name = payload.get("media_file")
    if not isinstance(raw_name, str) or not raw_name:
        return None
    media_path = (cache_entry / raw_name).resolve()
    try:
        media_path.relative_to(cache_entry.resolve())
    except ValueError:
        return None
    if not media_path.is_file():
        return None
    expected_bytes = _optional_int(payload.get("actual_bytes"))
    actual_bytes = media_path.stat().st_size
    if actual_bytes <= 0 or (
        expected_bytes is not None and expected_bytes != actual_bytes
    ):
        return None
    return media_path


def _write_download_cache(cache_entry: Path, cache_key: str, media_path: Path) -> None:
    media_path = media_path.resolve()
    stat = media_path.stat()
    payload = {
        "schema_version": "video-subtitle/download-cache-v1",
        "cache_key": cache_key,
        "media_file": media_path.name,
        "actual_bytes": stat.st_size,
        "actual_mib": round(stat.st_size / (1024 * 1024), 3),
    }
    marker_path = cache_entry / _DOWNLOAD_CACHE_FILENAME
    temporary_path = marker_path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_path, marker_path)


def _latest_media(
    directory: Path,
    *,
    before: dict[Path, tuple[int, int]] | None = None,
) -> Path | None:
    after = _media_snapshot(directory)
    if before is None:
        candidates = list(after)
    else:
        changed = [
            path
            for path, signature in after.items()
            if path not in before or before[path] != signature
        ]
        candidates = changed or list(after)
    if not candidates:
        return None
    candidates.sort(key=lambda item: after[item][0], reverse=True)
    return candidates[0]


def _download_result(
    media_path: Path,
    *,
    raw_result: Any,
    cache_key: str,
    cache_hit: bool,
    cache_state: str,
    retry_index: int,
    attempt_count: int,
) -> dict[str, Any]:
    stat = media_path.stat()
    return {
        "schema_version": "video-subtitle/download-result-v1",
        "provider": "opencli",
        "cache_key": cache_key,
        "cache_hit": cache_hit,
        "cache_state": cache_state,
        "retry_index": retry_index,
        "attempt_count": attempt_count,
        "actual_path": str(media_path.resolve()),
        "actual_bytes": stat.st_size,
        "actual_mib": round(stat.st_size / (1024 * 1024), 3),
        "raw_result": raw_result,
    }


def _raise_for_download_status(payload: Any) -> None:
    if not isinstance(payload, list) or not payload:
        return
    first = payload[0]
    if not isinstance(first, dict):
        return
    status = str(first.get("status", "")).lower()
    if status in {"failed", "error"}:
        raise OpenCliError(
            "DOWNLOAD_FAILED",
            str(first.get("size") or "OpenCLI reported a failed download"),
        )


def _is_retryable_download_error(error: OpenCliError) -> bool:
    code = error.code.strip().upper()
    if code in {
        "OPENCLI_TIMEOUT",
        "TIMEOUT",
        "COMMAND_RESULT_UNKNOWN",
        "DOWNLOAD_ARTIFACT_NOT_FOUND",
        "NETWORK_ERROR",
        "CONNECTION_ERROR",
    }:
        return True
    message = f"{error.message} {error.help_text}".lower()
    return any(
        token in message
        for token in (
            "timed out",
            "timeout",
            "temporarily unavailable",
            "connection reset",
            "command result unknown",
        )
    )


def _positive_int_setting(
    *values: Any,
    default: int,
    label: str,
) -> int:
    selected = next(
        (value for value in values if value is not None and value != ""), default
    )
    try:
        parsed = int(selected)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be an integer") from error
    if parsed < 1:
        raise ValueError(f"{label} must be positive")
    return parsed


def _nonnegative_int_setting(
    *values: Any,
    default: int,
    label: str,
) -> int:
    selected = next(
        (value for value in values if value is not None and value != ""), default
    )
    try:
        parsed = int(selected)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be an integer") from error
    if parsed < 0:
        raise ValueError(f"{label} cannot be negative")
    return parsed


def _nonnegative_float_setting(
    *values: Any,
    default: float,
    label: str,
) -> float:
    selected = next(
        (value for value in values if value is not None and value != ""), default
    )
    try:
        parsed = float(selected)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be numeric") from error
    if parsed < 0:
        raise ValueError(f"{label} cannot be negative")
    return parsed
