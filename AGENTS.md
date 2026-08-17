# Repository Instructions

This repository is the canonical source for **Video Content Skills**, an Agent-native
video evidence and content-production toolkit. Keep the default context small: route
to the relevant Skill first, then read deeper references only when the task requires
them.

## Progressive context

1. Use this file for repository-wide invariants and routing.
2. Read exactly one primary `SKILL.md` for the current task.
3. Follow links from that Skill into `references/`, scripts, or topic documents only
   when the current step needs them.
4. Read `docs/plans/` and `docs/cases/` only for history or comparison; they are not
   current execution contracts.
5. For repository changes, read [`docs/skill-maintenance.md`](docs/skill-maintenance.md).

## Skill routing

- Bilibili URL, local video/audio, subtitle retrieval, OCR, ASR, evidence review, or
  canonical subtitle work: read
  [`.agents/skills/video-subtitle/SKILL.md`](.agents/skills/video-subtitle/SKILL.md)
  completely before acting.
- Transform already verified video evidence into an article or another carrier: read
  [`.agents/skills/video-to-content/SKILL.md`](.agents/skills/video-to-content/SKILL.md).
- Run, resume, retry, or drain an authorized Bilibili Watch Later-to-WeChat cycle:
  read
  [`.agents/skills/video-watch-later-automation/SKILL.md`](.agents/skills/video-watch-later-automation/SKILL.md).
- Place an audited article into an already signed-in WeChat editor and save a draft:
  read
  [`.agents/skills/wechat-draft-handoff/SKILL.md`](.agents/skills/wechat-draft-handoff/SKILL.md).

Outside an active Watch Later profile, an input alone authorizes evidence work only.
Do not choose a carrier unless the user requested one or explicitly delegated that
decision.

## Global evidence boundaries

- Current URL support is Bilibili only. Do not claim unsupported platform adapters.
- Platform subtitle availability and continuous visual hard subtitles are independent
  facts. Use `plan_hard_subtitle_scout` whenever continuity is uncertain. Apply this
  decision whether or not platform subtitles exist. Full-video OCR is required when
  continuous hard subtitles are present.
- Preserve raw platform, OCR, ASR, and reviewed evidence as separate immutable
  artifacts. Never silently replace one source with another.
- Tools establish reproducible evidence and state; the Agent resolves semantic
  conflicts and records the canonical result.
- For video-derived articles, default supporting images are the original cover and
  timestamped frames from the source video. Use fewer images rather than generated,
  stock, or filler visuals unless the user explicitly approved another policy.

## Environment and resource boundaries

- Prefer registered repository MCP tools; otherwise use the equivalent JSON CLI.
- On a fresh machine, start with `python scripts/bootstrap.py`, then follow the
  capability-specific actions returned by the bootstrap contract. Detailed setup is
  in [`docs/environment.md`](docs/environment.md) and the active Skill.
- Do not infer readiness from paths. Require `setup.ready=true`; run deep `doctor`
  checks before ASR or explicitly shared-GPU work.
- Heavy runtimes and models must use `requirements/runtime-lock.json` through
  `scripts/runtime_setup.py`. Large downloads require the confirmation defined by
  the setup contract.
- Preserve `download_cache` across retries and related jobs. Treat manifest
  `actual_bytes` and `actual_mib` as authoritative.
- OCR and ASR sharing one GPU must run serially. Parallelize only independent work
  that cannot exhaust the same constrained resource.
- Never request cookies, passwords, tokens, or browser storage. Login, hardware,
  privilege prompts, and confirmed large downloads are legitimate human boundaries;
  ordinary installation, path discovery, retry, and fallback are Agent work.

## Automation and carrier boundaries

- Multi-input work uses one `video-content/batch-v1` ledger with independent evidence,
  content, audit, and optional handoff artifacts per item.
- Watch Later operations are one-shot primitives. The caller owns recurrence; this
  repository must not start a hidden daemon.
- Retry technical failures, record physically insufficient evidence as
  `unprocessable`, and use `paused_auth` only for a real authentication boundary.
  One failed item must not block the rest of a batch.
- Preserve source media cache and task state so interrupted work resumes instead of
  downloading, transcribing, or saving a draft again.
- The Python/MCP content project stops at an audited deliverable. Browser state
  changes require the explicit `wechat-draft-handoff` authorization.
- WeChat handoff may use an existing visible login only. Persist no credentials,
  cookies, URL tokens, clipboard payloads, or browser storage.
- A draft is complete only after a validated
  `video-content/wechat-draft-receipt-v1` receipt states `published=false` and no
  publish actions occurred.
- Publishing, scheduling, mass sending, originality declarations, monetization, and
  account management are outside every Skill.

## Skill maintenance

`.agents/skills/` is the only canonical Skill source. Do not create another
Agent-specific copy. Keep task contracts in `SKILL.md`, conditional depth in
`references/`, deterministic behavior in code/schema, and maintenance rules in
[`docs/skill-maintenance.md`](docs/skill-maintenance.md).

Preserve compatibility identifiers unless a separately approved migration includes a
compatibility layer. The project brand is `Video Content Skills`; existing runtime
names such as `video-subtitle`, `video_subtitle`, `.video-subtitle-local`, schema IDs,
and the `video-subtitle-skill` distribution remain stable in this release.

## Verification

Before committing implementation changes, run:

```text
python -m ruff check .
python -m ruff format --check .
python -m pytest
python scripts/mcp_smoke.py
npm test
npm run pack:check
python scripts/repro_check.py --require-tier core --require-tier agent
```

Require the `media` tier only when FFmpeg or FFprobe is available. The `live` tier is
manual because it depends on current Bilibili, Browser Bridge, OCR/ASR hardware, and
separately authorized WeChat state.

Commit messages must be written in Chinese and describe the actual change precisely.
