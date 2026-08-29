---
name: wechat-draft
description: Place an audited WeChat article into an already signed-in WeChat Official Account editor and, only when explicitly authorized, save one draft. Use visible Browser Bridge state, transient clipboard HTML, refresh readback, and a validated Draft Receipt. Never publishes.
---

# WeChat Draft

Use only after `content_validate.valid=true` for `carrier=wechat_article`.
Read [editor-checklist.md](references/editor-checklist.md) before browser
mutation or when editor state is ambiguous. Read
[recovery-and-readback.md](references/recovery-and-readback.md) after a browser
timeout, empty snapshot, unreliable editor entry, or uncertain save result.

Transient handoff packages, observations, and browser diagnostics belong in the
current Job or `runs/<run_id>/`; never leave clipboard payloads, previews, or
loose JSON at the state-root top level.

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
2. Validate the reconstructed package. Use `scripts/prepare_clipboard.py` only
   for transient rich HTML. Never persist the HTML/Base64 payload or read the
   previous clipboard.
3. Use `scripts/browser-adapter.js` against the one visible editor. When a
   creation-source declaration is required, pass the inspected visible control
   selector as `creationSourceSelector`; the snapshot must report exactly one
   selected “内容由AI生成” candidate. If the editor target or declaration control
   is ambiguous, stop rather than guess.
4. Place title and body; wait for every intended image to become visible,
   loadable, and WeChat-hosted. Confirm zero local-path markers remain.
5. Set the approved summary and original-video cover. Leave author blank unless
   the user supplied an account author identity. When `required_declarations`
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
8. Build a no-secret `video-content/wechat-editor-observation-v2` when the AI
   creation-source declaration is required. Record `declared=true`,
   `type=ai_generated`, and `read_back=true` only from the selected pre-save
   state plus the fresh post-refresh snapshot, then call `wechat_bind`. For a
   revision, pass the returned `supersedes_receipt_id`. Require
   `validation.valid=true` and `published=false`.

## Observation must prove

- current Content SHA-256 and exact title;
- stable numeric `appmsgid`;
- intended image count equals visible loaded WeChat-hosted image count;
- zero local-path markers;
- cover selected and summary filled;
- save mode is `draft`;
- refresh readback was performed on the same draft and content remains present;
- when required, “内容由AI生成” had exactly one selected visible control before
  save and was selected again in a fresh post-refresh snapshot;
- a revision retained the same `appmsgid` and superseded exactly one prior Receipt;
- `published=false`.

## Browser and secret boundary

The Browser Adapter observes visible controls only. Persist no cookies, tokens,
raw image URLs, browser storage, URL query tokens, QR-login data, or clipboard
payload. Login is a legitimate human boundary; credentials are never requested.

## Hard boundaries

- Never overwrite unrelated editor content based on a guessed target.
- Never save a second draft when a valid Draft Receipt already exists. An
  authorized revision may update only that same platform draft and must create a
  superseding Receipt rather than hiding or overwriting history.
- Never click publish, mass send, schedule, originality, monetization, or account
  management controls. Selecting “内容由AI生成” is allowed only as the required
  creation-source disclosure.
- Never report completion until refresh readback and receipt validation pass.
