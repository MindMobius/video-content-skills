from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import jsonschema

from video_subtitle.core.batch import get_batch, initialize_batch, update_batch_item

ROOT = Path(__file__).resolve().parents[1]


def _inputs() -> list[dict[str, str]]:
    return [
        {
            "kind": "video_url",
            "value": "https://www.bilibili.com/video/BV1fixture1/",
        },
        {
            "kind": "video_url",
            "value": "https://www.bilibili.com/video/BV1fixture2/",
        },
    ]


def test_batch_manifest_tracks_each_video_and_stage_independently(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "batch.json"

    result = initialize_batch(
        manifest,
        _inputs(),
        target_medium="article",
        draft_requested=True,
    )

    assert result["reused_existing_batch"] is False
    assert result["summary"] == {"total": 2, "by_status": {"pending": 2}}
    assert result["resumable"] == [
        {"item_id": "item-001", "stage": "subtitle", "status": "pending"},
        {"item_id": "item-002", "stage": "subtitle", "status": "pending"},
    ]
    schema = json.loads(
        (ROOT / "schemas" / "batch-manifest.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(json.loads(manifest.read_text(encoding="utf-8")), schema)

    reused = initialize_batch(
        manifest,
        _inputs(),
        target_medium="article",
        draft_requested=True,
    )
    assert reused["reused_existing_batch"] is True


def test_batch_enforces_prerequisites_and_supports_retry(tmp_path: Path) -> None:
    manifest = tmp_path / "batch.json"
    initialize_batch(manifest, _inputs(), draft_requested=True)

    try:
        update_batch_item(
            manifest,
            item_id="item-001",
            stage="content",
            status="running",
        )
    except ValueError as error:
        assert "completed subtitle" in str(error)
    else:  # pragma: no cover
        raise AssertionError("content must wait for subtitle evidence")

    running = update_batch_item(
        manifest,
        item_id="item-001",
        stage="subtitle",
        status="running",
    )
    assert running["items"][0]["stages"]["subtitle"]["status"] == "running"
    update_batch_item(
        manifest,
        item_id="item-001",
        stage="subtitle",
        status="failed",
        error="temporary OCR process failure",
    )
    update_batch_item(
        manifest,
        item_id="item-001",
        stage="subtitle",
        status="running",
    )
    artifact = tmp_path / "item-001" / "manifest.json"
    artifact.parent.mkdir()
    artifact.write_text("{}", encoding="utf-8")
    result = update_batch_item(
        manifest,
        item_id="item-001",
        stage="subtitle",
        status="completed",
        artifact=str(artifact),
    )

    item = result["items"][0]
    assert item["stages"]["subtitle"]["attempts"] == 2
    assert item["stages"]["subtitle"]["artifact"] == "item-001/manifest.json"
    assert result["resumable"][0] == {
        "item_id": "item-001",
        "stage": "content",
        "status": "pending",
    }
    assert not manifest.with_suffix(".json.lock").exists()


def test_batch_rejects_credentials_and_out_of_tree_artifacts(tmp_path: Path) -> None:
    manifest = tmp_path / "batch.json"
    try:
        initialize_batch(
            manifest,
            [{"kind": "video_url", "value": "https://example.test/?token=secret"}],
        )
    except ValueError as error:
        assert "credentials" in str(error)
    else:  # pragma: no cover
        raise AssertionError("token-bearing URL must be rejected")

    initialize_batch(manifest, _inputs())
    update_batch_item(
        manifest,
        item_id="item-001",
        stage="subtitle",
        status="running",
    )
    outside = tmp_path.parent / "outside-manifest.json"
    outside.write_text("{}", encoding="utf-8")
    try:
        update_batch_item(
            manifest,
            item_id="item-001",
            stage="subtitle",
            status="completed",
            artifact=str(outside),
        )
    except ValueError as error:
        assert "under the batch directory" in str(error)
    else:  # pragma: no cover
        raise AssertionError("batch artifact must remain portable")


def test_batch_cli_round_trip(tmp_path: Path) -> None:
    manifest = tmp_path / "batch.json"
    command = [
        sys.executable,
        "-m",
        "video_subtitle.cli",
        "batch-init",
        "--manifest",
        str(manifest),
        "--input",
        _inputs()[0]["value"],
        "--input",
        _inputs()[1]["value"],
        "--medium",
        "article",
        "--draft",
    ]
    initialized = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    status = subprocess.run(
        [
            sys.executable,
            "-m",
            "video_subtitle.cli",
            "batch-status",
            "--manifest",
            str(manifest),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert initialized.returncode == 0, initialized.stderr
    assert status.returncode == 0, status.stderr
    assert json.loads(status.stdout)["summary"]["total"] == 2
    assert get_batch(manifest)["intent"]["draft_requested"] is True
