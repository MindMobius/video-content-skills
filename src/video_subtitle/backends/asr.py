from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..core.util import read_json, tail_text


class AsrUnavailable(RuntimeError):
    pass


class AsrExecutionError(RuntimeError):
    def __init__(self, message: str, *, log_path: Path | None = None) -> None:
        super().__init__(message)
        self.log_path = log_path


class AsrBackend(Protocol):
    name: str

    def describe(self) -> dict[str, Any]: ...

    def run(
        self,
        video_path: Path,
        output_path: Path,
        log_path: Path,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class Qwen3AsrOptions:
    python_executable: str | None = None
    ffmpeg_executable: str | None = None
    model: str | None = None
    aligner: str | None = None
    language: str = "auto"
    context: str = ""
    context_source: str = "none"
    time_start: str = "0:00"
    time_end: str = ""
    chunk_seconds: int = 240
    max_cue_seconds: float = 10.0
    max_cue_chars: int = 84

    def as_dict(self) -> dict[str, Any]:
        return {
            "python_executable": self.python_executable,
            "ffmpeg_executable": self.ffmpeg_executable,
            "model": self.model,
            "aligner": self.aligner,
            "language": self.language,
            "context": self.context,
            "context_source": self.context_source,
            "time_start": self.time_start,
            "time_end": self.time_end,
            "chunk_seconds": self.chunk_seconds,
            "max_cue_seconds": self.max_cue_seconds,
            "max_cue_chars": self.max_cue_chars,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Qwen3AsrOptions:
        return cls(
            python_executable=value.get("python_executable") or None,
            ffmpeg_executable=value.get("ffmpeg_executable") or None,
            model=value.get("model") or None,
            aligner=value.get("aligner") or None,
            language=str(value.get("language") or "auto"),
            context=str(value.get("context") or ""),
            context_source=str(value.get("context_source") or "none"),
            time_start=str(value.get("time_start") or "0:00"),
            time_end=str(value.get("time_end") or ""),
            chunk_seconds=int(value.get("chunk_seconds", 240)),
            max_cue_seconds=float(value.get("max_cue_seconds", 10.0)),
            max_cue_chars=int(value.get("max_cue_chars", 84)),
        )


class Qwen3AsrBackend:
    name = "qwen3"

    def __init__(
        self,
        python_executable: Path,
        ffmpeg_executable: Path,
        model: str,
        aligner: str,
        options: Qwen3AsrOptions,
    ) -> None:
        self.python_executable = python_executable.resolve()
        self.ffmpeg_executable = ffmpeg_executable.resolve()
        self.model = _resolve_model_reference(model)
        self.aligner = _resolve_model_reference(aligner)
        self.options = options

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": True,
            "python": str(self.python_executable),
            "ffmpeg": str(self.ffmpeg_executable),
            "model": self.model,
            "aligner": self.aligner,
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

        raw_json_path = output_path.with_name(f"{output_path.stem}.raw.json")
        context_path = output_path.with_name(f"{output_path.stem}.context.txt")
        context_path.write_text(self.options.context, encoding="utf-8")
        worker_script = Path(__file__).with_name("qwen_asr_worker.py").resolve()
        command = [
            str(self.python_executable),
            str(worker_script),
            "--input",
            str(video_path),
            "--output-srt",
            str(output_path),
            "--output-json",
            str(raw_json_path),
            "--context-file",
            str(context_path),
            "--ffmpeg",
            str(self.ffmpeg_executable),
            "--model",
            self.model,
            "--aligner",
            self.aligner,
            "--language",
            self.options.language,
            "--time-start",
            self.options.time_start,
            "--chunk-seconds",
            str(self.options.chunk_seconds),
            "--max-cue-seconds",
            str(self.options.max_cue_seconds),
            "--max-cue-chars",
            str(self.options.max_cue_chars),
        ]
        if self.options.time_end:
            command += ["--time-end", self.options.time_end]

        environment = os.environ.copy()
        environment["TQDM_DISABLE"] = "1"
        environment["TOKENIZERS_PARALLELISM"] = "false"
        environment["HF_HUB_DISABLE_TELEMETRY"] = "1"
        with log_path.open(
            "w",
            encoding="utf-8",
            errors="replace",
        ) as log:
            process = subprocess.run(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
            )

        if process.returncode != 0:
            detail = tail_text(log_path, max_chars=6_000).strip()
            message = f"Qwen3-ASR worker exited with code {process.returncode}"
            if detail:
                message += f": {detail}"
            raise AsrExecutionError(message, log_path=log_path)
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise AsrExecutionError(
                "Qwen3-ASR completed but did not produce a non-empty SRT file",
                log_path=log_path,
            )
        if not raw_json_path.is_file():
            raise AsrExecutionError(
                "Qwen3-ASR completed but did not produce its evidence JSON",
                log_path=log_path,
            )

        payload = read_json(raw_json_path)
        context_echo_retries = int(payload.get("context_echo_retries", 0))
        warnings: list[dict[str, Any]] = []
        if context_echo_retries:
            warnings.append(
                {
                    "code": "ASR_CONTEXT_ECHO_RETRY",
                    "message": (
                        f"Qwen3-ASR echoed supplied context in {context_echo_retries} "
                        "chunk(s); those chunks were retranscribed without context."
                    ),
                    "retry_count": context_echo_retries,
                }
            )
        return {
            "strategy": "chunked_forced_alignment",
            "language_requested": self.options.language,
            "context_source": self.options.context_source,
            "time_start": self.options.time_start,
            "time_end": self.options.time_end,
            "chunk_seconds": self.options.chunk_seconds,
            "model_load_seconds": payload.get("model_load_seconds"),
            "audio_extract_seconds": payload.get("audio_extract_seconds"),
            "inference_seconds": payload.get("inference_seconds"),
            "total_seconds": payload.get("total_seconds"),
            "peak_gpu_memory_mib": payload.get("peak_gpu_memory_mib"),
            "detected_languages": payload.get("detected_languages", []),
            "context_echo_retries": context_echo_retries,
            "chunk_count": len(payload.get("chunks", [])),
            "warnings": warnings,
            "supporting_artifacts": [
                {
                    "kind": "asr_raw_json",
                    "path": str(raw_json_path),
                },
                {
                    "kind": "asr_context",
                    "path": str(context_path),
                },
            ],
        }


def resolve_asr_backend(
    backend_name: str,
    options: Qwen3AsrOptions,
) -> AsrBackend:
    normalized = backend_name.lower().strip()
    if normalized == "none":
        raise AsrUnavailable("ASR was disabled for this request")
    if normalized not in {"auto", "qwen3"}:
        raise AsrUnavailable(f"Unsupported ASR backend: {backend_name}")

    python_executable = _resolve_executable(
        options.python_executable
        or os.getenv("VIDEO_SUBTITLE_ASR_PYTHON")
        or os.getenv("SUBTITLE_AGENT_ASR_PYTHON"),
        fallback=None,
    )
    if python_executable is None:
        raise AsrUnavailable(
            "Qwen3-ASR Python is not configured. Set VIDEO_SUBTITLE_ASR_PYTHON "
            "or pass --asr-python."
        )
    ffmpeg_executable = _resolve_executable(
        options.ffmpeg_executable
        or os.getenv("VIDEO_SUBTITLE_FFMPEG")
        or os.getenv("SUBTITLE_AGENT_FFMPEG"),
        fallback="ffmpeg",
    )
    if ffmpeg_executable is None:
        raise AsrUnavailable(
            "ffmpeg is required for Qwen3-ASR audio chunking. Set "
            "VIDEO_SUBTITLE_FFMPEG or pass --ffmpeg."
        )

    model = (
        options.model
        or os.getenv("VIDEO_SUBTITLE_QWEN_ASR_MODEL")
        or os.getenv("SUBTITLE_AGENT_QWEN_ASR_MODEL")
        or ""
    ).strip()
    aligner = (
        options.aligner
        or os.getenv("VIDEO_SUBTITLE_QWEN_ALIGNER_MODEL")
        or os.getenv("SUBTITLE_AGENT_QWEN_ALIGNER_MODEL")
        or ""
    ).strip()
    if not model:
        raise AsrUnavailable(
            "Qwen3-ASR model is not configured. Set "
            "VIDEO_SUBTITLE_QWEN_ASR_MODEL to a local model directory."
        )
    if not aligner:
        raise AsrUnavailable(
            "Qwen3 Forced Aligner is not configured. Set "
            "VIDEO_SUBTITLE_QWEN_ALIGNER_MODEL to a local model directory."
        )
    return Qwen3AsrBackend(
        python_executable,
        ffmpeg_executable,
        model,
        aligner,
        options,
    )


def asr_doctor(
    options: Qwen3AsrOptions,
    *,
    deep: bool = True,
) -> dict[str, Any]:
    try:
        backend = resolve_asr_backend("qwen3", options)
    except AsrUnavailable as error:
        return {
            "backend": "qwen3",
            "available": False,
            "error": str(error),
        }

    assert isinstance(backend, Qwen3AsrBackend)
    if not deep:
        return {
            "backend": "qwen3",
            "available": True,
            "python": str(backend.python_executable),
            "ffmpeg": str(backend.ffmpeg_executable),
            "model": backend.model,
            "aligner": backend.aligner,
            "runtime": None,
            "runtime_checked": False,
            "error": None,
        }
    probe = (
        "import json, torch; import qwen_asr; "
        "print(json.dumps({'torch': torch.__version__, "
        "'cuda_available': torch.cuda.is_available(), "
        "'gpu': torch.cuda.get_device_name(0) if torch.cuda.is_available() else None, "
        "'gpu_memory_mib': round(torch.cuda.get_device_properties(0).total_memory "
        "/ 1024 / 1024) if torch.cuda.is_available() else None}))"
    )
    try:
        process = subprocess.run(
            [str(backend.python_executable), "-c", probe],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {
            "backend": "qwen3",
            "available": False,
            "error": f"Qwen3-ASR environment probe failed: {error}",
        }
    if process.returncode != 0:
        return {
            "backend": "qwen3",
            "available": False,
            "error": (process.stderr or process.stdout).strip(),
        }
    try:
        runtime = json.loads(process.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {
            "backend": "qwen3",
            "available": False,
            "error": "Qwen3-ASR environment probe returned malformed JSON",
        }
    available = bool(runtime.get("cuda_available"))
    return {
        "backend": "qwen3",
        "available": available,
        "python": str(backend.python_executable),
        "ffmpeg": str(backend.ffmpeg_executable),
        "model": backend.model,
        "aligner": backend.aligner,
        "runtime": runtime,
        "runtime_checked": True,
        "error": None if available else "CUDA is not available to Qwen3-ASR",
    }


def _resolve_executable(value: str | None, *, fallback: str | None) -> Path | None:
    selected = (value or "").strip()
    if selected:
        candidate = Path(selected).expanduser()
        if candidate.is_file():
            return candidate.resolve()
        resolved = shutil.which(selected)
        return Path(resolved).resolve() if resolved else None
    if fallback:
        resolved = shutil.which(fallback)
        if resolved:
            return Path(resolved).resolve()
    return None


def _resolve_model_reference(value: str) -> str:
    candidate = Path(value).expanduser()
    return str(candidate.resolve()) if candidate.exists() else value
