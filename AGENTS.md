# Repository Instructions

This is an Agent-first video evidence and content-transformation repository.
**`AGENTS.md` is the operational entrypoint.** `README.md` is the short human
overview; this file defines the repository contract and tells an Agent what to
read and run next. Read this file before changing code, running a video task,
or choosing a Skill.

Do not start from a historical script, a browser tab, a preview file, or an
archived run. Those are evidence or history, not current instructions.

## Agent entry：从这里开始

Use this entry sequence for every task; the task type decides which later
checks are necessary. Keep one `config`, one `home`, and one `run_id` for
the whole operation. In the commands below, `python` means the
project interpreter; on Windows, use `.\.venv\Scripts\python.exe` when the
virtual environment is not activated. The bootstrap script is the exception: it
may start with the host Python because it creates the environment.

### 1. 定位仓库

Run `git rev-parse --show-toplevel` and use that directory as the repository
root. Resolve all repository-relative paths from there, even when the shell was
opened in a Skill or `scripts/` subdirectory.

### 2. 先判断任务类型，避免无效步骤

先判断你是在维护仓库，还是在处理视频。项目支持 OCR、ASR 和微信交接，
不代表每次任务都要安装、启动或检查全部组件。

| 任务 | 必要步骤 | 不要做 |
| --- | --- | --- |
| 文档、目录或只读诊断 | 目录自检 + 相关文档/测试 | 不安装 VideOCR/ASR，不打开微信 |
| Python、Skill 或契约改动 | 目录自检 + 相关测试；提交前做完整验证 | 不用一次 live 操作代替自动化测试 |
| 单视频取证/转写/内容 | 只申请当前步骤需要的 capability；ASR 前做 deep doctor | 不先进入微信，不重复下载已有媒体 |
| Watch Later → 微信草稿 | 扫描/幂等 → 取证 → 内容审计 → 可见交接 | 不创建第二状态根，不创建隐藏 daemon |

语义取舍（字幕是否可信、哪些细节要保留、文章是否真的完整）交给 Agent；
路径、哈希、状态、回读和是否允许副作用交给程序。没有必要的能力就跳过安装，
遇到物理上无法取得的证据才结束为 `unprocessable`。

### 3. 判断是现有环境还是新机器

- If `<repo>/.video-content/config.json` exists, inspect the current layout before
  touching a video.
- If it does not exist or the project package is unavailable, use the fresh
  machine flow below. Do not create a parallel state root just to make a command
  appear to work.

### 4. 固定运行上下文并做目录自检

The normal context is:

```text
config = <repo>/.video-content/config.json
home   = config.values.home; if absent, the config directory
run_id = one identifier for this scan or processing run
```

For an existing checkout, run:

```text
python scripts/validate_layout.py
```

Continue only when the report says `ready=true`, has no repository/state-root
residuals or unexpected entries, and has no unresolved historical paths. After
a migration or a large archive move, also run `python scripts/validate_layout.py
--integrity`.

### 5. 检查或安装组件

Use the environment contract rather than guessing from one command:

```text
python scripts/bootstrap.py
python scripts/bootstrap.py --apply --capability <required-capability>
```

The first command reports the setup contract. The second creates/uses the
repository `.venv`, installs the project and MCP support, and runs setup. If the
project is already installed but a capability or path changed, the setup action
can also be invoked directly:

Common capability IDs are `platform_subtitle`, `video_download`,
`hard_ocr_local`, `hard_ocr_url`, `audio_asr_local`, `audio_asr_url`, and
`watch_later_monitor`. Request only the IDs needed by the current route; the
full decision table lives in the video-evidence
[environment reference](.agents/skills/video-evidence/references/environment.md).

```text
python -m video_content.cli system setup --capability <required-capability>
```

For pinned heavy runtimes, use the sequence below instead of inventing a download
URL or choosing `latest`:

```text
python scripts/runtime_setup.py plan <dependency>
python scripts/runtime_setup.py install <dependency> <reported-options>
python scripts/runtime_setup.py verify <dependency> <reported-options>
```

Execute safe `agent_actions` yourself. Persist discovered non-secret paths with
`video-content system configure`, then rerun setup. Ask the user only for
listed `human_actions`: browser login, hardware/OS boundaries, and downloads
that require explicit confirmation. A temporary Store or a command started
without the active config is not evidence that a component is missing.

### 6. 用 doctor 确认能力真的可用

After installation or any environment change, run a deep doctor for the
capability you actually need:

```text
python -m video_content.cli system doctor --capability <required-capability> --deep
```

Read the returned `configuration.path`, `configuration.state_root`,
`dependencies`, `agent_actions`, and `human_actions`. Start the video task only
when the required dependencies are `ready`; run deep doctor before ASR or any
explicit shared-GPU parallelism.

### 7. 按任务加载 Skill

Choose one route from the table below, read its `SKILL.md`, and only then read
that Skill's low-frequency `references/` or scripts. A bare video input does
not silently select a carrier; use WeChat only when the user or an active
Profile explicitly authorizes it.

### 8. 验收后才报告完成

Do not treat a process exit code, renderer output, file count, save toast, or
`appmsgid` as completion by itself. Confirm the evidence/content contract;
when WeChat is authorized, confirm the same visible draft after refresh and
save a validated Draft Receipt with `published=false`. Never publish, mass
send, schedule, declare originality, or manage an account.

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

## Progressive reading map

Read only the next layer needed for the task:

- Always: this file, then the one matching `SKILL.md`;
- Video/evidence setup: the video-evidence `environment.md` and
  `evidence-decisions.md` references when the capability or source decision is
  unclear;
- Content transformation: the video-to-content `source-faithful-adaptation.md`
  and `content-acceptance.md` references, plus the
  [expression-audit reference](.agents/skills/video-to-content/references/source-aware-expression-audit.md),
  when writing or reviewing a Content object;
- Watch Later: its `job-lifecycle.md` reference when scanning, retrying, or
  resuming Jobs;
- WeChat: its `editor-checklist.md` or `recovery-and-readback.md` reference only
  when entering or recovering the editor;
- Maintenance/diagnosis: read `docs/repository-layout.md`,
  `docs/architecture.md`, or `docs/operations.md` for the specific question.

Do not load every reference or historical plan by default. The matching Skill
is the router; references explain one stable decision; scripts perform only
deterministic work.

## Fresh machine and component installation

The short version is:

```text
python scripts/bootstrap.py
python scripts/bootstrap.py --apply --config <config-path> --capability <required-capability>
```

For normal repository use, omit `--config` and let bootstrap bind the canonical
`<repo>/.video-content/config.json`. Pass an explicit `--config` only for an
isolated or reproducibility check, and pass its matching `--home` to the
operation as well.

Treat `video-content/bootstrap-v2` as the setup contract:

1. execute safe `agent_actions`;
2. persist non-secret paths with `video-content system configure`;
3. rerun setup after environment changes;
4. ask only for remaining `human_actions`;
5. obtain confirmation for `confirmation_required=true` downloads;
6. run deep doctor before ASR or explicit shared-GPU parallelism.

For a one-time move from a previous local state, dry-run
`scripts/migrate_legacy_state.py` before `--apply`; it archives the source,
verifies hashes, seeds idempotent completed Jobs, and creates no compatibility
runtime. Never invent a release URL or silently choose `latest`.

## Runtime layout

The repository is source-only. Runtime data belongs in the ignored
`.video-content/` root, which has one configuration file and the fixed
subdirectories `profiles/`, `jobs/`, `cache/media/`, `indexes/`, `locks/`,
`meta/`, `runs/`, and `archive/`. Do not create ad-hoc state roots beside the
repository, and do not put live artifacts or one-off scripts at the state-root
top level. Historical material is retained under `archive/`; active retries
use `runs/<run_id>/`.

`config.py` automatically discovers `.video-content/config.json` when an Agent
runs from this repository. CLI, MCP, and direct Python API calls must use that
same discovered context; a direct API launched from a repository subdirectory
must still resolve to the repository root. When a selected config has no explicit
`home`, the config file's containing state directory is the anchor; outside a
discoverable checkout, the user-level config directory is used instead of the
current working directory. An isolated test must pass both an explicit
`--config` and `--home`; a temporary Store alone is not a valid environment
check. Before executing a capability, report the resolved config path, state root,
and `system doctor` result. Never infer a missing runtime from a command that
was launched without the active configuration. Historical absolute paths in
immutable Artifacts are provenance only; consult `meta/path-relocation.json`
instead of rewriting them. Migration receipts belong under
`meta/migration-receipt.json`, never at the state-root top level.

Run `python scripts/validate_layout.py` before and after a structural change;
it is read-only and must report `ready=true`. The checker also enforces the
repository root source-layout allowlist, so a new top-level preview, log,
script, or media file fails loudly instead of becoming an unofficial runtime
入口. After a migration or large-scale archive move, also run
`python scripts/validate_layout.py --integrity` to hash-check all active Job
Artifacts. If either report shows residual temporary directories, unexpected
repository/state-root entries, unresolved historical paths, or integrity
errors, fix or archive them before starting another video Job.

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

Content uses a saved Transcript. The default editorial policy is 来源忠实
(source-faithful): repair transcription, translation, oral noise, paragraphing,
and visual references while preserving source structure, speaker roles,
professional density, examples, uncertainty, and voice. Summary, audience
rewrite, style imitation, a new thesis, a new analogy, or material reorder
requires an explicit user request. Mechanical cue concatenation, fixed-length
paragraphing, or regex punctuation is not written adaptation and must never be
marked `reviewed_by=agent` or `status=passed`. A `raw Transcript passthrough`
validation result is a hard Content-stage stop, not permission to continue.

A written edition is the source's written form, not a second-hand video explainer（不是二手解说）.
The body normally adopts the source's direct 叙述视角: preserve the source
speaker's `I`/`we`, questions, satire, judgments, and speaker attribution where
they carry meaning. Keep source disclosure concentrated in metadata or one short disclosure; do not wrap ordinary paragraphs in repeated “视频认为”,
“视频指出”, “创作者介绍”, or “本期视频里” narration. These words remain valid
when a video, creator, or act of publishing is the actual discussion object or
when attribution is materially necessary. This is an Agent semantic judgment,
not a global banned-word or regex rule.

After a complete source-faithful draft exists, run 来源感知表达审校 only on
Agent-added or carrier-adaptation language such as the title, transitions,
summary, evidence boundaries, and ending. Record it as
`audit.expression_audit` with `policy=source_aware_minimal`, then recheck source
fidelity. Source-owned contrasts, questions, metaphors, lists, professional
phrasing, and real repetition take priority over generic style preferences.
This is not a fixed公众号文风, a full-text rewrite, a regex “AI tone” scan, or
permission to reduce information density.

For Watch Later Profiles, `source_faithful_full` is the default contract. It
preserves substantive content rather than every cue（保留实质内容，不是每个 cue）. Advertising,
sponsorship copy, 商品推广, subscribe/like/follow language, and other platform CTA
are normally explicit omissions when they do not advance the subject. Preserve
a compact sponsorship or 利益披露 when it affects provenance or interpretation,
and treat promotion as material when the promoted product is itself the topic.
Removing a segment means removing its heading and editorial trace too: never
leave “已删除广告”, “视频原文中的推广段”, or another 占位说明 in the article.
The Content audit must map every material section from Transcript cues to output
blocks, list omissions, and include a per-frame visual plan whose block index
points to the actual body image. Content media must exactly match ordered document
image blocks. The Profile frame minimum is only a floor; select and inspect frames
at real visual or argument transitions rather than
using evenly spaced screenshots. A scout-proven static source may use an audited
`visual_exception`; never duplicate meaningless frames to satisfy the minimum.

An existing Content Artifact, successful renderer, or complete media list is not
proof that the article is complete. `source_faithful_full` must not silently become
a summary: the Agent checks the actual body at the opening, middle, and ending and
keeps material details, professional qualifiers, and source progression. A
passing `expression_audit` is required in addition to the existing section and
visual audits; it cannot repair or excuse missing source content.

Video-derived images default to the original cover and timestamped source
frames; do not generate or source filler visuals without separate user
approval.

The Python/MCP layer stops at an audited Content object. WeChat mutation is
optional, visible, and separately authorized. The clipboard payload is
transient. Persist only no-secret visible observations and a validated
`video-content/draft-receipt-v1` with `published=false`. When the Profile
requires it, select and refresh-read-back the WeChat creation-source disclosure
“内容由AI生成”; this is not an originality declaration.

After an ambiguous browser read or save, inspect the same visible target and
active Draft Receipts before retrying. A technical timeout is retryable, not a
reason to create another draft; a real login page is the only `paused_auth`
boundary.

Never publish, mass send, schedule, declare originality, monetize, or manage an
account.

## Automation boundary

Watch Later operations are one-shot. Codex automation or the calling Agent owns
recurrence; this repository must not create a daemon. Jobs are idempotent by
stable source identity. Do not create a second draft for a Job with a validated
Draft Receipt. An explicitly authorized correction may update only the same
numeric `appmsgid`; save a new Receipt with `supersedes_receipt_id` and retain the
older immutable Receipt as history.

## Verification

Before committing implementation changes run:

```text
python scripts/validate_layout.py
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
