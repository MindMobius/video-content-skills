---
name: video-to-content
description: Transform verified video subtitle evidence into a traceable content map and one suitable medium such as an article, one-page visual, card series, brief, or script. Use when the user wants to understand, condense, republish, or share a video's information without losing claims, evidence, caveats, attribution, or uncertainty.
---

# Video to Content

Use this Skill after a video has at least one readable subtitle evidence source.
The default goal is faithful information transfer, not engagement optimization.

The tools preserve state, validate references, version artifacts, and detect
stale sources. You perform semantic reconstruction, medium selection, writing,
visual planning, and fidelity judgment. Do not replace those decisions with a
fixed summarization script.

## Entry conditions

For a video URL or local video without a completed subtitle job, use the
`video-subtitle` Skill first. Do not build a content map from title,
description, or metadata alone.

When a completed subtitle job already exists:

1. List its evidence sources.
2. Resolve consequential subtitle conflicts or record them as unresolved.
3. Call `initialize_video_content` with the user's actual objective, audience,
   and output language.

The content layer adds no OCR, ASR, browser, model, or rendering dependency. It
uses the evidence already collected by `video-subtitle`. A requested final
format may require a separate renderer available to the calling Agent.

## Mandatory workflow

### 1. Reconstruct the content before choosing a medium

Read [`prompts/build-content-map.md`](prompts/build-content-map.md) and
[`references/traceability.md`](references/traceability.md).

Use `get_video_content_project` to inspect the pinned evidence snapshot. Read
subtitle evidence in bounded time ranges. For a long video, progressively cover
the timeline and accumulate a semantic map; do not place the entire transcript
in context merely because it fits.

Author a `video-content/content-map-v1` document and save it with
`save_video_content_document(kind="content_map")`.

The map is canonical and independent of the eventual carrier. Its timestamps
preserve traceability; its sections describe semantic relationships and do not
need to follow the video's sequence. It must contain:

- actual analysis coverage and omitted ranges;
- evidence excerpts with source IDs and timestamps;
- attributed claims and their evidence references;
- caveats, counterpoints, terms, visual references, and uncertainties when
  present;
- Agent synthesis only in `agent_inferences`, never disguised as speaker text;
- `external_verification=not_checked` unless an external source was actually
  checked.

Subtitle evidence proves what the video says or displays. It does not by itself
prove that the claim is factually correct.

### 2. Select one suitable medium

Read [`prompts/select-medium.md`](prompts/select-medium.md) and
[`references/media-routing.md`](references/media-routing.md).

If the user explicitly requested a medium, honor it unless the requested
compression would materially distort the content; explain that conflict before
changing the medium. Otherwise choose from content topology:

- `article`: deep argument, high context dependency, important qualifications;
- `one_page`: one clear structure that remains truthful under strong compression;
- `card_series`: modular ideas that need sequence but not long-form continuity;
- `brief`: rapid orientation with a small number of core conclusions;
- `script`: a spoken adaptation whose delivery and transitions matter;
- `custom`: a user-specified carrier not covered above.

Save one `video-content/media-plan-v1` document. Record rejected alternatives,
required claims and caveats, every deliberate omission, the carrier-specific
restructuring strategy, and the intended narrative voice. Do not generate all
possible media by default.

For a single-author monologue, default to `narrative_voice.mode=source_author`:
write from the source author's perspective instead of wrapping the content in
phrases such as “这个视频认为” or “作者表示”. For interviews or multi-speaker
material, preserve speaker identities unless the user explicitly requests a
separate editorial voice.

### 3. Create the deliverable

Read [`prompts/create-deliverable.md`](prompts/create-deliverable.md).

Create the selected artifact using your own language and reasoning. Rebuild its
information architecture for the selected carrier: claims may be merged,
split, reordered, foregrounded, or moved into supporting context. Source order
is evidence metadata, not a layout template. Use an
available rendering or image skill only when it materially improves the chosen
carrier. Rendering may improve hierarchy and appearance; it must not decide
what the source means.

Call `save_video_content_deliverable` with:

- the selected medium and actual serialization format;
- the final content;
- every claim ID represented in the artifact;
- every caveat ID represented in the artifact.

The tool rejects a deliverable that omits elements marked as required by the
media plan. Each revision is stored separately.

### 4. Audit fidelity before delivery

Read [`prompts/audit-fidelity.md`](prompts/audit-fidelity.md).

Perform a fresh semantic pass over the deliverable, current content map, and
relevant subtitle ranges. Check every material statement, not only the title
and outline. Save a `video-content/fidelity-audit-v1` document.

- `pass`: all material statements are faithful and all required elements exist;
- `pass_with_warnings`: no semantic error remains, but non-blocking limitations
  must be disclosed;
- `fail`: unsupported claims, distortion, hidden uncertainty, missing context,
  missing caveats, attribution errors, or translation errors remain.

On `fail`, revise the deliverable, save a new revision, and audit that new
revision. Never relabel an error as a warning to finish the workflow.

Call `validate_video_content_project` before final delivery. Deliver only when
`ready_for_delivery=true`.

## Tool map

Content project:

- `initialize_video_content`: pin the subtitle manifest and evidence hashes.
- `get_video_content_project`: inspect lifecycle, artifact IDs, and integrity.
- `validate_video_content_project`: detect changed sources, changed artifacts,
  missing audits, and stale audits.

Agent-authored artifacts:

- `save_video_content_document`: validate and version `content_map`,
  `media_plan`, or `fidelity_audit` JSON.
- `save_video_content_deliverable`: version the final Markdown, HTML, SVG, JSON,
  or text artifact and bind it to claim/caveat IDs.
- `read_video_content_artifact`: read a bounded current or historical artifact.

Subtitle evidence remains available through `list_subtitle_evidence` and
`read_subtitle_evidence`.

The JSON CLI exposes the same lifecycle:

```powershell
video-subtitle content-init --manifest .\result\manifest.json
video-subtitle content-save --project .\content\<project-id>\project.json `
  --kind content_map --document .\content-map.json
video-subtitle content-save --project .\content\<project-id>\project.json `
  --kind media_plan --document .\media-plan.json
video-subtitle content-deliverable `
  --project .\content\<project-id>\project.json `
  --medium article --format markdown --content-file .\article.md `
  --title "..." --used-claim-id claim-0001
video-subtitle content-save --project .\content\<project-id>\project.json `
  --kind fidelity_audit --document .\fidelity-audit.json
video-subtitle content-validate --project .\content\<project-id>\project.json
```

See [`references/contracts.md`](references/contracts.md) for schema locations,
artifact versioning, and field semantics.

## Hard boundaries

- Never edit or overwrite platform subtitle, OCR, ASR, or reviewed subtitle
  evidence.
- Never treat source agreement as external factual verification.
- Never manufacture a quote from a paraphrase or translation.
- Never mistake a changed section order for a fidelity error; audit meaning,
  attribution, certainty, and necessary context instead.
- Never add an external narrator wrapper to a single-author adaptation whose
  media plan calls for the source author's voice.
- Never silently remove a limitation that changes a conclusion.
- Never optimize emotion, stance, click-through, or conversion unless the user
  explicitly asks for that separate objective.
- Never choose a visual carrier merely because it looks more shareable. Choose
  it only when the content remains understandable and accurate after visual
  compression.
- Never claim full-video coverage when only selected ranges were read.

Final reporting must state the selected medium, analysis coverage, unresolved
uncertainties, audit status, and deliverable artifact ID.
