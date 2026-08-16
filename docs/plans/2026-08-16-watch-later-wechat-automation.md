# Watch Later to WeChat Draft Automation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a fail-closed automation path that discovers new Bilibili Watch Later items, creates a traceable canonical subtitle, converts usable items into audited WeChat articles, and saves exactly one verified draft per item.

**Architecture:** Keep the existing extraction, content-project, renderer, and WeChat receipt layers as atomic primitives. Add a deterministic control plane for profiles, snapshots, idempotent jobs, retries, standing draft authorization, and artifact bindings. The calling Agent remains responsible for semantic evidence selection, canonical subtitle authoring, article writing, and fidelity repair.

**Tech Stack:** Python 3.10+ standard-library core, JSON Schema 2020-12, MCP 2.x, Node.js 22+, OpenCLI Browser Bridge, pytest, jsonschema, Ruff, Node test runner.

---

## Constraints

- Follow `@video-subtitle`, `@video-to-content`, and `@wechat-draft-handoff`.
- Use `@tdd-workflow` for implementation and `@verification-loop` before phase commits.
- Do not add a permanent daemon. Expose one-shot scan/cycle operations; the calling Agent or Codex automation owns scheduling.
- Do not assume the locked OpenCLI version already supports Watch Later. Verify first and keep parsing transport-independent.
- Preserve current manual workflows; automation is additive.
- Never persist cookies, tokens, passwords, browser storage, clipboard Base64, or token-bearing URLs.
- Use Chinese commit messages.

## Phase 1: Contracts and deterministic state

### Task 1: Restore the declared lint baseline

**Files:**
- Modify: `pyproject.toml`

**Step 1: Reproduce the failure**

```powershell
python -m ruff check .
```

Expected: 12 `E402` findings in the three clean-clone bootstrap scripts.

**Step 2: Add narrow per-file exceptions**

```toml
[tool.ruff.lint.per-file-ignores]
".agents/skills/wechat-draft-handoff/scripts/prepare_clipboard.py" = ["E402"]
"scripts/render_wechat_article.py" = ["E402"]
"scripts/repro_check.py" = ["E402"]
```

Do not disable `E402` globally. These scripts intentionally add the repository root to `sys.path` before package imports.

**Step 3: Verify**

```powershell
python -m ruff check .
python -m ruff format --check .
```

Expected: PASS.

**Step 4: Commit**

```powershell
git add pyproject.toml
git commit -m "明确干净克隆启动脚本的导入检查例外"
```

### Task 2: Add versioned automation schemas

**Files:**
- Create: `schemas/automation-profile.schema.json`
- Create: `schemas/automation-job.schema.json`
- Create: `schemas/watch-later-snapshot.schema.json`
- Create: `schemas/canonical-subtitle.schema.json`
- Create: `schemas/draft-authorization.schema.json`
- Create: `schemas/automation-handoff-binding.schema.json`
- Create: `tests/test_automation_contracts.py`

**Step 1: Write failing schema tests**

```python
SCHEMAS = {
    "profile": "automation-profile.schema.json",
    "job": "automation-job.schema.json",
    "snapshot": "watch-later-snapshot.schema.json",
    "canonical": "canonical-subtitle.schema.json",
    "authorization": "draft-authorization.schema.json",
    "binding": "automation-handoff-binding.schema.json",
}


def test_automation_examples_are_schema_valid():
    for name, filename in SCHEMAS.items():
        jsonschema.validate(_example(name), _schema(filename))


def test_authorization_rejects_publish():
    document = _example("authorization")
    document["allowed_actions"] = ["save_wechat_draft", "publish"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(document, _schema(SCHEMAS["authorization"]))
```

Run:

```powershell
python -m pytest tests/test_automation_contracts.py -q
```

Expected: FAIL because schemas do not exist.

**Step 2: Implement these contracts**

```text
video-automation/profile-v1
  profile_id, version, enabled, source, content, evidence_policy,
  retry_policy, draft_authorization_id, prohibited_actions

video-automation/job-v1
  job_id, idempotency_key, profile_id, profile_version, source,
  status, stage, attempts, artifacts, retry, termination, timestamps

video-automation/watch-later-snapshot-v1
  snapshot_id, captured_at, profile_id, account_profile_alias,
  entries, new_entries, source_digest

video-subtitle/canonical-v1
  canonical_id, manifest_sha256, status, evidence, cues,
  decisions, unresolved, artifacts, created_at

video-automation/draft-authorization-v1
  authorization_id, status, profile_ids, browser_profile_alias,
  allowed_actions, prohibited_actions, created_at, revoked_at

video-automation/handoff-binding-v1
  binding_id, job_id, authorization_id, project_id, deliverable_id,
  fidelity_audit_id, receipt_path, receipt_sha256, appmsgid, created_at
```

Required invariants:

- `allowed_actions` is exactly `["save_wechat_draft"]`.
- prohibited actions include publish, mass send, schedule, originality, and account management.
- canonical status is `usable` or `unusable`.
- usable canonical documents require cues and no blocking unresolved issue.
- unusable canonical documents require a structured termination reason.
- terminal jobs cannot contain a retry timestamp.

**Step 3: Verify and commit**

```powershell
python -m pytest tests/test_automation_contracts.py -q
git add schemas tests/test_automation_contracts.py
git commit -m "增加视频自动化与最佳字幕数据契约"
```

### Task 3: Implement profiles and standing draft authorization

**Files:**
- Create: `src/video_subtitle/core/automation_profile.py`
- Create: `tests/core/test_automation_profile.py`

**Step 1: Write failing tests**

Cover deterministic profile identity, draft-only authorization, revoked authorization, wrong-profile authorization, and recursive secret-key rejection.

```python
def test_authorization_allows_only_draft_save(tmp_path):
    result = save_draft_authorization(
        tmp_path / "authorization.json",
        {
            "profile_ids": ["profile-watch-later"],
            "browser_profile_alias": "wechat-main",
            "allowed_actions": ["save_wechat_draft"],
        },
    )
    assert result["allowed_actions"] == ["save_wechat_draft"]
```

Run and expect failure:

```powershell
python -m pytest tests/core/test_automation_profile.py -q
```

**Step 2: Implement APIs**

```python
def save_automation_profile(path: Path, document: dict[str, Any]) -> dict[str, Any]: ...
def read_automation_profile(path: Path) -> dict[str, Any]: ...
def save_draft_authorization(
    path: Path, document: dict[str, Any]
) -> dict[str, Any]: ...
def read_draft_authorization(path: Path) -> dict[str, Any]: ...
def require_active_draft_authorization(
    profile: dict[str, Any], authorization: dict[str, Any]
) -> None: ...
```

Use `read_json` and `write_json_atomic`, do not mutate caller input, and reject keys matching cookie, token, password, storage, clipboard payload, or Base64 recursively.

**Step 3: Verify and commit**

```powershell
python -m pytest tests/core/test_automation_profile.py -q
git add src/video_subtitle/core/automation_profile.py tests/core/test_automation_profile.py
git commit -m "实现自动化配置与长期草稿授权校验"
```

### Task 4: Add a durable automation job state machine

**Files:**
- Create: `src/video_subtitle/core/locking.py`
- Modify: `src/video_subtitle/core/batch.py`
- Create: `src/video_subtitle/core/automation_job.py`
- Create: `tests/core/test_automation_job.py`
- Modify: `tests/test_batch.py`

**Step 1: Write failing transition and locking tests**

Test idempotent job creation, invalid transitions, bounded retries, terminal-state immutability, concurrent writer exclusion, and unchanged batch behavior.

Run:

```powershell
python -m pytest tests/core/test_automation_job.py tests/test_batch.py -q
```

Expected: FAIL.

**Step 2: Extract the shared lock**

```python
@contextmanager
def exclusive_file_lock(path: Path, timeout_seconds: float = 5.0) -> Iterator[None]: ...
```

Move the current batch lock implementation into `core/locking.py` and update batch code without semantic changes.

**Step 3: Implement job APIs**

```python
def automation_idempotency_key(
    platform: str, bvid: str, page: int, profile_id: str, profile_version: int
) -> str: ...


def initialize_automation_job(
    store: Path, source: dict[str, Any], profile: dict[str, Any]
) -> dict[str, Any]: ...


def get_automation_job(path: Path) -> dict[str, Any]: ...
def list_automation_jobs(
    store: Path, *, status: str | None = None
) -> dict[str, Any]: ...
def transition_automation_job(
    path: Path,
    *,
    status: str,
    stage: str | None = None,
    artifact_kind: str | None = None,
    artifact_path: str | None = None,
    error: dict[str, Any] | None = None,
    next_retry_at: str | None = None,
) -> dict[str, Any]: ...
```

Use explicit transitions:

```python
ALLOWED = {
    "discovered": {"queued"},
    "queued": {"evidence_running", "cancelled"},
    "evidence_running": {"evidence_ready", "retry_wait", "unprocessable"},
    "evidence_ready": {"canonicalizing"},
    "canonicalizing": {"canonical_ready", "retry_wait", "unprocessable"},
    "canonical_ready": {"content_generating"},
    "content_generating": {"content_auditing", "retry_wait", "unprocessable"},
    "content_auditing": {"content_generating", "rendering", "unprocessable"},
    "rendering": {"handoff_running", "retry_wait", "unprocessable"},
    "handoff_running": {"completed", "retry_wait", "paused_auth"},
    "paused_auth": {"handoff_running", "cancelled"},
}
```

`retry_wait` must remember the stage to resume and enforce the profile retry limit. `completed`, `unprocessable`, `failed_retry_exhausted`, and `cancelled` are terminal.

**Step 4: Verify and commit**

```powershell
python -m pytest tests/core/test_automation_job.py tests/test_batch.py -q
git add src/video_subtitle/core/locking.py src/video_subtitle/core/batch.py src/video_subtitle/core/automation_job.py tests/core/test_automation_job.py tests/test_batch.py
git commit -m "增加自动化任务状态机与持久化锁"
```

## Phase 2: Watch Later discovery and queueing

### Task 5: Normalize Watch Later entries and compute snapshots

**Files:**
- Create: `src/video_subtitle/platforms/watch_later.py`
- Create: `tests/fixtures/bilibili-watch-later/first.json`
- Create: `tests/fixtures/bilibili-watch-later/reordered-with-new.json`
- Create: `tests/platforms/test_watch_later.py`

**Step 1: Write fixture-backed failing tests**

Test that order changes do not count as new videos, one new BVID/page is detected once, duplicate rows collapse, malformed entries are rejected, and snapshots contain no secret-bearing fields.

```python
def test_snapshot_detects_only_new_identity():
    first = build_watch_later_snapshot(...)
    second = build_watch_later_snapshot(..., previous=first)
    assert [(item["bvid"], item["page"]) for item in second["new_entries"]] == [
        ("BV1NEW", 1)
    ]
```

Run and expect failure:

```powershell
python -m pytest tests/platforms/test_watch_later.py -q
```

**Step 2: Implement transport-independent normalization**

```python
@dataclass(frozen=True)
class WatchLaterEntry:
    bvid: str
    page: int
    title: str
    url: str
    position: int
    added_at: str | None = None


class WatchLaterSource(Protocol):
    def list_entries(self, *, limit: int | None = None) -> list[dict[str, Any]]: ...


def normalize_watch_later_entries(
    rows: list[dict[str, Any]],
) -> list[WatchLaterEntry]: ...
def build_watch_later_snapshot(
    profile_id: str,
    account_profile_alias: str,
    entries: list[WatchLaterEntry],
    *,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]: ...
```

Identity is BVID plus page. Do not couple this module to OpenCLI subprocess behavior.

**Step 3: Verify and commit**

```powershell
python -m pytest tests/platforms/test_watch_later.py -q
git add src/video_subtitle/platforms/watch_later.py tests/platforms/test_watch_later.py tests/fixtures/bilibili-watch-later
git commit -m "实现稍后再看快照与新增视频识别"
```

### Task 6: Add a verified OpenCLI Watch Later adapter

**Files:**
- Create: `opencli-plugin/opencli-plugin.json`
- Create: `opencli-plugin/package.json`
- Create: `opencli-plugin/lib/normalize-watch-later.mjs`
- Create: `opencli-plugin/watch-later.js`
- Create: `tests/js/opencli-watch-later.test.mjs`
- Modify: `package.json`
- Modify: `npm-shrinkwrap.json`

**Step 1: Run a capability discovery gate**

```powershell
opencli list
opencli bilibili --help
```

Do not proceed by assumption. If the locked OpenCLI release now contains a verified Watch Later command, document and use its JSON contract. Otherwise create a repository-owned read-only plugin command:

```text
video-subtitle watch-later
```

**Step 2: Write parser tests before live extraction**

```javascript
import { normalizeWatchLaterPayload } from '../../opencli-plugin/lib/normalize-watch-later.mjs'

it('keeps only stable fields', () => {
  const rows = normalizeWatchLaterPayload(payload)
  assert.deepEqual(Object.keys(rows[0]).sort(), [
    'addedAt', 'bvid', 'page', 'position', 'title', 'url',
  ])
})
```

Also assert that tokens, cookies, raw provider responses, and query-bearing secret URLs are absent.

**Step 3: Implement the adapter with the official author workflow**

Requirements:

- use the existing Browser Bridge login;
- list Watch Later entries without modifying the list;
- paginate to completion or the requested limit;
- emit only BVID, page, title, canonical URL, position, and optional added time;
- return structured login-expired and malformed-response errors;
- keep endpoint or selector details inside the plugin;
- never print or persist browser credentials.

**Step 4: Validate and package**

```powershell
opencli validate video-subtitle/watch-later
npm test
npm run pack:check
```

Add `opencli-plugin/**/*` to the npm package file list. Expected: validation and tests PASS; dry-run package includes plugin files.

**Step 5: Commit**

```powershell
git add opencli-plugin tests/js package.json npm-shrinkwrap.json
git commit -m "增加稍后再看只读OpenCLI适配器"
```

### Task 7: Connect setup, Python transport, scanning, and job creation

**Files:**
- Modify: `src/video_subtitle/platforms/bilibili.py`
- Modify: `src/video_subtitle/requirements.json`
- Modify: `src/video_subtitle/environment.py`
- Modify: `src/video_subtitle/diagnostics.py`
- Create: `src/video_subtitle/core/automation_scan.py`
- Modify: `requirements/runtime-lock.json`
- Modify: `schemas/runtime-lock.schema.json`
- Modify: `tests/platforms/test_bilibili.py`
- Modify: `tests/test_environment.py`
- Modify: `tests/test_runtime_setup.py`
- Create: `tests/core/test_automation_scan.py`

**Step 1: Write failing tests**

Cover:

- `OpenCliClient.watch_later()` calls the verified command and rejects malformed results;
- `watch_later_monitor` setup requires OpenCLI, the local adapter, and Browser Bridge;
- missing adapter is an Agent action before browser login becomes a human action;
- first scan creates one job per entry;
- identical or reordered scans create no duplicate jobs;
- one added entry creates exactly one job;
- removing an item later does not cancel an existing job;
- a malformed scan creates no partial jobs.

Run:

```powershell
python -m pytest tests/platforms/test_bilibili.py tests/test_environment.py tests/test_runtime_setup.py tests/core/test_automation_scan.py -q
```

Expected: FAIL.

**Step 2: Implement the Python client method**

```python
def watch_later(self, *, limit: int | None = None) -> list[dict[str, Any]]:
    args = ["video-subtitle", "watch-later"]
    if limit is not None:
        args += ["--limit", str(limit)]
    payload = self._call(args)
    if not isinstance(payload, list):
        raise OpenCliError(
            "MALFORMED_RESULT",
            "OpenCLI Watch Later did not return a row array",
        )
    return payload
```

Use the actual built-in command if Task 6 discovers one.

**Step 3: Add capability setup**

Add `watch_later_monitor` to `requirements.json`. Probe command registration rather than inferring readiness from a directory. Return a safe Agent-installable local-plugin action with a resolved repository path when missing.

**Step 4: Implement scanning**

```python
def scan_watch_later(
    *,
    profile_path: Path,
    source: WatchLaterSource,
    store: Path,
    limit: int | None = None,
) -> dict[str, Any]: ...
```

Build and validate a complete snapshot before creating jobs. Use the Task 4 idempotency key. Return snapshot path, entry count, new-entry count, created jobs, and existing jobs.

**Step 5: Verify and commit**

```powershell
python -m pytest tests/platforms/test_bilibili.py tests/test_environment.py tests/test_runtime_setup.py tests/core/test_automation_scan.py -q
git add src/video_subtitle requirements schemas tests
git commit -m "接入稍后再看能力检查与幂等入队"
```

## Phase 3: Canonical subtitles and content gating

### Task 8: Add canonical subtitle persistence and manifest integration

**Files:**
- Create: `src/video_subtitle/core/canonical.py`
- Modify: `src/video_subtitle/core/evidence.py`
- Create: `tests/core/test_canonical.py`
- Modify: `tests/core/test_evidence.py`

**Step 1: Write failing tests**

Cover known evidence references, valid cue timing, stale manifest hashes, raw-evidence immutability, blocking unresolved issues, unusable termination, and canonical evidence discoverability.

```python
def test_usable_canonical_is_added_as_derived_evidence(manifest_path):
    result = save_canonical_subtitle(manifest_path, document=_usable_document())
    catalog = list_subtitle_evidence_for_manifest(manifest_path)
    assert result["status"] == "usable"
    assert any(
        item["source_kind"] == "canonical_subtitle" for item in catalog["evidence"]
    )
```

Run:

```powershell
python -m pytest tests/core/test_canonical.py tests/core/test_evidence.py -q
```

Expected: FAIL.

**Step 2: Implement APIs**

```python
def save_canonical_subtitle(
    manifest_path: Path,
    *,
    document: dict[str, Any],
) -> dict[str, Any]: ...


def get_canonical_subtitle(manifest_path: Path) -> dict[str, Any]: ...
def require_usable_canonical_subtitle(manifest_path: Path) -> dict[str, Any]: ...
```

For usable documents, atomically write:

```text
subtitle.canonical.srt
subtitle.canonical.json
subtitle.canonical.report.json
```

Append a derived source and artifact set without replacing platform, OCR, ASR, or reviewed evidence. For unusable documents, write only the report and do not expose readable canonical evidence.

**Step 3: Verify and commit**

```powershell
python -m pytest tests/core/test_canonical.py tests/core/test_evidence.py -q
git add src/video_subtitle/core/canonical.py src/video_subtitle/core/evidence.py tests/core/test_canonical.py tests/core/test_evidence.py
git commit -m "增加可追溯最佳字幕产物"
```

### Task 9: Gate automated content and implement bounded repair

**Files:**
- Create: `src/video_subtitle/core/automation_content.py`
- Modify: `src/video_subtitle/core/automation_job.py`
- Modify: `tests/core/test_content.py`
- Create: `tests/core/test_automation_content.py`
- Modify: `tests/core/test_automation_job.py`

**Step 1: Write failing tests**

Test that:

- manual content projects still work without canonical evidence;
- automated projects reject missing or unusable canonical evidence;
- profile intent supplies objective, audience, language, and fixed WeChat medium;
- existing Content Map and Media Plan remain internal compatibility artifacts;
- failed audits with remaining repair attempts return to content generation;
- passing audits advance to rendering;
- exhausted semantic repair attempts become `unprocessable`;
- failed audits can never advance to rendering.

Run:

```powershell
python -m pytest tests/core/test_content.py tests/core/test_automation_content.py tests/core/test_automation_job.py -q
```

Expected: FAIL.

**Step 2: Implement the automated initializer**

```python
def initialize_automated_content_project(
    *,
    manifest_path: Path,
    profile_path: Path,
    job_path: Path,
) -> dict[str, Any]: ...
```

Require a `canonical_ready` job and usable canonical subtitle, then call the existing `initialize_content_project`. Persist automation binding beside the job rather than making automation fields mandatory for every generic content project. Return instructions to materialize existing Content Map and Media Plan documents from the profile without asking the user again.

**Step 3: Implement bounded audit repair**

```python
def record_automation_audit(
    job_path: Path,
    *,
    audit_path: Path,
    max_repair_attempts: int,
) -> dict[str, Any]: ...
```

Use the current content-project validator. Count semantic repair attempts separately from technical retries.

**Step 4: Verify and commit**

```powershell
python -m pytest tests/core/test_content.py tests/core/test_automation_content.py tests/core/test_automation_job.py -q
git add src/video_subtitle/core/automation_content.py src/video_subtitle/core/automation_job.py tests/core
git commit -m "让自动内容项目消费最佳字幕并有限修复"
```

## Phase 4: Draft idempotency and Agent orchestration

### Task 10: Bind standing authorization to an existing WeChat receipt

**Files:**
- Create: `src/video_subtitle/core/automation_handoff.py`
- Create: `tests/core/test_automation_handoff.py`
- Modify: `src/video_subtitle/core/portable.py`
- Modify: `tests/test_portable_bundle.py`
- Modify: `.agents/skills/wechat-draft-handoff/SKILL.md`
- Modify: `.agents/skills/wechat-draft-handoff/references/wechat-editor-checklist.md`
- Modify: `tests/test_wechat_draft_handoff_skill.py`

**Step 1: Write failing tests**

Cover active, revoked, expired, and wrong-profile authorization; receipt validation and project binding; stable `appmsgid`; secret-free binding; portable bundle inclusion; and duplicate-handoff prevention.

```python
def test_existing_binding_prevents_duplicate_handoff(job_path):
    prepared = prepare_automation_handoff(
        job_path=job_path,
        profile_path=PROFILE,
        authorization_path=AUTHORIZATION,
    )
    assert prepared["already_completed"] is True
```

Also add Skill contract tests requiring standing authorization, current job binding, login pause, receipt validation, and all existing publish prohibitions.

Run:

```powershell
python -m pytest tests/core/test_automation_handoff.py tests/test_portable_bundle.py tests/test_wechat_draft_handoff_skill.py -q
```

Expected: FAIL.

**Step 2: Implement binding APIs**

```python
def prepare_automation_handoff(
    *, job_path: Path, profile_path: Path, authorization_path: Path
) -> dict[str, Any]: ...


def bind_automation_handoff_receipt(
    *,
    job_path: Path,
    authorization_path: Path,
    receipt_path: Path,
    output_path: Path,
) -> dict[str, Any]: ...


def get_existing_handoff_binding(job_path: Path) -> dict[str, Any] | None: ...
```

Require the referenced receipt to validate, bind the current project/deliverable/audit, state `published=false`, and contain no publish actions. Store only relative paths, hashes, IDs, authorization ID, and stable `appmsgid`.

**Step 3: Update handoff instructions**

Add a dedicated standing-authorization entry path without weakening the existing one-item explicit authorization path. Stop before browser mutation when a valid binding already exists. Treat expired login as `paused_auth`, not semantic failure.

**Step 4: Verify and commit**

```powershell
python -m pytest tests/core/test_automation_handoff.py tests/test_portable_bundle.py tests/test_wechat_draft_handoff_skill.py -q
git add src/video_subtitle/core/automation_handoff.py src/video_subtitle/core/portable.py .agents/skills/wechat-draft-handoff tests
git commit -m "绑定长期授权与微信草稿回执"
```

### Task 11: Expose automation APIs through CLI and MCP

**Files:**
- Modify: `src/video_subtitle/cli.py`
- Modify: `src/video_subtitle/mcp_server.py`
- Modify: `scripts/mcp_smoke.py`
- Create: `tests/test_automation_cli.py`
- Modify: `tests/test_dsh_bundle.py`

**Step 1: Write failing discovery tests**

Add JSON CLI commands:

```text
automation-profile-save
automation-authorize-drafts
automation-scan
automation-jobs
automation-job
automation-job-update
canonical-save
canonical-status
```

Add MCP tools:

```text
save_video_automation_profile
authorize_video_automation_drafts
scan_bilibili_watch_later
list_video_automation_jobs
get_video_automation_job
update_video_automation_job
save_canonical_subtitle
get_canonical_subtitle
```

Run:

```powershell
python -m pytest tests/test_automation_cli.py tests/test_dsh_bundle.py -q
python scripts/mcp_smoke.py
```

Expected: FAIL on missing commands and tools.

**Step 2: Implement thin adapters**

CLI and MCP must delegate to core modules. Authorization creation requires an explicit `confirm_draft_only_authorization` boolean and returns the prohibited-action list. Do not duplicate state validation in interface files.

**Step 3: Verify and commit**

```powershell
python -m pytest tests/test_automation_cli.py tests/test_dsh_bundle.py -q
python scripts/mcp_smoke.py
git add src/video_subtitle/cli.py src/video_subtitle/mcp_server.py scripts/mcp_smoke.py tests/test_automation_cli.py tests/test_dsh_bundle.py
git commit -m "暴露视频自动化与最佳字幕工具接口"
```

### Task 12: Add the Watch Later automation Skill

**Files:**
- Create: `.agents/skills/video-watch-later-automation/SKILL.md`
- Create: `.agents/skills/video-watch-later-automation/agents/openai.yaml`
- Modify: `AGENTS.md`
- Modify: `dsh/plugin.js`
- Modify: `README.md`
- Modify: `tests/test_skill_distribution.py`
- Create: `tests/test_watch_later_automation_skill.py`

**Step 1: Write failing Skill tests**

Assert that the Skill:

- is discoverable and packaged;
- treats adding an item as task submission;
- performs only required setup probes;
- never asks the user to resolve unavailable evidence;
- distinguishes retryable, paused-auth, and terminal-unprocessable states;
- uses the standing profile instead of asking for a medium;
- invokes evidence, content, and handoff Skills in order;
- processes a bounded number of jobs per wake-up;
- never publishes.

Run:

```powershell
python -m pytest tests/test_skill_distribution.py tests/test_watch_later_automation_skill.py -q
```

Expected: FAIL.

**Step 2: Write the orchestration loop**

```text
scan
→ claim one runnable job
→ collect minimum sufficient evidence
→ save usable or unusable canonical subtitle
→ stop unusable jobs
→ create internal content artifacts from the profile
→ generate, audit, and repair within limits
→ render and validate the WeChat package
→ verify standing authorization
→ save exactly one draft
→ validate receipt and binding
→ complete the job
```

Persist state after every stage. Do not turn a semantic impossibility into a user question.

**Step 3: Update discovery and packaging**

Register the fourth Skill in DSH and update public docs only after tests establish the final tool and package counts.

**Step 4: Verify and commit**

```powershell
python -m pytest tests/test_skill_distribution.py tests/test_watch_later_automation_skill.py -q
npm test
npm run pack:check
git add .agents/skills/video-watch-later-automation AGENTS.md dsh/plugin.js README.md tests
git commit -m "增加稍后再看到公众号草稿的自动化Skill"
```

## Phase 5: End-to-end contract and release readiness

### Task 13: Add a deterministic automation reproduction fixture

**Files:**
- Create: `tests/fixtures/automation/`
- Create: `tests/test_automation_workflow.py`
- Modify: `scripts/repro_check.py`
- Modify: `tests/test_repro_check.py`

**Step 1: Build a no-service fixture**

Include two Watch Later snapshots with one new item, independent subtitle evidence with one repairable disagreement, a valid canonical document, internal content artifacts, an audited WeChat article package, a mock editor observation, a receipt and binding, plus one unusable evidence case.

Do not include credentials, token-bearing URLs, or a real user source video.

**Step 2: Write the failing workflow test**

Assert:

- first cycle discovers one new job;
- usable item reaches completed with one `appmsgid`;
- running twice creates no second job or draft;
- unusable item stops before content generation;
- raw evidence hashes remain unchanged;
- all published fields remain false.

**Step 3: Extend the existing Agent reproduction tier**

Add:

```json
{
  "name": "watch_later_to_draft_contract",
  "status": "passed",
  "details": {
    "jobs_created": 1,
    "draft_bindings": 1,
    "duplicate_drafts": 0,
    "published": false
  }
}
```

Run:

```powershell
python -m pytest tests/test_automation_workflow.py tests/test_repro_check.py -q
python scripts/repro_check.py --require-tier core --require-tier agent
```

Expected: PASS.

**Step 4: Commit**

```powershell
git add tests/fixtures/automation tests/test_automation_workflow.py tests/test_repro_check.py scripts/repro_check.py
git commit -m "增加稍后再看到草稿的确定性复现验收"
```

### Task 14: Document one-shot scheduling, synchronize version, and run release gates

**Files:**
- Create: `docs/watch-later-automation.md`
- Modify: `docs/environment.md`
- Modify: `docs/reproducibility.md`
- Modify: `README.md`
- Modify: `pyproject.toml`
- Modify: `package.json`
- Modify: `npm-shrinkwrap.json`
- Modify: `src/video_subtitle/__init__.py`
- Modify: `src/video_subtitle/requirements.json`
- Modify: `requirements/runtime-lock.json`
- Modify: relevant version/distribution tests

**Step 1: Document the operator contract**

Explain that the repository exposes one-shot operations and the calling Agent or Codex automation owns the schedule. Document:

```powershell
video-subtitle automation-profile-save --document .\profile.json
video-subtitle automation-authorize-drafts --document .\authorization.json --confirm-draft-only-authorization
video-subtitle automation-scan --profile .\profile.json
video-subtitle automation-jobs --profile .\profile.json
```

State clearly:

- login expiry pauses the handoff stage;
- evidence insufficiency terminates without asking the user;
- no publishing occurs;
- live acceptance remains manual;
- repository implementation alone does not register a recurring automation.

**Step 2: Synchronize version**

After all feature tests pass, bump Python, npm, package `__version__`, and version tests to `0.7.0`. Update runtime `verified_at` only for components actually reverified.

**Step 3: Run the complete gate**

```powershell
python -m ruff check .
python -m ruff format --check .
python -m pytest
python scripts/mcp_smoke.py
npm test
npm run pack:check
python scripts/repro_check.py --require-tier core --require-tier agent
```

Expected:

- all checks PASS;
- MCP smoke lists existing and new tools with descriptions;
- npm package contains all four Skills, new schemas, and the OpenCLI plugin;
- live remains `manual_required`;
- no artifact reports publishing.

**Step 4: Run live acceptance separately**

Only with current user authorization and active browser sessions:

1. add a dedicated test video to Bilibili Watch Later;
2. scan and confirm exactly one job;
3. complete evidence and canonical subtitle generation;
4. generate and audit the article;
5. save one WeChat draft;
6. rerun and confirm no duplicate draft;
7. verify receipt and binding state `published=false`;
8. do not remove or modify the Watch Later item without separate instruction.

**Step 5: Commit**

```powershell
git add docs README.md pyproject.toml package.json npm-shrinkwrap.json src/video_subtitle requirements tests
git commit -m "发布稍后再看到公众号草稿自动化能力"
```

## Final execution boundary

Do not register a real recurring Codex automation, mutate the user's Bilibili Watch Later list, or access the live WeChat editor merely by implementing this plan. Recurring scheduling and live platform interaction remain separate explicitly authorized actions after repository implementation and live acceptance succeed.
