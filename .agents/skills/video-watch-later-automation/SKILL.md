---
name: video-watch-later-automation
description: Orchestrate an authorized, fail-closed Bilibili Watch Later pipeline that discovers new videos, builds canonical subtitle evidence, creates audited WeChat articles, and saves at most one draft per job. Use for one scheduled cycle, queue draining, retry, resume, or standing Watch Later-to-WeChat automation; never publish.
---

# Video Watch Later Automation

Use this orchestration Skill when the user has explicitly chosen the standing
workflow "Bilibili Watch Later -> verified subtitle -> WeChat article -> saved
WeChat draft", or asks to run or resume one cycle of that workflow. It composes
[`../video-subtitle/SKILL.md`](../video-subtitle/SKILL.md),
[`../video-to-content/SKILL.md`](../video-to-content/SKILL.md), and
[`../wechat-draft-handoff/SKILL.md`](../wechat-draft-handoff/SKILL.md).

The repository exposes durable one-shot operations. The calling Agent or an
external Codex automation owns recurrence: wake up, scan once, drain eligible
jobs, persist every transition, and stop. Do not create a hidden daemon.

## Responsibility split

Use deterministic tools for identity, schemas, hashes, locks, retries, guarded
state transitions, receipts, and duplicate prevention. Use Agent judgment for:

- deciding whether continuous hard subtitles are visually present;
- comparing platform subtitles, OCR, ASR, and reviewed evidence;
- authoring the best canonical subtitle without changing raw evidence;
- turning verified evidence into a faithful article and repairing audit issues;
- operating the visible WeChat editor semantically and checking saved state.

Do not add approval forms or per-video questions where the standing profile and
draft authorization already answer them. Do not ask the user to resolve poor
media, missing speech, irreconcilable subtitle evidence, or an article that
cannot pass its bounded audit. Those are machine-observable terminal outcomes.

## Standing authorization

Before unattended cycles begin, require both versioned documents:

1. A `video-automation/profile-v1` profile fixing Bilibili Watch Later as the
   source and `wechat_article` as the requested carrier.
2. An active `video-automation/draft-authorization-v1` authorization covering
   that profile, with `allowed_actions` exactly `['save_wechat_draft']` and all
   prohibited actions retained.

Create them with `save_video_automation_profile` and
`authorize_video_automation_drafts`. The authorization call must include
`confirm_draft_only_authorization=true`; never infer or renew it silently. Never
request or persist cookies, passwords, tokens, QR-login payloads, clipboard
payloads, or browser storage.

If the user did not explicitly select this standing workflow, return to the
normal Skills and do not assume a WeChat carrier or platform mutation.

## One automation cycle

### 1. Verify the environment

Call `video_subtitle_setup` for `watch_later_monitor` and the evidence
capabilities required by the profile. Execute safe `agent_actions`, persist
non-secret paths with `configure_video_subtitle`, and require
`video_subtitle_doctor` readiness before the relevant stage. Browser login is a
human boundary; dependency installation and path discovery are Agent work.

### 2. Discover and queue

Call `scan_bilibili_watch_later` once with the profile and durable store, then
use `list_video_automation_jobs` to find eligible jobs. Watch Later identity is
BVID plus page, combined with profile ID and version. Reordering must not create
a new job, a second scan must not duplicate a job, and removing an item later
must not cancel work already submitted.

Process each job independently. Never merge videos into one evidence manifest,
article, receipt, or handoff binding.

### 3. Build independent subtitle evidence

For a queued job, move it through the guarded evidence states and follow
`video-subtitle` completely:

- preserve platform, OCR, ASR, and reviewed artifacts as separate immutable
  evidence;
- assess visual hard subtitles independently of platform-track availability;
- call `plan_hard_subtitle_scout` when continuity is uncertain;
- run full-video OCR when continuous hard subtitles are present;
- retain the download cache across retries and related evidence passes;
- use ASR when allowed and useful, not as an invented replacement for absent
  information.

Retry technical failures according to the job policy. If the source is
physically incapable of yielding adequate evidence, transition the job to
`unprocessable` with a concise non-secret reason. Do not ask the user what the
video did not contain and do not fabricate missing claims.

### 4. Author the canonical subtitle

Read the relevant evidence ranges and let the Agent reconcile them using timing,
context, source independence, agreement, visual inspection, and confidence. Raw
artifacts remain unchanged. Write a
[`video-automation/canonical-subtitle-v1`](../../../schemas/canonical-subtitle.schema.json)
document and call `save_canonical_subtitle`.

A canonical subtitle is usable only when its report says so. Preserve unresolved
ambiguities explicitly. If the evidence cannot support a coherent, faithful
subtitle, end as `unprocessable`; do not continue merely to produce output.

### 5. Generate, audit, and render the article

Call `initialize_automated_video_content` only from a usable canonical subtitle,
then follow `video-to-content`. The profile has already selected a WeChat
article, so do not ask for a carrier again.

The Agent authors the Content Map, Media Plan, article, and fidelity audit; the
repository validates and versions them. Use only the original cover and useful
timestamped source frames unless the standing profile was explicitly changed by
the user. Repair failed audits only within `max_content_repairs`. When the limit
is exhausted or fidelity is fundamentally unattainable, end as `unprocessable`.

Use the first-party WeChat renderer when its restrained contract fits. Do not
enter handoff until the project validates as delivery-ready and the job has a
valid content binding and audit artifact.

### 6. Save exactly one WeChat draft

Call `prepare_video_automation_handoff` before touching the browser.

- If it reports an existing handoff binding, skip the editor. The job already
  has its durable saved-draft result.
- If standing authorization is inactive, revoked, expired, or does not cover the
  current profile, fail closed. Never broaden it or reauthorize automatically.
- If the signed-in browser session has expired, record `paused_auth` and stop
  this stage. Resume only after the visible login state is restored; never ask
  for credentials.

For a ready handoff, follow `wechat-draft-handoff` using the active standing
authorization as the explicit permission for this job. The only permitted
platform action is `save_wechat_draft`. Verify the visible editor, paste the
audited package, wait for WeChat-hosted images, fill only authorized metadata,
and save one draft.

Require a validated `video-content/wechat-draft-receipt-v1` receipt with a stable
numeric `appmsgid`, `published=false`, and
`publish_actions_performed=[]`. Then call `bind_video_automation_handoff`.
Completion requires that binding; a toast, uploaded images, or an unbound receipt
is not enough. The binding is the idempotency guard that prevents a second draft.

## Failure mapping

- Temporary network, subprocess, browser-control, or service failure:
  `retry_wait`, using the persisted resume status and bounded technical attempts.
- Technical attempts exhausted: `failed_retry_exhausted`.
- Expired interactive browser login: `paused_auth`.
- Missing, contradictory, or unusable evidence: `unprocessable`.
- Content still failing after bounded repairs: `unprocessable`.
- Existing valid handoff binding: no platform action; treat the saved draft as
  already complete.

Terminal evidence or content failures are final records, not questions for the
user. Authentication is the only normal pause requiring an external-state
change.

## Hard boundaries

- Never publish, schedule, mass send, declare originality, enable monetization,
  or manage either platform account.
- Never remove, reorder, or mark Bilibili Watch Later items as completed.
- Never create more than one job or one WeChat draft for the same idempotency
  identity.
- Never replace raw evidence with the canonical subtitle; canonical output is
  derived evidence.
- Never treat platform subtitle availability as proof that visual OCR is
  unnecessary.
- Never report completion without a validated draft receipt and automation
  handoff binding.
