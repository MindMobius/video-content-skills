from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Cue:
    start_ms: int
    end_ms: int
    text: str


_SRT_TIME = re.compile(r"(?P<h>\d{1,3}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{3})")


def seconds_to_ms(value: Any) -> int:
    if isinstance(value, (int, float)):
        seconds = float(value)
    elif isinstance(value, str):
        normalized = value.strip().removesuffix("s")
        seconds = float(normalized)
    else:
        raise TypeError(f"Unsupported timestamp: {value!r}")
    if seconds < 0:
        raise ValueError(f"Timestamp cannot be negative: {value!r}")
    return round(seconds * 1000)


def platform_rows_to_cues(rows: Iterable[dict[str, Any]]) -> list[Cue]:
    cues: list[Cue] = []
    for row in rows:
        start_ms = seconds_to_ms(row.get("from"))
        end_ms = seconds_to_ms(row.get("to"))
        if end_ms < start_ms:
            raise ValueError(f"Subtitle end precedes start: {row!r}")
        text = str(row.get("content", "")).replace("\r\n", "\n").strip()
        if not text:
            continue
        cues.append(Cue(start_ms=start_ms, end_ms=end_ms, text=text))
    return cues


def format_srt_time(milliseconds: int) -> str:
    milliseconds = max(0, int(milliseconds))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def format_short_time(milliseconds: int) -> str:
    total_seconds = max(0, int(milliseconds)) // 1000
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def write_srt(path: Path, cues: Iterable[Cue]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks: list[str] = []
    for index, cue in enumerate(cues, start=1):
        blocks.append(
            f"{index}\n"
            f"{format_srt_time(cue.start_ms)} --> {format_srt_time(cue.end_ms)}\n"
            f"{cue.text}"
        )
    path.write_text("\n\n".join(blocks) + ("\n" if blocks else ""), encoding="utf-8")


def parse_srt(path: Path) -> list[Cue]:
    content = path.read_text(encoding="utf-8-sig", errors="replace")
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    cues: list[Cue] = []
    for block in re.split(r"\n{2,}", normalized):
        lines = block.splitlines()
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue
        start_raw, end_raw = [
            item.strip() for item in lines[timing_index].split("-->", 1)
        ]
        start_ms = _parse_srt_time(start_raw)
        end_ms = _parse_srt_time(end_raw)
        text = "\n".join(lines[timing_index + 1 :]).strip()
        if text:
            cues.append(Cue(start_ms=start_ms, end_ms=end_ms, text=text))
    return cues


def reconcile_cross_scale_cues(
    primary_cues: Iterable[Cue],
    validation_cues: Iterable[Cue],
    *,
    similarity_threshold: float = 0.72,
    minimum_validation_coverage: float = 0.65,
) -> tuple[list[Cue], dict[str, Any]]:
    """Use low-resolution OCR as a scene-text filter for a clearer OCR pass.

    Validation timings form the output timeline. For every validation cue, the
    most similar overlapping full cue or contiguous line window from the
    primary pass supplies the text. This keeps large caption text that survives
    both scales while dropping small UI/slide text seen only at high resolution.
    """
    if not 0 <= similarity_threshold <= 1:
        raise ValueError("similarity_threshold must be between 0 and 1")
    if not 0 <= minimum_validation_coverage <= 1:
        raise ValueError("minimum_validation_coverage must be between 0 and 1")

    primary = list(primary_cues)
    validation = list(validation_cues)
    primary_duration = sum(max(0, cue.end_ms - cue.start_ms) for cue in primary)
    validation_duration = sum(max(0, cue.end_ms - cue.start_ms) for cue in validation)
    coverage_ratio = min(
        1.0,
        validation_duration / primary_duration if primary_duration else 0.0,
    )
    cue_ratio = len(validation) / len(primary) if primary else 0.0
    metrics: dict[str, Any] = {
        "primary_cue_count": len(primary),
        "validation_cue_count": len(validation),
        "validation_duration_coverage": round(coverage_ratio, 4),
        "validation_cue_ratio": round(cue_ratio, 4),
        "similarity_threshold": similarity_threshold,
    }

    if not primary:
        metrics.update(
            {
                "strategy": "validation_only",
                "reason": "primary_empty",
                "output_cue_count": len(validation),
            }
        )
        return validation, metrics

    if (
        not validation
        or coverage_ratio < minimum_validation_coverage
        or cue_ratio < 0.5
    ):
        metrics.update(
            {
                "strategy": "primary_fallback",
                "reason": (
                    "validation_empty"
                    if not validation
                    else "validation_coverage_insufficient"
                ),
                "output_cue_count": len(primary),
            }
        )
        return primary, metrics

    output: list[Cue] = []
    similarities: list[float] = []
    primary_text_selected = 0
    validation_text_selected = 0
    primary_line_window_selected = 0
    unmatched_validation_cues = 0
    used_primary_indexes: set[int] = set()

    for validation_cue in validation:
        best: tuple[float, int, int, str, bool] | None = None
        validation_text = _normalize_for_comparison(validation_cue.text)
        for primary_index, primary_cue in enumerate(primary):
            overlap = max(
                0,
                min(validation_cue.end_ms, primary_cue.end_ms)
                - max(validation_cue.start_ms, primary_cue.start_ms),
            )
            if overlap <= 0:
                continue
            for candidate_text, is_full_text in _contiguous_text_windows(
                primary_cue.text
            ):
                candidate_normalized = _normalize_for_comparison(candidate_text)
                similarity = SequenceMatcher(
                    None,
                    validation_text,
                    candidate_normalized,
                    autojunk=False,
                ).ratio()
                candidate = (
                    similarity,
                    overlap,
                    primary_index,
                    candidate_text,
                    is_full_text,
                )
                if best is None or candidate[:2] > best[:2]:
                    best = candidate

        if best is None:
            selected_text = validation_cue.text
            validation_text_selected += 1
            unmatched_validation_cues += 1
        else:
            similarity, _, primary_index, candidate_text, is_full_text = best
            similarities.append(similarity)
            used_primary_indexes.add(primary_index)
            if similarity >= similarity_threshold:
                selected_text = _restore_validation_quotes(
                    candidate_text,
                    validation_cue.text,
                )
                primary_text_selected += 1
                if not is_full_text:
                    primary_line_window_selected += 1
            else:
                selected_text = validation_cue.text
                validation_text_selected += 1

        output.append(
            Cue(
                start_ms=validation_cue.start_ms,
                end_ms=validation_cue.end_ms,
                text=selected_text,
            )
        )

    metrics.update(
        {
            "strategy": "cross_scale_consensus",
            "output_cue_count": len(output),
            "primary_text_selected": primary_text_selected,
            "validation_text_selected": validation_text_selected,
            "primary_line_window_selected": primary_line_window_selected,
            "unmatched_validation_cues": unmatched_validation_cues,
            "unused_primary_cues": len(primary) - len(used_primary_indexes),
            "mean_best_similarity": (
                round(sum(similarities) / len(similarities), 4)
                if similarities
                else None
            ),
        }
    )
    return output, metrics


def _restore_validation_quotes(primary_text: str, validation_text: str) -> str:
    """Repair OCR's common curly-quote-to-66/99 substitution.

    Large CJK subtitles frequently render opening and closing quotes as glyph
    shapes that a high-resolution pass reads as standalone ``66`` and ``99``.
    Only apply the repair when the independent validation pass contains the
    corresponding quote, so genuine numbers are preserved.
    """
    quote_number_pattern = re.compile(r"(?:(?<=[：:])\s*66(?:\s+|$)|(?:66|99)\s*$)")
    if quote_number_pattern.search(primary_text) and not re.search(
        r"(?<!\d)(?:66|99)(?!\d)",
        validation_text,
    ):
        return validation_text

    result = primary_text
    if "“" in validation_text and "“" not in result:
        result = re.sub(r"(?<!\d)66(?!\d)", "“", result, count=1)
    if "”" in validation_text and "”" not in result:
        positions = list(re.finditer(r"(?<!\d)99(?!\d)", result))
        if positions:
            match = positions[-1]
            result = result[: match.start()] + "”" + result[match.end() :]
    return re.sub(r"\s+([“”])\s*", r"\1", result)


def _normalize_for_comparison(value: str) -> str:
    return "".join(
        character.casefold()
        for character in value
        if unicodedata.category(character)[0] in {"L", "N"}
    )


def _contiguous_text_windows(value: str) -> Iterable[tuple[str, bool]]:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines:
        return
    full_text = "\n".join(lines)
    yield full_text, True
    if len(lines) == 1:
        return
    for start in range(len(lines)):
        for end in range(start + 1, len(lines) + 1):
            candidate = "\n".join(lines[start:end])
            if candidate != full_text:
                yield candidate, False


def _parse_srt_time(value: str) -> int:
    match = _SRT_TIME.fullmatch(value)
    if not match:
        raise ValueError(f"Invalid SRT timestamp: {value}")
    return (
        int(match.group("h")) * 3_600_000
        + int(match.group("m")) * 60_000
        + int(match.group("s")) * 1_000
        + int(match.group("ms"))
    )


def write_cues_json(path: Path, cues: Iterable[Cue]) -> None:
    payload = [asdict(cue) for cue in cues]
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_transcript_markdown(
    path: Path,
    cues: Iterable[Cue],
    *,
    title: str,
    source: str,
) -> None:
    lines = [f"# {title or '视频字幕'}", "", f"- 来源：`{source}`", ""]
    lines.extend(f"[{format_short_time(cue.start_ms)}] {cue.text}" for cue in cues)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
