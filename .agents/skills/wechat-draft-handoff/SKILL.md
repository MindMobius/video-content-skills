---
name: wechat-draft-handoff
description: Place an audited WeChat Official Account article package into an already signed-in editor and optionally save it as a draft, including local images through a transient clipboard-only transport. Use only when the user explicitly requests platform handoff; never publish, schedule, or manage the account.
---

# WeChat Draft Handoff

Use this optional downstream Skill only after `video-to-content` has produced a
validated WeChat article package. It moves an existing audited artifact into a
visible, already signed-in WeChat Official Account editor. It does not rewrite
the article, replace the content audit, or extend the core Python/MCP pipeline.

The broader content and receipt contracts are documented in
[`docs/content-workflow.md`](../../../docs/content-workflow.md) and
[`docs/reproducibility.md`](../../../docs/reproducibility.md).

The browser page is live external state. Read the current page, act from
semantic controls and visible status, and verify the result. Do not turn a
successful run into a fixed coordinate script.

The page may contain hidden duplicate fields, inactive menu instances, and
helper image nodes. Treat only visible, enabled controls and rendered content as
live state. A matching DOM node by itself is not a completion receipt.

## Authorization gate

Proceed through exactly one explicit authorization path:

1. **Interactive path:** The user explicitly asked to place this article in the
   WeChat editor. Saving the draft requires an explicit request to save, not
   merely to inspect or populate the form.
2. **Standing automation path:** `prepare_video_automation_handoff` validated an
   active `video-automation/draft-authorization-v1` document for this job and
   returned `allowed_actions=['save_wechat_draft']`. This prior bounded grant
   replaces a repeated per-item prompt; it does not authorize any other platform
   action. If preparation reports an existing handoff binding, do not touch the
   editor or create another draft.

In either path, all of the following must also be true:

- The article package has a current fidelity audit of `pass` or
  `pass_with_warnings`, and `validate_video_content_project` reports
  `ready_for_delivery=true`.
- The target browser is already signed in and the intended article editor is
  visible. In an automation job, expired login becomes `paused_auth`; resume
  only after the visible login state is restored. In an interactive task, ask
  the user to complete interactive login.
- The clean HTML, local assets, title, and any requested summary or cover
  instruction are known.

If the article is not audited, return to
[`../video-to-content/SKILL.md`](../video-to-content/SKILL.md). If the user only
asked for a WeChat article file, stop at the normal package handoff; do not infer
permission to touch the platform.

Never ask the user for, extract, copy, export, log, or persist cookies,
passwords, QR-login payloads, browser-storage values, or URL tokens. Use the
existing visible browser session only.

## Required capabilities

The calling Agent needs tools that can:

- inspect and control the signed-in browser page;
- write a rich `text/html` clipboard payload and paste it into the editor;
- read the explicitly supplied local image files and assemble temporary image
  data without logging or persisting it;
- inspect the resulting editor DOM or equivalent visible page state;
- fill title and summary fields, choose a cover from the body when instructed,
  and invoke the draft-save control.

These are caller capabilities, not Python requirements of this repository. If
the browser tool cannot write rich clipboard HTML containing image bytes, use
the manual local-image fallback defined in
[`../video-to-content/references/wechat-article.md`](../video-to-content/references/wechat-article.md).
Do not claim that images were imported when only path markers were pasted.

Use the two bundled deterministic adapters when their host capabilities are
available:

- [`scripts/prepare_clipboard.py`](scripts/prepare_clipboard.py) validates the
  package and assembles the one-time rich clipboard payload. Its default is a
  no-write dry run; use `--copy` only immediately before the authorized paste.
- [`scripts/browser-adapter.js`](scripts/browser-adapter.js) observes the current
  editor through semantic DOM state and emits a no-secret
  `video-content/wechat-browser-snapshot-v1`. Load or evaluate it through a
  CDP-capable browser tool when direct semantic inspection is insufficient;
  never depend on fixed coordinates or a stored tab ID. The snapshot is partial
  evidence, not the final saved-draft observation.

The adapters do not log in, choose the target article, click save, or authorize
platform mutation. Inspect the visible page and verify every postcondition.

## Workflow

For a standing automation job, call `prepare_video_automation_handoff` before
the first browser observation or mutation. If it returns
`already_completed=true`, use the existing handoff binding as the durable result
and stop without opening or changing the editor. If login is no longer active,
transition the job to `paused_auth`; do not create a receipt and do not ask for
credentials.

Read [`references/wechat-editor-checklist.md`](references/wechat-editor-checklist.md)
before making platform changes.

When content timing tools are available, start one explicit
`wechat_handoff` phase with category `external` immediately before the first
editor mutation. Finish it as `completed` only after the saved draft has been
read back and its receipt validates; otherwise finish it as `failed` or
`cancelled`. Timing is operational metadata and must not change the fidelity
audit or imply that platform state is part of the content artifact.

### 1. Preflight the audited package

Read the current deliverable, audit, and WeChat package. Confirm that:

- the clean HTML is the audited body fragment, not a preview wrapper;
- every `data-local-image-slot` has one visible relative-path marker and one
  matching local file;
- the clean HTML stores no local image as a relative, `file:`, `data:`, or
  `blob:` `img` source;
- image order, title, summary source, cover choice, author field, and originality
  setting are known or deliberately left unchanged;
- every reader-facing `pass_with_warnings` limitation remains visibly disclosed;
  an operational local-image warning stays recorded in the content audit and is
  verified separately in platform state.

When this repository is available, run its deterministic package preflight from
the repository root:

```powershell
python scripts/validate_wechat_package.py <wechat-article-directory>
```

Require `valid=true` before building the clipboard payload. This validator checks
portable files, paths, markers, preview wording, and stock rendering artifacts;
it does not replace the Agent's semantic fidelity audit.

Do not modify the saved clean HTML merely to make the platform handoff easier.

### 2. Build a clipboard-only transport

Create one temporary rich-text fragment in memory or directly in the clipboard:

1. Start from the audited clean HTML.
2. Replace each local-image marker, in order, with an `img` element whose `src`
   is a correctly typed `data:image/...;base64,...` URL built from the matching
   local file.
3. Preserve the surrounding article order and reasonable responsive image
   styling.
4. Write the result as rich `text/html` clipboard content.

Prefer the bundled helper from the repository root:

```powershell
# Validate and count assets without changing the clipboard
python .agents/skills/wechat-draft-handoff/scripts/prepare_clipboard.py `
  <wechat-article-directory>

# Run only immediately before the authorized paste
python .agents/skills/wechat-draft-handoff/scripts/prepare_clipboard.py `
  <wechat-article-directory> --copy
```

Require `ok=true`, `payload_persisted=false`, and
`previous_clipboard_read=false`. Do not redirect, capture, or serialize the rich
payload; the helper's JSON report deliberately excludes it.

The Base64 payload is transport data only. Do not save it beside the article,
write it back to the deliverable, include it in logs, commit it, or bind it to a
new fidelity audit. Do not inspect or record the user's previous clipboard
contents.

### 3. Paste the article once

Inspect the editor before changing it. If it contains unrelated content, do not
clear or overwrite it without explicit scope from the user.

Paste the complete temporary rich-text fragment into the article body in one
operation. Prefer this ordered paste over individually locating seven or more
image positions with coordinates. Wait for WeChat to finish converting and
uploading the images before editing metadata or saving.

### 4. Verify platform ingestion

Verify the live editor state, not merely the clipboard call:

- the visible, non-empty, successfully loaded body-image count equals the
  intended local-image count; ignore hidden, zero-size, empty-source, or helper
  image nodes;
- each visible imported image now uses a WeChat-hosted source such as
  `mmbiz.qpic.cn`, rather than `data:`, `file:`, or `assets/...`;
- no visible relative-path marker remains unless the run intentionally fell
  back to manual insertion;
- article text, section order, source disclosure, and restrained formatting are
  intact;
- no stock author, CTA, underline-heavy emphasis, or unsupported claim appeared
  during paste.

If any image is missing or still transient, repair the handoff or stop with a
precise manual fallback. Do not report success from a partially uploaded body.
Do not count every `img` element indiscriminately or accept the first matching
field in the DOM; verify current rendered state and resolved image sources.
Visible body-image count equals the intended image count only after those
visibility, loading, and source checks have excluded helper nodes.

When DOM script evaluation is available, use the bundled browser adapter to
classify only visible, complete, non-zero-size body images as WeChat-hosted,
transient, other, or empty. Combine that sanitized snapshot with cover,
originality, content checks, timestamps, and durable-save state read from the
current visible editor; only then persist the complete
`video-content/wechat-editor-observation-v1` JSON. If script evaluation is
unavailable, perform the same state checks with semantic browser inspection; the
observation contract is authoritative, not a particular browser transport.

### 5. Fill metadata without changing provenance

Fill only the fields authorized by the user:

- use the audited title unless the user requested a different one;
- derive a short summary from the audited article when no approved summary file
  exists, without adding new claims;
- use the designated original cover through “从正文选择” when the package and
  user instruction call for it, then confirm the intended body image was chosen,
  crop confirmation completed, a visible cover preview uses a WeChat-hosted
  source, and the empty-cover placeholder is gone;
- leave the platform author field blank unless the user explicitly supplies an
  account author identity;
- do not claim platform originality or source exclusivity unless the user
  explicitly instructs it and owns that decision.

Read title, cover, author, and originality state from the visible interactive
controls. Hidden duplicate inputs or inactive menu copies do not establish the
current value.

### 6. Save only the authorized draft

When the user explicitly requested a saved draft, or the current automation
preparation authorizes only `save_wechat_draft`, click the draft-save control
and wait for a durable receipt. Prefer a stable article identifier together with
a persisted manual-save or version-history entry when both are available; a
transient success toast alone is not sufficient. After saving, re-read the
title, summary, body, imported images, and cover so the receipt also proves that
the saved state remained complete. Resolve validation errors before reporting
completion.

Never click publish, mass send, schedule, original-content declaration, account
management, or monetization controls. A request to publish is a separate,
high-impact task and is outside this Skill.

### 7. Persist and validate the draft receipt

For a saved draft, write `wechat-draft-receipt.json` beside the WeChat article
package using `video-content/wechat-draft-receipt-v1` and
[`../../../schemas/wechat-draft-receipt.schema.json`](../../../schemas/wechat-draft-receipt.schema.json).
This receipt is an observation of live platform state, not a new content
deliverable and not a replacement fidelity audit.

Record the current project, deliverable, and fidelity-audit IDs; ISO timestamps
for the first editor mutation and durable save; title and stable `appmsgid`;
intended, visible-loaded, WeChat-hosted, non-WeChat, and remaining-path-marker
image counts; cover, summary, author, originality, and content-check state; the
persisted manual-save history entry and saved-page read-back; `published=false`;
and an empty `publish_actions_performed` array. Do not copy the platform URL
token, cookies, clipboard Base64, or hidden browser state into the receipt.

Build and validate it from the repository root:

```powershell
python scripts/build_wechat_draft_receipt.py `
  <wechat-article-directory>\wechat-editor-observation.json `
  --project <content-project>\project.json `
  --output <wechat-article-directory>\wechat-draft-receipt.json
```

The builder validates the observation schema, rejects secret-bearing fields,
constructs the receipt, and runs the receipt validator. Require `ok=true` and
`validation.valid=true`. A success toast, assigned `appmsgid`, image upload, or
history entry alone is insufficient; the validator requires the complete,
current combination and checks that the receipt still targets the current
audited deliverable. If the user requested editor population without saving,
do not fabricate this saved-draft receipt.

For a standing automation job, call `bind_video_automation_handoff` only after
that validation passes. The binding must match the current job, authorization,
project, receipt hash, and stable `appmsgid`; it completes the job and prevents a
duplicate draft on later cycles. An unbound receipt is not automation
completion.

## Completion report

Report the live result separately from the core content artifact:

- title placed in the editor;
- intended/imported visible, loadable body-image counts;
- cover and summary state;
- whether the draft was saved and which durable receipt established it;
- the validated receipt path, IDs, and measured `wechat_handoff` duration when
  timing was enabled;
- any warnings or remaining manual action;
- an explicit statement that nothing was published.

Do not change the content project's fidelity audit from warnings to `pass`
because platform import succeeded. Content fidelity and platform handoff are
independent states.

## Hard boundaries

- Never operate the platform without either explicit per-item authorization
  or a current standing authorization limited to `save_wechat_draft`.
- Never save again when an existing handoff binding already proves completion.
- Never overwrite unrelated editor content based on a guessed target.
- Never persist the Base64 clipboard transport as a formal deliverable.
- Never treat WeChat CDN upload as evidence that the article is semantically
  correct.
- Never publish, schedule, mass send, declare originality, or manage the
  account.
- Never claim success until the editor state and draft-save state are visibly
  verified.
