---
name: video-to-content
description: Transform a verified video Transcript into an audited article or other requested carrier. Use only after durable Evidence and a usable or verified Transcript exist.
---

# Video to Content

This Skill changes form, not evidence. The Transcript is the only textual source
of truth; raw Evidence remains available for high-risk checks.

## Read progressively

- Structuring and traceability rules: [traceability.md](references/traceability.md)
- WeChat article manuscript and renderer: [wechat-article.md](references/wechat-article.md)

## Preconditions

- A Job has a saved Transcript with `quality.status=usable|verified`.
- The user requested a carrier, or an active automation Profile already selected
  one. Outside automation, do not invent a carrier from a bare video link.
- The intended audience, purpose, and fidelity threshold are understood.

## Main flow

1. Read the Transcript and its uncertainty/correction notes.
2. Design a carrier-appropriate structure. Do not mechanically turn every cue
   into a paragraph.
3. Preserve claims, attribution, uncertainty, causality, and important limits.
4. For video-derived imagery, use only the original cover and timestamped source
   frames by default. Use fewer images rather than filler.
5. Build the carrier document and an explicit audit.
6. For `wechat_article`, prefer `scripts/render_wechat_article.py`; it creates
   clean HTML, preview, local assets, and one-line relative image markers.
7. Save Content with `content_save`, then require `content_validate.valid=true`.

## Audit

The audit must be Agent-authored and state `passed` or `approved` only after
checking:

- no material claim was invented or reversed;
- attribution and speaker identity remain clear;
- uncertainty and conditions were not removed for style;
- title and summary do not overclaim;
- every image is an original cover or timestamped source frame;
- the output contains no persisted Base64 image or secret-bearing URL.

## Boundaries

- Do not generate diagrams, illustrations, stock images, or synthetic visual
  summaries unless the user separately requested or approved them.
- Content validation does not authorize a platform action.
- Do not log in, upload, save a draft, publish, schedule, or mass-send from this
  Skill.
