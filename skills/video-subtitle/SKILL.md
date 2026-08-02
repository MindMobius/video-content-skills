---
name: video-subtitle
description: Retrieve, inspect, and verify subtitle evidence from supported video links or local files. Use for Bilibili metadata and platform subtitles, hard-subtitle OCR, audio ASR, timestamped evidence comparison, and auditable subtitle correction.
---

# Video Subtitle

Use this Skill when a task depends on what a video actually says or displays.
Do not infer a transcript or summary from metadata alone.

The tools acquire and preserve evidence. You decide which capabilities are
needed, which source and time range to inspect, how to compare meanings, and
when the evidence is sufficient. Do not turn semantic judgment into a fixed
script.

## Mandatory environment loop

Run this loop before the first extraction on a machine and whenever a requested
capability changes:

1. Select only the capabilities required by the task.
2. Call `video_subtitle_setup` with those capability IDs.
3. Execute every safe `agent_action` yourself. If an action has
   `confirmation_required=true`, obtain confirmation before the large download.
4. Ask the user only for entries under `human_actions` that remain after Agent
   actions are complete.
5. Persist discovered paths and the Browser Bridge profile alias with
   `configure_video_subtitle`.
6. Rerun setup. Do not start extraction until `ready=true` for the requested
   capabilities.
7. Call `video_subtitle_doctor` with `deep=true` before using ASR or before
   enabling shared-GPU parallel execution.

If the MCP server and CLI are not installed but the repository is available,
run this from the repository root:

```powershell
python scripts/bootstrap.py
python scripts/bootstrap.py --apply --capability platform_subtitle
```

The first command reports bootstrap actions without changing the environment.
The second creates `.venv`, installs the package with MCP support, and returns
the setup report. Continue with the same action loop.

Never ask the user to paste cookies, passwords, or tokens. The Bilibili human
step is to connect OpenCLI Browser Bridge, log in in the browser, and provide the
profile alias. Hardware, browser login, OS privilege prompts, and explicitly
confirmed large model downloads are legitimate human boundaries; locating
executables and installing ordinary dependencies are Agent work.

## Capability IDs

- `platform_subtitle`: Bilibili metadata and exposed subtitle tracks.
- `video_download`: authenticated source-video acquisition.
- `hard_ocr_local`: VideOCR on an existing local video.
- `hard_ocr_url`: Bilibili download plus VideOCR.
- `audio_asr_local`: Qwen3-ASR plus Forced Aligner on a local video.
- `audio_asr_url`: Bilibili download plus Qwen3-ASR.

Do not request `all` merely because it exists. A fast Bilibili summary normally
needs `platform_subtitle` and `hard_ocr_url`; high-value cross-checking may also
need `audio_asr_url`.

## Current provider boundary

Bilibili ordinary links, short links, and multipart videos are supported through
OpenCLI and its Browser Bridge login state. Local video paths can bypass
download. YouTube and Douyin adapters are not implemented yet. Do not claim
support merely because OCR and ASR are platform-independent.

## Tool map

Environment:

- `video_subtitle_setup`: return machine-readable dependency states plus Agent
  and human actions.
- `configure_video_subtitle`: persist non-secret paths, profile aliases, job
  home, and media scheduling policy.
- `video_subtitle_doctor`: verify paths, browser login, OCR, ASR, CUDA, and GPU
  memory. Use `deep=false` for a quick check and `deep=true` before heavy work.

Acquisition:

- `inspect_bilibili_video`: inspect metadata and multipart selection without
  extraction.
- `start_subtitle_extraction`: start a durable acquisition job.
- `get_subtitle_job`: poll state, attempts, warnings, scheduling, and artifacts.

Evidence:

- `list_subtitle_evidence`: discover immutable, time-addressable sources.
- `read_subtitle_evidence`: read only the selected source and time range.
- `read_subtitle_artifact`: read bounded non-timeline reports or text artifacts.

Optional full-subtitle review:

- `prepare_subtitle_review`
- `get_subtitle_review_window`
- `submit_subtitle_review_window`

The review tools are helpers, not a mandatory pipeline.

## Downstream content handoff

When the user's goal continues beyond subtitles into an article, one-page
visual, card series, brief, script, or another carrier, finish the required
subtitle evidence work and then use the
[`video-to-content` Skill](../video-to-content/SKILL.md). That Skill pins this
job's evidence, reconstructs a medium-independent content map, selects one
suitable carrier, and requires a fidelity audit before delivery.

Do not bypass the handoff by summarizing metadata or an unresolved evidence
bundle directly. Subtitle correction and content transformation are separate
derived layers; neither may rewrite raw evidence.

## Acquisition policy

Use the smallest useful loop:

1. Observe metadata, job state, or the evidence catalog.
2. Form one concrete question.
3. Call the narrowest tool and time range that can answer it.
4. Compare the returned evidence semantically.
5. Stop when the user's requested confidence is reached; otherwise obtain one
   more independent source or a narrower rerun.

Default extraction prefers:

```text
platform subtitle > hard OCR > audio ASR
```

This is only a convenience order, not a truth ranking. Platform lookup should
come first because it is cheap. When it is absent, hard-subtitle OCR is the main
source for videos whose editorial text is burned into the picture. ASR is a
fallback for videos without visible subtitles and an independent checker for
important or terminology-heavy material.

For quick, low-risk work, use the default behavior. For high-value material,
consider `collect_all_sources=true` and `asr_backend=qwen3`. Do not run full-video
ASR, double-scale OCR, or full review solely because the capability exists.

For a known conflict, prefer `time_start` / `time_end` for OCR and
`asr_time_start` / `asr_time_end` for ASR. Use `asr_context` only for verified
spelling candidates such as names, organizations, acronyms, and technical terms;
it is not a source of truth.

## OCR and ASR scheduling

OCR and ASR are independent media jobs and their evidence is merged in a stable
order after both finish.

- `media_execution=auto`: run in parallel when the configured backends do not
  share the GPU; use serial execution when GPU VideOCR and Qwen3-ASR share it.
- `media_execution=serial`: always minimize concurrent resource pressure.
- `media_execution=parallel`: explicit opt-in. Use only after a deep doctor check
  and a representative workload validation show that concurrent execution is
  both stable and faster. Available GPU memory proves only that the processes
  may fit; it does not prove throughput. Match the validation to OCR resolution,
  consensus passes, video shape, and ASR settings.

Persist a proven host policy with `configure_video_subtitle`; otherwise leave it
at `auto`. Treat benchmark results as host-specific evidence, never as a general
performance guarantee.

## Evidence boundaries

- Platform subtitles, hard OCR, and audio ASR remain independent evidence.
- `selected_source` is a reading default, not a truth claim.
- `fusion_status=independent_evidence` is a valid completed state.
- Raw artifacts are immutable. Corrections must be new derived artifacts with
  source IDs, reasons, and timestamps.
- `EMPTY_RESULT` means only that the platform exposed no usable track.
- Double-scale OCR agreement proves repeatability across image scales, not that
  the burned-in subtitle itself is factually or orthographically correct.
- ASR can reveal OCR omissions or implausible wording, but it cannot alone prove
  homophonic names, numbers, symbols, or specialist spelling.
- For foreign audio with translated hard subtitles, align by overlapping time
  and meaning. Do not compare strings or silently replace the translation with
  ASR output.
- If OCR and ASR conflict on a consequential term, inspect the source frame,
  title/description, on-screen title cards, and an authoritative external source.
  Leave the item unresolved when evidence remains insufficient.

## CLI fallback

The JSON CLI exposes the same contract when MCP is unavailable:

```powershell
video-subtitle setup --capability platform_subtitle --capability hard_ocr_url
video-subtitle configure --profile browser-bridge-profile --videocr C:\path\videocr-cli.exe
video-subtitle doctor --capability platform_subtitle --capability hard_ocr_url

video-subtitle --home .\.video-subtitle start "<bilibili-url>" `
  --collect-all-sources --asr-backend qwen3 --media-execution auto
video-subtitle --home .\.video-subtitle status "<job-id>"
video-subtitle evidence-list --manifest ".\result\manifest.json"
video-subtitle evidence-read --manifest ".\result\manifest.json" `
  --evidence-id ev-0001 --start-ms 360000 --end-ms 390000
```

Report the final source coverage, unresolved conflicts, warnings, and relevant
host-specific timing. Do not report a precision percentage unless it was
measured against an independently verified reference transcript.
