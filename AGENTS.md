# Repository Instructions

This repository is an Agent-first subtitle evidence and content-transformation
project. Read this file before choosing tools or changing the environment.

## Skill routing

- For a video URL, local video, audio, subtitle file, subtitle retrieval, OCR,
  ASR, or evidence correction, read
  [`.agents/skills/video-subtitle/SKILL.md`](.agents/skills/video-subtitle/SKILL.md)
  completely before acting.
- After verified subtitle evidence exists, use
  [`.agents/skills/video-to-content/SKILL.md`](.agents/skills/video-to-content/SKILL.md)
  only when the user requested a transformed deliverable.
- After an audited WeChat article exists, use
  [`.agents/skills/wechat-draft-handoff/SKILL.md`](.agents/skills/wechat-draft-handoff/SKILL.md)
  only when the user explicitly asks to place it in an already signed-in
  WeChat editor. Saving the draft must also be explicitly in scope. This Skill
  never publishes.
- If the user supplied only an input, finish the subtitle evidence first and
  ask whether they want only subtitles or a specific carrier. Do not choose a
  carrier unless the user explicitly delegates that decision.

The directories under `.agents/skills/` are the canonical Skill sources. Do
not create a second copy under another Agent-specific directory. Consumers that
need personal or project installation should use a Skill installer so it can
link or copy the canonical source without creating an untracked fork.

## Fresh-machine entry

If the MCP tools and `video-subtitle` CLI are unavailable, run from the
repository root:

```text
python scripts/bootstrap.py
python scripts/bootstrap.py --apply --config <config-path> --capability <required-capability>
```

Treat the single `video-subtitle/bootstrap-v2` JSON output as the environment
contract. It reports the canonical Skill paths, the JSON CLI command, the stdio
MCP launch contract, and the nested capability setup result:

1. Execute safe `agent_actions` yourself.
2. Persist discovered non-secret paths with `video-subtitle configure`.
3. Rerun setup after every environment change.
4. Ask the user only for remaining `human_actions`.
5. Obtain confirmation before any action with
   `confirmation_required=true`.
6. Run a deep doctor check before ASR or explicit shared-GPU parallelism.

Never request cookies, passwords, or tokens. Browser login, hardware absence,
OS privilege prompts, and confirmed large downloads are legitimate human
boundaries; ordinary dependency installation and path discovery are Agent
work.

## Tool boundary

- Prefer the repository MCP tools when they are already registered.
- Otherwise use the JSON CLI; it exposes the same durable evidence and content
  contracts.
- Do not infer successful setup from a path alone. Require `setup.ready=true`
  for the requested capabilities and verify heavy runtimes with `doctor`.
- Current URL support is Bilibili only. Do not claim YouTube or Douyin support
  until their adapters exist.
- The Python/MCP content project stops at an audited deliverable. It does not
  log in to publishing platforms, upload files, or change platform state.
- The optional `wechat-draft-handoff` Skill may use an existing visible browser
  login to place an audited article and save it as a draft only after explicit
  user authorization. It must not read credentials or browser secrets.
- Scheduling, publishing, mass sending, originality declarations, monetization,
  and channel-account management remain outside every Skill in this repository.

## Verification

Before committing implementation changes, run:

```text
python -m ruff check .
python -m ruff format --check .
python -m pytest
python scripts/mcp_smoke.py
```

Preserve raw platform, OCR, ASR, and reviewed evidence as separate immutable
artifacts. Do not silently replace one source with another.

Commit messages must be written in Chinese and describe the actual change
precisely without being unnecessarily long.
