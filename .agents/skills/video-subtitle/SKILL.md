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

Treat setup output as the capability truth and
[`requirements/runtime-lock.json`](../../../requirements/runtime-lock.json) as
the heavy-runtime version truth. Bootstrap installs the repository Python/MCP
layer; it does not silently download VideOCR, ASR environments, or models. When
setup returns one of those actions, run the read-only plan first:

```powershell
python scripts/runtime_setup.py plan videocr
python scripts/runtime_setup.py plan asr
python scripts/runtime_setup.py plan qwen_asr_model
```

Use the plan's exact variant, profile, revision, destination, and next command.
Before `install`, show the user the known byte cost and lock SHA-256 and obtain
confirmation for every action that requires `--confirm-large-download`. Run
`verify` afterward, persist only the discovered executable or model path, rerun
setup, and then run doctor. Never replace a pinned revision with `latest` merely
because an upstream release is newer.

If the MCP server and CLI are not installed but the repository is available,
run this from the repository root:

```powershell
python scripts/bootstrap.py
python scripts/bootstrap.py --apply `
  --config .video-subtitle-local/config.json `
  --capability platform_subtitle
```

The first command reports bootstrap actions without changing the environment.
The second creates `.venv`, installs the package with MCP support, and returns
one `video-subtitle/bootstrap-v2` JSON document. Its `skills`, `cli`, and `mcp`
sections are the discovery and invocation contract; its nested `setup` section
continues the capability action loop. Use an explicit `--config` path for an
isolated checkout, CI run, or reproducibility audit so host configuration does
not silently affect the result.

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
- `plan_hard_subtitle_scout`: calculate opening, quarter, middle,
  three-quarter, and ending OCR windows from a duration. It merges overlaps and
  reports coverage; it never decides whether hard subtitles exist.

Optional full-subtitle review:

- `prepare_subtitle_review`
- `get_subtitle_review_window`
- `submit_subtitle_review_window`

The review tools are helpers, not a mandatory pipeline.

## Downstream content handoff

If the user provides only a video URL, video file, audio file, or subtitle file
without naming a desired deliverable, finish the required subtitle evidence
work first. Then stop and ask whether the user wants only the organized
subtitle or wants it transformed into a specific carrier. You may recommend a
carrier, but do not choose or generate one without either an explicit carrier
request or explicit delegation of that decision.

When the user has requested an article, one-page visual, card series, brief,
script, or another carrier, use the
[`video-to-content` Skill](../video-to-content/SKILL.md). That Skill pins this
job's evidence, reconstructs a medium-independent content map, records the
user-authorized carrier, and requires a fidelity audit before delivery. If the
carrier was already specified in the initial request, continue without asking
the same question again.

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

Platform subtitle availability and burned-in hard-subtitle presence are two
independent observations. Never use one as a proxy for the other:

1. Query platform subtitles first because lookup is cheap. Preserve the track as
   independent evidence and keep its human-versus-ASR provenance unresolved unless
   the platform actually proves it.
2. Independently determine whether the picture contains continuous editorial hard
   subtitles. A usable platform track does not permit skipping this decision.
3. If continuous hard subtitles exist, run full-video OCR even when platform
   subtitles are available. For edited explainers, interviews, translated videos,
   and terminology-heavy material, OCR is normally the primary evidence for what
   the publisher chose to display; platform subtitles and ASR are checkers.
4. Skip full-video OCR only after visual scouting establishes that continuous hard
   subtitles are absent, or when direct source knowledge already establishes that
   fact. Do not infer absence from sparse OCR cues alone.
5. Use ASR as the fallback when no usable text track exists and as an independent
   semantic checker when risk, language, names, numbers, or terminology justify it.

When continuous hard subtitles are uncertain, call
`plan_hard_subtitle_scout` regardless of whether platform subtitles exist. Run the
returned windows with `time_start` and `time_end`, then inspect their frames, cue
density, text role, and continuity. A few title cards are not continuous subtitles,
while one sparse or failed OCR window is not proof that subtitles are absent. The
calling Agent owns this semantic decision. Skip the scout when the source is
already known to contain or not contain continuous hard subtitles, or when the
plan's coverage approaches the full duration and therefore saves no work.

Use `ocr_backend=none` and `asr_backend=none` only for an intentional platform-only
probe. Once OCR or ASR is explicitly requested, the extraction job must not let a
platform subtitle track short-circuit that request. Use
`collect_all_sources=true` when the manifest should make the multi-source intent
explicit. Do not run full-video ASR, double-scale OCR, or full review solely because
the capability exists.

For a known conflict, prefer `time_start` / `time_end` for OCR and
`asr_time_start` / `asr_time_end` for ASR. Use `asr_context` only for verified
spelling candidates such as names, organizations, acronyms, and technical terms;
it is not a source of truth.

## Download reliability and cache

Background jobs default to a persistent media cache under
`<VIDEO_SUBTITLE_HOME>/cache/media`. Cache identity includes platform, BVID,
selected part, and requested quality. Reuse a completed cache entry across OCR
and ASR jobs instead of downloading the same media again.

OpenCLI browser commands default to a 180-second timeout in this project and
transient download failures receive two bounded retries with linear backoff.
Persist host-specific values only after observing the actual environment:

- `opencli_browser_timeout` / `VIDEO_SUBTITLE_OPENCLI_BROWSER_TIMEOUT`;
- `download_retries` / `VIDEO_SUBTITLE_DOWNLOAD_RETRIES`;
- `download_retry_backoff` / `VIDEO_SUBTITLE_DOWNLOAD_RETRY_BACKOFF`;
- `download_cache` / `VIDEO_SUBTITLE_DOWNLOAD_CACHE`.

Do not trust OpenCLI's display-oriented `size` field as file evidence. Read
`actual_bytes`, `actual_mib`, `cache_key`, `cache_hit`, `cache_state`,
`retry_index`, `attempt_count`, and the artifact path from the manifest; those
values are derived from the file that actually landed.
If OpenCLI reports an unknown command result but a completed media file exists,
the adapter records that recovery rather than downloading it again.

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
video-subtitle configure --profile browser-bridge-profile `
  --videocr C:\path\videocr-cli.exe `
  --opencli-browser-timeout 180 --download-retries 2 `
  --download-retry-backoff 2 --download-cache C:\path\media-cache
video-subtitle doctor --capability platform_subtitle --capability hard_ocr_url

video-subtitle ocr-scout-plan --duration-seconds 3600 --window-seconds 20

video-subtitle --home .\.video-subtitle start "<bilibili-url>" `
  --collect-all-sources --asr-backend qwen3 --media-execution auto
video-subtitle --home .\.video-subtitle status "<job-id>"
video-subtitle evidence-list --manifest ".\result\manifest.json"
video-subtitle evidence-read --manifest ".\result\manifest.json" `
  --evidence-id ev-0001 --start-ms 360000 --end-ms 390000
```

For an offline reproducibility audit of the repository itself, run
`python scripts/repro_check.py --require-tier core --require-tier agent`. Add the
`media` tier only with an explicit working FFmpeg or FFprobe path. Never infer
current Bilibili login, GPU OCR/ASR behavior, or other live-service readiness
from deterministic fixture results.

Report the final source coverage, unresolved conflicts, warnings, and relevant
host-specific timing. Do not report a precision percentage unless it was
measured against an independently verified reference transcript.
