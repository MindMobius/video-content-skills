from __future__ import annotations

import json
from pathlib import Path

from video_content.api import job_list
from video_content.config import (
    configured_home,
    default_state_root,
    resolve_config_path,
)
from video_content.store import Store


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "src" / "video_content").mkdir(parents=True)
    (root / ".video-content").mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    return root


def _write_config(root: Path, home: Path) -> Path:
    path = root / ".video-content" / "config.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "video-content/config-v1",
                "values": {"home": str(home), "videocr": "videocr.exe"},
            }
        ),
        encoding="utf-8",
    )
    return path


def test_project_local_config_is_discovered_before_os_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    root = _project(tmp_path)
    config = _write_config(root, tmp_path / "state")
    nested = root / "tools"
    nested.mkdir()
    monkeypatch.chdir(nested)
    monkeypatch.delenv("VIDEO_CONTENT_CONFIG", raising=False)
    monkeypatch.delenv("VIDEO_CONTENT_HOME", raising=False)

    assert resolve_config_path() == config.resolve()


def test_store_uses_the_home_from_discovered_project_config(
    tmp_path: Path, monkeypatch
) -> None:
    root = _project(tmp_path)
    state = tmp_path / "state"
    _write_config(root, state)
    monkeypatch.chdir(root)
    monkeypatch.delenv("VIDEO_CONTENT_CONFIG", raising=False)
    monkeypatch.delenv("VIDEO_CONTENT_HOME", raising=False)

    assert Store.from_environment().root == state.resolve()


def test_direct_api_calls_share_the_discovered_store(
    tmp_path: Path, monkeypatch
) -> None:
    root = _project(tmp_path)
    state = tmp_path / "state"
    _write_config(root, state)
    store = Store(state)
    store.create_job(
        source={"platform": "bilibili", "bvid": "BV1test"},
        idempotency_key="bilibili_BV1test_p1",
    )
    monkeypatch.chdir(root)
    monkeypatch.delenv("VIDEO_CONTENT_CONFIG", raising=False)
    monkeypatch.delenv("VIDEO_CONTENT_HOME", raising=False)

    result = job_list()

    assert result["count"] == 1
    assert result["jobs"][0]["idempotency_key"] == "bilibili_BV1test_p1"


def test_default_state_root_stays_at_project_root_from_nested_directory(
    tmp_path: Path, monkeypatch
) -> None:
    root = _project(tmp_path)
    nested = root / "tools" / "nested"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    assert default_state_root() == (root / ".video-content").resolve()


def test_explicit_config_file_anchors_store_context_without_home(
    tmp_path: Path, monkeypatch
) -> None:
    config = tmp_path / ".video-content" / "config.json"
    config.parent.mkdir()
    monkeypatch.setenv("VIDEO_CONTENT_CONFIG", str(config))
    monkeypatch.delenv("VIDEO_CONTENT_HOME", raising=False)

    assert configured_home() == config.parent.resolve()


def test_non_project_invocation_uses_user_level_state_root(
    tmp_path: Path, monkeypatch
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    appdata = tmp_path / "appdata"
    monkeypatch.chdir(outside)
    monkeypatch.delenv("VIDEO_CONTENT_CONFIG", raising=False)
    monkeypatch.delenv("VIDEO_CONTENT_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(appdata))

    assert default_state_root() == (appdata / "video-content").resolve()
