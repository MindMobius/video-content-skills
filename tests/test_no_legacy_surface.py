from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_HISTORY = {
    "docs/plans/2026-08-17-video-content-clean-slate-design.md",
    "docs/plans/2026-08-17-video-content-clean-slate.md",
}
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
FORBIDDEN = (
    "video-" + "subtitle",
    "video_" + "subtitle",
    "VIDEO_" + "SUBTITLE",
    ".video-" + "subtitle",
    "video-" + "automation",
    "video-watch-later-" + "automation",
    "wechat-draft-" + "handoff",
    "prepare_" + "subtitle_review",
    "get_" + "subtitle_review_window",
    "submit_" + "subtitle_review_window",
    "start_" + "video_content_phase",
    "finish_" + "video_content_phase",
    "initialize_" + "video_batch",
    "project_" + "bundle",
    "DeepSeek " + "Harness",
)


def _tracked_paths() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    return [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def test_tracked_repository_has_no_removed_runtime_surface() -> None:
    violations: list[str] = []
    for relative in _tracked_paths():
        normalized = relative.replace("\\", "/")
        for token in FORBIDDEN:
            if token in normalized:
                violations.append(f"path:{normalized}:{token}")
        if (
            normalized in ALLOWED_HISTORY
            or Path(normalized).suffix.lower() not in TEXT_SUFFIXES
        ):
            continue
        content = (ROOT / normalized).read_text(encoding="utf-8")
        for token in FORBIDDEN:
            if token in content:
                violations.append(f"text:{normalized}:{token}")
    assert violations == []
