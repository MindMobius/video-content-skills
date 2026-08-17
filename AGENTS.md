# Repository Instructions

This is an Agent-first video evidence and content-transformation repository.
Read this file before changing code or choosing a Skill.

## Skill routing

- Video URL/local media/subtitle/OCR/ASR/evidence work: read
  [`.agents/skills/video-evidence/SKILL.md`](.agents/skills/video-evidence/SKILL.md).
- Transform an existing usable/verified Transcript: read
  [`.agents/skills/video-to-content/SKILL.md`](.agents/skills/video-to-content/SKILL.md).
- Authorized Bilibili Watch Later scan, drain, retry, or resume: read
  [`.agents/skills/watch-later-to-wechat/SKILL.md`](.agents/skills/watch-later-to-wechat/SKILL.md),
  which routes the other Skills.
- Place validated WeChat content in an already signed-in editor and save a
  draft: read [`.agents/skills/wechat-draft/SKILL.md`](.agents/skills/wechat-draft/SKILL.md).

`.agents/skills/` is the only canonical Skill source. Do not create an
Agent-specific fork elsewhere.

Outside an active automation Profile, a bare video input authorizes Evidence and
Transcript only. Do not select a carrier unless the user requested one or
explicitly delegated that choice.

## Fresh machine

```text
python scripts/bootstrap.py
python scripts/bootstrap.py --apply --config <config-path> --capability <required-capability>
```

For a one-time move from a previous local state, dry-run
`scripts/migrate_legacy_state.py` before `--apply`; it archives the source,
verifies hashes, seeds idempotent completed Jobs, and creates no compatibility
runtime.

Treat `video-content/bootstrap-v2` as the environment contract:

1. execute safe `agent_actions`;
2. persist non-secret paths with `video-content system configure`;
3. rerun setup after environment changes;
4. ask only for remaining `human_actions`;
5. obtain confirmation for `confirmation_required=true` downloads;
6. run deep doctor before ASR or explicit shared-GPU parallelism.

For pinned heavy runtimes use `scripts/runtime_setup.py plan|install|verify`.
Never invent a release URL or silently choose `latest`. Browser login,
hardware/OS boundaries, and confirmed large downloads are human boundaries;
ordinary installation, path discovery, and retries are Agent work.

Use only `VIDEO_CONTENT_*`, `.video-content`, `video-content`,
`video-content-mcp`, and the `video_content` module.

## Core model

Only six business products persist:

```text
Profile, Job, Evidence, Transcript, Content, Draft Receipt
```

Use `run_id` plus Job queries for multiple inputs. Do not recreate project,
batch, phase, operation, binding, or portable-bundle wrappers.

The Store writes atomically, keeps Artifact hashes, rejects path escape and
secret-like fields, and never overwrites a raw Artifact with different bytes.

## Evidence boundary

- Current URL support is Bilibili only.
- Platform-track availability and visual hard-subtitle continuity are
  independent facts.
- When hard subtitles are uncertain, scout and inspect sampled frames before
  deciding whether full-video OCR can be skipped.
- If continuous hard subtitles exist, full-video OCR is required.
- Preserve platform, OCR, ASR, and Agent-reviewed evidence separately.
- Reuse the media cache across related retries; actual file bytes are
  authoritative.
- OCR and ASR use one shared GPU lane unless deep doctor verified otherwise.

Physical evidence insufficiency becomes `unprocessable`; do not ask the user to
change physics. Retry technical failures and use `paused_auth` only for a real
login boundary.

## Content and platform boundary

Content uses a saved Transcript. Video-derived images default to the original
cover and timestamped source frames; do not generate or source filler visuals
without separate user approval.

The Python/MCP layer stops at an audited Content object. WeChat mutation is
optional, visible, and separately authorized. The clipboard payload is
transient. Persist only no-secret visible observations and a validated
`video-content/draft-receipt-v1` with `published=false`.

Never publish, mass send, schedule, declare originality, monetize, or manage an
account.

## Automation boundary

Watch Later operations are one-shot. Codex automation or the calling Agent owns
recurrence; this repository must not create a daemon. Jobs are idempotent by
stable source identity. Do not create a second draft for a Job with a validated
Draft Receipt.

## Verification

Before committing implementation changes run:

```text
python -m ruff check .
python -m ruff format --check .
python -m pytest
python scripts/mcp_smoke.py
npm test
npm run pack:check
python scripts/repro_check.py --require-tier core --require-tier agent
```

Add the `media` tier when FFmpeg/FFprobe is available. The `live` tier remains
manual and requires current Bilibili/Browser Bridge state, representative
OCR/ASR, and separately authorized WeChat interaction.

Commit messages must be concise Chinese descriptions of the actual change.
