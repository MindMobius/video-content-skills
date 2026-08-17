# Environment and capability setup

Use the repository contract, not guessed paths.

## Fresh machine

From the repository root:

```powershell
python scripts/bootstrap.py
python scripts/bootstrap.py --apply --config <config-path> --capability <capability>
```

Bootstrap returns one `video-content/bootstrap-v2` document with the canonical
Skill paths, CLI command, MCP stdio contract, setup state, `agent_actions`, and
`human_actions`.

## Capability loop

1. Call `system_setup` with only required capability IDs.
2. Execute ordinary installs and path discovery yourself.
3. Persist non-secret paths with `system_configure`.
4. Rerun setup after each environment change.
5. Ask the user only for browser login, hardware/OS boundaries, or an action
   marked `confirmation_required=true`.
6. Require `ready=true`; then run `system_doctor`.

Capability IDs:

- `platform_subtitle`
- `video_download`
- `hard_ocr_local`
- `hard_ocr_url`
- `audio_asr_local`
- `audio_asr_url`
- `watch_later_monitor`

## Heavy runtimes

Never invent a URL or select `latest`. Use the pinned helper:

```powershell
python scripts/runtime_setup.py plan <dependency>
python scripts/runtime_setup.py install <dependency> <reported-options>
python scripts/runtime_setup.py verify <dependency> <reported-options>
```

VideOCR, ASR, and model installation require
`--confirm-large-download`. Show the locked variant, revision, destination,
known bytes, and lock SHA-256 first. Resume an incomplete target using the same
locked plan; do not replace its `.video-content-installing.json` plan.

Configuration uses only `VIDEO_CONTENT_*`; the default state root is
`.video-content` or `VIDEO_CONTENT_HOME`.
