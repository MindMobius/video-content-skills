from pathlib import Path
from threading import Barrier

from video_subtitle.backends.asr import Qwen3AsrOptions
from video_subtitle.backends.ocr import OcrUnavailable, VideOcrOptions
from video_subtitle.pipeline import ExtractionPipeline, ExtractionRequest
from video_subtitle.platforms.bilibili import OpenCliError


class FakeClient:
    platform = "bilibili"

    def __init__(self, subtitles):
        self._subtitles = subtitles

    def video(self, url: str, *, page=None):
        return {
            "bvid": "BV1fake",
            "title": "测试视频",
            "duration": "1m0s (60s)",
            "requires_payment": "false",
        }

    def subtitles(self, url: str, *, lang="ai-zh", page=None):
        if isinstance(self._subtitles, Exception):
            raise self._subtitles
        return self._subtitles

    def download(self, *args, **kwargs):
        raise AssertionError("download should not be called in this test")


class FakeOcrBackend:
    name = "fake-ocr"

    def describe(self):
        return {"name": self.name, "available": True}

    def run(self, video_path: Path, output_path: Path, log_path: Path):
        output_path.write_text(
            "1\n00:00:01,000 --> 00:00:02,000\n硬字幕\n",
            encoding="utf-8",
        )
        log_path.write_text("done\n", encoding="utf-8")
        return {"strategy": "single_scale", "image_max_width": 720}


class FakeAsrBackend:
    name = "fake-asr"

    def describe(self):
        return {"name": self.name, "available": True}

    def run(self, video_path: Path, output_path: Path, log_path: Path):
        output_path.write_text(
            "1\n00:00:01,000 --> 00:00:02,000\nAudio transcript\n",
            encoding="utf-8",
        )
        log_path.write_text("done\n", encoding="utf-8")
        return {
            "strategy": "chunked_forced_alignment",
            "language_requested": "auto",
            "detected_languages": ["English"],
            "context_source": "test",
        }


class CoordinatedOcrBackend(FakeOcrBackend):
    def __init__(self, barrier: Barrier) -> None:
        self.barrier = barrier

    def run(self, video_path: Path, output_path: Path, log_path: Path):
        self.barrier.wait(timeout=2)
        return super().run(video_path, output_path, log_path)


class CoordinatedAsrBackend(FakeAsrBackend):
    def __init__(self, barrier: Barrier) -> None:
        self.barrier = barrier

    def run(self, video_path: Path, output_path: Path, log_path: Path):
        self.barrier.wait(timeout=2)
        return super().run(video_path, output_path, log_path)


class MultipartFakeClient(FakeClient):
    def __init__(self):
        super().__init__(
            [{"index": 1, "from": "1.00s", "to": "2.50s", "content": "第一分P"}]
        )
        self.video_pages = []
        self.subtitle_pages = []

    def video(self, url: str, *, page=None):
        self.video_pages.append(page)
        if page == 1:
            return {
                "bvid": "BV1fake",
                "title": "第一分P",
                "duration": "1m0s (60s)",
                "parts": "2",
                "page": "1",
            }
        return {
            "bvid": "BV1fake",
            "title": "合集标题",
            "duration": "1m10s (70s)",
            "parts": "2",
        }

    def subtitles(self, url: str, *, lang="ai-zh", page=None):
        self.subtitle_pages.append(page)
        return super().subtitles(url, lang=lang, page=page)


def test_platform_subtitle_completes_without_ocr(tmp_path: Path) -> None:
    client = FakeClient(
        [{"index": 1, "from": "1.00s", "to": "2.50s", "content": "平台字幕"}]
    )

    def should_not_resolve(*args):
        raise AssertionError("OCR should not be resolved when platform subtitles exist")

    manifest = ExtractionPipeline(
        client,
        ocr_resolver=should_not_resolve,  # type: ignore[arg-type]
    ).run(
        ExtractionRequest(
            url="https://www.bilibili.com/video/BV1fake",
            output_dir=tmp_path,
        )
    )
    assert manifest["status"] == "completed"
    assert manifest["selected_source"]["kind"] == "platform_subtitle"
    assert manifest["selected_source"]["platform"] == "bilibili"
    assert (tmp_path / "subtitle.platform.srt").exists()
    assert (tmp_path / "subtitle.platform.md").exists()


def test_missing_platform_and_backend_returns_needs_ocr(tmp_path: Path) -> None:
    client = FakeClient(OpenCliError("EMPTY_RESULT", "no subtitle"))

    def missing_backend(*args):
        raise OcrUnavailable("VideOCR missing")

    manifest = ExtractionPipeline(
        client,
        ocr_resolver=missing_backend,  # type: ignore[arg-type]
    ).run(
        ExtractionRequest(
            url="https://www.bilibili.com/video/BV1fake",
            output_dir=tmp_path,
        )
    )
    assert manifest["status"] == "needs_ocr"
    assert manifest["stage"] == "waiting_for_ocr_backend"
    assert manifest["next_action"]["code"] == "CONFIGURE_VIDEOCR"
    assert not (tmp_path / "video").exists()


def test_explicitly_disabled_ocr_requests_enable_action(tmp_path: Path) -> None:
    client = FakeClient(OpenCliError("EMPTY_RESULT", "no subtitle"))

    def disabled_backend(*args):
        raise OcrUnavailable("OCR was disabled")

    manifest = ExtractionPipeline(
        client,
        ocr_resolver=disabled_backend,  # type: ignore[arg-type]
    ).run(
        ExtractionRequest(
            url="https://www.bilibili.com/video/BV1fake",
            output_dir=tmp_path,
            ocr_backend="none",
        )
    )
    assert manifest["status"] == "needs_ocr"
    assert manifest["next_action"]["code"] == "ENABLE_OCR"


def test_local_video_runs_hard_ocr(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake")
    output = tmp_path / "result"
    client = FakeClient(OpenCliError("EMPTY_RESULT", "no subtitle"))

    manifest = ExtractionPipeline(
        client,
        ocr_resolver=lambda *_: FakeOcrBackend(),  # type: ignore[arg-type]
    ).run(
        ExtractionRequest(
            url="https://www.bilibili.com/video/BV1fake",
            output_dir=output,
            video_path=video,
            videocr=VideOcrOptions(),
        )
    )
    assert manifest["status"] == "completed"
    assert manifest["selected_source"]["kind"] == "hard_ocr"
    assert manifest["selected_source"]["backend"] == "fake-ocr"
    assert manifest["selected_source"]["strategy"] == "single_scale"
    assert (output / "subtitle.ocr.json").exists()
    assert (output / "subtitle.ocr.md").exists()
    assert (output / "ocr.log").exists()


def test_collect_all_preserves_platform_ocr_and_asr_evidence(
    tmp_path: Path,
) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake")
    output = tmp_path / "result"
    client = FakeClient(
        [{"index": 1, "from": "1.00s", "to": "2.50s", "content": "平台字幕"}]
    )

    manifest = ExtractionPipeline(
        client,
        ocr_resolver=lambda *_: FakeOcrBackend(),  # type: ignore[arg-type]
        asr_resolver=lambda *_: FakeAsrBackend(),  # type: ignore[arg-type]
    ).run(
        ExtractionRequest(
            url="https://www.bilibili.com/video/BV1fake",
            output_dir=output,
            video_path=video,
            collect_all_sources=True,
            asr_backend="qwen3",
            videocr=VideOcrOptions(),
            qwen3_asr=Qwen3AsrOptions(context="verified terms"),
        )
    )

    assert manifest["status"] == "completed"
    assert manifest["selected_source"]["kind"] == "evidence_bundle"
    assert manifest["selected_source"]["primary"]["kind"] == "platform_subtitle"
    assert [source["kind"] for source in manifest["sources"]] == [
        "platform_subtitle",
        "hard_ocr",
        "audio_asr",
    ]
    selected_transcript = [
        artifact
        for artifact in manifest["artifacts"]
        if artifact["kind"] == "transcript_markdown"
        and artifact.get("selected") is True
    ]
    assert selected_transcript[0]["source"] == "platform_subtitle:bilibili"
    assert (output / "evidence.index.json").exists()
    assert (output / "evidence.index.md").exists()
    assert not (output / "review.packet.json").exists()
    assert manifest["review"] is None
    assert manifest["selected_source"]["fusion_status"] == "independent_evidence"
    assert manifest["execution"]["media_requested"] == "auto"
    assert manifest["execution"]["media_resolved"] == "parallel"


def test_parallel_media_execution_starts_ocr_and_asr_together(
    tmp_path: Path,
) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake")
    barrier = Barrier(2)
    client = FakeClient(OpenCliError("EMPTY_RESULT", "no subtitle"))

    manifest = ExtractionPipeline(
        client,
        ocr_resolver=lambda *_: CoordinatedOcrBackend(barrier),  # type: ignore[arg-type]
        asr_resolver=lambda *_: CoordinatedAsrBackend(barrier),  # type: ignore[arg-type]
    ).run(
        ExtractionRequest(
            url="https://www.bilibili.com/video/BV1fake",
            output_dir=tmp_path / "result",
            video_path=video,
            collect_all_sources=True,
            asr_backend="qwen3",
            media_execution="parallel",
        )
    )

    assert manifest["status"] == "completed"
    assert manifest["execution"]["media_resolved"] == "parallel"
    assert [source["kind"] for source in manifest["sources"]] == [
        "hard_ocr",
        "audio_asr",
    ]
    media_attempts = manifest["attempts"][-2:]
    assert (
        media_attempts[0]["concurrent_group"] == media_attempts[1]["concurrent_group"]
    )
    assert all(attempt["backend_started_at"] for attempt in media_attempts)
    assert all(attempt["backend_elapsed_seconds"] >= 0 for attempt in media_attempts)


def test_serial_media_execution_remains_available(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake")
    client = FakeClient(OpenCliError("EMPTY_RESULT", "no subtitle"))

    manifest = ExtractionPipeline(
        client,
        ocr_resolver=lambda *_: FakeOcrBackend(),  # type: ignore[arg-type]
        asr_resolver=lambda *_: FakeAsrBackend(),  # type: ignore[arg-type]
    ).run(
        ExtractionRequest(
            url="https://www.bilibili.com/video/BV1fake",
            output_dir=tmp_path / "result",
            video_path=video,
            collect_all_sources=True,
            asr_backend="qwen3",
            media_execution="serial",
        )
    )

    assert manifest["status"] == "completed"
    assert manifest["execution"]["media_resolved"] == "serial"
    assert all(
        "concurrent_group" not in attempt
        for attempt in manifest["attempts"]
        if attempt["source"] in {"hard_ocr", "audio_asr"}
    )


def test_auto_media_execution_is_conservative_for_shared_gpu(
    tmp_path: Path,
) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake")
    client = FakeClient(OpenCliError("EMPTY_RESULT", "no subtitle"))

    manifest = ExtractionPipeline(
        client,
        ocr_resolver=lambda *_: FakeOcrBackend(),  # type: ignore[arg-type]
        asr_resolver=lambda *_: FakeAsrBackend(),  # type: ignore[arg-type]
    ).run(
        ExtractionRequest(
            url="https://www.bilibili.com/video/BV1fake",
            output_dir=tmp_path / "result",
            video_path=video,
            collect_all_sources=True,
            asr_backend="qwen3",
            videocr=VideOcrOptions(use_gpu=True),
        )
    )

    assert manifest["execution"] == {
        "media_requested": "auto",
        "media_resolved": "serial",
        "backends": ["hard_ocr", "audio_asr"],
        "shared_gpu": True,
        "decision": "auto_shared_gpu_safe_serial",
    }


def test_asr_can_complete_when_platform_and_ocr_are_unavailable(
    tmp_path: Path,
) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake")
    output = tmp_path / "result"
    client = FakeClient(OpenCliError("EMPTY_RESULT", "no subtitle"))

    manifest = ExtractionPipeline(
        client,
        asr_resolver=lambda *_: FakeAsrBackend(),  # type: ignore[arg-type]
    ).run(
        ExtractionRequest(
            url="https://www.bilibili.com/video/BV1fake",
            output_dir=output,
            video_path=video,
            ocr_backend="none",
            asr_backend="qwen3",
            qwen3_asr=Qwen3AsrOptions(context="verified terms"),
        )
    )

    assert manifest["status"] == "completed"
    assert manifest["selected_source"]["kind"] == "audio_asr"
    assert (output / "subtitle.asr.srt").exists()


def test_multipart_request_defaults_explicitly_to_page_one(tmp_path: Path) -> None:
    client = MultipartFakeClient()

    manifest = ExtractionPipeline(client).run(
        ExtractionRequest(
            url="https://www.bilibili.com/video/BV1fake",
            output_dir=tmp_path,
        )
    )

    assert manifest["status"] == "completed"
    assert client.video_pages == [None, 1]
    assert client.subtitle_pages == [1]
    assert manifest["video"]["title"] == "第一分P"
    assert manifest["video"]["page"] == "1"
    assert manifest["warnings"][0]["code"] == "MULTIPART_DEFAULTED_TO_PAGE_1"
