from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import jsonschema

from video_subtitle.core.content import initialize_content_project
from video_subtitle.core.portable import (
    export_content_bundle,
    import_content_bundle,
    verify_content_bundle,
)
from video_subtitle.core.srt import Cue, write_srt
from video_subtitle.core.util import write_json_atomic

ROOT = Path(__file__).resolve().parents[1]


def _project(root: Path) -> Path:
    subtitle = root / "subtitle.ocr.srt"
    write_srt(subtitle, [Cue(0, 2000, "可迁移的字幕证据。")])
    source_video = root / "source.mp4"
    source_video.write_bytes(b"large media placeholder")
    manifest = {
        "schema_version": "video-subtitle/v1",
        "job_id": "sub_portable_test",
        "status": "completed",
        "stage": "done",
        "request": {"language": "zh-CN"},
        "video": {"title": "迁移测试", "author": "测试作者", "duration_seconds": 2},
        "selected_source": {
            "kind": "hard_ocr",
            "fusion_status": "independent_evidence",
        },
        "review": None,
        "sources": [
            {
                "kind": "hard_ocr",
                "artifact_source": "hard_ocr:videocr",
                "cue_count": 1,
            }
        ],
        "attempts": [],
        "artifacts": [
            {
                "kind": "subtitle_srt",
                "path": str(subtitle),
                "source": "hard_ocr:videocr",
                "owned_by_job": True,
                "selected": True,
            },
            {
                "kind": "source_video",
                "path": str(source_video),
                "owned_by_job": True,
                "selected": False,
            },
        ],
        "warnings": [],
        "error": None,
    }
    manifest_path = root / "manifest.json"
    write_json_atomic(manifest_path, manifest)
    project = initialize_content_project(manifest_path)
    project_path = Path(project["project_path"])
    package = project_path.parent / "wechat-article"
    package.mkdir()
    (package / "article.html").write_text("<p>可移植文章</p>", encoding="utf-8")
    return project_path


def _rewrite_bundle_manifest(bundle: Path, transform) -> None:
    temporary = bundle.with_suffix(".rewritten.zip")
    with (
        zipfile.ZipFile(bundle, "r") as source,
        zipfile.ZipFile(temporary, "w") as output,
    ):
        for item in source.infolist():
            payload = source.read(item.filename)
            if item.filename == "bundle.json":
                document = json.loads(payload.decode("utf-8"))
                transform(document)
                payload = json.dumps(document, ensure_ascii=False).encode("utf-8")
            output.writestr(item, payload)
    temporary.replace(bundle)


def test_export_verify_and_import_preserve_project_references(tmp_path: Path) -> None:
    job = tmp_path / "job"
    job.mkdir()
    project_path = _project(job)
    bundle = tmp_path / "portable.zip"

    exported = export_content_bundle(
        project_path,
        bundle,
        agent_name="codex",
        model_name="test-model",
    )
    verified = verify_content_bundle(bundle)

    assert exported["ok"] is True
    assert verified["valid"] is True
    assert exported["excluded"][0]["kind"] == "source_video"
    with zipfile.ZipFile(bundle) as archive:
        document = json.loads(archive.read("bundle.json").decode("utf-8"))
        assert all(item["path"].startswith("workspace/") for item in document["files"])
        assert not any(
            item["path"].endswith("source.mp4") for item in document["files"]
        )
        assert document["provenance"]["agent"] == {
            "name": "codex",
            "model": "test-model",
        }
        assert document["provenance"]["browser_adapter"]["version"] == "1"
        schema = json.loads(
            (ROOT / "schemas" / "portable-bundle.schema.json").read_text(
                encoding="utf-8"
            )
        )
        jsonschema.validate(document, schema)

    imported = import_content_bundle(bundle, tmp_path / "imported")
    imported_project = Path(imported["project_path"])
    assert imported["ok"] is True
    assert imported_project.is_file()
    assert imported["project_id"] == exported["project_id"]
    assert imported["integrity"]["valid"] is True
    assert (tmp_path / "imported" / "workspace" / "subtitle.ocr.srt").is_file()


def test_export_rejects_persisted_base64_or_browser_tokens(tmp_path: Path) -> None:
    job = tmp_path / "job"
    job.mkdir()
    project_path = _project(job)
    unsafe = project_path.parent / "unsafe.html"
    unsafe.write_text('<img src="data:image/png;base64,AAAA">', encoding="utf-8")

    try:
        export_content_bundle(project_path, tmp_path / "unsafe.zip")
    except ValueError as error:
        assert "secret scan failed" in str(error)
        assert "persisted_base64_image" in str(error)
    else:  # pragma: no cover
        raise AssertionError("transient image data must not enter a portable bundle")
    assert not (tmp_path / "unsafe.zip").exists()

    unsafe.unlink()
    try:
        export_content_bundle(
            project_path,
            tmp_path / "unsafe-provenance.zip",
            agent_name="https://example.test/?token=secret",
        )
    except ValueError as error:
        assert "agent name" in str(error)
        assert "url_token" in str(error)
    else:  # pragma: no cover
        raise AssertionError("bundle provenance must not contain URL tokens")


def test_verifier_rejects_path_traversal_archive(tmp_path: Path) -> None:
    bundle = tmp_path / "malicious.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr(
            "bundle.json",
            json.dumps(
                {
                    "schema_version": "video-content/portable-bundle-v1",
                    "bundle_id": "bundle_0123456789abcdef",
                    "project_id": "content_0123456789abcdef",
                    "project_entry": "workspace/project.json",
                    "files": [],
                }
            ),
        )
        archive.writestr("../escape.txt", "forbidden")

    report = verify_content_bundle(bundle)

    assert report["valid"] is False
    assert "unsafe_member" in {item["code"] for item in report["errors"]}


def test_bundle_cli_verify_returns_machine_readable_result(tmp_path: Path) -> None:
    job = tmp_path / "job"
    job.mkdir()
    project_path = _project(job)
    bundle = tmp_path / "portable.zip"
    export_content_bundle(project_path, bundle)

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "project_bundle.py"),
            "verify",
            str(bundle),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["valid"] is True


def test_verifier_rejects_tampered_identity_and_manifest_secrets(
    tmp_path: Path,
) -> None:
    job = tmp_path / "job"
    job.mkdir()
    project_path = _project(job)
    bundle = tmp_path / "portable.zip"
    export_content_bundle(project_path, bundle)

    _rewrite_bundle_manifest(
        bundle,
        lambda document: document.update({"bundle_id": "bundle_0000000000000000"}),
    )
    identity_result = verify_content_bundle(bundle)
    assert identity_result["valid"] is False
    assert "bundle_id" in {item["code"] for item in identity_result["errors"]}

    bundle.unlink()
    export_content_bundle(project_path, bundle)

    def add_secret(document: dict) -> None:
        document["provenance"]["agent"]["name"] = "https://example.test/?token=secret"

    _rewrite_bundle_manifest(bundle, add_secret)
    secret_result = verify_content_bundle(bundle)
    assert secret_result["valid"] is False
    assert any(
        item["code"] == "secret_detected" and item.get("path") == "bundle.json"
        for item in secret_result["errors"]
    )


def test_verifier_returns_invalid_for_malformed_manifest(tmp_path: Path) -> None:
    bundle = tmp_path / "malformed.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr(
            "bundle.json",
            json.dumps(
                {
                    "schema_version": "video-content/portable-bundle-v1",
                    "bundle_id": "bundle_0123456789abcdef",
                    "project_id": "content_fixture",
                    "project_entry": "workspace/project.json",
                    "files": [{}],
                    "excluded": [],
                    "secret_scan": {"passed": True},
                    "provenance": {},
                }
            ),
        )

    report = verify_content_bundle(bundle)

    assert report["valid"] is False
    assert "schema" in {item["code"] for item in report["errors"]}
