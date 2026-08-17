from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..srt import parse_srt, reconcile_cross_scale_cues, write_srt
from ..util import tail_text


class OcrUnavailable(RuntimeError):
    pass


class OcrExecutionError(RuntimeError):
    def __init__(self, message: str, *, log_path: Path | None = None) -> None:
        super().__init__(message)
        self.log_path = log_path


class OcrBackend(Protocol):
    name: str

    def describe(self) -> dict[str, Any]: ...

    def run(
        self,
        video_path: Path,
        output_path: Path,
        log_path: Path,
    ) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class VideOcrOptions:
    executable: str | None = None
    language: str = "ch"
    use_gpu: bool = False
    full_frame: bool = False
    crop: tuple[int, int, int, int] | None = None
    time_start: str = "0:00"
    time_end: str = ""
    confidence_threshold: int = 75
    similarity_threshold: int = 80
    frames_to_skip: int = 1
    image_max_width: int = 720
    consensus_image_max_width: int | None = None
    min_subtitle_duration: float = 0.2

    def as_dict(self) -> dict[str, Any]:
        return {
            "executable": self.executable,
            "language": self.language,
            "use_gpu": self.use_gpu,
            "full_frame": self.full_frame,
            "crop": list(self.crop) if self.crop else None,
            "time_start": self.time_start,
            "time_end": self.time_end,
            "confidence_threshold": self.confidence_threshold,
            "similarity_threshold": self.similarity_threshold,
            "frames_to_skip": self.frames_to_skip,
            "image_max_width": self.image_max_width,
            "consensus_image_max_width": self.consensus_image_max_width,
            "min_subtitle_duration": self.min_subtitle_duration,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> VideOcrOptions:
        crop_value = value.get("crop")
        crop = tuple(int(item) for item in crop_value) if crop_value else None
        if crop is not None and len(crop) != 4:
            raise ValueError("OCR crop must contain x, y, width, height")
        return cls(
            executable=value.get("executable") or None,
            language=str(value.get("language") or "ch"),
            use_gpu=bool(value.get("use_gpu", False)),
            full_frame=bool(value.get("full_frame", False)),
            crop=crop,  # type: ignore[arg-type]
            time_start=str(value.get("time_start") or "0:00"),
            time_end=str(value.get("time_end") or ""),
            confidence_threshold=int(value.get("confidence_threshold", 75)),
            similarity_threshold=int(value.get("similarity_threshold", 80)),
            frames_to_skip=int(value.get("frames_to_skip", 1)),
            image_max_width=int(value.get("image_max_width", 720)),
            consensus_image_max_width=(
                int(value["consensus_image_max_width"])
                if value.get("consensus_image_max_width") is not None
                else None
            ),
            min_subtitle_duration=float(value.get("min_subtitle_duration", 0.2)),
        )


class VideOcrBackend:
    name = "videocr"

    def __init__(self, executable: Path, options: VideOcrOptions) -> None:
        self.executable = executable.resolve()
        self.options = options

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": True,
            "executable": str(self.executable),
            "options": self.options.as_dict(),
        }

    def run(
        self,
        video_path: Path,
        output_path: Path,
        log_path: Path,
    ) -> dict[str, Any]:
        video_path = video_path.resolve()
        output_path = output_path.resolve()
        log_path = log_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        consensus_width = self.options.consensus_image_max_width
        if consensus_width is None or consensus_width == self.options.image_max_width:
            command = self._command(
                video_path, output_path, self.options.image_max_width
            )
            self._run_command(
                command,
                output_path,
                log_path,
                label=f"single scale: {self.options.image_max_width}px",
                append=False,
                required=True,
            )
            return {
                "strategy": "single_scale",
                "image_max_width": self.options.image_max_width,
            }

        primary_path = output_path.with_name(
            f"{output_path.stem}.primary{output_path.suffix}"
        )
        validation_path = output_path.with_name(
            f"{output_path.stem}.validation{output_path.suffix}"
        )
        primary_command = self._command(
            video_path,
            primary_path,
            self.options.image_max_width,
        )
        self._run_command(
            primary_command,
            primary_path,
            log_path,
            label=f"primary scale: {self.options.image_max_width}px",
            append=False,
            required=True,
        )
        primary_cues = parse_srt(primary_path)
        if not primary_cues:
            raise OcrExecutionError(
                "VideOCR primary pass produced an SRT file with no usable cues",
                log_path=log_path,
            )

        validation_command = self._command(
            video_path,
            validation_path,
            consensus_width,
        )
        validation_error = self._run_command(
            validation_command,
            validation_path,
            log_path,
            label=f"validation scale: {consensus_width}px",
            append=True,
            required=False,
        )
        warnings: list[dict[str, str]] = []
        if validation_error is not None:
            write_srt(output_path, primary_cues)
            warnings.append(
                {
                    "code": "OCR_CONSENSUS_FALLBACK",
                    "message": (
                        "The validation OCR pass failed; the primary OCR transcript "
                        "was preserved."
                    ),
                    "detail": validation_error,
                }
            )
            reconciliation: dict[str, Any] = {
                "strategy": "primary_fallback",
                "reason": "validation_execution_failed",
                "primary_cue_count": len(primary_cues),
                "output_cue_count": len(primary_cues),
            }
        else:
            validation_cues = parse_srt(validation_path)
            reconciled_cues, reconciliation = reconcile_cross_scale_cues(
                primary_cues,
                validation_cues,
            )
            write_srt(output_path, reconciled_cues)
            if reconciliation["strategy"] != "cross_scale_consensus":
                warnings.append(
                    {
                        "code": "OCR_CONSENSUS_FALLBACK",
                        "message": (
                            "The validation OCR pass did not cover enough primary "
                            "captions; the primary transcript was preserved."
                        ),
                        "detail": str(reconciliation.get("reason") or "unknown"),
                    }
                )

        return {
            "strategy": reconciliation["strategy"],
            "primary_image_max_width": self.options.image_max_width,
            "validation_image_max_width": consensus_width,
            "reconciliation": reconciliation,
            "supporting_artifacts": [
                {
                    "kind": "ocr_primary_srt",
                    "path": str(primary_path),
                    "cue_count": len(primary_cues),
                },
                {
                    "kind": "ocr_validation_srt",
                    "path": str(validation_path),
                    "cue_count": (
                        len(parse_srt(validation_path))
                        if validation_path.is_file()
                        else 0
                    ),
                },
            ],
            "warnings": warnings,
        }

    def _command(
        self,
        video_path: Path,
        output_path: Path,
        image_max_width: int,
    ) -> list[str]:
        command = _python_or_executable(self.executable)
        command += [
            "--video_path",
            str(video_path),
            "--output",
            str(output_path),
            "--ocr_engine",
            "paddleocr",
            "--lang",
            self.options.language,
            "--use_gpu",
            str(self.options.use_gpu).lower(),
            "--use_fullframe",
            str(self.options.full_frame).lower(),
            "--time_start",
            self.options.time_start,
            "--conf_threshold",
            str(self.options.confidence_threshold),
            "--sim_threshold",
            str(self.options.similarity_threshold),
            "--frames_to_skip",
            str(self.options.frames_to_skip),
            "--ocr_image_max_width",
            str(image_max_width),
            "--min_subtitle_duration",
            str(self.options.min_subtitle_duration),
        ]
        if self.options.time_end:
            command += ["--time_end", self.options.time_end]
        if self.options.crop:
            x, y, width, height = self.options.crop
            command += [
                "--crop_x",
                str(x),
                "--crop_y",
                str(y),
                "--crop_width",
                str(width),
                "--crop_height",
                str(height),
            ]
        return command

    @staticmethod
    def _run_command(
        command: list[str],
        output_path: Path,
        log_path: Path,
        *,
        label: str,
        append: bool,
        required: bool,
    ) -> str | None:
        output_path.unlink(missing_ok=True)
        with log_path.open(
            "a" if append else "w",
            encoding="utf-8",
            errors="replace",
        ) as log:
            log.write(f"\n=== VideOCR {label} ===\n")
            log.flush()
            process = subprocess.run(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        if process.returncode != 0:
            detail = tail_text(log_path, max_chars=4_000).strip()
            message = f"VideOCR exited with code {process.returncode}"
            if detail:
                message += f": {detail}"
            if required:
                raise OcrExecutionError(message, log_path=log_path)
            return message
        if not output_path.exists() or output_path.stat().st_size == 0:
            message = (
                "VideOCR exited successfully but did not produce a non-empty SRT file"
            )
            if required:
                raise OcrExecutionError(message, log_path=log_path)
            return message
        return None


def resolve_ocr_backend(
    backend_name: str,
    options: VideOcrOptions,
) -> OcrBackend:
    normalized = backend_name.lower().strip()
    if normalized == "none":
        raise OcrUnavailable("OCR was disabled for this request")
    if normalized not in {"auto", "videocr"}:
        raise OcrUnavailable(f"Unsupported OCR backend: {backend_name}")

    executable = _resolve_videocr_executable(options.executable)
    if executable is None:
        raise OcrUnavailable(
            "VideOCR CLI is not installed or configured. Set VIDEO_CONTENT_VIDEOCR "
            "or pass --ocr-executable with videocr-cli.exe."
        )
    return VideOcrBackend(executable, options)


def ocr_doctor(options: VideOcrOptions) -> dict[str, Any]:
    executable = _resolve_videocr_executable(options.executable)
    if executable is None:
        return {
            "backend": "videocr",
            "available": False,
            "executable": None,
            "help": (
                "Install a VideOCR CLI release and set VIDEO_CONTENT_VIDEOCR "
                "to videocr-cli.exe."
            ),
        }
    return {
        "backend": "videocr",
        "available": True,
        "executable": str(executable),
    }


def _resolve_videocr_executable(value: str | None) -> Path | None:
    selected = (
        value or os.getenv("VIDEO_CONTENT_VIDEOCR") or os.getenv("VIDEOCR_BIN") or ""
    ).strip()
    if selected:
        candidate = Path(selected).expanduser()
        if candidate.is_file():
            return candidate.resolve()
        resolved = shutil.which(selected)
        return Path(resolved).resolve() if resolved else None

    for command in ("videocr-cli", "videocr-cli.exe"):
        resolved = shutil.which(command)
        if resolved:
            return Path(resolved).resolve()
    return None


def _python_or_executable(path: Path) -> list[str]:
    if path.suffix.lower() == ".py":
        return [sys.executable, str(path)]
    return [str(path)]
