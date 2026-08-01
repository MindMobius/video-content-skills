from video_subtitle.backends.ocr import VideOcrOptions


def test_videocr_options_roundtrip_consensus_settings() -> None:
    options = VideOcrOptions(
        crop=(250, 850, 1420, 155),
        image_max_width=1280,
        consensus_image_max_width=600,
        min_subtitle_duration=0.8,
    )

    assert VideOcrOptions.from_dict(options.as_dict()) == options
