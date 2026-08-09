import json
import subprocess
import sys
from pathlib import Path

from scripts.validate_wechat_package import validate_package

ROOT = Path(__file__).parents[1]


def _write_valid_package(root: Path) -> None:
    assets = root / "assets"
    assets.mkdir(parents=True)
    (assets / "01-cover.jpg").write_bytes(b"cover")
    (assets / "02-diagram.png").write_bytes(b"diagram")
    (root / "article.md").write_text("# Article\n", encoding="utf-8")
    (root / "image-import-checklist.md").write_text(
        "# Images\n\n1. `assets/01-cover.jpg`\n2. `assets/02-diagram.png`\n",
        encoding="utf-8",
    )
    body = (
        '<section><p data-local-image-slot="assets/01-cover.jpg">'
        "<span>assets/01-cover.jpg</span></p><p>Body</p>"
        '<p data-local-image-slot="assets/02-diagram.png">'
        "<span>assets/02-diagram.png</span></p></section>"
    )
    (root / "article.html").write_text(body, encoding="utf-8")
    (root / "article-preview.html").write_text(
        "<!doctype html><html><body><p>复制排版正文；本地图片仍需按清单插入</p>"
        + body
        + "</body></html>",
        encoding="utf-8",
    )


def _error_codes(report: dict[str, object]) -> set[str]:
    return {item["code"] for item in report["errors"]}


def test_validator_accepts_portable_minimal_image_package(tmp_path: Path) -> None:
    _write_valid_package(tmp_path)

    report = validate_package(tmp_path)

    assert report["valid"] is True
    assert report["counts"] == {
        "markers": 2,
        "checklist_entries": 2,
        "clean_img_elements": 0,
    }
    assert report["errors"] == []
    assert report["warnings"] == []


def test_validator_rejects_marker_asset_and_checklist_drift(tmp_path: Path) -> None:
    _write_valid_package(tmp_path)
    (tmp_path / "assets" / "02-diagram.png").unlink()
    (tmp_path / "image-import-checklist.md").write_text(
        "# Images\n\n1. `assets/02-diagram.png`\n2. `assets/01-cover.jpg`\n",
        encoding="utf-8",
    )

    report = validate_package(tmp_path)

    assert report["valid"] is False
    assert {"checklist_order_mismatch", "missing_image_asset"} <= _error_codes(report)


def test_validator_rejects_nonportable_and_decorative_shell(tmp_path: Path) -> None:
    _write_valid_package(tmp_path)
    body = (tmp_path / "article.html").read_text(encoding="utf-8")
    body = (
        "<html><body><u>underline</u><p>点赞 / 在看 / 转发</p>"
        '<img src="data:image/png;base64,AAAA">'
        "<p>C:/Users/example/image.png</p>" + body + "</body></html>"
    )
    (tmp_path / "article.html").write_text(body, encoding="utf-8")

    report = validate_package(tmp_path)

    assert report["valid"] is False
    assert {
        "clean_html_has_preview_shell",
        "underline_emphasis",
        "stock_engagement_shell",
        "persisted_base64_image",
        "nonportable_image_source",
        "absolute_local_path",
    } <= _error_codes(report)


def test_validator_rejects_misleading_preview_copy(tmp_path: Path) -> None:
    _write_valid_package(tmp_path)
    body = (tmp_path / "article.html").read_text(encoding="utf-8")
    (tmp_path / "article-preview.html").write_text(
        "<!doctype html><html><body><button>复制到公众号</button>"
        "<p>可直接粘贴</p>" + body + "</body></html>",
        encoding="utf-8",
    )

    report = validate_package(tmp_path)

    assert report["valid"] is False
    assert {
        "preview_copy_label",
        "preview_image_warning",
        "misleading_preview_copy",
    } <= _error_codes(report)


def test_validator_cli_returns_agent_readable_json(tmp_path: Path) -> None:
    _write_valid_package(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "validate_wechat_package.py"),
            str(tmp_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0
    report = json.loads(completed.stdout)
    assert report["schema_version"] == "video-content/wechat-package-validation-v1"
    assert report["valid"] is True
    assert str(tmp_path) not in completed.stdout


def test_validator_is_discoverable_from_skills_and_public_docs() -> None:
    script_name = "scripts/validate_wechat_package.py"
    documents = [
        ROOT / ".agents" / "skills" / "wechat-draft-handoff" / "SKILL.md",
        ROOT
        / ".agents"
        / "skills"
        / "video-to-content"
        / "references"
        / "wechat-article.md",
        ROOT / "README.md",
        ROOT / "docs" / "content-workflow.md",
        ROOT / "docs" / "reproducibility.md",
    ]

    for document in documents:
        assert script_name in document.read_text(encoding="utf-8")

    case = (ROOT / "docs" / "cases" / "BV1jxREBSEUv-wechat-draft-handoff.md").read_text(
        encoding="utf-8"
    )
    assert "稳定文章标识" in case
    assert "辅助节点" in case
    assert "source_author" in case
    assert "errors: 0" in case
