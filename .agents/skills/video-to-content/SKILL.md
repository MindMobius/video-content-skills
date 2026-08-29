---
name: video-to-content
description: Transform a verified video Transcript into a source-faithful written edition or other requested carrier. Use only after durable Evidence and a usable or verified Transcript exist.
---

# Video to Content

This Skill changes medium, not authorship. The Transcript is the only textual
source of truth; raw Evidence remains available for delivery, visual-reference,
and high-risk checks.

The default output is a source-faithful written edition. Preserve the source
structure, speaker roles, professional density, examples, uncertainty, and
voice. Do not treat a carrier such as WeChat as permission to reauthor the
video.

All temporary manuscripts, frame candidates, previews, and audit material must
stay in the current Job or `runs/<run_id>/`; do not write them as
`current-*`/`latest-*` files or directories at the state-root top level.
Reusable helpers belong in the repository `scripts/` directory and must not be
invented inside the active state root.

## Read progressively

- Default editorial boundary: [source-faithful-adaptation.md](references/source-faithful-adaptation.md)
- After a complete draft exists, review only Agent-added carrier language:
  [source-aware-expression-audit.md](references/source-aware-expression-audit.md)
- Traceability and omission rules: [traceability.md](references/traceability.md)
- Content completion, failure classification, and recovery: [content-acceptance.md](references/content-acceptance.md)
- WeChat article manuscript and renderer: [wechat-article.md](references/wechat-article.md)
- Selecting and checking source frames: [source-frame-selection.md](references/source-frame-selection.md)

## Preconditions

- A Job has a saved Transcript with `quality.status=usable|verified`.
- The user requested a carrier, or an active automation Profile already selected
  one. Outside automation, do not invent a carrier from a bare video link.
- The intended audience and purpose are understood. Unless the user explicitly
  requested an editorial departure, use the source-faithful default.

## Main flow

1. Read the complete Transcript, corrections, uncertainties, and Evidence
   references.
2. Build an ephemeral source map: source type, speakers and roles, source
   structure, terms, examples, source-owned analogies, counterexamples,
   caveats, visual references, and tone. Do not persist it as a new product.
3. Inspect source-video ranges when speaker changes, delivery, visual references,
   or uncertain wording affect the written edition. Do not derive new textual
   facts outside the Transcript.
4. Produce a readable written edition in the source structure. Repair
   transcription and translation, remove only oral noise, and adapt paragraphing
   without mechanically turning every cue into a paragraph. Cue concatenation,
   fixed-length paragraphing, and regex punctuation are preprocessing only; they
   are not Agent review and must not be marked as a passed written edition.
5. Summary, audience rewrite, style imitation, a new thesis, a new analogy, or
   material reorder are allowed only when explicitly requested. Record every
   such departure in the audit.
6. For video-derived imagery, use only the original cover and timestamped source
   frames by default. Identify material visual or argument transitions, extract
   nearby candidates, inspect them, and place the selected frame at the matching
   passage. A Profile minimum is a floor, not a target; long or visually dense
   videos normally require more frames. Never satisfy the contract with evenly
   spaced filler screenshots. If scout evidence proves a static source with no
   material visual transitions, record an approved `visual_exception` with the
   scout Artifact IDs instead of duplicating meaningless frames.
7. Build the carrier document and an explicit source-fidelity audit. When the
   active Profile selects `source_faithful_full`, include `adaptation_mode`,
   `visual_policy`, `material_sections.items`, `omissions`, and a per-frame
   `visual_plan`. Every material section maps Transcript cue indices to output
   block indices; every frame records `artifact_id`, `timestamp_ms`,
   `block_index`, and placement reason.
8. Read [content-acceptance.md](references/content-acceptance.md), inspect the
   actual body at the opening, middle, and ending, and distinguish a concise
   source-faithful edition from an over-compressed summary.
9. Read [source-aware-expression-audit.md](references/source-aware-expression-audit.md).
   Review title, summary, headings, transitions, evidence-boundary language,
   material details, and the ending. Change only Agent-added or carrier-adaptation
   scaffolding; retain source-owned contrasts, lists, questions, metaphors, and
   professional phrasing. Record the result as `audit.expression_audit` and then
   recheck source fidelity.
10. For `wechat_article`, prefer `scripts/render_wechat_article.py`; it creates
   clean HTML, preview, local assets, and one-line relative image markers.
11. Save Content with `content_save`, then require `content_validate.valid=true`.
   A `raw Transcript passthrough` or invalid `expression_audit` error is a hard
   stop: return to Content and repair the actual body before any WeChat handoff.
   Do not bypass either check by changing audit labels or adding cosmetic edits.

A render result, article length, media Artifact list, or valid HTML is not Content
completion. A source frame counts only when it is an actual ordered image block in
the carrier document and its audit points to that exact block. If material details,
professional qualifiers, or the source's argument progression disappeared, Content
is incomplete even when every mechanical field is present.

## Audit

The audit must be Agent-authored and state `passed` or `approved` only after
reading the actual body at the opening, middle, and ending, then checking:

- every material section remains traceable to Transcript or cited Evidence
  ranges;
- source structure, speaker roles, attribution, counterexamples, and important
  limits remain intact unless the user explicitly requested a departure;
- no new thesis, analogy, scene, causality, certainty, or conclusion was added;
- transcription cleanup did not remove meaningful repetition or professional
  detail;
- professional density, humor, emotional intensity, and overall source voice did
  not drift for the carrier;
- material omissions, compression, reorder, and editorial additions are listed;
- title and summary do not overclaim or promote a minor detail into the main
  claim;
- `expression_audit` reviews Agent-added carrier language with
  `policy=source_aware_minimal`, preserves source-owned expression, and records
  every revised or deliberately retained rule hit against the final document;
- every image is an original cover or timestamped source frame;
- every material section has an explicit source-to-output mapping, all are
  preserved, and omissions are explicit;
- every source frame is tied to a meaningful passage, visually inspected, and
  present at the audited document block;
- the output contains no persisted Base64 image or secret-bearing URL.

Do not use article-to-Transcript character ratio or lexical overlap as a target
for gratuitous rewriting. The deterministic passthrough check combines several
high-risk signals only; the Agent must still judge whether material examples,
questions, limits, disagreements, and professional detail remain.

## Boundaries

- Do not infer a house style from the requested carrier. Source-aware expression
  review is not a fixed WeChat style and never authorizes full-text rewriting.
- Do not generate diagrams, illustrations, stock images, or synthetic visual
  summaries unless the user separately requested or approved them.
- Content validation does not authorize a platform action.
- Do not log in, upload, save a draft, publish, schedule, or mass-send from this
  Skill.
