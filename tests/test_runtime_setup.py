from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import jsonschema

from scripts import runtime_setup

ROOT = Path(__file__).resolve().parents[1]


def _lock() -> dict:
    return json.loads(
        (ROOT / "requirements" / "runtime-lock.json").read_text(encoding="utf-8")
    )


def test_runtime_lock_is_schema_valid_and_pins_large_artifacts() -> None:
    lock = _lock()
    schema = json.loads(
        (ROOT / "schemas" / "runtime-lock.schema.json").read_text(encoding="utf-8")
    )

    jsonschema.validate(lock, schema)
    assert lock["videocr"]["version"] == "1.5.1"
    assert all(
        len(asset["sha256"]) == 64 for asset in lock["videocr"]["variants"].values()
    )
    assert len(lock["models"]["qwen_asr_model"]["revision"]) == 40
    assert lock["models"]["qwen_asr_model"]["confirmation_required"] is True


def test_videocr_plan_defaults_to_cpu_for_current_platform(monkeypatch) -> None:
    monkeypatch.setattr(runtime_setup.platform, "system", lambda: "Windows")
    monkeypatch.setattr(runtime_setup.platform, "machine", lambda: "AMD64")

    report = runtime_setup._plan(_lock(), "videocr", None, None, "")

    assert report["ok"] is True
    assert report["variant"] == "windows-x86_64-cpu"
    assert report["confirmation_required"] is True
    assert report["download"]["bytes"] > 400_000_000
    assert "--confirm-large-download" in report["next_command"]


def test_videocr_verify_checks_size_and_sha256(tmp_path: Path) -> None:
    payload = b"verified archive"
    archive = tmp_path / "fixture.7z"
    archive.write_bytes(payload)
    lock = deepcopy(_lock())
    lock["videocr"]["variants"]["fixture"] = {
        "asset": archive.name,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "url": "https://example.invalid/fixture.7z",
    }

    report = runtime_setup._verify(lock, "videocr", archive, "fixture", "", quick=False)

    assert report["ok"] is True
    assert report["actual_sha256"] == report["expected_sha256"]


def test_large_install_refuses_to_run_without_confirmation(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "runtime_setup.py"),
            "install",
            "videocr",
            "--path",
            str(tmp_path / "download"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 1
    report = json.loads(completed.stdout)
    assert report["ok"] is False
    assert "--confirm-large-download" in report["error"]
    assert not (tmp_path / "download").exists()


def test_bootstrap_installs_with_the_repository_constraints() -> None:
    source = (ROOT / "scripts" / "bootstrap.py").read_text(encoding="utf-8")

    assert 'root / "requirements" / "mcp-constraints.txt"' in source
    assert (ROOT / "uv.lock").is_file()
    assert (ROOT / "npm-shrinkwrap.json").is_file()


def test_interrupted_runtime_target_is_resumable_only_for_the_same_plan(
    tmp_path: Path,
) -> None:
    target = tmp_path / "model"
    marker = {
        "schema_version": "video-content/runtime-installing-v1",
        "dependency": "qwen_asr_model",
        "revision": "fixture-revision",
    }

    assert runtime_setup._prepare_resumable_target(target, marker) == "new"
    (target / "partial.bin").write_bytes(b"partial")
    assert runtime_setup._prepare_resumable_target(target, marker) == "resume"

    changed = {**marker, "revision": "different-revision"}
    try:
        runtime_setup._prepare_resumable_target(target, changed)
    except ValueError as error:
        assert "different interrupted installation" in str(error)
    else:  # pragma: no cover
        raise AssertionError("a different runtime plan must not reuse partial files")


def test_new_asr_environment_requires_the_locked_python_series(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(runtime_setup, "_current_python_series", lambda: "3.10")
    target = tmp_path / "asr"

    try:
        runtime_setup._install_asr(_lock(), target, "cpu")
    except ValueError as error:
        assert "requires Python 3.12" in str(error)
    else:  # pragma: no cover
        raise AssertionError("ASR installation must use the Python series in the lock")
    assert not target.exists()


def test_asr_state_rejects_a_different_python_series(
    monkeypatch, tmp_path: Path
) -> None:
    lock = _lock()
    versions = {
        "python_version": "3.11",
        "torch": lock["asr"]["profiles"]["cpu"]["torch"],
        "qwen_asr": lock["asr"]["qwen_asr"],
        "transformers": lock["asr"]["transformers"],
        "cuda_available": False,
        "cuda_runtime": None,
    }
    monkeypatch.setattr(
        runtime_setup.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 0, stdout=json.dumps(versions), stderr=""
        ),
    )

    state = runtime_setup._asr_state(tmp_path / "python", lock, "cpu")

    assert state["available"] is True
    assert state["valid"] is False
    assert state["python_version"] == "3.11"


def test_successful_runtime_reuse_clears_interrupted_marker(
    monkeypatch, tmp_path: Path
) -> None:
    target = tmp_path / "model"
    target.mkdir()
    (target / runtime_setup.RECEIPT_NAME).write_text("{}", encoding="utf-8")
    marker = target / runtime_setup.INSTALLING_NAME
    marker.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        runtime_setup,
        "_verify_model",
        lambda *_args, **_kwargs: {"valid": True, "file_count": 1},
    )
    monkeypatch.setattr(runtime_setup.shutil, "which", lambda _name: None)

    result = runtime_setup._download_model(_lock(), "qwen_asr_model", target)

    assert result["ok"] is True
    assert result["reused"] is True
    assert not marker.exists()


def test_model_verify_rejects_unexpected_files(tmp_path: Path) -> None:
    payload = b"model"
    model = tmp_path / "model"
    model.mkdir()
    artifact = model / "model.bin"
    artifact.write_bytes(payload)
    expected = {"repo_id": "fixture/model", "revision": "a" * 40}
    receipt = {
        "repo_id": expected["repo_id"],
        "revision": expected["revision"],
        "files": [
            {
                "path": "model.bin",
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        ],
    }
    (model / runtime_setup.RECEIPT_NAME).write_text(
        json.dumps(receipt), encoding="utf-8"
    )

    assert runtime_setup._verify_model(model, expected, quick=False)["valid"] is True
    (model / "unexpected.bin").write_bytes(b"unexpected")
    result = runtime_setup._verify_model(model, expected, quick=False)

    assert result["valid"] is False
    assert "unexpected:unexpected.bin" in result["mismatches"]
