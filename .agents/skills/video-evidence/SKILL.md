---
name: video-evidence
description: Acquire and verify evidence from a Bilibili video URL or local video, audio, or subtitle file. Use for metadata, platform subtitle tracks, persistent downloads, hard-subtitle scouting and OCR, audio ASR, timestamped comparison, and Agent-authored Transcript correction.
---

# Video Evidence

Use this Skill whenever the answer depends on what a video actually says or
shows. Metadata is never a transcript.

The repository collects durable observations; the Agent makes semantic and
visual judgments. Preserve platform, OCR, ASR, and reviewed material as
separate immutable artifacts.

## Runtime files

Use the repository's single runtime context: `.video-content/config.json` and
its configured `home`. Store durable Job artifacts through the Store; put
one-off logs, sampled frames, and intermediate reports under
`runs/<run_id>/`, then archive them under `archive/<date>-<reason>/` when the
run is over. Never create batch-named directories or loose JSON/scripts at the
state-root top level, and never use a parallel `.video-content-local` root.

## Read progressively

Read only what the current task needs:

- Environment missing or capability not ready: [environment.md](references/environment.md)
- Deciding between platform subtitle, OCR, and ASR: [evidence-decisions.md](references/evidence-decisions.md)
- Normalizing a final Transcript: [transcript.md](references/transcript.md)

## Main flow

1. Identify the input and requested outcome. Current URL support is Bilibili;
   local media and subtitle files may bypass platform download.
2. Request only the required capabilities through `system_setup`. Execute safe
   `agent_actions`; ask the user only for remaining `human_actions` or a
   confirmed large download.
3. Require `setup.ready=true` for the selected capabilities. Run a deep
   `system_doctor` before ASR or explicit shared-GPU parallelism.
4. Call `source_inspect`, then `evidence_start`.
5. Treat a platform subtitle track and visible hard subtitles as independent
   facts. Platform availability never proves OCR is unnecessary.
6. When continuous hard subtitles are uncertain, use the deterministic scout
   plan and inspect sampled frames. Sparse OCR text is not proof of absence.
7. If continuous hard subtitles exist, run full-video OCR. Use ASR when audio is
   needed to fill or cross-check gaps. Keep OCR and ASR serial on a shared GPU
   unless the current machine has been explicitly verified for parallel use.
8. Inspect artifacts by time range and compare meaning. Never overwrite a raw
   source with a corrected one.
9. Save one Agent-authored Transcript with `transcript_save`, including selected
   Evidence IDs, corrections, unresolved uncertainty, and a quality conclusion.

## Source priority is not a fixed rule

A usable platform track is often the fastest evidence. Hard OCR can represent
what viewers saw. ASR can recover speech that was never shown or detect OCR
omissions. The best Transcript may use different sources for different ranges.
The Agent must explain material corrections instead of silently choosing one
source globally.

## Physical limits

If the media has no usable audio, readable text, or obtainable source, record
`unprocessable` and continue with other jobs. This is a physical result, not a
question the user can solve. Retry technical failures; use `paused_auth` only
for a real browser authentication boundary.

## Boundaries

- Never request cookies, passwords, tokens, or browser storage.
- Do not claim YouTube or Douyin URL support.
- Preserve the download cache across related retries and jobs.
- Treat actual file bytes in the manifest as authoritative.
- Do not transform the Transcript into an article unless the user requested a
  carrier or an active automation Profile already selected one.
