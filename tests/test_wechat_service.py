from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

import jsonschema
import pytest
from wechat_handoff_helpers import verified_observation

from video_content.content import content_save, transcript_save
from video_content.store import Store
from video_content.wechat import validate_draft_receipt, wechat_bind, wechat_prepare

ROOT = Path(__file__).resolve().parents[1]


def _png_bytes(width: int, height: int) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return (
            struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))
        )

    rows = b"".join(b"\x00" + (b"\x20\x40\x60" * width) for _ in range(height))
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
            chunk(b"IDAT", zlib.compress(rows)),
            chunk(b"IEND", b""),
        )
    )


def _ready_content(
    tmp_path: Path,
    *,
    image_size: tuple[int, int] = (1280, 720),
    second_image_size: tuple[int, int] | None = None,
) -> tuple[Store, str, str]:
    store = Store(tmp_path / "home")
    job, _ = store.create_job(
        source={"platform": "bilibili", "bvid": "BV1wechat", "page": 1},
        idempotency_key="bilibili_BV1wechat_p1",
        initial_stage="evidence",
        initial_status="running",
    )
    evidence_id = "evidence_wechat"
    store.save_document(
        job["job_id"],
        kind="evidence",
        document={
            "schema_version": "video-content/evidence-v1",
            "evidence_id": evidence_id,
            "job_id": job["job_id"],
            "source": job["source"],
            "observations": [],
            "artifact_refs": [],
            "decision": {},
            "created_at": "2026-08-17T00:00:00Z",
        },
        identifier_field="evidence_id",
        identifier_prefix="evidence",
    )
    transcript = transcript_save(
        store,
        job_id=job["job_id"],
        evidence_ids=[evidence_id],
        cues=[{"start_ms": 0, "end_ms": 1000, "text": "正文证据"}],
        text="正文证据",
        quality={"status": "verified"},
    )["transcript"]
    cover_path = tmp_path / "cover.png"
    cover_path.write_bytes(_png_bytes(*image_size))
    cover = store.put_artifact(
        job["job_id"], kind="video_cover", source_path=cover_path
    )
    blocks = [
        {
            "type": "image",
            "artifact_id": cover["artifact_id"],
            "source_kind": "video_cover",
        },
        {"type": "paragraph", "text": "正文证据"},
    ]
    if second_image_size is not None:
        second_path = tmp_path / "second-cover.png"
        second_path.write_bytes(_png_bytes(*second_image_size))
        second = store.put_artifact(
            job["job_id"], kind="video_cover", source_path=second_path
        )
        blocks.append(
            {
                "type": "image",
                "artifact_id": second["artifact_id"],
                "source_kind": "video_cover",
            }
        )
    content = content_save(
        store,
        job_id=job["job_id"],
        transcript_id=transcript["transcript_id"],
        carrier="wechat_article",
        document={
            "schema_version": "video-content/wechat-manuscript-v1",
            "title": "一篇待保存的测试文章",
            "summary": "测试摘要",
            "source": {
                "title": "测试视频",
                "creator": "测试作者",
                "canonical_url": "https://www.bilibili.com/video/BV1wechat",
            },
            "blocks": blocks,
        },
        audit={"status": "passed", "reviewed_by": "agent"},
    )["content"]
    return store, job["job_id"], content["content_id"]


def _observation(
    content_sha256: str,
    *,
    appmsgid: str = "100000721",
    schema_version: str = "video-content/wechat-editor-observation-v4",
    image_sizes: list[tuple[int, int]] | None = None,
) -> dict:
    selected_sizes = list(image_sizes or [(1280, 720)])
    observation = {
        "schema_version": schema_version,
        "started_at": "2026-08-17T08:00:00Z",
        "saved_at": "2026-08-17T08:02:00Z",
        "title": "一篇待保存的测试文章",
        "content_sha256": content_sha256,
        "draft_identity": {"appmsgid": appmsgid},
        "body_images": {
            "intended": len(selected_sizes),
            "items": [
                {
                    "visible": True,
                    "complete": True,
                    "natural_width": width,
                    "natural_height": height,
                    "width": width / 2,
                    "height": height / 2,
                    "host_class": "wechat",
                }
                for width, height in selected_sizes
            ],
            "local_path_markers_remaining": 0,
        },
        "cover": (
            {
                "selected": True,
                "crop_confirmed": True,
                "editor_visible_after_refresh": True,
                "rendered_width": 235,
                "rendered_height": 100,
                "list_thumbnail_read_back": True,
                "persistent_media_present": True,
                "crop_data_present": True,
            }
            if schema_version == "video-content/wechat-editor-observation-v4"
            else {"selected": True, "crop_confirmed": True}
        ),
        "summary": {"filled": True, "text": "测试摘要"},
        "content_checks": {
            "source_disclosure_present": True,
            "ending_present": True,
            "stock_cta_present": False,
        },
        "save": {"saved": True, "mode": "draft", "history_read_back": True},
        "refresh_readback": {
            "performed": True,
            "same_draft": True,
            "content_present": True,
        },
        "published": False,
    }
    if schema_version in {
        "video-content/wechat-editor-observation-v2",
        "video-content/wechat-editor-observation-v3",
        "video-content/wechat-editor-observation-v4",
    }:
        observation["creation_source"] = {
            "declared": True,
            "type": "ai_generated",
            "read_back": True,
        }
    return observation


def test_wechat_prepare_requires_explicit_authorization_and_persists_no_payload(
    tmp_path: Path,
) -> None:
    store, job_id, content_id = _ready_content(tmp_path)
    with pytest.raises(PermissionError, match="explicit authorization"):
        wechat_prepare(
            store,
            job_id=job_id,
            content_id=content_id,
            authorized=False,
            save_draft=True,
        )
    result = wechat_prepare(
        store,
        job_id=job_id,
        content_id=content_id,
        authorized=True,
        save_draft=True,
        copy_to_clipboard=False,
    )
    assert result["authorization"] == {"save_draft": True, "publish": False}
    assert result["required_declarations"] == {}
    assert result["observation_schema"] == "video-content/wechat-editor-observation-v4"
    assert len(result["expected_images"]) == 1
    assert result["expected_images"][0]["source_kind"] == "video_cover"
    assert result["expected_images"][0]["pixel_width"] == 1280
    assert result["expected_images"][0]["pixel_height"] == 720
    assert result["clipboard"]["payload_persisted"] is False
    assert "html" not in result["clipboard"]
    assert Path(result["article_html"]).is_file()
    assert result["job"]["stage"] == "handoff"


def test_wechat_bind_requires_refresh_readback_and_creates_one_receipt(
    tmp_path: Path,
) -> None:
    store, job_id, content_id = _ready_content(tmp_path)
    prepared = wechat_prepare(
        store,
        job_id=job_id,
        content_id=content_id,
        authorized=True,
        save_draft=True,
    )
    observation = _observation(prepared["content_sha256"])
    observation.pop("creation_source")
    schema = json.loads(
        (ROOT / "schemas" / "wechat-editor-observation.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(observation, schema)
    result = wechat_bind(
        store,
        job_id=job_id,
        content_id=content_id,
        observation=verified_observation(store, job_id, content_id),
    )
    receipt = result["receipt"]
    assert receipt["schema_version"] == "video-content/draft-receipt-v1"
    assert receipt["published"] is False
    assert receipt["draft_identity"]["appmsgid"] == "100000721"
    assert result["validation"]["valid"] is True
    assert result["job"]["status"] == "completed"
    assert (
        validate_draft_receipt(store, job_id=job_id, receipt_id=receipt["receipt_id"])[
            "valid"
        ]
        is True
    )
    with pytest.raises(ValueError, match="already has"):
        wechat_bind(
            store,
            job_id=job_id,
            content_id=content_id,
            observation=observation,
        )


def test_image_bearing_wechat_draft_requires_aspect_aware_observation(
    tmp_path: Path,
) -> None:
    store, job_id, content_id = _ready_content(tmp_path)
    prepared = wechat_prepare(
        store,
        job_id=job_id,
        content_id=content_id,
        authorized=True,
        save_draft=True,
    )
    with pytest.raises(ValueError, match="observation-v4"):
        wechat_bind(
            store,
            job_id=job_id,
            content_id=content_id,
            observation=_observation(
                prepared["content_sha256"],
                schema_version="video-content/wechat-editor-observation-v1",
            ),
        )


def test_wechat_observation_rejects_hidden_cover_preview_false_positive(
    tmp_path: Path,
) -> None:
    store, job_id, content_id = _ready_content(tmp_path)
    prepared = wechat_prepare(
        store,
        job_id=job_id,
        content_id=content_id,
        authorized=True,
        save_draft=True,
    )
    observation = _observation(prepared["content_sha256"])
    observation["cover"].update(
        {
            "selected": True,
            "editor_visible_after_refresh": False,
            "rendered_width": 0,
            "rendered_height": 0,
        }
    )

    with pytest.raises(ValueError, match="editor_visible_after_refresh"):
        wechat_bind(
            store,
            job_id=job_id,
            content_id=content_id,
            observation=observation,
        )


def test_wechat_observation_requires_draft_list_cover_readback(
    tmp_path: Path,
) -> None:
    store, job_id, content_id = _ready_content(tmp_path)
    prepared = wechat_prepare(
        store,
        job_id=job_id,
        content_id=content_id,
        authorized=True,
        save_draft=True,
    )
    observation = _observation(prepared["content_sha256"])
    observation["cover"]["list_thumbnail_read_back"] = False

    with pytest.raises(ValueError, match="list_thumbnail_read_back"):
        wechat_bind(
            store,
            job_id=job_id,
            content_id=content_id,
            observation=observation,
        )


def test_wechat_observation_rejects_stretched_body_image(tmp_path: Path) -> None:
    store, job_id, content_id = _ready_content(tmp_path)
    prepared = wechat_prepare(
        store,
        job_id=job_id,
        content_id=content_id,
        authorized=True,
        save_draft=True,
    )
    observation = _observation(prepared["content_sha256"])
    observation["body_images"]["items"][0]["height"] = 300

    with pytest.raises(ValueError, match="aspect ratio"):
        wechat_bind(
            store,
            job_id=job_id,
            content_id=content_id,
            observation=observation,
        )


def test_wechat_observation_rejects_pre_stretched_input_even_when_rendering_is_consistent(
    tmp_path: Path,
) -> None:
    store, job_id, content_id = _ready_content(tmp_path)
    prepared = wechat_prepare(
        store,
        job_id=job_id,
        content_id=content_id,
        authorized=True,
        save_draft=True,
    )
    observation = _observation(prepared["content_sha256"], image_sizes=[(1000, 1000)])

    with pytest.raises(ValueError, match="Content Artifact"):
        wechat_bind(
            store,
            job_id=job_id,
            content_id=content_id,
            observation=observation,
        )


def test_wechat_observation_binds_image_geometry_in_content_order(
    tmp_path: Path,
) -> None:
    store, job_id, content_id = _ready_content(
        tmp_path, image_size=(1280, 720), second_image_size=(800, 800)
    )
    prepared = wechat_prepare(
        store,
        job_id=job_id,
        content_id=content_id,
        authorized=True,
        save_draft=True,
    )
    observation = _observation(
        prepared["content_sha256"], image_sizes=[(800, 800), (1280, 720)]
    )

    with pytest.raises(ValueError, match="image 1.*Content Artifact"):
        wechat_bind(
            store,
            job_id=job_id,
            content_id=content_id,
            observation=observation,
        )


def test_wechat_observation_accepts_preserved_vertical_image_ratio(
    tmp_path: Path,
) -> None:
    store, job_id, content_id = _ready_content(tmp_path, image_size=(1080, 1920))
    prepared = wechat_prepare(
        store,
        job_id=job_id,
        content_id=content_id,
        authorized=True,
        save_draft=True,
    )
    _observation(prepared["content_sha256"], image_sizes=[(1080, 1920)])

    result = wechat_bind(
        store,
        job_id=job_id,
        content_id=content_id,
        observation=verified_observation(store, job_id, content_id),
    )

    assert result["validation"]["valid"] is True


def test_wechat_profile_requires_ai_creation_source_and_refresh_readback(
    tmp_path: Path,
) -> None:
    store, job_id, content_id = _ready_content(tmp_path)
    store.save_profile(
        {
            "profile_id": "daily",
            "source": {
                "platform": "bilibili",
                "kind": "watch_later",
                "account_profile_alias": "fixture-browser",
            },
            "carrier": "wechat_article",
            "baseline": {},
            "settings": {
                "publish": False,
                "gpu_parallelism": 1,
                "wechat_creation_source": "ai_generated",
            },
            "enabled": True,
        }
    )
    job = store.get_job(job_id)
    job["profile_id"] = "daily"
    store.write_job(job)
    prepared = wechat_prepare(
        store,
        job_id=job_id,
        content_id=content_id,
        authorized=True,
        save_draft=True,
    )
    assert prepared["required_declarations"] == {"creation_source": "ai_generated"}
    with pytest.raises(ValueError, match="observation-v4"):
        wechat_bind(
            store,
            job_id=job_id,
            content_id=content_id,
            observation=_observation(
                prepared["content_sha256"],
                schema_version="video-content/wechat-editor-observation-v1",
            ),
        )
    invalid = _observation(prepared["content_sha256"])
    invalid["creation_source"]["read_back"] = False
    with pytest.raises(ValueError, match="creation source"):
        wechat_bind(
            store,
            job_id=job_id,
            content_id=content_id,
            observation=invalid,
        )


def test_wechat_revision_supersedes_receipt_without_creating_a_second_draft(
    tmp_path: Path,
) -> None:
    store, job_id, content_id = _ready_content(tmp_path)
    wechat_prepare(
        store,
        job_id=job_id,
        content_id=content_id,
        authorized=True,
        save_draft=True,
    )
    first = wechat_bind(
        store,
        job_id=job_id,
        content_id=content_id,
        observation=verified_observation(store, job_id, content_id),
    )["receipt"]
    original = next(
        item
        for item in store.list_artifacts(job_id, kind="content")
        if item.get("metadata", {}).get("content_id") == content_id
    )
    original_content = store.read_json_artifact(job_id, original["artifact_id"])
    replacement_document = json.loads(
        json.dumps(original_content["document"], ensure_ascii=False)
    )
    replacement_document["summary"] = "修订后的测试摘要"
    replacement_document["blocks"].append(
        {"type": "paragraph", "text": "补回原视频中的专业细节。"}
    )
    replacement = content_save(
        store,
        job_id=job_id,
        transcript_id=original_content["transcript_id"],
        carrier="wechat_article",
        document=replacement_document,
        audit={"status": "passed", "reviewed_by": "agent"},
    )["content"]
    revision = wechat_prepare(
        store,
        job_id=job_id,
        content_id=replacement["content_id"],
        authorized=True,
        save_draft=True,
        replace_existing_draft=True,
    )
    assert revision["draft_target"] == {
        "mode": "replace_existing",
        "appmsgid": "100000721",
        "supersedes_receipt_id": first["receipt_id"],
    }
    with pytest.raises(ValueError, match="same appmsgid"):
        wechat_bind(
            store,
            job_id=job_id,
            content_id=replacement["content_id"],
            observation=_observation(revision["content_sha256"], appmsgid="100000999"),
            supersedes_receipt_id=first["receipt_id"],
        )
    second = wechat_bind(
        store,
        job_id=job_id,
        content_id=replacement["content_id"],
        observation=verified_observation(store, job_id, replacement["content_id"]),
        supersedes_receipt_id=first["receipt_id"],
    )["receipt"]
    assert second["supersedes_receipt_id"] == first["receipt_id"]
    assert second["draft_identity"]["appmsgid"] == first["draft_identity"]["appmsgid"]
    old_validation = validate_draft_receipt(
        store, job_id=job_id, receipt_id=first["receipt_id"]
    )
    assert old_validation["valid"] is False
    assert any("superseded" in error for error in old_validation["errors"])
    assert (
        validate_draft_receipt(store, job_id=job_id, receipt_id=second["receipt_id"])[
            "valid"
        ]
        is True
    )


def test_wechat_platform_only_revision_can_supersede_same_content_receipt(
    tmp_path: Path,
) -> None:
    store, job_id, content_id = _ready_content(tmp_path)
    wechat_prepare(
        store,
        job_id=job_id,
        content_id=content_id,
        authorized=True,
        save_draft=True,
    )
    first = wechat_bind(
        store,
        job_id=job_id,
        content_id=content_id,
        observation=verified_observation(store, job_id, content_id),
    )["receipt"]

    repair = wechat_prepare(
        store,
        job_id=job_id,
        content_id=content_id,
        authorized=True,
        save_draft=True,
        replace_existing_draft=True,
    )
    second = wechat_bind(
        store,
        job_id=job_id,
        content_id=content_id,
        observation=verified_observation(store, job_id, content_id),
        supersedes_receipt_id=first["receipt_id"],
    )["receipt"]

    assert repair["draft_target"]["appmsgid"] == "100000721"
    assert second["receipt_id"] != first["receipt_id"]
    assert second["content_id"] == first["content_id"]
    assert second["supersedes_receipt_id"] == first["receipt_id"]
    assert (
        validate_draft_receipt(store, job_id=job_id, receipt_id=second["receipt_id"])[
            "valid"
        ]
        is True
    )


def test_wechat_bind_can_backfill_receipt_for_completed_content_job(
    tmp_path: Path,
) -> None:
    store, job_id, content_id = _ready_content(tmp_path)
    wechat_prepare(
        store,
        job_id=job_id,
        content_id=content_id,
        authorized=True,
        save_draft=True,
    )
    completed = store.get_job(job_id)
    completed["stage"] = "completed"
    completed["status"] = "completed"
    store.write_job(completed)

    result = wechat_bind(
        store,
        job_id=job_id,
        content_id=content_id,
        observation=verified_observation(store, job_id, content_id),
    )

    assert result["validation"]["valid"] is True
    assert result["receipt"]["published"] is False
    assert result["job"]["stage"] == "completed"
    assert result["job"]["status"] == "completed"


def test_wechat_bind_rejects_secret_fields_publish_and_missing_refresh(
    tmp_path: Path,
) -> None:
    store, job_id, content_id = _ready_content(tmp_path)
    prepared = wechat_prepare(
        store,
        job_id=job_id,
        content_id=content_id,
        authorized=True,
        save_draft=True,
    )
    observation = _observation(prepared["content_sha256"])
    observation["refresh_readback"]["performed"] = False
    with pytest.raises(ValueError, match="refresh readback"):
        wechat_bind(
            store, job_id=job_id, content_id=content_id, observation=observation
        )
    observation = _observation(prepared["content_sha256"])
    observation["url_token"] = "forbidden"
    with pytest.raises(ValueError, match="secret-like"):
        wechat_bind(
            store, job_id=job_id, content_id=content_id, observation=observation
        )
    observation = _observation(prepared["content_sha256"])
    observation["published"] = True
    with pytest.raises(ValueError, match="never publishes"):
        wechat_bind(
            store, job_id=job_id, content_id=content_id, observation=observation
        )
