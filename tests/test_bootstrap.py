from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]


def test_bootstrap_emits_one_machine_readable_contract(tmp_path: Path) -> None:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("VIDEO_CONTENT_"):
            environment.pop(name)

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "bootstrap.py"),
            "--config",
            str(tmp_path / "config.json"),
            "--capability",
            "hard_ocr_local",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert completed.returncode == 0
    report = json.loads(completed.stdout)
    schema = json.loads(
        (ROOT / "schemas" / "bootstrap.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(report, schema)
    discovered = [item["name"] for item in report["skills"]["available"]]
    expected = sorted(
        path.parent.name for path in (ROOT / ".agents" / "skills").glob("*/SKILL.md")
    )
    assert discovered == expected
    assert report["mcp"]["transport"] == "stdio"
    assert report["mcp"]["registration_owner"] == "calling_agent"
    assert report["installation"]["lock"]["verified"] is True
    assert len(report["installation"]["lock"]["sha256"]) == 64
    assert report["cli"]["command"][-2:] == [
        "--config",
        str((tmp_path / "config.json").resolve()),
    ]
    assert report["mcp"]["env"] == {
        "VIDEO_CONTENT_CONFIG": str((tmp_path / "config.json").resolve())
    }


def test_clean_checkout_ci_expects_capability_plan_not_host_runtime() -> None:
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    assert "--capability hard_ocr_local" in workflow
    assert "assert not report['ready']" in workflow
    assert "report['status']=='agent_action_required'" in workflow
    assert "report['setup']['requested_capabilities']==['hard_ocr_local']" in workflow
