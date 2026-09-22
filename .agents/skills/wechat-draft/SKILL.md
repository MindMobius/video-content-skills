---
name: wechat-draft
description: Save audited Content as an authorized WeChat draft using the canonical DOCX and guarded, resumable handoff. Read live snapshots, reserve each mutation once, refresh-read-back and bind the program-generated receipt. Never publishes.
---

# WeChat Draft

Use only after `content_validate.valid=true` for `carrier=wechat_article` and
a current user request or active Profile that explicitly authorize placement **and saving a draft**. Never click publish,
mass send, schedule, declare originality, monetize or manage an account.

## One entry, one target

1. Read [guarded-handoff.md](references/guarded-handoff.md) and use
   `wechat_prepare → wechat_step → wechat_bind`. These gates are mandatory for
   new handoffs and corrections. Do not copy an old `runs/*/upload*.mjs`, invent
   another DOCX builder, or write successful Observation flags by hand.
2. `wechat_prepare` validates Content, generates and verifies the exact
   `article-import.docx`, and returns the durable checkpoint and `next_action`.
   Supply the intended public account name from current authorization/Profile,
   not a historical token. Missing account identity grants no mutation.
3. Collect a fresh, read-only `collectHandoffSnapshot` from
   `scripts/browser-adapter.js`, using the controller's actual browser/tab IDs
   and selectors inspected in the current visible UI. Unknown is not success.
   Read [editor-checklist.md](references/editor-checklist.md) for UI-specific checks.
4. Follow the checkpoint, not a remembered sequence. `begin_import` and
   `begin_save` reserve one mutation **before** its browser action; only a response
   with `mutation_permitted=true` permits that one action. A lost response does
   not permit replay. All other steps are read-only checks.
5. Import only `document_import.path` / the granted `upload_path`, then run
   `verify_import`. A long body, any dialog, or an upload-complete signal cannot
   prove import success. The gate compares the entire normalized body and all
   intended images to the exact Content. See
   [document-import.md](references/document-import.md).
6. Set the approved title/summary, explicitly choose the original-video cover
   and confirm its crop, leave author blank and originality undeclared. When
   required, select **“内容由AI生成”** using the inspected visible
   `creationSourceSelector`. Then reserve `begin_save` and save as draft once.
7. Observe a stable numeric `appmsgid` with `saved`, refresh or reopen the same
   draft, and call `readback` with a fresh post-refresh snapshot. Check the actual
   opening, middle, and ending; full-body fingerprinting complements, not replaces,
   the Agent's semantic review. Cover must remain visible/non-zero, and the same
   draft-list card must prove persistent cover-media fields and crop data.
8. Bind only the Observation returned by `readback` via `wechat_bind`.
   Require `validation.valid=true` and `published=false`. For authorized revisions,
   `wechat_prepare(replace_existing_draft=true)` returns the exact original
   `appmsgid` and `supersedes_receipt_id`; never create a replacement draft.

## Recovery and completion

- Re-running `wechat_prepare` resumes the existing checkpoint; `resume_pending`
  is **not** permission to create an editor. Legacy in-progress Jobs enter
  `recovery_required` rather than assuming the earlier save failed.
- Read [recovery-and-readback.md](references/recovery-and-readback.md) on ambiguity.
  Preserve the editor while inspecting a separate list view. No blind retries,
  repeated imports, mixed clipboard/DOCX transports, or changes to Content to make
  an upload appear successful.
- Never save a second draft when a valid Draft Receipt already exists. A technical
  timeout is not login loss; `paused_auth` requires an actual visible login page.
- Every body image requires `natural_width`, `natural_height`, displayed width
  and height, correct aspect ratio, load completion and zero local-path markers.
  `wechat_bind` reconstructs expectations from Content Artifact bytes; an
  internally consistent stretched image is not proof of source fidelity.
- New/corrected observations use `video-content/wechat-editor-observation-v4`.
  A save toast or numeric ID alone is not completion; refresh readback and a
  valid current Receipt close the Job before the next one enters WeChat.

Checkpoint: `jobs/<job_id>/work/wechat-handoff.json`. Transport:
`work/<content_id>/handoff-package/document-import/article-import.docx`.
They belong to the existing Job, not a new business product or state root.
Preserve active checkpoints across restarts. Store no cookies, tokens, browser storage,
clipboard payloads or image CDN URLs. `scripts/prepare_clipboard.py`
remains a low-level diagnostic helper, not a bypass of this guarded DOCX route;
implicit clipboard fallback is disabled. After two explicitly failed DOCX imports in the same confirmed empty editor, only the guarded `begin_clipboard` action may reserve one canonical fallback; see guarded-handoff.md.

The canonical DOCX is a standard-OXML compatibility candidate, not a live WeChat compatibility proof. After two explicit failures in the same empty editor, use only the guarded fallback and retain the failed package for diagnosis.
