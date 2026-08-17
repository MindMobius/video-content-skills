from __future__ import annotations

from pathlib import Path

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
