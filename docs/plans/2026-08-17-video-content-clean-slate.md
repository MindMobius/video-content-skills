# Video Content Skills 1.0 Clean-slate Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把仓库硬切为 `video-content-skills` 1.0，用六种持久产物和最小 CLI/MCP 能力面覆盖单视频证据、内容生成、稍后再看自动化与微信草稿交接。

**Architecture:** 新建 `src/video_content/`，以统一 `Store`、六类文档和一个 Job 状态机替换 project/batch/phase/automation wrapper。CLI、MCP 和四个 Skill 调用同一服务层；Bilibili、下载、OCR、ASR、renderer 与 Browser Bridge 的已验证实现迁入新命名空间。旧运行数据通过一次性迁移脚本归档并提取基线，运行时不保留兼容层。

**Tech Stack:** Python 3.10+、标准库 dataclass/argparse/pathlib、JSON Schema、pytest、ruff、MCP 2.0、Node.js test runner、OpenCLI Browser Bridge。

---

## 执行约束

- 在 `D:\code\video-content-clean-slate-worktree` 的 `codex/video-content-clean-slate` 分支执行。
- 使用 `D:\code\video-subtitle-skill\.venv\Scripts\python.exe` 运行 Python 工具，除非新工作树建立自己的环境。
- 每个任务先写失败测试，再最小实现，再跑定向测试，再提交。
- 提交信息必须是简洁中文。
- 不创建旧 CLI、模块、环境变量、schema 或 Skill 的兼容入口。
- 不删除旧 `.video-subtitle-local` 数据；先验证绝对路径，再归档到仓库外。
- 不执行真实发布、群发或未经本轮明确授权的微信写操作。

### Task 1: 固定 1.0 元数据与六产物契约

**Files:**
- Modify: `pyproject.toml`
- Modify: `package.json`
- Modify: `npm-shrinkwrap.json`
- Create: `src/video_content/__init__.py`
- Create: `src/video_content/models.py`
- Create: `schemas/profile.schema.json`
- Create: `schemas/job.schema.json`
- Create: `schemas/evidence.schema.json`
- Create: `schemas/transcript.schema.json`
- Create: `schemas/content.schema.json`
- Create: `schemas/draft-receipt.schema.json`
- Create: `tests/test_v1_contracts.py`

**Step 1: 写失败测试**

测试要求：

```python
assert distribution_name == "video-content-skills"
assert version == "1.0.0"
assert module_import("video_content")
assert schema_ids == {
    "video-content/profile-v1",
    "video-content/job-v1",
    "video-content/evidence-v1",
    "video-content/transcript-v1",
    "video-content/content-v1",
    "video-content/draft-receipt-v1",
}
```

同时断言 Job status/stage 枚举、`published` 必须为 `false`、六种文档禁止未知顶层字段。

**Step 2: 验证测试先失败**

Run:

```powershell
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m pytest tests/test_v1_contracts.py -q
```

Expected: 因 `video_content` 和新 schema 不存在而失败。

**Step 3: 写最小模型和 schema**

`models.py` 至少提供：

```python
@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    kind: str
    path: str
    sha256: str
    bytes: int

@dataclass
class Job:
    schema: str
    job_id: str
    run_id: str | None
    idempotency_key: str
    source: dict[str, Any]
    stage: str
    status: str
    attempts: int
    artifacts: list[ArtifactRef]
    created_at: str
    updated_at: str
```

为 Profile、Evidence、Transcript、Content、DraftReceipt 建立明确 dataclass/序列化入口；schema 只约束稳定契约，不把 Agent 的临时思考过程持久化。

**Step 4: 更新元数据**

- Python 分发名 `video-content-skills`，版本 `1.0.0`；
- scripts 为 `video-content` / `video-content-mcp`；
- package data 指向 `video_content`；
- NPM workspace `private=true`，删除 main/exports/files/DSH bundle 元数据；
- 保留 Node 测试脚本，但不再把仓库当 NPM 产品发布。

**Step 5: 跑测试并提交**

Run:

```powershell
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m pytest tests/test_v1_contracts.py -q
```

Expected: PASS。

Commit:

```powershell
git add pyproject.toml package.json npm-shrinkwrap.json src/video_content schemas tests/test_v1_contracts.py
git commit -m "建立视频内容一体化核心契约"
```

### Task 2: 实现统一 Store、不可变 Artifact 和 Job 状态机

**Files:**
- Create: `src/video_content/util.py`
- Create: `src/video_content/store.py`
- Create: `src/video_content/jobs.py`
- Create: `tests/core/test_store.py`
- Create: `tests/core/test_jobs_v1.py`

**Step 1: 写 Store 失败测试**

覆盖：

- 原子 JSON 写入；
- `jobs/<job_id>/job.json` 和 `events.jsonl`；
- Artifact 首次保存成功，相同哈希幂等，不同内容拒绝覆盖；
- 拒绝绝对路径、`..` 和逃逸根目录；
- 按 `run_id`、status、source identity 查询；
- 同一 idempotency key 不重复建 Job。

**Step 2: 写状态机失败测试**

允许的主路径：

```text
queued -> inspecting -> evidence -> transcript -> content -> handoff -> completed
```

允许的控制状态：

```text
retryable -> queued
paused_auth -> queued
任意处理中状态 -> unprocessable
```

禁止终态回退、越级完成和重复微信 handoff。

**Step 3: 运行测试确认失败**

```powershell
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m pytest tests/core/test_store.py tests/core/test_jobs_v1.py -q
```

**Step 4: 最小实现**

`Store` 提供：

```python
create_job(...)
get_job(job_id)
list_jobs(run_id=None, status=None, profile_id=None)
update_job(job_id, *, stage=None, status=None, error=None, retry_at=None)
append_event(job_id, event)
put_artifact(job_id, *, kind, source_path=None, data=None, metadata=None)
list_artifacts(job_id, kind=None)
read_artifact(job_id, artifact_id)
save_profile(profile)
get_profile(profile_id)
```

所有写入先写同目录临时文件再 `replace`；Artifact 用 SHA-256 命名并登记 metadata。

**Step 5: 跑测试并提交**

```powershell
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m pytest tests/core/test_store.py tests/core/test_jobs_v1.py -q
git add src/video_content tests/core/test_store.py tests/core/test_jobs_v1.py
git commit -m "实现统一任务存储与状态机"
```

### Task 3: 迁移配置、环境诊断和重运行时安装

**Files:**
- Create: `src/video_content/config.py`
- Create: `src/video_content/environment.py`
- Create: `src/video_content/diagnostics.py`
- Create: `src/video_content/requirements.json`
- Modify: `scripts/bootstrap.py`
- Modify: `scripts/runtime_setup.py`
- Modify: `requirements/runtime-lock.json`
- Replace: `schemas/config.schema.json`
- Replace: `schemas/bootstrap.schema.json`
- Replace: `schemas/setup.schema.json`
- Replace: `schemas/requirements.schema.json`
- Modify: `tests/test_bootstrap.py`
- Modify: `tests/test_environment.py`
- Modify: `tests/test_diagnostics.py`
- Modify: `tests/test_runtime_setup.py`

**Step 1: 把测试改成 1.0 失败断言**

- 只识别 `VIDEO_CONTENT_HOME` 等新环境变量；
- 默认目录为 `.video-content`；
- bootstrap schema 为 `video-content/bootstrap-v1`；
- 输出 canonical Skill 路径、新 CLI 与 MCP launch contract；
- 大下载仍需 `--confirm-large-download`，锁文件 revision/SHA/bytes 行为不变；
- 不完整安装 marker 改为 `.video-content-installing.json`。

**Step 2: 运行定向测试确认失败**

```powershell
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m pytest tests/test_bootstrap.py tests/test_environment.py tests/test_diagnostics.py tests/test_runtime_setup.py -q
```

**Step 3: 迁移实现，不保留旧变量 fallback**

复制经过验证的依赖发现、doctor、锁定安装和恢复逻辑到 `video_content`，然后让脚本只导入新模块。

**Step 4: 验证并提交**

```powershell
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m pytest tests/test_bootstrap.py tests/test_environment.py tests/test_diagnostics.py tests/test_runtime_setup.py -q
git add src/video_content scripts/bootstrap.py scripts/runtime_setup.py requirements schemas tests
git commit -m "迁移视频内容运行环境契约"
```

### Task 4: 迁移 Bilibili、媒体缓存、OCR、ASR 与证据服务

**Files:**
- Create: `src/video_content/platforms/__init__.py`
- Create: `src/video_content/platforms/base.py`
- Create: `src/video_content/platforms/bilibili.py`
- Create: `src/video_content/platforms/watch_later.py`
- Create: `src/video_content/backends/__init__.py`
- Create: `src/video_content/backends/ocr.py`
- Create: `src/video_content/backends/asr.py`
- Create: `src/video_content/backends/qwen_asr_worker.py`
- Create: `src/video_content/evidence.py`
- Create: `src/video_content/scout.py`
- Create: `src/video_content/srt.py`
- Create: `tests/test_evidence_service.py`
- Modify: `tests/platforms/test_bilibili.py`
- Modify: `tests/platforms/test_watch_later.py`
- Modify: `tests/backends/test_ocr.py`
- Modify: `tests/backends/test_asr.py`
- Modify: `tests/core/test_scout.py`
- Modify: `tests/core/test_srt.py`

**Step 1: 写统一证据服务失败测试**

`source_inspect` 只支持 Bilibili；`evidence_start` 创建/恢复 Job，保存 media manifest、platform subtitle、OCR、ASR、scout 等独立 Artifact；下载缓存命中时不得重新下载。

测试必须证明：

- 平台字幕存在不等于硬字幕不存在；
- scout 结论 uncertain/continuous 时不能错误跳过全视频 OCR；
- URL-backed OCR/ASR 复用 `cache/media`；
- `actual_bytes` / `actual_mib` 来自实际文件；
- OCR 与 ASR 共享 GPU 时通过同一锁串行；
- 原始证据不能被规范字幕覆盖。

**Step 2: 跑定向测试确认失败**

```powershell
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m pytest tests/test_evidence_service.py tests/platforms tests/backends tests/core/test_scout.py tests/core/test_srt.py -q
```

**Step 3: 迁移底层实现并接入 Store**

删除 review window 依赖；scout 只生成 Evidence/建议，视觉判断由 Agent 完成。后台 worker 只通过 Job 和 Artifact 交换结果。

**Step 4: 验证并提交**

```powershell
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m pytest tests/test_evidence_service.py tests/platforms tests/backends tests/core/test_scout.py tests/core/test_srt.py -q
git add src/video_content tests
git commit -m "迁移视频来源与多重字幕证据能力"
```

### Task 5: 实现 Transcript 与 Content 服务并保留微信 renderer

**Files:**
- Create: `src/video_content/content.py`
- Create: `src/video_content/renderer.py`
- Modify: `scripts/render_wechat_article.py`
- Remove: `schemas/canonical-subtitle.schema.json`
- Remove: `schemas/content-map.schema.json`
- Remove: `schemas/content-project.schema.json`
- Remove: `schemas/fidelity-audit.schema.json`
- Remove: `schemas/media-plan.schema.json`
- Remove: `schemas/wechat-manuscript.schema.json`
- Modify: `tests/core/test_content.py`
- Modify: `tests/test_content_examples.py`
- Modify: `tests/test_wechat_renderer.py`
- Create: `tests/test_transcript_content_service.py`

**Step 1: 写失败测试**

- `transcript_save` 只接受已存在 Evidence 引用；
- Transcript 保存证据选择、校正摘要、未解决不确定性和质量结论；
- `content_save` 只接受可信 Transcript；
- 微信文章媒体只允许原封面与时间戳帧；
- renderer 输出 body HTML、preview、assets 和相对图片 marker；
- `content_validate` 校验 provenance、媒体哈希、无 Base64 持久图片、无未授权 synthetic image；
- 不再要求 project 初始化、phase 开始/结束或 deliverable wrapper。

**Step 2: 运行定向测试确认失败**

```powershell
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m pytest tests/test_transcript_content_service.py tests/core/test_content.py tests/test_content_examples.py tests/test_wechat_renderer.py -q
```

**Step 3: 迁移并收敛实现**

把现有 canonical/content/renderer 的有效校验合并到 `content.py`，删除阶段计时和 project 层。脚本成为薄入口。

**Step 4: 验证并提交**

```powershell
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m pytest tests/test_transcript_content_service.py tests/core/test_content.py tests/test_content_examples.py tests/test_wechat_renderer.py -q
git add -A src/video_content scripts schemas tests
git commit -m "统一规范字幕与内容交付模型"
```

### Task 6: 实现稍后再看 Profile、扫描与 Job 编排

**Files:**
- Create: `src/video_content/automation.py`
- Create: `tests/test_watch_later_service.py`
- Replace: `tests/test_automation_contracts.py`
- Replace: `tests/test_automation_workflow.py`
- Remove: `tests/test_batch.py`
- Remove: `tests/core/test_automation_actions.py`
- Remove: `tests/core/test_automation_content.py`
- Remove: `tests/core/test_automation_handoff.py`
- Remove: `tests/core/test_automation_integrity.py`
- Remove: `tests/core/test_automation_job.py`
- Remove: `tests/core/test_automation_paths.py`
- Remove: `tests/core/test_automation_profile.py`
- Remove: `tests/core/test_automation_scan.py`
- Remove: `schemas/automation-handoff-binding.schema.json`
- Remove: `schemas/automation-job.schema.json`
- Remove: `schemas/automation-profile.schema.json`
- Remove: `schemas/batch-manifest.schema.json`
- Remove: `schemas/watch-later-snapshot.schema.json`

**Step 1: 写统一自动化失败测试**

测试 fixture 的第一次扫描、重排和新增：

```python
first = watch_later_scan(profile_id="daily")
assert first.created == expected_initial_count
second = watch_later_scan(profile_id="daily")
assert second.created == 0
third = watch_later_scan(profile_id="daily", fixture="reordered-with-new")
assert third.created == 1
```

再覆盖：共享 `run_id`、幂等 source identity、技术失败 retry、证据不足 `unprocessable`、真实登录边界 `paused_auth`、完成后推进 baseline、不重复 handoff。

**Step 2: 运行测试确认失败**

```powershell
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m pytest tests/test_watch_later_service.py tests/test_automation_contracts.py tests/test_automation_workflow.py -q
```

**Step 3: 以 Profile + Job 实现，不重建 batch wrapper**

Profile 保存 baseline 与 carrier=`wechat_article`；扫描只创建/查询 Job。调用 Agent/Codex automation 负责周期触发和逐项推进，仓库不启动 daemon。

**Step 4: 验证并提交**

```powershell
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m pytest tests/test_watch_later_service.py tests/test_automation_contracts.py tests/test_automation_workflow.py -q
git add -A src/video_content schemas tests
git commit -m "用统一任务模型重建稍后再看自动化"
```

### Task 7: 迁移微信草稿准备、浏览器绑定和收据验证

**Files:**
- Create: `src/video_content/wechat.py`
- Modify: `scripts/build_wechat_draft_receipt.py`
- Modify: `scripts/validate_wechat_draft_receipt.py`
- Modify: `scripts/validate_wechat_package.py`
- Replace: `schemas/draft-authorization.schema.json`
- Replace: `schemas/wechat-browser-snapshot.schema.json`
- Replace: `schemas/wechat-editor-observation.schema.json`
- Modify: `tests/test_wechat_adapter.py`
- Modify: `tests/test_wechat_article_workflow.py`
- Modify: `tests/test_validate_wechat_package.py`
- Create: `tests/test_wechat_service.py`
- Keep/Modify: `tests/fixtures/mock-wechat-editor/*`
- Keep/Modify: `tests/js/mock-wechat-editor.test.mjs`
- Keep/Modify: `tests/js/wechat-browser-adapter.test.mjs`

**Step 1: 写失败测试**

- `wechat_prepare` 只接受 validated Content 和显式 authorization；
- 生成无秘密 handoff package，不保存 clipboard HTML；
- `wechat_bind` 必须验证当前 Content hash、可见编辑器 observation、保存后刷新回读和唯一性；
- 收据 schema 只能是 `video-content/draft-receipt-v1`；
- `published` 固定为 `false`；
- 同一 Job 已有有效收据时拒绝再次创建草稿；
- cookie、token、browser storage、Base64 图片触发失败。

**Step 2: 运行 Python 与 Node 定向测试确认失败**

```powershell
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m pytest tests/test_wechat_service.py tests/test_wechat_adapter.py tests/test_wechat_article_workflow.py tests/test_validate_wechat_package.py -q
npm test
```

**Step 3: 迁移有效实现并统一到 Draft Receipt**

保留 Browser Bridge adapter、临时 clipboard helper 和刷新回读；删除 generic/automation 两套 handoff binding。

**Step 4: 验证并提交**

```powershell
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m pytest tests/test_wechat_service.py tests/test_wechat_adapter.py tests/test_wechat_article_workflow.py tests/test_validate_wechat_package.py -q
npm test
git add -A src/video_content scripts schemas tests
git commit -m "统一微信草稿交接与收据验证"
```

### Task 8: 建立最小 CLI 与 MCP 能力面

**Files:**
- Create: `src/video_content/cli.py`
- Create: `src/video_content/mcp_server.py`
- Create: `src/video_content/__main__.py`
- Replace: `scripts/mcp_smoke.py`
- Replace: `tests/test_cli.py`
- Replace: `tests/test_mcp.py`
- Remove: `tests/test_automation_cli.py`
- Remove: `tests/test_pipeline.py`

**Step 1: 写 CLI 失败测试**

断言仅存在批准分组和动作：

```text
system setup|configure|doctor
source inspect
evidence start
job get|list|update|artifacts|read-artifact
content save|validate|save-transcript
watch-later scan
wechat prepare|bind
```

所有命令 stdout 只输出一个 JSON 文档，错误也使用稳定 JSON envelope 与非零退出码。

**Step 2: 写 MCP 失败测试**

精确断言 16 个 tool name：

```python
{
 "system_setup", "system_configure", "system_doctor", "source_inspect",
 "evidence_start", "job_get", "artifact_list", "artifact_read",
 "transcript_save", "content_save", "content_validate", "watch_later_scan",
 "job_list", "job_update", "wechat_prepare", "wechat_bind",
}
```

**Step 3: 运行测试确认失败**

```powershell
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m pytest tests/test_cli.py tests/test_mcp.py -q
```

**Step 4: 实现薄适配层**

CLI 与 MCP 调用同一 service functions，不在适配层复制模型、路径或状态逻辑。`mcp_smoke.py` 使用内存/临时 Store 验证工具注册和代表性调用。

**Step 5: 验证并提交**

```powershell
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m pytest tests/test_cli.py tests/test_mcp.py -q
D:\code\video-subtitle-skill\.venv\Scripts\python.exe scripts/mcp_smoke.py
git add -A src/video_content scripts tests
git commit -m "收敛视频内容CLI与MCP能力面"
```

### Task 9: 重建四个渐进式 Agent Skill

**Files:**
- Create: `.agents/skills/video-evidence/SKILL.md`
- Create: `.agents/skills/video-evidence/references/*`
- Create/Move: `.agents/skills/video-evidence/scripts/*`
- Replace: `.agents/skills/video-to-content/SKILL.md`
- Reorganize: `.agents/skills/video-to-content/references/*`
- Create: `.agents/skills/watch-later-to-wechat/SKILL.md`
- Create: `.agents/skills/watch-later-to-wechat/references/*`
- Create: `.agents/skills/wechat-draft/SKILL.md`
- Create: `.agents/skills/wechat-draft/references/*`
- Create/Move: `.agents/skills/wechat-draft/scripts/*`
- Remove: `.agents/skills/video-subtitle/`
- Remove: `.agents/skills/video-watch-later-automation/`
- Remove: `.agents/skills/wechat-draft-handoff/`
- Replace: `tests/test_skill_distribution.py`
- Replace: `tests/test_watch_later_automation_skill.py`
- Replace: `tests/test_wechat_draft_handoff_skill.py`
- Create: `tests/test_agent_skill_routing.py`

**Step 1: 写结构和路由失败测试**

- 恰好四个 Skill；
- 每个 frontmatter `name` 与目录一致；
- `SKILL.md` 控制长度，只包含触发、边界、主流程和按需引用；
- canonical source 只在 `.agents/skills`；
- 所有本地链接存在；
- 不引用旧 CLI、模块、schema、目录或已删除动作；
- 自动化 Skill 明确 no daemon/no publish/retry/unprocessable/paused_auth/GPU serial；
- 微信 Skill 明确 explicit authorization、visible login、refresh readback、`published=false`。

**Step 2: 运行测试确认失败**

```powershell
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m pytest tests/test_skill_distribution.py tests/test_agent_skill_routing.py tests/test_watch_later_automation_skill.py tests/test_wechat_draft_handoff_skill.py -q
```

**Step 3: 重建 Skill**

迁移仍有用的脚本与细节，删除重复说明。低频环境、证据判断、内容约束和浏览器交接细节分别进入 references。

**Step 4: 验证并提交**

```powershell
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m pytest tests/test_skill_distribution.py tests/test_agent_skill_routing.py tests/test_watch_later_automation_skill.py tests/test_wechat_draft_handoff_skill.py -q
git add -A .agents tests
git commit -m "重建四个渐进式视频内容技能"
```

### Task 10: 重写 Agent 入口文档并删除开发遗留文档

**Files:**
- Replace: `README.md`
- Replace: `AGENTS.md`
- Replace: `docs/skill-maintenance.md`
- Create: `docs/architecture.md`
- Create: `docs/operations.md`
- Remove: `docs/cases/`
- Remove: 旧的 watch-later/rebrand/hardening 计划文档
- Remove or merge: `docs/content-workflow.md`
- Remove or merge: `docs/environment.md`
- Remove or merge: `docs/reproducibility.md`
- Remove: `docs/research.md`
- Remove or merge: `docs/watch-later-automation.md`
- Remove or merge: `docs/workflow.md`
- Replace: `tests/test_project_documentation.py`

**Step 1: 写文档失败测试**

断言：

- README 简短说明项目意义、四种能力、Agent 路由、边界和最短 fresh-machine 入口；
- AGENTS 只保留仓库级路由、环境契约、工具边界、验证和提交规则；
- `skill-maintenance.md` 解释渐进式维护、何时改 SKILL/reference/script/schema/test；
- 活动文档不出现旧项目标识和已删除能力；
- `docs/plans/` 最终只保留 clean-slate design 与 implementation plan，作为 1.0 决策依据。

**Step 2: 运行测试确认失败**

```powershell
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m pytest tests/test_project_documentation.py -q
```

**Step 3: 重写和清理**

README 目标约 80–120 行，面向 Agent 而非人工操作手册。`architecture.md` 解释六产物和状态机，`operations.md` 解释 setup/doctor/cache/retry/live boundary。

**Step 4: 验证并提交**

```powershell
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m pytest tests/test_project_documentation.py -q
git add -A README.md AGENTS.md docs tests/test_project_documentation.py
git commit -m "重写视频内容技能文档入口"
```

### Task 11: 建立历史数据归档与一次性迁移工具

**Files:**
- Create: `scripts/migrate_legacy_state.py`
- Create: `tests/test_legacy_state_migration.py`
- Modify: `.gitignore`

**Step 1: 写失败测试**

在临时目录构造旧 profile、13 个 completed job、receipt 和 media cache，断言：

- dry-run 只输出源/目标绝对路径、数量和哈希计划；
- apply 前检查源在预期目录、目标在仓库外且不存在冲突；
- 原目录被整体归档，文件数量与哈希不变；
- 新 Profile 保存 baseline 和 carrier；
- 13 个 source identity 作为 completed/imported Job 或幂等登记存在；
- media cache 被受控迁移且 manifest 中实际字节一致；
- 新系统不会为相同 source identity 新建 Job 或 handoff；
- 脚本不把秘密字段复制进新 Store；
- 失败可恢复且不删除唯一副本。

**Step 2: 运行测试确认失败**

```powershell
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m pytest tests/test_legacy_state_migration.py -q
```

**Step 3: 实现 dry-run / apply / verify**

Windows 移动使用单一 PowerShell/Python 路径语义；递归移动前对 `resolve()` 后的源、归档根和新 Store 根做包含关系检查。默认先复制/验证再把源重命名为只读归档，绝不直接递归删除。

**Step 4: fixture 验证并提交**

```powershell
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m pytest tests/test_legacy_state_migration.py -q
git add scripts/migrate_legacy_state.py tests/test_legacy_state_migration.py .gitignore
git commit -m "增加旧运行数据安全迁移工具"
```

### Task 12: 删除旧实现、DSH、portable bundle 和旧 schema

**Files:**
- Remove: `src/video_subtitle/`
- Remove: `dsh/`
- Remove: `scripts/project_bundle.py`
- Remove: `schemas/portable-bundle.schema.json`
- Remove: `schemas/review-decisions.schema.json`
- Remove: `schemas/review-packet.schema.json`
- Remove: `schemas/evidence-catalog.schema.json`
- Remove: `schemas/evidence-range.schema.json`
- Remove: `schemas/manifest.schema.json`
- Remove: `schemas/ocr-scout-plan.schema.json` if folded into Evidence metadata
- Remove: `tests/test_dsh_bundle.py`
- Remove: `tests/test_portable_bundle.py`
- Remove: `tests/core/test_review.py`
- Remove: obsolete legacy tests
- Modify: `scripts/repro_check.py`
- Modify: `.github/workflows/*`
- Modify: `uv.lock`
- Create: `tests/test_no_legacy_surface.py`

**Step 1: 写遗留面失败测试**

扫描 tracked text/path，禁止：

```text
video-subtitle-skill
video_subtitle
video-subtitle/
VIDEO_SUBTITLE_
.video-subtitle
prepare_subtitle_review
get_subtitle_review_window
submit_subtitle_review_window
start_video_content_phase
finish_video_content_phase
initialize_video_batch
project_bundle
DeepSeek Harness
```

允许 clean-slate 设计/实施计划在“删除清单”中引用旧词；测试使用 allowlist 精确限定这两个文件。

**Step 2: 删除旧实现并更新锁文件/CI**

不把旧代码搬到 `legacy/`。`repro_check.py` 改为检查新模块、四个 Skill、六 schema、CLI/MCP 和 renderer。

**Step 3: 运行遗留面与打包测试**

```powershell
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m pytest tests/test_no_legacy_surface.py tests/test_repro_check.py -q
npm run pack:check
```

Expected: 仓库活动面无旧标识，NPM dry-run 只作为 workspace 边界检查。

**Step 4: 提交**

```powershell
git add -A
git commit -m "删除旧字幕项目兼容面与开发遗留"
```

### Task 13: 建立完整离线端到端 fixture

**Files:**
- Create: `tests/test_end_to_end_v1.py`
- Reuse/Modify: `tests/fixtures/authorized-video/*`
- Reuse/Modify: `tests/fixtures/automation/*`
- Reuse/Modify: `tests/fixtures/bilibili-watch-later/*`
- Reuse/Modify: `tests/fixtures/mock-wechat-editor/*`

**Step 1: 写端到端测试**

使用临时 `VIDEO_CONTENT_HOME` 执行：

```text
source_inspect
-> evidence_start
-> 保存 platform/OCR fixture
-> transcript_save
-> content_save
-> content_validate
-> wechat_prepare
-> mock editor observation
-> wechat_bind
-> validated Draft Receipt
```

断言 Job 最终 `completed`、六类产物关系完整、原始证据哈希未改变、图片只来自 fixture video/cover/frame、`published=false`、重复运行不产生第二个 Job/Content/Receipt。

**Step 2: 运行确认失败，再补齐最小集成缺口**

```powershell
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m pytest tests/test_end_to_end_v1.py -q
```

**Step 3: 跑通过并提交**

```powershell
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m pytest tests/test_end_to_end_v1.py -q
git add tests/test_end_to_end_v1.py tests/fixtures src/video_content
git commit -m "验证视频到微信草稿完整离线链路"
```

### Task 14: 对真实本机状态执行归档和基线迁移

**Files outside repository:**
- Source: `D:\code\video-subtitle-skill\.video-subtitle-local`
- Archive: 选择 `D:\code\video-content-archive\video-subtitle-local-2026-08-17` 或同级明确仓库外目录
- New state: `D:\code\video-content-state`（或现有配置指定的新 `VIDEO_CONTENT_HOME`）

**Step 1: 精确检查路径**

```powershell
Resolve-Path 'D:\code\video-subtitle-skill\.video-subtitle-local'
Test-Path 'D:\code\video-content-archive\video-subtitle-local-2026-08-17'
Test-Path 'D:\code\video-content-state'
```

确认 source 位于旧仓库内，archive/new state 位于仓库外，且不会覆盖未知目录。

**Step 2: dry-run 并保存报告**

```powershell
D:\code\video-subtitle-skill\.venv\Scripts\python.exe scripts/migrate_legacy_state.py plan --source <source> --archive <archive> --home <new-home> --output <report>
```

检查 13 completed jobs、13 receipts、媒体文件数和哈希摘要。

**Step 3: apply 与 verify**

```powershell
D:\code\video-subtitle-skill\.venv\Scripts\python.exe scripts/migrate_legacy_state.py apply --plan <report>
D:\code\video-subtitle-skill\.venv\Scripts\python.exe scripts/migrate_legacy_state.py verify --plan <report>
```

Expected: 旧状态只读归档，新 Profile/baseline/cache 可用，相同 13 个 source identity 不会重新入队。

**Step 4: 不提交运行数据**

只在最终报告记录路径、数量、哈希验证和防重复结果；任何本机 profile、receipt、媒体或授权状态都不得进入 Git。

### Task 15: 全量验证、修复、推送并快进合入 main

**Files:**
- Modify as required by failures

**Step 1: 运行完整验证**

```powershell
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m ruff check .
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m ruff format --check .
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m pytest
D:\code\video-subtitle-skill\.venv\Scripts\python.exe scripts/mcp_smoke.py
npm test
npm run pack:check
D:\code\video-subtitle-skill\.venv\Scripts\python.exe scripts/repro_check.py --require-tier core --require-tier agent
```

如果 FFmpeg/FFprobe 可用，再运行 media tier 并显式传路径。live tier 只报告本机边界，不在未获单独授权时执行微信写操作。

**Step 2: 检查仓库与构建产物**

```powershell
git diff --check
git status --short
git grep -n -I -e 'video_subtitle' -e 'VIDEO_SUBTITLE_' -e 'video-subtitle-skill'
D:\code\video-subtitle-skill\.venv\Scripts\python.exe -m build
```

Expected: 除两个 clean-slate 决策文档的历史说明外无旧活动标识；wheel/sdist 只含新模块和批准资产。

**Step 3: 提交最终修复**

```powershell
git add -A
git commit -m "完成视频内容技能一体化重构验证"
```

若无额外修改则不创建空提交。

**Step 4: 推送分支**

```powershell
git push -u origin codex/video-content-clean-slate
```

**Step 5: 在主工作树快进 main**

先确认 `D:\code\video-subtitle-skill` 的 `main` 干净且仍指向共同基线，再执行：

```powershell
git -C D:\code\video-subtitle-skill fetch origin
git -C D:\code\video-subtitle-skill merge --ff-only codex/video-content-clean-slate
git -C D:\code\video-subtitle-skill push origin main
```

**Step 6: 最终核验**

```powershell
git -C D:\code\video-subtitle-skill status --short --branch
git -C D:\code\video-subtitle-skill log -5 --oneline --decorate
git ls-remote --heads origin main codex/video-content-clean-slate
```

最终报告分别列出：架构变化、删除内容、保留能力、测试数量与命令、真实历史数据迁移结果、未执行的 live 边界、提交与远端 main SHA。
