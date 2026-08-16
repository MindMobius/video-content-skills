"""Generate the repository-owned audio plus hard-subtitle acceptance video."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    ffmpeg = args.ffmpeg.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    video = output_dir / "authorized-hard-subtitle.mp4"
    command = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=0x18332e:s=640x360:r=24:d=3",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000:duration=3",
        "-vf",
        (
            "drawtext=text='AUTHORIZED TEST SUBTITLE':fontcolor=white:fontsize=28:"
            "borderw=2:bordercolor=black:x=(w-text_w)/2:y=h-70"
        ),
        "-c:v",
        "libx264",
        "-preset",
        "veryslow",
        "-crf",
        "28",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        "-shortest",
        "-metadata",
        "comment=Repository-owned acceptance fixture",
        str(video),
    ]
    completed = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", check=False
    )
    if completed.returncode:
        raise SystemExit(completed.stderr or completed.stdout)
    fixture = {
        "schema_version": "video-subtitle/authorized-media-fixture-v1",
        "license": "CC0-1.0",
        "generated": True,
        "duration_seconds": 3,
        "video": {
            "path": video.name,
            "bytes": video.stat().st_size,
            "sha256": _sha256(video),
            "width": 640,
            "height": 360,
            "has_audio": True,
            "hard_subtitle": "AUTHORIZED TEST SUBTITLE",
        },
        "generator": {
            "script": "scripts/generate_media_fixture.py",
            "ffmpeg_version": _ffmpeg_version(ffmpeg),
        },
    }
    (output_dir / "fixture.json").write_text(
        json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(fixture, ensure_ascii=False, indent=2))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ffmpeg_version(ffmpeg: Path) -> str:
    completed = subprocess.run(
        [str(ffmpeg), "-version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return (completed.stdout or completed.stderr).splitlines()[0]


if __name__ == "__main__":
    main()
