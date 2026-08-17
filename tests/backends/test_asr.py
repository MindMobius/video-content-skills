from video_content.backends.asr import (
    AsrUnavailable,
    Qwen3AsrOptions,
    resolve_asr_backend,
)


def test_qwen3_asr_options_roundtrip() -> None:
    options = Qwen3AsrOptions(
        python_executable="python.exe",
        ffmpeg_executable="ffmpeg.exe",
        model="Qwen3-ASR-1.7B",
        aligner="Qwen3-ForcedAligner-0.6B",
        language="English",
        context="ASD-STE100",
        context_source="test",
        time_start="1:00",
        time_end="1:30",
        chunk_seconds=180,
        max_cue_seconds=8.0,
        max_cue_chars=72,
    )

    assert Qwen3AsrOptions.from_dict(options.as_dict()) == options


def test_disabled_asr_is_explicitly_unavailable() -> None:
    try:
        resolve_asr_backend("none", Qwen3AsrOptions())
    except AsrUnavailable as error:
        assert "disabled" in str(error)
    else:
        raise AssertionError("disabled ASR should not resolve")
