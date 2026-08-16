from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from video_subtitle import diagnostics


class FakeClient:
    platform = "bilibili"

    def __init__(self, *, auth: list[dict] | None = None) -> None:
        self.settings = SimpleNamespace(
            display_command="opencli",
            profile="bridge",
            ytdlp_path="yt-dlp",
            ffmpeg_path="ffmpeg",
        )
        self.auth = auth or []
        self.auth_calls = 0
        self.availability_calls = 0

    def is_command_available(self) -> bool:
        self.availability_calls += 1
        return True

    def auth_status(self) -> list[dict]:
        self.auth_calls += 1
        return self.auth


def test_local_ocr_doctor_skips_platform_download_and_asr(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = FakeClient()
    monkeypatch.setattr(
        diagnostics,
        "ocr_doctor",
        lambda _options: {
            "backend": "videocr",
            "available": True,
            "executable": "videocr",
        },
    )
    monkeypatch.setattr(
        diagnostics,
        "asr_doctor",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("ASR probe should be skipped")
        ),
    )

    report = diagnostics.doctor(
        client,  # type: ignore[arg-type]
        capabilities=["hard_ocr_local"],
        deep=True,
        config_path=tmp_path / "config.json",
    )

    assert report["ok"] is True
    assert report["probes"] == {
        "platform": False,
        "watch_later": False,
        "download": False,
        "hard_ocr": True,
        "audio_asr": False,
    }
    assert report["capabilities"]["hard_ocr_local"] is True
    assert client.availability_calls == 0
    assert client.auth_calls == 0
    assert report["audio_asr"]["skipped"] == "not_requested"


def test_url_ocr_requires_authenticated_platform_transport(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = FakeClient(auth=[])
    monkeypatch.setattr(
        diagnostics,
        "ocr_doctor",
        lambda _options: {
            "backend": "videocr",
            "available": True,
            "executable": "videocr",
        },
    )
    monkeypatch.setattr(
        diagnostics,
        "executable_status",
        lambda configured, fallback: {
            "available": True,
            "path": configured or fallback,
        },
    )

    report = diagnostics.doctor(
        client,  # type: ignore[arg-type]
        capabilities=["hard_ocr_url"],
        deep=False,
        config_path=tmp_path / "config.json",
    )

    assert report["capabilities"]["video_download"] is False
    assert report["capabilities"]["hard_ocr_url"] is False
    assert report["setup"]["ready"] is False
    assert [item["dependency_id"] for item in report["setup"]["human_actions"]] == [
        "browser_bridge"
    ]
    assert client.auth_calls == 1
