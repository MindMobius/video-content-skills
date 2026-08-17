from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import jsonschema

from scripts.validate_wechat_package import validate_package
from video_content.wechat_renderer import render_wechat_package

ROOT = Path(__file__).resolve().parents[1]


def _write_manuscript(root: Path) -> Path:
    (root / "cover.jpg").write_bytes(b"original cover")
    (root / "frame.png").write_bytes(b"source frame")
    manuscript = {
        "schema_version": "video-content/wechat-manuscript-v1",
        "title": "不是把长视频缩短，而是把论证重新搭起来",
        "summary": "一篇保留论点、依据与限定条件的载体转换示例。",
        "source": {
            "title": "测试视频",
            "creator": "测试创作者",
            "canonical_url": "https://www.bilibili.com/video/BV1fixture",
        },
        "blocks": [
            {"type": "image", "path": "cover.jpg", "source_kind": "video_cover"},
            {
                "type": "lead",
                "text": "我真正想解决的，不是把一小时压成三分钟。",
            },
            {"type": "heading", "text": "先把问题说清楚"},
            {
                "type": "paragraph",
                "text": "载体变化以后，内容结构也应该变化，但论点与限定条件不能丢。",
            },
            {
                "type": "image",
                "path": "frame.png",
                "source_kind": "video_frame",
                "timestamp_ms": 42000,
                "caption": "原视频 00:42 画面",
            },
            {
                "type": "list",
                "items": ["先固定证据", "再重构结构", "最后审计忠实度"],
            },
            {"type": "key_point", "text": "形式可以重写，证据不能失踪。"},
        ],
    }
    path = root / "manuscript.json"
    path.write_text(json.dumps(manuscript, ensure_ascii=False), encoding="utf-8")
    return path


def test_wechat_manuscript_schema_accepts_renderer_fixture(tmp_path: Path) -> None:
    manuscript_path = _write_manuscript(tmp_path)
    document = json.loads(manuscript_path.read_text(encoding="utf-8"))
    schema = json.loads(
        (ROOT / "schemas" / "wechat-manuscript.schema.json").read_text(encoding="utf-8")
    )

    jsonschema.validate(document, schema)


def test_renderer_builds_restrained_portable_package(tmp_path: Path) -> None:
    manuscript_path = _write_manuscript(tmp_path)
    output = tmp_path / "wechat"

    result = render_wechat_package(manuscript_path, output)
    validation = validate_package(output)

    assert result["ok"] is True
    assert result["reused"] is False
    assert validation["valid"] is True
    assert validation["counts"] == {
        "markers": 2,
        "checklist_entries": 2,
        "clean_img_elements": 0,
    }
    clean_html = (output / "article.html").read_text(encoding="utf-8")
    assert "data-source-disclosure" in clean_html
    assert "data-local-image-slot" in clean_html
    assert "assets/01-cover.jpg" in clean_html
    assert "assets/02-frame.png" in clean_html
    assert "<img" not in clean_html
    assert "underline" not in clean_html.lower()
    assert str(tmp_path) not in clean_html
    assert "这个视频" not in clean_html
    assert (output / "assets" / "01-cover.jpg").read_bytes() == b"original cover"

    manifest = json.loads((output / "render-manifest.json").read_text(encoding="utf-8"))
    assert manifest["renderer"]["theme"] == "restrained-editorial"
    assert manifest["policy"]["image_sources"] == ["video_cover", "video_frame"]
    assert manifest["policy"]["underlines"] == 0


def test_renderer_is_idempotent_but_refuses_mismatched_output(tmp_path: Path) -> None:
    manuscript_path = _write_manuscript(tmp_path)
    output = tmp_path / "wechat"
    render_wechat_package(manuscript_path, output)

    reused = render_wechat_package(manuscript_path, output)
    assert reused["reused"] is True

    document = json.loads(manuscript_path.read_text(encoding="utf-8"))
    document["title"] = "另一篇文章"
    manuscript_path.write_text(
        json.dumps(document, ensure_ascii=False), encoding="utf-8"
    )
    try:
        render_wechat_package(manuscript_path, output)
    except ValueError as error:
        assert "different manuscript" in str(error)
    else:  # pragma: no cover
        raise AssertionError("mismatched output must not be overwritten")


def test_renderer_refuses_to_reuse_tampered_output(tmp_path: Path) -> None:
    manuscript_path = _write_manuscript(tmp_path)
    output = tmp_path / "wechat"
    render_wechat_package(manuscript_path, output)
    (output / "article.html").write_text("tampered", encoding="utf-8")

    try:
        render_wechat_package(manuscript_path, output)
    except ValueError as error:
        assert "integrity check" in str(error)
        assert "article.html" in str(error)
    else:  # pragma: no cover
        raise AssertionError("tampered render output must not be reused")


def test_renderer_rejects_non_video_article_images(tmp_path: Path) -> None:
    manuscript_path = _write_manuscript(tmp_path)
    document = json.loads(manuscript_path.read_text(encoding="utf-8"))
    document["blocks"][0]["source_kind"] = "generated"
    manuscript_path.write_text(
        json.dumps(document, ensure_ascii=False), encoding="utf-8"
    )

    try:
        render_wechat_package(manuscript_path, tmp_path / "wechat")
    except ValueError as error:
        assert "original video cover" in str(error)
    else:  # pragma: no cover
        raise AssertionError(
            "generated image must be rejected by the baseline renderer"
        )


def test_renderer_cli_returns_machine_readable_validation(tmp_path: Path) -> None:
    manuscript_path = _write_manuscript(tmp_path)
    output = tmp_path / "wechat"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "render_wechat_article.py"),
            str(manuscript_path),
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["ok"] is True
    assert report["validation"]["valid"] is True
