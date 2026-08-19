from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from video_content.content import content_save, transcript_save
from video_content.store import Store
from video_content.wechat import validate_draft_receipt, wechat_bind, wechat_prepare

ROOT = Path(__file__).resolve().parents[1]


def _ready_content(tmp_path: Path) -> tuple[Store, str, str]:
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
    cover_path = tmp_path / "cover.jpg"
    cover_path.write_bytes(b"cover")
    cover = store.put_artifact(
        job["job_id"], kind="video_cover", source_path=cover_path
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
            "blocks": [
                {
                    "type": "image",
                    "artifact_id": cover["artifact_id"],
                    "source_kind": "video_cover",
                },
                {"type": "paragraph", "text": "正文证据"},
            ],
        },
        audit={"status": "passed", "reviewed_by": "agent"},
    )["content"]
    return store, job["job_id"], content["content_id"]


def _observation(content_sha256: str) -> dict:
    return {
        "schema_version": "video-content/wechat-editor-observation-v1",
        "started_at": "2026-08-17T08:00:00Z",
        "saved_at": "2026-08-17T08:02:00Z",
        "title": "一篇待保存的测试文章",
        "content_sha256": content_sha256,
        "draft_identity": {"appmsgid": "100000721"},
        "body_images": {
            "intended": 1,
            "items": [
                {
                    "visible": True,
                    "complete": True,
                    "natural_width": 1280,
                    "width": 640,
                    "height": 360,
                    "host_class": "wechat",
                }
            ],
            "local_path_markers_remaining": 0,
        },
        "cover": {"selected": True, "crop_confirmed": True},
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
        observation=observation,
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


def test_wechat_bind_can_backfill_receipt_for_completed_content_job(
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
    completed = store.get_job(job_id)
    completed["stage"] = "completed"
    completed["status"] = "completed"
    store.write_job(completed)

    result = wechat_bind(
        store,
        job_id=job_id,
        content_id=content_id,
        observation=_observation(prepared["content_sha256"]),
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
