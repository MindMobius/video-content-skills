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

## Read progressively

- Default editorial boundary: [source-faithful-adaptation.md](references/source-faithful-adaptation.md)
- Traceability and omission rules: [traceability.md](references/traceability.md)
- WeChat article manuscript and renderer: [wechat-article.md](references/wechat-article.md)

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
   without mechanically turning every cue into a paragraph.
5. Summary, audience rewrite, style imitation, a new thesis, a new analogy, or
   material reorder are allowed only when explicitly requested. Record every
   such departure in the audit.
6. For video-derived imagery, use only the original cover and timestamped source
   frames by default. Place them where the source uses the corresponding visual
   evidence; use fewer images rather than filler.
7. Build the carrier document and an explicit source-fidelity audit.
8. For `wechat_article`, prefer `scripts/render_wechat_article.py`; it creates
   clean HTML, preview, local assets, and one-line relative image markers.
9. Save Content with `content_save`, then require `content_validate.valid=true`.

## Audit

The audit must be Agent-authored and state `passed` or `approved` only after
checking:

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
- every image is an original cover or timestamped source frame;
- the output contains no persisted Base64 image or secret-bearing URL.

## Boundaries

- Do not infer a house style from the requested carrier.
- Do not generate diagrams, illustrations, stock images, or synthetic visual
  summaries unless the user separately requested or approved them.
- Content validation does not authorize a platform action.
- Do not log in, upload, save a draft, publish, schedule, or mass-send from this
  Skill.
