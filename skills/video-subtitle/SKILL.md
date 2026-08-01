---
name: video-subtitle
description: Retrieve and verify subtitle evidence from video links or local files through composable platform, OCR, ASR, MCP, and CLI tools. The current release includes a Bilibili adapter.
---

# Video Subtitle

Use this skill when a task depends on what a video actually says or displays. Do
not infer a transcript or summary from metadata alone.

## Model

This skill exposes evidence tools rather than prescribing a fixed pipeline. The
caller decides which source to inspect, which time range needs more evidence, and
when the available evidence is sufficient for the user's task.

Use tools for retrieval, OCR, ASR, timestamps, persistence, and validation. Use
your own reasoning for semantic comparison, translation, terminology, conflict
resolution, and choosing the next tool call.

## Current providers

- Bilibili links and short links are supported through OpenCLI and its Browser
  Bridge login state.
- Local video files can be supplied to the extraction tool.
- YouTube and Douyin adapters are not implemented yet. Do not claim support merely
  because OCR and ASR backends are platform-independent.

## Capability map

- `video_subtitle_doctor`: inspect Bilibili login transport and local OCR/ASR
  capabilities.
- `inspect_bilibili_video`: read Bilibili metadata or resolve multipart selection
  without starting extraction.
- `start_subtitle_extraction`: acquire one or more independent subtitle sources.
- `get_subtitle_job`: inspect job state, attempts, warnings, and artifacts.
- `list_subtitle_evidence`: discover source IDs and time-addressable subtitle
  artifacts before choosing evidence.
- `read_subtitle_evidence`: read only the source and time range currently needed.
- `prepare_subtitle_review`: optionally suggest fixed OCR/ASR review windows. It is
  not a prerequisite for using evidence.
- `get_subtitle_review_window` and `submit_subtitle_review_window`: optionally
  persist a complete window-by-window reviewed subtitle.
- `read_subtitle_artifact`: read reports or bounded text artifacts that are not
  naturally addressed by subtitle time.

## Evidence loop

Use the smallest useful loop:

1. Observe the current state or evidence catalog.
2. Form a concrete question, such as whether a platform track exists or whether
   OCR missed speech near a timestamp.
3. Call the narrowest tool that can answer that question.
4. Compare the returned evidence semantically.
5. Stop when the requested confidence is reached; otherwise obtain another source
   or a narrower range.

Do not run ASR, OCR, review-window generation, or full-video review merely because
the capability exists.

## Evidence boundaries

- Platform, hard-OCR, and audio-ASR outputs are independent evidence. Preserve and
  identify the source supporting each correction.
- `selected_source` is a convenience default, not a truth claim.
- `fusion_status=independent_evidence` is a valid completed extraction state.
- Raw artifacts are immutable. Corrections belong in derived artifacts.
- Compare different-language OCR and ASR by meaning within overlapping time
  ranges, not by character similarity.
- ASR can reveal OCR omissions but cannot independently prove homophonic names,
  numbers, or terminology spellings.
- Keep uncertain claims unresolved or obtain more evidence. Never silently replace
  publisher subtitles with a plausible model answer.
- `EMPTY_RESULT` only means the platform exposed no usable subtitle track.

## Extraction choices

For a low-risk request, use the default extraction behavior. It returns a Bilibili
platform track when available and otherwise falls back to hard OCR; ASR stays off.

For high-value or terminology-heavy material, consider
`collect_all_sources=true` and `asr_backend=qwen3`. This collects evidence; it does
not require reconciling every cue.

For a known conflict, prefer targeted acquisition with `time_start` / `time_end`
for OCR or `asr_time_start` / `asr_time_end` for ASR. Whole-video ASR should
normally run without context. Use `asr_context` only for verified spelling
candidates such as names, organizations, acronyms, and technical terms.

## Optional review helper

Use fixed review windows only when the user needs a fully reconciled subtitle or a
heuristic index would save context. Flags are suggestions, not conclusions. High
priority does not mean wrong, and an unflagged cue can still be wrong.

## CLI fallback

If MCP is unavailable, use the same contract through the JSON CLI:

```powershell
video-subtitle doctor
video-subtitle --home .\.video-subtitle start "<bilibili-url>"
video-subtitle --home .\.video-subtitle status "<job-id>"
video-subtitle evidence-list --manifest ".\result\manifest.json"
video-subtitle evidence-read --manifest ".\result\manifest.json" `
  --evidence-id ev-0001 --start-ms 360000 --end-ms 390000
```

The optional batch-review helpers remain available:

```powershell
video-subtitle review-prepare --manifest ".\result\manifest.json"
video-subtitle review-window --manifest ".\result\manifest.json" --window-id rw-0001
video-subtitle review-apply --manifest ".\result\manifest.json" --decisions ".\review-decisions.json"
```
