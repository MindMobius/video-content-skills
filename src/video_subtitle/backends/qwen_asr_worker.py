from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import time
import unicodedata
import wave
from pathlib import Path
from typing import Any

import torch
from qwen_asr import Qwen3ASRModel


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-srt", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--context-file", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--aligner", required=True)
    parser.add_argument("--language", default="auto")
    parser.add_argument("--time-start", default="0:00")
    parser.add_argument("--time-end", default="")
    parser.add_argument("--chunk-seconds", type=int, default=240)
    parser.add_argument("--max-cue-seconds", type=float, default=10.0)
    parser.add_argument("--max-cue-chars", type=int, default=84)
    args = parser.parse_args()

    if args.chunk_seconds < 30 or args.chunk_seconds > 300:
        raise ValueError("--chunk-seconds must be between 30 and 300")
    if args.max_cue_seconds <= 0:
        raise ValueError("--max-cue-seconds must be positive")
    if args.max_cue_chars < 10:
        raise ValueError("--max-cue-chars must be at least 10")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available to PyTorch")
    start_offset_seconds = _parse_time(args.time_start)
    end_seconds = _parse_time(args.time_end) if args.time_end else None
    if end_seconds is not None and end_seconds <= start_offset_seconds:
        raise ValueError("--time-end must be later than --time-start")

    args.output_srt.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    context = args.context_file.read_text(encoding="utf-8", errors="replace")
    started = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix="video-subtitle-asr-") as temp_name:
        chunk_dir = Path(temp_name)
        extract_started = time.perf_counter()
        _extract_audio_chunks(
            args.ffmpeg.resolve(),
            args.input.resolve(),
            chunk_dir,
            args.chunk_seconds,
            time_start=start_offset_seconds,
            time_end=end_seconds,
        )
        audio_extract_seconds = time.perf_counter() - extract_started
        audio_chunks = sorted(chunk_dir.glob("chunk-*.wav"))
        if not audio_chunks:
            raise RuntimeError("ffmpeg did not produce any audio chunks")

        print(
            f"[qwen3-asr] loading model on {torch.cuda.get_device_name(0)}",
            flush=True,
        )
        load_started = time.perf_counter()
        model = Qwen3ASRModel.from_pretrained(
            args.model,
            dtype=torch.bfloat16,
            device_map="cuda:0",
            max_inference_batch_size=1,
            max_new_tokens=4096,
            forced_aligner=args.aligner,
            forced_aligner_kwargs={
                "dtype": torch.bfloat16,
                "device_map": "cuda:0",
            },
        )
        model_load_seconds = time.perf_counter() - load_started

        all_cues: list[dict[str, Any]] = []
        chunk_results: list[dict[str, Any]] = []
        offset_seconds = start_offset_seconds
        inference_seconds = 0.0
        peak_gpu_memory_mib = 0.0
        detected_languages: list[str] = []
        context_echo_retries = 0
        requested_language = (
            None if args.language.strip().lower() == "auto" else args.language
        )

        for index, audio_chunk in enumerate(audio_chunks):
            duration_seconds = _wav_duration(audio_chunk)
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()
            run_started = time.perf_counter()
            results = model.transcribe(
                audio=str(audio_chunk),
                context=context,
                language=requested_language,
                return_time_stamps=True,
            )
            elapsed = time.perf_counter() - run_started
            if not results:
                inference_seconds += elapsed
                offset_seconds += duration_seconds
                continue

            raw_result = _jsonable(results[0])
            initial_text = str(raw_result.get("text") or "").strip()
            echo_metrics = _context_echo_metrics(initial_text, context)
            context_retry: dict[str, Any] | None = None
            if echo_metrics["detected"]:
                print(
                    f"[qwen3-asr] context echo detected in chunk {index + 1}; "
                    "retrying without context",
                    flush=True,
                )
                retry_started = time.perf_counter()
                retry_results = model.transcribe(
                    audio=str(audio_chunk),
                    context="",
                    language=requested_language,
                    return_time_stamps=True,
                )
                retry_elapsed = time.perf_counter() - retry_started
                elapsed += retry_elapsed
                context_echo_retries += 1
                if retry_results:
                    raw_result = _jsonable(retry_results[0])
                context_retry = {
                    "triggered": True,
                    "metrics": echo_metrics,
                    "initial_text": initial_text,
                    "retry_elapsed_seconds": retry_elapsed,
                    "retry_text": str(raw_result.get("text") or "").strip(),
                }

            inference_seconds += elapsed
            peak_mib = torch.cuda.max_memory_allocated() / 1024**2
            peak_gpu_memory_mib = max(peak_gpu_memory_mib, peak_mib)
            language = str(raw_result.get("language") or "")
            if language and language not in detected_languages:
                detected_languages.append(language)
            text = str(raw_result.get("text") or "").strip()
            items = (
                raw_result.get("time_stamps", {}).get("items", [])
                if isinstance(raw_result.get("time_stamps"), dict)
                else []
            )
            cues = _items_to_cues(
                items,
                transcript_text=text,
                offset_seconds=offset_seconds,
                max_cue_seconds=args.max_cue_seconds,
                max_cue_chars=args.max_cue_chars,
            )
            if not cues and text:
                cues = [
                    {
                        "start_ms": round(offset_seconds * 1000),
                        "end_ms": round((offset_seconds + duration_seconds) * 1000),
                        "text": text,
                    }
                ]
            all_cues.extend(cues)
            chunk_results.append(
                {
                    "index": index,
                    "offset_seconds": offset_seconds,
                    "duration_seconds": duration_seconds,
                    "elapsed_seconds": elapsed,
                    "peak_gpu_memory_mib": peak_mib,
                    "language": language,
                    "text": text,
                    "result": raw_result,
                    "cue_count": len(cues),
                    "context_retry": context_retry,
                }
            )
            print(
                f"[qwen3-asr] chunk {index + 1}/{len(audio_chunks)} "
                f"({duration_seconds:.2f}s) transcribed in {elapsed:.3f}s",
                flush=True,
            )
            offset_seconds += duration_seconds

    _write_srt(args.output_srt.resolve(), all_cues)
    payload = {
        "engine": "qwen3-asr",
        "model": args.model,
        "aligner": args.aligner,
        "context": context,
        "language_requested": args.language,
        "time_start": args.time_start,
        "time_end": args.time_end,
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(0),
        "audio_extract_seconds": audio_extract_seconds,
        "model_load_seconds": model_load_seconds,
        "inference_seconds": inference_seconds,
        "total_seconds": time.perf_counter() - started,
        "peak_gpu_memory_mib": peak_gpu_memory_mib,
        "detected_languages": detected_languages,
        "context_echo_retries": context_echo_retries,
        "cue_count": len(all_cues),
        "chunks": chunk_results,
    }
    args.output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output_srt": str(args.output_srt.resolve()),
                "output_json": str(args.output_json.resolve()),
                "cue_count": len(all_cues),
                "total_seconds": payload["total_seconds"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


def _extract_audio_chunks(
    ffmpeg: Path,
    input_path: Path,
    chunk_dir: Path,
    chunk_seconds: int,
    *,
    time_start: float,
    time_end: float | None,
) -> None:
    output_pattern = chunk_dir / "chunk-%04d.wav"
    command = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
    ]
    if time_start > 0:
        command += ["-ss", str(time_start)]
    command += [
        "-i",
        str(input_path),
        "-map",
        "0:a:0",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        "-f",
        "segment",
        "-segment_time",
        str(chunk_seconds),
        "-reset_timestamps",
        "1",
    ]
    if time_end is not None:
        command += ["-t", str(time_end - time_start)]
    command += [
        "-y",
        str(output_pattern),
    ]
    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"ffmpeg audio extraction failed with code {process.returncode}: "
            f"{process.stderr.strip()}"
        )


def _parse_time(value: str) -> float:
    normalized = value.strip()
    if not normalized:
        return 0.0
    parts = normalized.split(":")
    try:
        numbers = [float(part) for part in parts]
    except ValueError as error:
        raise ValueError(f"Invalid time value: {value}") from error
    if any(number < 0 for number in numbers) or len(numbers) > 3:
        raise ValueError(f"Invalid time value: {value}")
    seconds = 0.0
    for number in numbers:
        seconds = seconds * 60 + number
    return seconds


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as stream:
        return stream.getnframes() / stream.getframerate()


def _items_to_cues(
    items: Any,
    *,
    transcript_text: str,
    offset_seconds: float,
    max_cue_seconds: float,
    max_cue_chars: int,
) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    tokens: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "")
        try:
            start = float(item["start_time"])
            end = float(item["end_time"])
        except (KeyError, TypeError, ValueError):
            continue
        if not text.strip() or end < start:
            continue
        tokens.append({"text": text, "start": start, "end": end})
    if not tokens:
        return []
    tokens = _restore_transcript_punctuation(tokens, transcript_text)

    cues: list[dict[str, Any]] = []
    group: list[dict[str, Any]] = []
    for index, token in enumerate(tokens):
        group.append(token)
        text = _join_tokens([str(item["text"]) for item in group])
        start = float(group[0]["start"])
        end = float(group[-1]["end"])
        next_start = (
            float(tokens[index + 1]["start"]) if index + 1 < len(tokens) else None
        )
        silence = next_start - end if next_start is not None else 0.0
        sentence_end = bool(re.search(r"[.!?。！？]$|[.!?。！？][\"'”’]$", text))
        should_flush = (
            index + 1 == len(tokens)
            or end - start >= max_cue_seconds
            or len(text) >= max_cue_chars
            or (silence >= 0.75 and end - start >= 1.2)
            or (sentence_end and end - start >= 1.0)
        )
        if not should_flush:
            continue
        cues.append(
            {
                "start_ms": round((offset_seconds + start) * 1000),
                "end_ms": round((offset_seconds + max(end, start + 0.2)) * 1000),
                "text": text,
            }
        )
        group = []
    return cues


def _restore_transcript_punctuation(
    tokens: list[dict[str, Any]],
    transcript_text: str,
) -> list[dict[str, Any]]:
    raw_characters: list[str] = []
    raw_positions: list[int] = []
    for index, character in enumerate(transcript_text):
        if character.isalnum():
            raw_characters.append(character.casefold())
            raw_positions.append(index)
    token_normalized = [
        "".join(
            character.casefold()
            for character in str(token["text"])
            if character.isalnum()
        )
        for token in tokens
    ]
    if (
        not raw_characters
        or any(not value for value in token_normalized)
        or "".join(token_normalized) != "".join(raw_characters)
    ):
        return tokens

    output: list[dict[str, Any]] = []
    raw_offset = 0
    for index, (token, normalized) in enumerate(zip(tokens, token_normalized)):
        start_position = raw_positions[raw_offset]
        raw_offset += len(normalized)
        end_position = (
            raw_positions[raw_offset]
            if raw_offset < len(raw_positions)
            else len(transcript_text)
        )
        if index == 0 and start_position:
            start_position = 0
        display_text = transcript_text[start_position:end_position].strip()
        output.append({**token, "text": display_text or token["text"]})
    return output


def _context_echo_metrics(text: str, context: str) -> dict[str, Any]:
    normalized_text = _normalize_echo_text(text)
    normalized_context = _normalize_echo_text(context)
    if len(normalized_context) < 24 or len(normalized_text) < 24:
        return {
            "detected": False,
            "common_prefix_chars": 0,
            "context_chars": len(normalized_context),
        }
    common_prefix_chars = len(
        os.path.commonprefix([normalized_text, normalized_context])
    )
    threshold = min(80, max(32, round(len(normalized_context) * 0.25)))
    return {
        "detected": common_prefix_chars >= threshold,
        "common_prefix_chars": common_prefix_chars,
        "threshold": threshold,
        "context_chars": len(normalized_context),
    }


def _normalize_echo_text(value: str) -> str:
    return "".join(character.casefold() for character in value if character.isalnum())


def _join_tokens(tokens: list[str]) -> str:
    result = ""
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        if not result:
            result = token
            continue
        if _needs_space(result[-1], token[0]):
            result += " "
        result += token
    return result.strip()


def _needs_space(previous: str, current: str) -> bool:
    if current in ",.;:!?%)]}。；：，！？、”’":
        return False
    if previous in "([{“‘":
        return False
    if _is_word_character(current) and previous in ',.;:!?)]}。；：，！？、”’"':
        return True
    return _is_word_character(previous) and _is_word_character(current)


def _is_word_character(character: str) -> bool:
    category = unicodedata.category(character)
    if category[0] not in {"L", "N"}:
        return False
    return not ("\u3400" <= character <= "\u9fff")


def _write_srt(path: Path, cues: list[dict[str, Any]]) -> None:
    blocks: list[str] = []
    for index, cue in enumerate(cues, start=1):
        blocks.append(
            f"{index}\n"
            f"{_format_srt_time(int(cue['start_ms']))} --> "
            f"{_format_srt_time(int(cue['end_ms']))}\n"
            f"{cue['text']}"
        )
    path.write_text(
        "\n\n".join(blocks) + ("\n" if blocks else ""),
        encoding="utf-8",
    )


def _format_srt_time(milliseconds: int) -> str:
    hours, remainder = divmod(max(0, milliseconds), 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "tolist"):
        return _jsonable(value.tolist())
    if hasattr(value, "__dict__"):
        return _jsonable(vars(value))
    return str(value)


if __name__ == "__main__":
    main()
