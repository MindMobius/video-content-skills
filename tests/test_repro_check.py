from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.repro_check import run_repro_check

ROOT = Path(__file__).resolve().parents[1]


def test_repro_check_core_tier_passes() -> None:
    report = run_repro_check(required_tiers=["core"])
    assert report["ok"] is True
    assert report["schema_version"] == "video-content/repro-check-v1"
    assert report["tiers"]["core"]["status"] == "passed"
    flow = next(
        item
        for item in report["tiers"]["core"]["checks"]
        if item["name"] == "six_product_flow"
    )
    assert flow["details"]["products"] == {
        "profiles": 1,
        "jobs": 1,
        "evidence": 1,
        "transcript": 1,
        "content": 1,
        "draft_receipt": 1,
    }
    assert flow["details"]["idempotency"] == {
        "reused_job": True,
        "reused_content": True,
        "second_draft_blocked": True,
        "jobs": 1,
        "content": 1,
        "draft_receipt": 1,
    }
    assert report["boundaries"]["published"] is False


def test_repro_check_agent_tier_covers_mcp_and_watch_later() -> None:
    report = run_repro_check(required_tiers=["agent"])
    assert report["ok"] is True
    checks = {item["name"]: item for item in report["tiers"]["agent"]["checks"]}
    assert checks["mcp_protocol"]["details"]["tool_count"] == 16
    assert checks["watch_later_idempotency"]["details"] == {
        "jobs": 3,
        "duplicates": 0,
        "new_after_reorder": 1,
    }


def test_repro_check_cli_writes_the_same_json_contract(tmp_path: Path) -> None:
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
    assert json.loads(completed.stdout) == json.loads(
        output.read_text(encoding="utf-8")
    )
