# Evidence decisions

## Platform subtitle

Useful when it is complete and aligned. A machine-generated platform track is
still evidence, not truth. Inspect suspicious names, numbers, terminology, and
timing.

## Visual hard subtitle

Run the scout whenever continuity is uncertain, even if a platform track
exists. Inspect sampled frames for text role, position, density, and continuity:
logos, comments, titles, and occasional labels are not continuous subtitles.
If continuous subtitles are present, full-video OCR is required.

## Audio ASR

Use ASR when speech is missing from visual text, OCR has gaps, or high-value
claims require an independent acoustic check. ASR must not silently replace
platform or OCR evidence.

## Corrections

A correction needs a time range, original reading, replacement, evidence IDs,
and reason. Preserve raw artifacts. Save the normalized result only as a new
Transcript.

## Failure classification

- network/tool/runtime failure: `retryable`
- real login boundary: `paused_auth`
- media physically cannot provide enough evidence: `unprocessable`
- evidence is sufficient for Agent normalization: continue to Transcript
