# Build Content Map

Use this reasoning frame to author `video-content/content-map-v1`. Do not ask a
script to infer these fields.

## Inputs

- content project state and pinned evidence IDs;
- video metadata;
- subtitle evidence read in bounded time ranges;
- resolved subtitle corrections and unresolved conflicts;
- the user's objective and requested output language.

## Task

Reconstruct the video's semantic structure before considering presentation.

1. Record exactly which evidence IDs and timeline ranges were analyzed.
2. Identify the video's content type and write a neutral summary.
3. Create timestamped `evidence_refs` from actual returned cues. Preserve the
   source language in the excerpt; translate in claim text when needed.
4. Express each material proposition as a claim. Attribute it to a speaker,
   publisher, or explicit Agent synthesis.
5. Separate direct source support from contextual or contested support.
6. Record caveats, counterpoints, defined terms, useful visual moments, and
   uncertainties. Empty arrays are valid only when the source genuinely lacks
   that category.
7. Put any cross-section synthesis in `agent_inferences`, with its evidence and
   reasoning. Do not place it in a speaker-attributed claim.
8. Build conceptual sections that expose the argument or explanatory structure.
   They may merge, split, or reorder source ranges. Timestamps belong to
   evidence references for traceability; they do not prescribe section order.

## Quality gate

Before saving, verify:

- every claim has at least one valid evidence reference;
- exact names, numbers, symbols, and specialist terms were checked against the
  strongest available evidence;
- foreign audio and translated hard subtitles were compared by meaning and
  overlapping time, not string similarity;
- `external_verification` does not exceed what was actually checked;
- partial coverage and unresolved ambiguity are explicit;
- sections reflect semantic relationships rather than the playback timeline;
- no target-medium wording or layout choice has leaked into the canonical map.

Return the JSON document required by
[`../../../../schemas/content-map.schema.json`](../../../../schemas/content-map.schema.json).
