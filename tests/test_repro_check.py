from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from scripts.repro_check import run_repro_check

ROOT = Path(__file__).resolve().parents[1]


def test_authorized_media_fixture_hash_and_license() -> None:
    root = ROOT / "tests" / "fixtures" / "authorized-video"
    fixture = json.loads((root / "fixture.json").read_text(encoding="utf-8"))
    video = root / fixture["video"]["path"]

    assert fixture["generated"] is True
    assert fixture["license"] == "CC0-1.0"
    assert fixture["video"]["has_audio"] is True
    assert fixture["video"]["hard_subtitle"] == "AUTHORIZED TEST SUBTITLE"
    assert hashlib.sha256(video.read_bytes()).hexdigest() == fixture["video"]["sha256"]
    assert video.stat().st_size == fixture["video"]["bytes"]


def test_repro_check_core_tier_passes() -> None:
    report = run_repro_check(required_tiers=["core"])

    assert report["ok"] is True
    assert report["tiers"]["core"]["status"] == "passed"
    assert report["boundaries"]["credentials_persisted"] is False
    assert report["boundaries"]["published"] is False


def test_repro_check_agent_tier_includes_watch_later_contract() -> None:
    report = run_repro_check(required_tiers=["agent"])
    checks = {item["name"]: item for item in report["tiers"]["agent"]["checks"]}

    automation = checks["watch_later_to_draft_contract"]
    assert automation["status"] == "passed"
    assert automation["details"]["jobs_created"] == 1
    assert automation["details"]["draft_bindings"] == 1
    assert automation["details"]["duplicate_drafts"] == 0
    assert automation["details"]["published"] is False


def test_repro_check_cli_writes_the_same_machine_readable_contract(
    tmp_path: Path,
) -> None:
    output = tmp_path / "repro-report.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "repro_check.py"),
            "--require-tier",
            "core",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    stdout_report = json.loads(completed.stdout)
    file_report = json.loads(output.read_text(encoding="utf-8"))
    assert stdout_report == file_report
    assert file_report["schema_version"] == "video-subtitle/repro-check-v1"
