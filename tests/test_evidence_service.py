from __future__ import annotations

from pathlib import Path

import pytest

from video_content import evidence as evidence_module
from video_content.evidence import evidence_start, source_inspect
from video_content.store import Store


class FakeClient:
    platform = "bilibili"

    def video(self, url: str, *, page=None):
        return {
            "bvid": "BV1fake",
            "title": "测试视频",
            "duration": "60",
            "page": str(page or 1),
        }

    def subtitles(self, url: str, *, lang="ai-zh", page=None):
        return [{"index": 1, "from": "1.00s", "to": "2.50s", "content": "平台字幕"}]

    def download(self, *args, **kwargs):
        raise AssertionError("download should not be needed")


class FakeNoSubtitleClient(FakeClient):
    def subtitles(self, url: str, *, lang="ai-zh", page=None):
        return []


def test_source_inspection_is_bilibili_only_and_stable() -> None:
    result = source_inspect(
        "https://www.bilibili.com/video/BV1fake", page=1, client=FakeClient()
    )
    assert result["schema_version"] == "video-content/source-inspection-v1"
    assert result["source"]["idempotency_key"] == "bilibili_BV1fake_p1"
    assert result["metadata"]["title"] == "测试视频"


def test_evidence_start_persists_independent_artifacts_and_requires_visual_decision(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path)
    result = evidence_start(
        store,
        url="https://www.bilibili.com/video/BV1fake",
        page=1,
        ocr_backend="none",
        client=FakeClient(),
    )
    evidence = result["evidence"]
    assert evidence["schema_version"] == "video-content/evidence-v1"
    assert evidence["decision"]["platform_track_available"] is True
    assert evidence["decision"]["hard_subtitle_visual_decision"] == "not_assessed"
    assert evidence["observations"][0]["kind"] == "platform_subtitle"
    kinds = {item["kind"] for item in store.list_artifacts(result["job"]["job_id"])}
    assert {
        "subtitle_srt",
        "subtitle_json",
        "transcript_markdown",
        "evidence",
        "extraction_manifest",
    } <= kinds
    assert result["job"]["stage"] == "evidence"
    assert result["job"]["status"] == "running"


def test_evidence_records_agent_visual_assessment(tmp_path: Path) -> None:
    result = evidence_start(
        Store(tmp_path),
        url="https://www.bilibili.com/video/BV1fake",
        page=1,
        ocr_backend="none",
        hard_subtitle_visual_decision="not_continuous",
        visual_assessment={
            "method": "deterministic_scout",
            "sample_count": 15,
        },
        client=FakeClient(),
    )
    decision = result["evidence"]["decision"]
    assert decision["hard_subtitle_visual_decision"] == "not_continuous"
    assert decision["visual_assessment"]["sample_count"] == 15
    assert "no continuous hard subtitles" in decision["agent_action"]


def test_evidence_start_is_idempotent_for_same_video(tmp_path: Path) -> None:
    store = Store(tmp_path)
    first = evidence_start(
        store, url="BV1fake", ocr_backend="none", client=FakeClient()
    )
    second = evidence_start(
        store, url="BV1fake", ocr_backend="none", client=FakeClient()
    )
    assert second["reused_existing_job"] is True
    assert second["job"]["job_id"] == first["job"]["job_id"]
    assert len(store.list_jobs()) == 1


def test_evidence_reuses_existing_source_video_when_retry_metadata_differs(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path)
    job, _ = store.create_job(
        source={
            "platform": "bilibili",
            "bvid": "BV1same",
            "page": 1,
            "url": "https://www.bilibili.com/video/BV1same",
        },
        idempotency_key="bilibili_BV1same_p1",
    )
    video_path = tmp_path / "downloaded.mp4"
    video_path.write_bytes(b"same-video-bytes")
    existing = store.put_artifact(
        job["job_id"],
        kind="source_video",
        source_path=video_path,
        metadata={
            "kind": "source_video",
            "source": "bilibili_download",
            "owned_by_job": False,
            "mib": 0.0,
        },
    )
    subtitle_path = tmp_path / "subtitle.json"
    subtitle_path.write_text("[]\n", encoding="utf-8")
    manifest = {
        "schema_version": "video-content/extraction-run-v1",
        "status": "completed",
        "stage": "done",
        "video": {"bvid": "BV1same", "title": "同一视频"},
        "sources": [
            {
                "kind": "hard_ocr",
                "artifact_source": "hard_ocr:videocr",
                "backend": "videocr",
                "cue_count": 1,
            }
        ],
        "artifacts": [
            {
                "kind": "source_video",
                "path": str(video_path),
                "source": "local",
                "owned_by_job": False,
                "bytes": video_path.stat().st_size,
                "mib": 0.0,
            },
            {
                "kind": "subtitle_json",
                "path": str(subtitle_path),
                "source": "hard_ocr:videocr",
                "owned_by_job": True,
                "cue_count": 1,
                "selected": True,
            },
        ],
        "warnings": [],
    }

    class ExistingPipeline:
        def __init__(self, client) -> None:
            pass

        def run(self, request, *, job_id, on_update=None):
            if on_update:
                on_update(manifest)
            return manifest

    result = evidence_start(
        store,
        url="https://www.bilibili.com/video/BV1same",
        page=1,
        ocr_backend="videocr",
        video_path=video_path,
        hard_subtitle_visual_decision="continuous",
        client=FakeClient(),
        pipeline_factory=ExistingPipeline,
    )

    source_refs = store.list_artifacts(job["job_id"], kind="source_video")
    assert result["evidence"] is not None
    assert source_refs == [existing]
    assert source_refs[0]["metadata"]["source"] == "bilibili_download"


def test_missing_subtitle_with_disabled_backend_is_retryable(tmp_path: Path) -> None:
    result = evidence_start(
        Store(tmp_path),
        url="https://www.bilibili.com/video/BV1fake",
        page=1,
        ocr_backend="none",
        download_if_needed=False,
        client=FakeNoSubtitleClient(),
    )
    assert result["evidence"] is None
    assert result["manifest"]["status"] == "needs_ocr"
    assert result["job"]["status"] == "retryable"
    assert result["job"]["last_error"]["code"] == "ENABLE_OCR"


def test_retryable_evidence_resume_increments_attempts(tmp_path: Path) -> None:
    store = Store(tmp_path)
    first = evidence_start(
        store,
        url="https://www.bilibili.com/video/BV1fake",
        page=1,
        ocr_backend="none",
        download_if_needed=False,
        client=FakeNoSubtitleClient(),
    )
    assert first["job"]["status"] == "retryable"
    assert first["job"]["attempts"] == 1
    resumed = evidence_start(
        store,
        url="https://www.bilibili.com/video/BV1fake",
        page=1,
        ocr_backend="none",
        client=FakeClient(),
    )
    assert resumed["job"]["status"] == "running"
    assert resumed["job"]["stage"] == "evidence"
    assert resumed["job"]["attempts"] == 2


class _CoverHeaders:
    def __init__(self, media_type: str, length: int) -> None:
        self.media_type = media_type
        self.length = length

    def get_content_type(self) -> str:
        return self.media_type

    def get(self, name: str):
        if name.lower() == "content-length":
            return str(self.length)
        return None


class _CoverResponse:
    def __init__(self, *, url: str, payload: bytes, media_type: str) -> None:
        self.url = url
        self.payload = payload
        self.headers = _CoverHeaders(media_type, len(payload))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def geturl(self) -> str:
        return self.url

    def read(self, limit: int) -> bytes:
        return self.payload[:limit]


def test_cover_download_accepts_only_raster_hdslb_redirects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = _CoverResponse(
        url="https://i1.hdslb.com/bfs/archive/cover.jpg",
        payload=b"jpeg-fixture",
        media_type="image/jpeg",
    )
    monkeypatch.setattr(evidence_module, "urlopen", lambda *args, **kwargs: response)
    store = Store(tmp_path)
    job, _ = store.create_job(
        source={"platform": "bilibili"}, idempotency_key="cover_fixture"
    )
    reference = evidence_module._ensure_video_cover(
        store,
        job["job_id"],
        "https://i0.hdslb.com/bfs/archive/cover.jpg",
    )
    assert reference["kind"] == "video_cover"
    assert reference["media_type"] == "image/jpeg"
    assert reference["metadata"]["source_host"] == "i1.hdslb.com"


def test_cover_download_rejects_redirect_outside_bilibili(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = _CoverResponse(
        url="https://example.com/cover.jpg",
        payload=b"jpeg-fixture",
        media_type="image/jpeg",
    )
    monkeypatch.setattr(evidence_module, "urlopen", lambda *args, **kwargs: response)
    store = Store(tmp_path)
    job, _ = store.create_job(
        source={"platform": "bilibili"}, idempotency_key="redirect_fixture"
    )
    with pytest.raises(ValueError, match="redirect left"):
        evidence_module._ensure_video_cover(
            store,
            job["job_id"],
            "https://i0.hdslb.com/bfs/archive/cover.jpg",
        )
