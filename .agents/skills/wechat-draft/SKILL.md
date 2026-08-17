---
name: wechat-draft
description: Place an audited WeChat article into an already signed-in WeChat Official Account editor and, only when explicitly authorized, save one draft. Use visible Browser Bridge state, transient clipboard HTML, refresh readback, and a validated Draft Receipt. Never publishes.
---

# WeChat Draft

Use only after `content_validate.valid=true` for `carrier=wechat_article`.
Read [editor-checklist.md](references/editor-checklist.md) before browser
mutation or when editor state is ambiguous.

## Authorization gate

The current user request or active automation Profile must explicitly authorize
both editor placement and draft saving. Historical browser login or an existing
Content object is not authorization. If saving is not in scope, do not fabricate
a Draft Receipt.

## Main flow

1. Call `wechat_prepare` with `authorized=true` and `save_draft=true`. It rejects
   invalid Content and Jobs that already have a Draft Receipt.
2. Validate the reconstructed package. Use `scripts/prepare_clipboard.py` only
   for transient rich HTML. Never persist the HTML/Base64 payload or read the
   previous clipboard.
3. Use `scripts/browser-adapter.js` against the one visible editor. If the
   editor target is ambiguous or unrelated content is present, stop rather than
   guess.
4. Place title and body; wait for every intended image to become visible,
   loadable, and WeChat-hosted. Confirm zero local-path markers remain.
5. Set the approved summary and original-video cover. Leave author blank unless
   the user supplied an account author identity. Do not declare originality.
6. Save only as draft. Require a stable numeric `appmsgid` and durable save
   evidence.
7. Refresh or reopen the same draft and re-read title, body, images, cover, and
   summary. A transient toast is insufficient.
8. Build a no-secret `video-content/wechat-editor-observation-v1` and call
   `wechat_bind`. Require `validation.valid=true` and `published=false`.

## Observation must prove

- current Content SHA-256 and exact title;
- stable numeric `appmsgid`;
- intended image count equals visible loaded WeChat-hosted image count;
- zero local-path markers;
- cover selected and summary filled;
- save mode is `draft`;
- refresh readback was performed on the same draft and content remains present;
- `published=false`.

## Browser and secret boundary

The Browser Adapter observes visible controls only. Persist no cookies, tokens,
raw image URLs, browser storage, URL query tokens, QR-login data, or clipboard
payload. Login is a legitimate human boundary; credentials are never requested.

## Hard boundaries

- Never overwrite unrelated editor content based on a guessed target.
- Never save a second draft when a valid Draft Receipt already exists.
- Never click publish, mass send, schedule, originality, monetization, or account
  management controls.
- Never report completion until refresh readback and receipt validation pass.
