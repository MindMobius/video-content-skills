from __future__ import annotations

import copy
import hashlib
import io
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from test_wechat_service import _ready_content

from video_content.content import content_save, get_content
from video_content.wechat import wechat_prepare
from video_content.wechat_docx import (
    WP,
    A,
    R,
    W,
    build_docx,
    inspect_bound_docx,
    manuscript_parts,
    text_digest,
)


def test_docx_is_deterministic_and_embeds_exact_images_with_native_aspect(tmp_path):
    store, job, content = _ready_content(
        tmp_path, image_size=(720, 1280), second_image_size=(1000, 1000)
    )
    first = wechat_prepare(
        store, job_id=job, content_id=content, authorized=True, save_draft=True
    )
    second = wechat_prepare(
        store, job_id=job, content_id=content, authorized=True, save_draft=True
    )
    docx = first["document_import"]
    assert docx == second["document_import"]
    assert docx["validated"] is True
    assert docx["validation_scope"] == "local_package_only"
    with zipfile.ZipFile(docx["path"]) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
        rels = {
            r.attrib["Id"]: r.attrib["Target"]
            for r in ET.fromstring(archive.read("word/_rels/document.xml.rels"))
        }
        blips = list(root.iter(f"{{{A}}}blip"))
        extents = list(root.iter(f"{{{WP}}}extent"))
        assert len(blips) == 2
        for blip, extent, expected in zip(blips, extents, docx["images"]):
            data = archive.read("word/" + rels[blip.attrib[f"{{{R}}}embed"]])
            assert hashlib.sha256(data).hexdigest() == expected["sha256"]
            assert int(extent.attrib["cx"]) / int(extent.attrib["cy"]) == pytest.approx(
                expected["pixel_width"] / expected["pixel_height"], rel=0.001
            )
        text = "".join(x.text or "" for x in root.iter(f"{{{W}}}t"))
        assert "原始内容：" in text
        assert "正文证据" in text
        assert text_digest(text) == docx["text_sha256"]
        expected_parts = {
            "[Content_Types].xml",
            "_rels/.rels",
            "docProps/core.xml",
            "docProps/app.xml",
            "word/styles.xml",
            "word/settings.xml",
            "word/webSettings.xml",
            "word/fontTable.xml",
            "word/numbering.xml",
            "word/theme/theme1.xml",
        }
        assert expected_parts <= set(archive.namelist())
        package_rels = ET.fromstring(archive.read("_rels/.rels"))
        assert {r.attrib["Target"] for r in package_rels} >= {
            "word/document.xml",
            "docProps/core.xml",
            "docProps/app.xml",
        }
        document_rels = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
        assert {r.attrib["Target"] for r in document_rels} >= {
            "styles.xml",
            "settings.xml",
            "webSettings.xml",
            "fontTable.xml",
            "theme/theme1.xml",
            "numbering.xml",
        }


def test_no_invented_png_count_limit_or_text_block_loss(tmp_path):
    store, job, cid = _ready_content(tmp_path)
    content = get_content(store, job, cid)
    doc = copy.deepcopy(content["document"])
    image = copy.deepcopy(doc["blocks"][0])
    doc["blocks"] = [
        image,
        {"type": "heading", "text": "主题"},
        {"type": "list", "items": ["列表甲", "列表乙"]},
        {"type": "quote", "text": "引文"},
        {"type": "paragraph", "text": "结尾"},
    ]
    # Repeating bytes tests DOCX's image transport, not editorial frame selection.
    doc["blocks"].extend(copy.deepcopy(image) for _ in range(7))
    candidate = {**content, "document": doc}
    result = build_docx(store, job, candidate, tmp_path / "eight-images.docx")
    assert len(result["images"]) == 8
    parts = manuscript_parts(doc)
    assert any(x.get("text") == "列表乙" for x in parts)
    with zipfile.ZipFile(result["path"]) as archive:
        assert (
            len(
                ET.fromstring(archive.read("word/document.xml")).findall(
                    f".//{{{A}}}blip"
                )
            )
            == 8
        )
        # Reused image bytes may be deduplicated, never their document occurrences.
        assert len([n for n in archive.namelist() if n.startswith("word/media/")]) == 1


def test_preexisting_variant_is_not_silently_overwritten(tmp_path):
    store, job, cid = _ready_content(tmp_path)
    path = tmp_path / "article-import.docx"
    path.write_bytes(b"previous experiment")
    with pytest.raises(ValueError, match="differs from canonical"):
        build_docx(store, job, get_content(store, job, cid), path)
    assert path.read_bytes() == b"previous experiment"


def test_pending_upload_cannot_be_changed_by_removing_content_images(tmp_path):
    store, job, cid = _ready_content(tmp_path, second_image_size=(640, 360))
    wechat_prepare(store, job_id=job, content_id=cid, authorized=True, save_draft=True)
    original = get_content(store, job, cid)
    doc = copy.deepcopy(original["document"])
    doc["blocks"].pop()
    changed = content_save(
        store,
        job_id=job,
        transcript_id=original["transcript_id"],
        carrier="wechat_article",
        document=doc,
        audit={"status": "passed", "reviewed_by": "agent"},
    )["content"]
    with pytest.raises(ValueError, match="different Content/transport"):
        wechat_prepare(
            store,
            job_id=job,
            content_id=changed["content_id"],
            authorized=True,
            save_draft=True,
        )


def _rewrite_package(path, transform):
    with zipfile.ZipFile(path) as source:
        parts = {n: source.read(n) for n in source.namelist()}
    transform(parts)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    path.write_bytes(out.getvalue())
    return hashlib.sha256(out.getvalue()).hexdigest()


def test_library_package_is_repeatable_and_reopens_in_independent_consumer(tmp_path):
    from docx import Document

    store, job, cid = _ready_content(tmp_path, image_size=(720, 1280))
    content = get_content(store, job, cid)
    a = build_docx(store, job, content, tmp_path / "a.docx")
    b = build_docx(store, job, content, tmp_path / "b.docx")
    assert a["sha256"] == b["sha256"]
    reopened = Document(a["path"])
    assert len(reopened.inline_shapes) == 1
    assert text_digest("".join(p.text for p in reopened.paragraphs)) == a["text_sha256"]
    shape = reopened.inline_shapes[0]
    assert shape.width / shape.height == pytest.approx(720 / 1280, rel=0.001)
    assert shape.height < reopened.sections[0].page_height


def test_prepare_resumes_legacy_bytes_without_running_new_generator(
    tmp_path, monkeypatch
):
    store, job, cid = _ready_content(tmp_path)
    first = wechat_prepare(
        store, job_id=job, content_id=cid, authorized=True, save_draft=True
    )
    path = Path(first["document_import"]["path"])

    def make_minimal(parts):
        rels = ET.fromstring(parts["word/_rels/document.xml.rels"])
        for rel in list(rels):
            if rel.get("Type") != f"{R}/image":
                rels.remove(rel)
        parts["word/_rels/document.xml.rels"] = ET.tostring(rels)
        for name in list(parts):
            if name not in (
                "[Content_Types].xml",
                "_rels/.rels",
                "word/document.xml",
                "word/_rels/document.xml.rels",
            ) and not name.startswith("word/media/"):
                del parts[name]

    digest = _rewrite_package(path, make_minimal)
    checkpoint_path = store.job_dir(job) / "work" / "wechat-handoff.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint.update(docx_sha256=digest, phase="import_pending", import_attempts=2)
    checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")
    before = path.read_bytes()
    monkeypatch.setattr(
        "video_content.wechat.build_docx",
        lambda *_: pytest.fail("must not regenerate a bound transport"),
    )
    second = wechat_prepare(
        store, job_id=job, content_id=cid, authorized=True, save_draft=True
    )
    assert second["document_import"]["sha256"] == digest
    assert second["checkpoint"] == {
        **checkpoint,
        "next_action": "observe_same_editor_do_not_upload_again",
        "mutation_permitted": False,
    }
    assert path.read_bytes() == before


@pytest.mark.parametrize("missing", [True, False])
def test_bound_transport_loss_or_tampering_never_regenerates(
    tmp_path, monkeypatch, missing
):
    store, job, cid = _ready_content(tmp_path)
    result = wechat_prepare(
        store, job_id=job, content_id=cid, authorized=True, save_draft=True
    )
    path = Path(result["document_import"]["path"])
    cp = (store.job_dir(job) / "work" / "wechat-handoff.json").read_bytes()
    if missing:
        path.unlink()
    else:
        path.write_bytes(b"unapproved replacement")
    monkeypatch.setattr(
        "video_content.wechat.build_docx",
        lambda *_: pytest.fail("must not reset a bound transport"),
    )
    with pytest.raises(ValueError, match="Bound DOCX"):
        wechat_prepare(
            store, job_id=job, content_id=cid, authorized=True, save_draft=True
        )
    assert (store.job_dir(job) / "work" / "wechat-handoff.json").read_bytes() == cp
    assert path.exists() is not missing


@pytest.mark.parametrize(
    "change, message",
    [
        ("position", "position drift"),
        ("shape", "aspect drift"),
        ("external", "external relationships"),
    ],
)
def test_package_audit_rejects_structural_drift_even_with_matching_file_hash(
    tmp_path, change, message
):
    store, job, cid = _ready_content(tmp_path)
    content = get_content(store, job, cid)
    path = tmp_path / "tampered.docx"
    build_docx(store, job, content, path)

    def alter(parts):
        root = ET.fromstring(parts["word/document.xml"])
        if change == "position":
            body = root.find(f"{{{W}}}body")
            picture = next(p for p in body if p.find(f".//{{{A}}}blip") is not None)
            body.remove(picture)
            body.insert(len(body) - 1, picture)
        elif change == "shape":
            root.find(f".//{{{A}}}xfrm/{{{A}}}ext").set("cy", "1")
        else:
            rels = ET.fromstring(parts["word/_rels/document.xml.rels"])
            rels[0].set("TargetMode", "External")
            parts["word/_rels/document.xml.rels"] = ET.tostring(rels)
        parts["word/document.xml"] = ET.tostring(root)

    digest = _rewrite_package(path, alter)
    with pytest.raises(ValueError, match=message):
        inspect_bound_docx(store, job, content, path, expected_sha256=digest)
