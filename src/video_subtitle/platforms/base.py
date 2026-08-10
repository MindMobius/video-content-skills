from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class PlatformError(RuntimeError):
    """Structured failure returned by a video-platform adapter."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        help_text: str = "",
        exit_code: int | None = None,
        raw_output: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.help_text = help_text
        self.exit_code = exit_code
        self.raw_output = raw_output

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "help": self.help_text,
            "exit_code": self.exit_code,
        }


class VideoPlatformClient(Protocol):
    """Minimal interface required by the extraction pipeline."""

    platform: str

    def video(self, url: str, *, page: int | None = None) -> dict[str, str]: ...

    def subtitles(
        self,
        url: str,
        *,
        lang: str = "ai-zh",
        page: int | None = None,
    ) -> list[dict[str, Any]]: ...

    def download(
        self,
        url: str,
        output_dir: Path,
        *,
        quality: str = "1080p",
        page: int | None = None,
        cache_dir: Path | None = None,
        cache_key: str | None = None,
    ) -> tuple[Path, Any]: ...
