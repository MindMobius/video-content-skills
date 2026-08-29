from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.validate_layout import build_report
from video_content.layout import (
    inspect_state_layout,
    read_path_relocation,
    resolve_recorded_path,
    write_path_relocation,
)


def _make_state(root: Path, *, config: bool = True) -> None:
    for relative in (
        "profiles",
        "jobs",
        "cache/media",
        "indexes",
        "locks",
        "meta",
        "runs",
        "archive",
    ):
        (root / Path(*relative.split("/"))).mkdir(parents=True, exist_ok=True)
    if config:
        (root / "config.json").write_text(
            json.dumps(
                {
                    "schema_version": "video-content/config-v1",
                    "values": {"home": str(root)},
                }
            ),
            encoding="utf-8",
        )


def test_layout_inspector_rejects_unexpected_state_root_entries(
    tmp_path: Path,
) -> None:
    state = tmp_path / ".video-content"
    _make_state(state)
    (state / "run-old.py").write_text("# legacy\n", encoding="utf-8")

    report = inspect_state_layout(state, require_config=True)

    assert report["ready"] is False
    assert report["unexpected_entries"] == ["run-old.py"]


def test_layout_checker_accepts_a_clean_repository(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    state = repository / ".video-content"
    _make_state(state)

    report = build_report(repository)

    assert report["ready"] is True
    assert report["repository_residuals"] == []


def test_layout_checker_uses_explicit_config_as_state_anchor(
    tmp_path: Path, monkeypatch
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _make_state(repository / ".video-content")
    isolated_state = tmp_path / "isolated-state"
    _make_state(isolated_state)
    config = isolated_state / "config.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": "video-content/config-v1",
                "values": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("VIDEO_CONTENT_CONFIG", raising=False)
    monkeypatch.delenv("VIDEO_CONTENT_HOME", raising=False)

    report = build_report(repository, config_path=config)

    assert report["ready"] is True
    assert Path(report["state_root"]) == isolated_state.resolve()


def test_layout_checker_resolves_relative_home_from_config_directory(
    tmp_path: Path, monkeypatch
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _make_state(repository / ".video-content")
    context = tmp_path / "context"
    config = context / "settings" / "config.json"
    config.parent.mkdir(parents=True)
    isolated_state = context / "runtime"
    _make_state(isolated_state)
    config.write_text(
        json.dumps(
            {
                "schema_version": "video-content/config-v1",
                "values": {"home": "../runtime"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("VIDEO_CONTENT_CONFIG", raising=False)
    monkeypatch.delenv("VIDEO_CONTENT_HOME", raising=False)

    report = build_report(repository, config_path=config)

    assert report["ready"] is True
    assert Path(report["state_root"]) == isolated_state.resolve()


def test_layout_checker_requires_the_default_config(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _make_state(repository / ".video-content", config=False)

    report = build_report(repository)

    assert report["ready"] is False
    assert "The canonical .video-content/config.json is missing." in report["errors"]


def test_layout_checker_reports_repository_temp_roots(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    state = repository / ".video-content"
    _make_state(state)
    (repository / ".tmp-live-test-example").mkdir()
    (repository / "src" / ("video_" + "subtitle")).mkdir(parents=True)

    report = build_report(repository)

    assert report["ready"] is False
    assert report["repository_residuals"] == [
        ".tmp-live-test-example",
        "src/" + "video_" + "subtitle",
    ]


def test_layout_checker_rejects_unplanned_repository_entries(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _make_state(repository / ".video-content")
    (repository / "latest-article-preview.json").write_text("{}", encoding="utf-8")

    report = build_report(repository)

    assert report["ready"] is False
    assert report["repository_unexpected_entries"] == ["latest-article-preview.json"]


def test_path_relocation_resolves_active_and_archived_history_without_rewriting(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    _make_state(state)
    recorded_root = tmp_path / "old-state"
    active_file = state / "jobs" / "job-1" / "job.json"
    active_file.parent.mkdir(parents=True)
    active_file.write_text("active", encoding="utf-8")
    archived_file = state / "archive" / "legacy" / "wechat-observations" / "result.json"
    archived_file.parent.mkdir(parents=True)
    archived_file.write_text("archived", encoding="utf-8")

    registry = write_path_relocation(
        state,
        recorded_root=recorded_root,
        current_root=state,
        archive_root=state / "archive" / "legacy",
        reason="test relocation",
    )

    assert registry["relocations"][0]["recorded_root"] == str(recorded_root.resolve())
    assert read_path_relocation(state)["exists"] is True
    active = resolve_recorded_path(
        recorded_root / "jobs" / "job-1" / "job.json", state_root=state
    )
    archived = resolve_recorded_path(
        recorded_root / "wechat-observations" / "result.json", state_root=state
    )
    assert active["status"] == "relocated"
    assert Path(active["resolved_path"]) == active_file.resolve()
    assert archived["status"] == "archived"
    assert Path(archived["resolved_path"]) == archived_file.resolve()
    schema = json.loads(
        (Path("schemas") / "path-relocation.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(
        json.loads(
            (state / "meta" / "path-relocation.json").read_text(encoding="utf-8")
        ),
        schema,
    )


def test_layout_checker_requires_a_registry_for_historical_absolute_paths(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    state = repository / ".video-content"
    _make_state(state)
    job = state / "jobs" / "job-1"
    job.mkdir()
    (job / "job.json").write_text(
        json.dumps(
            {"path": str(tmp_path / "old-state" / "jobs" / "job-1" / "job.json")}
        ),
        encoding="utf-8",
    )

    report = build_report(repository)

    assert report["ready"] is False
    assert report["historical_path_references"]["reference_count"] == 1
    assert any("path-relocation.json" in error for error in report["errors"])


def test_layout_checker_accepts_registered_historical_paths(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    state = repository / ".video-content"
    _make_state(state)
    old_root = tmp_path / "old-state"
    job = state / "jobs" / "job-1"
    job.mkdir()
    (job / "job.json").write_text("{}", encoding="utf-8")
    (state / "jobs" / "job-1" / "record.json").write_text(
        json.dumps({"path": str(old_root / "jobs" / "job-1" / "job.json")}),
        encoding="utf-8",
    )
    write_path_relocation(
        state,
        recorded_root=old_root,
        current_root=state,
        archive_root=state / "archive" / "legacy",
    )

    report = build_report(repository)

    assert report["ready"] is True
    assert report["historical_path_references"]["status"] == "mapped"
    assert report["historical_path_references"]["unresolved_examples"] == []


def test_layout_checker_rejects_hidden_environment_state_override(
    tmp_path: Path, monkeypatch
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _make_state(repository / ".video-content")
    monkeypatch.setenv("VIDEO_CONTENT_HOME", str(tmp_path / "unrelated-state"))
    monkeypatch.delenv("VIDEO_CONTENT_CONFIG", raising=False)

    report = build_report(repository)

    assert report["ready"] is False
    assert any("environment override" in error for error in report["errors"])


def test_path_relocation_never_resolves_outside_registered_roots(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    _make_state(state)
    old_root = tmp_path / "old-state"
    write_path_relocation(state, recorded_root=old_root, current_root=state)

    result = resolve_recorded_path(
        str(old_root / ".." / "outside.txt"), state_root=state
    )

    assert result["status"] == "unmapped"
    assert result["resolved_path"] is None
