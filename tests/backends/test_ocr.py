from video_content.backends.ocr import VideOcrOptions, resolve_ocr_backend


def test_videocr_options_roundtrip_consensus_settings() -> None:
    options = VideOcrOptions(
        crop=(250, 850, 1420, 155),
        image_max_width=1280,
        consensus_image_max_width=600,
        min_subtitle_duration=0.8,
    )

    assert VideOcrOptions.from_dict(options.as_dict()) == options


def test_videocr_auto_device_matches_locked_variant_path(tmp_path) -> None:
    gpu = tmp_path / "videocr-cli-GPU-v1.5.1-CUDA-12.9" / "videocr-cli.exe"
    gpu.parent.mkdir()
    gpu.write_bytes(b"fixture")
    cpu = tmp_path / "videocr-cli-CPU-v1.5.1" / "videocr-cli.exe"
    cpu.parent.mkdir()
    cpu.write_bytes(b"fixture")

    gpu_backend = resolve_ocr_backend("videocr", VideOcrOptions(executable=str(gpu)))
    cpu_backend = resolve_ocr_backend("videocr", VideOcrOptions(executable=str(cpu)))

    assert gpu_backend.describe()["options"]["use_gpu"] is True
    assert cpu_backend.describe()["options"]["use_gpu"] is False


def test_videocr_explicit_device_overrides_variant_name(tmp_path) -> None:
    executable = tmp_path / "videocr-cli-GPU" / "videocr-cli.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"fixture")

    backend = resolve_ocr_backend(
        "videocr",
        VideOcrOptions(executable=str(executable), use_gpu=False),
    )

    assert backend.describe()["options"]["use_gpu"] is False
