---
name: wechat-draft
description: Place an audited WeChat article into an already signed-in WeChat Official Account editor and, only when explicitly authorized, save one draft. Prefer validated DOCX document import for image-rich articles, retain transient clipboard HTML as fallback, then refresh-read-back and bind a Draft Receipt. Never publishes.
---

# WeChat Draft

Use only after `content_validate.valid=true` for `carrier=wechat_article`.
Read [editor-checklist.md](references/editor-checklist.md) before browser
mutation or when editor state is ambiguous. For a document-import handoff, read
[document-import.md](references/document-import.md) before choosing or uploading
the file. Read [recovery-and-readback.md](references/recovery-and-readback.md)
after a browser timeout, empty snapshot, unreliable editor entry, uncertain
import, or uncertain save result.

Transient handoff packages, `article-import.docx`, observations, and browser
diagnostics belong in the current Job or `runs/<run_id>/`; never leave document
imports, clipboard payloads, previews, or loose JSON at the state-root top level.

## Authorization gate

The current user request or active automation Profile must explicitly authorize
both editor placement and draft saving. Historical browser login or an existing
Content object is not authorization. If saving is not in scope, do not fabricate
a Draft Receipt.

## Main flow

1. Call `wechat_prepare` with `authorized=true` and `save_draft=true`. It rejects
   invalid Content and ordinary attempts to create a second draft. For an
   explicitly authorized correction of an existing draft, also pass
   `replace_existing_draft=true`; the handoff must return the current numeric
   `appmsgid` and `supersedes_receipt_id`.
2. Validate the reconstructed package and choose one transport. For an
   image-rich article, prefer a validated `article-import.docx` whose text and
   embedded-image order match the exact final Content. Each embedded image must
   use the final Content Artifact bytes, and its DOCX display extent must preserve
   the image pixel aspect ratio; constrain maximum width only and let height scale
   automatically. Use `scripts/prepare_clipboard.py` only as a transient rich-HTML
   fallback. Never mix DOCX import and clipboard placement in the same editor
   state, persist the HTML/Base64 payload, or read the previous clipboard.
3. Use the current editor's visible document-import control for DOCX, or
   `scripts/browser-adapter.js` for the clipboard path. When a creation-source
   declaration is required, pass the inspected visible control selector as
   `creationSourceSelector`; the snapshot must report exactly one selected
   “内容由AI生成” candidate. If the editor target, import state, or declaration
   control is ambiguous, stop rather than guess.
4. Wait for document conversion or body placement to finish. Check the actual
   opening, middle, and ending; require every intended image to be visible,
   loadable, non-zero, and WeChat-hosted, in Content block order. Exclude zero-size
   editor separator nodes. For each real image, compare natural width/height with
   rendered width/height and stop if the aspect ratio changed. Confirm zero
   local-path markers remain. An import-complete signal is not proof of a complete
   body.
5. Replace any import-derived placeholder title such as `article-import` with
   the exact approved Content title, set the approved summary, and actively select
   the original-video cover rather than trusting the editor's default candidate.
   Leave author blank unless the user supplied an account author identity. When `required_declarations`
   requests `creation_source=ai_generated`, select the visible WeChat option
   **“内容由AI生成”** and capture the selected state. This is a creation-source
   disclosure, not an originality declaration; do not select originality.
6. Save only as draft. Require a stable numeric `appmsgid` and durable save
   evidence. A revision must keep the exact previous `appmsgid`; otherwise it is
   a second draft and must stop.
7. Refresh or reopen the same draft and re-read title, body, images, cover,
   summary, and creation-source control with a fresh Browser Adapter snapshot. A
   transient toast or the pre-save DOM state is insufficient.
   If any browser read or click times out, retry observation against the same
   visible target first; do not open a second editor until the current target has
   been ruled out.
8. For any image-bearing draft, build a no-secret
   `video-content/wechat-editor-observation-v3`; it records each real image's
   `natural_width`, `natural_height`, displayed `width`, and displayed `height`.
   When the AI creation-source declaration is required, record `declared=true`,
   `type=ai_generated`, and `read_back=true` only from the selected pre-save state
   plus the fresh post-refresh snapshot. Then call `wechat_bind`. For a revision,
   pass the returned `supersedes_receipt_id`. Require `validation.valid=true` and
   `published=false`.

## Observation must prove

- current Content SHA-256 and exact title;
- stable numeric `appmsgid`;
- intended image count and order equal the visible loaded WeChat-hosted body
  images, regardless of DOCX or clipboard transport;
- every real body image has positive natural and displayed dimensions, while
  zero-size editor separators are excluded;
- each image's natural and displayed width/height ratios match within the v3
  tolerance, so a fixed editor box cannot silently stretch the source frame;
- zero local-path markers;
- cover selected and summary filled;
- save mode is `draft`;
- refresh readback was performed on the same draft and content remains present;
- when required, “内容由AI生成” had exactly one selected visible control before
  save and was selected again in a fresh post-refresh snapshot;
- a revision retained the same `appmsgid` and superseded exactly one prior Receipt;
- `published=false`.

## Browser and secret boundary

The Browser Adapter observes visible controls only. Choose the browser target from
its current authenticated state and actual control capabilities; do not hard-code
Chrome, the in-app browser, or a historical tab. `setFiles: Not allowed` is a
controller-capability failure, not a bad DOCX path, so copying the same file to
another directory is not recovery. Re-read the same target first; if the tab is
stale, open a new Agent-controlled tab only within the same authenticated browser
session before retrying the single upload. Persist no cookies, tokens, raw image
URLs, browser storage, URL query tokens, QR-login data, or clipboard payload.
Login is a legitimate human boundary; credentials are never requested.

## Hard boundaries

- Never overwrite unrelated editor content based on a guessed target, and never
  layer a clipboard retry over an uncertain DOCX import.
- Never save a second draft when a valid Draft Receipt already exists. An
  authorized revision may update only that same platform draft and must create a
  superseding Receipt rather than hiding or overwriting history.
- Never click publish, mass send, schedule, originality, monetization, or account
  management controls. Selecting “内容由AI生成” is allowed only as the required
  creation-source disclosure.
- Never report completion until refresh readback and receipt validation pass.
