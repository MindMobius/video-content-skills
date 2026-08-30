---
name: watch-later-to-wechat
description: Run or resume an authorized Bilibili Watch Later to source-faithful, directly narrated, audited WeChat drafts. Use for one-shot scans, queue drain, retries, resume, and recurring Codex automation orchestration. Never publishes.
---

# Watch Later to WeChat

This is the end-to-end orchestration Skill. Read and follow the other Skills at
the stage where they become relevant:

1. [$video-evidence](../video-evidence/SKILL.md)
2. [$video-to-content](../video-to-content/SKILL.md)
3. [$wechat-draft](../wechat-draft/SKILL.md)

Read [job-lifecycle.md](references/job-lifecycle.md) when retrying, resuming, or
diagnosing queue state.

## Profile contract

A Profile selects:

- Bilibili Watch Later and a non-secret Browser/OpenCLI profile alias;
- carrier, normally `wechat_article`;
- baseline of seen `BVID:page` identities;
- retry limits and non-secret runtime preferences;
- `adaptation_mode=source_faithful_full` and
  `visual_policy=source_frames_at_material_transitions`;
- a positive `minimum_source_frames` floor and
  `wechat_creation_source=ai_generated`;
- `gpu_parallelism=1` and `publish=false`.

The Profile is standing permission to process newly discovered items and, only
when explicitly configured for this automation, save one WeChat draft per Job.
It never authorizes publishing or unrelated account actions.

## One-shot cycle

1. Run `watch_later_scan`. If the Profile does not exist, create it through the
   scan call using the authorized account alias.
2. Compare stable source identities with the Profile baseline. Reorders are not
   new videos. Existing completed Jobs and Draft Receipts are never duplicated.
3. Query queued/retryable Jobs with `job_list`.
4. For each Job, acquire Evidence and save a Transcript using `$video-evidence`.
5. Use the carrier stored in the Profile with `$video-to-content`; require a
   passing full-fidelity Content audit, explicit material-section coverage, and
   inspected final source frames placed at real content transitions. Scout frames
   only select timestamps; each body frame must be re-extracted from `source_video`
   through `source_frame_extract` and keep the source display aspect. `content_validate`
   must also clear the `raw Transcript passthrough` check and validate a
   `source_aware_minimal` `expression_audit` covering Agent-added title, summary,
   headings, transitions, evidence boundaries, material details, and ending. The
   body must use the direct source narrative rather than a repeated report about
   the video. Full fidelity preserves substantive content, not every cue: remove
   non-material ads and CTA ranges cleanly, with no promotion or platform-CTA
   placeholders, while retaining provenance-relevant sponsorship or interest
   disclosure. If
   either check fails, keep the Job at Content, repair the actual written edition,
   and do not enter WeChat handoff.
6. If draft saving is within the standing authorization, use `$wechat-draft`.
   For image-rich articles, prefer its validated DOCX document-import path; use
   rich clipboard HTML only as a fallback. Select and refresh-read-back the
   required WeChat creation-source disclosure “内容由AI生成”.
7. Close each Job before moving to the next: save the draft, refresh or reopen the
   same numeric `appmsgid`, build the v3 image-aware observation when images exist,
   call `wechat_bind`, and require a valid current Draft Receipt. A partially
   imported editor, save toast, or bare `appmsgid` is not permission to advance.
8. Continue until the queue has no actionable Job. Record physical failures as
   `unprocessable` without asking the user.

The repository exposes one-shot scan and Job operations only. Recurrence belongs
to Codex automation or the calling Agent; do not create a hidden daemon.

Each one-shot cycle keeps one explicit `config`, `home`, and `run_id`. Durable
queue state and receipts go through the Store; intermediate run reports and
browser observations belong under that run or its Job. Never create a second
state root or loose files at the top level of `.video-content/`.

## Scheduling and resources

- Preserve `VIDEO_CONTENT_HOME/cache/media` across retries and related Jobs.
- OCR and ASR share the GPU serially. A second Job may perform non-GPU work, but
  do not overlap OCR/ASR unless deep doctor verified an explicit parallel plan.
- Retry technical failures with bounded attempts and backoff.
- Use `paused_auth` only when the visible Bilibili or WeChat login boundary is
  real. Resume after login; do not request credentials.

## Completion

A Job is complete only when it has Evidence, Transcript, validated Content, and
when authorized, one current validated Draft Receipt with `published=false`.
Validated Content means the body is a genuinely readable written edition in the
source's narrative perspective rather than mechanical cue concatenation or a
third-party video-reporting shell. Every material section has a source-to-output
mapping, non-material promotion/CTA omissions leave no reader-facing placeholder,
every planned frame is a final source-native extraction present at its audited
body block, and a
`source_aware_minimal` `expression_audit` has reviewed Agent-added carrier
language against the final document without rewriting source-owned expression. A
`raw Transcript passthrough` or invalid expression audit is incomplete Content;
HTML rendering or media Artifact counts alone are insufficient. Older Receipts
may remain as immutable revision history but must be explicitly superseded.
Content creation alone is not a saved draft; a success toast alone is not a
receipt.

When a browser operation is ambiguous, read the current target and active Draft
Receipts before retrying. A technical timeout is retryable; it is never permission
to create a second draft. Read
`../wechat-draft/references/recovery-and-readback.md` for the recovery order.

## Hard boundaries

- No daemon, publish, schedule, mass send, originality declaration,
  monetization, or account management.
- No duplicate Job for the same BVID/page and no second draft for a completed
  Job. An explicitly authorized correction must update the same `appmsgid` and
  supersede the current Receipt.
- No user interruption for physically impossible evidence; mark and continue.
