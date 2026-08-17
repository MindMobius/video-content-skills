# Watch Later Automation Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 统一自动化任务 artifact 路径、减少机械状态调用，并为单任务和批次提供可修复的完整性审计与最终摘要。

**Architecture:** 在 `core` 层新增路径契约、组合动作和完整性审计三个小模块。现有状态机仍是唯一状态来源，Agent 继续负责语义判断；CLI 与 MCP 只暴露确定性动作和审计结果，不引入常驻调度服务。

**Tech Stack:** Python 3.10、pathlib、原子 JSON ledger、pytest、argparse、FastMCP、JSON Schema。

---

### Task 1: 统一 job artifact 路径解析

**Files:**
- Create: `src/video_subtitle/core/automation_paths.py`
- Modify: `src/video_subtitle/core/automation_job.py`
- Modify: `src/video_subtitle/core/automation_content.py`
- Modify: `src/video_subtitle/core/automation_handoff.py`
- Test: `tests/core/test_automation_paths.py`
- Test: `tests/core/test_automation_content.py`
- Test: `tests/core/test_automation_handoff.py`

**Step 1: 写失败测试**

覆盖：

- 传入 `<workspace>/.video-subtitle-local/.../<job>/artifact.json` 形式的工作区相对路径时，元数据保存为 `artifact.json` 或真实 job-relative 路径；
- 短相对路径仍按 job 根目录解析；
- 绝对路径必须位于 job 根目录；
- `record_automation_audit` 使用 resolve 后的 project path；
- handoff 未显式指定 output 时使用 `<job>/handoff-binding.json`。

**Step 2: 运行失败测试**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core/test_automation_paths.py tests/core/test_automation_content.py tests/core/test_automation_handoff.py -q
```

Expected: 新测试因路径重复拼接或缺少默认 output 行为失败。

**Step 3: 实现最小路径模块并替换分散拼接**

公开函数：

```python
def job_root(job_path: Path) -> Path: ...
def resolve_job_artifact_path(job_path: Path, value: str | Path, *, must_exist: bool, label: str) -> Path: ...
def job_relative_artifact_path(job_path: Path, value: str | Path, *, must_exist: bool, label: str) -> str: ...
```

解析顺序：绝对路径；当前工作目录相对且位于 job 内；job-root 相对。最终必须位于 job 根目录。

**Step 4: 运行测试并提交**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core/test_automation_paths.py tests/core/test_automation_job.py tests/core/test_automation_content.py tests/core/test_automation_handoff.py -q
git add src/video_subtitle/core tests/core
git commit -m "统一自动化任务产物路径解析"
```

### Task 2: 合并证据与规范字幕的机械状态操作

**Files:**
- Create: `src/video_subtitle/core/automation_actions.py`
- Modify: `src/video_subtitle/mcp_server.py`
- Modify: `src/video_subtitle/cli.py`
- Test: `tests/core/test_automation_actions.py`
- Test: `tests/test_automation_cli.py`
- Test: `tests/test_mcp_surface.py`

**Step 1: 写失败测试**

覆盖：

- `begin_automation_evidence` 只允许 queued job；
- `complete_automation_evidence` 验证 manifest completed、BVID/page 匹配并自动绑定 `subtitle_manifest`；
- `save_automation_canonical_subtitle` 自动进入 canonicalizing 并在 usable 时进入 canonical_ready；
- unusable canonical 自动转为 unprocessable，保留 report artifact 和 termination；
- manifest 不匹配时不推进状态。

**Step 2: 运行失败测试**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core/test_automation_actions.py tests/test_automation_cli.py tests/test_mcp_surface.py -q
```

Expected: 新动作和 CLI/MCP surface 尚不存在。

**Step 3: 实现组合动作**

新增：

```python
def begin_automation_evidence(job_path: Path) -> dict[str, Any]: ...
def complete_automation_evidence(job_path: Path, manifest_path: Path) -> dict[str, Any]: ...
def save_automation_canonical_subtitle(job_path: Path, manifest_path: Path, document: dict[str, Any]) -> dict[str, Any]: ...
```

CLI 新增：

```text
automation-evidence-begin
automation-evidence-complete
automation-canonical-save
```

MCP 新增对应 Agent 友好工具。保留低层 `automation-job-update` 作为兼容接口。

**Step 4: 运行测试并提交**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core/test_automation_actions.py tests/test_automation_cli.py tests/test_mcp_surface.py -q
git add src/video_subtitle tests
git commit -m "合并证据与规范字幕的自动化状态操作"
```

### Task 3: 增加任务完整性审计与安全路径修复

**Files:**
- Create: `src/video_subtitle/core/automation_integrity.py`
- Modify: `src/video_subtitle/cli.py`
- Modify: `src/video_subtitle/mcp_server.py`
- Test: `tests/core/test_automation_integrity.py`
- Test: `tests/test_automation_cli.py`
- Test: `tests/test_mcp_surface.py`

**Step 1: 写失败测试**

构造标准 artifact、缺失 artifact、哈希漂移和旧式重复路径。断言：

- audit 报告准确区分 valid、missing、hash_mismatch、noncanonical；
- repair 只在规范候选文件哈希匹配时更新 job metadata；
- repair 不移动或删除文件；
- completed job 缺少有效 handoff binding 时整体 invalid；
- store summary 检出重复 appmsgid。

**Step 2: 运行失败测试**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core/test_automation_integrity.py tests/test_automation_cli.py tests/test_mcp_surface.py -q
```

Expected: 审计 API、CLI 和 MCP surface 尚不存在。

**Step 3: 实现审计和安全修复**

新增：

```python
def audit_automation_job(job_path: Path, *, repair_paths: bool = False) -> dict[str, Any]: ...
def audit_automation_store(store: Path, *, repair_paths: bool = False) -> dict[str, Any]: ...
```

修复算法仅接受 job-relative metadata 变更：从旧路径中提取最后一个 job ID 后的后缀，或寻找唯一的同哈希更短路径。不得改变 artifact 内容。

CLI 新增：

```text
automation-audit --store <path> [--repair-paths]
```

MCP 新增 `audit_video_automation_store`。

**Step 4: 运行测试并提交**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core/test_automation_integrity.py tests/test_automation_cli.py tests/test_mcp_surface.py -q
git add src/video_subtitle tests
git commit -m "增加自动化任务完整性审计与路径修复"
```

### Task 4: 同步 Skill、文档和契约验收

**Files:**
- Modify: `.agents/skills/video-watch-later-automation/SKILL.md`
- Modify: `AGENTS.md`
- Modify: `docs/watch-later-automation.md`
- Modify: `README.md`
- Modify: `tests/test_watch_later_automation_skill.py`
- Modify: `tests/test_automation_workflow.py`
- Modify: `scripts/repro_check.py`
- Modify: `tests/test_repro_check.py`

**Step 1: 更新 Skill 路由**

要求 Agent 优先使用组合动作；每轮结束运行 store audit；只有 `paused_auth` 属于正常人工边界；审计 repair 只修元数据。

**Step 2: 扩展确定性复现测试**

加入：

- workspace-relative artifact 不产生嵌套路径；
- usable canonical 单调用推进到 canonical_ready；
- 第二次 handoff 不创建重复草稿；
- store audit `valid=true` 且 duplicate appmsgid 为空。

**Step 3: 运行文档和复现测试并提交**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_watch_later_automation_skill.py tests/test_automation_workflow.py tests/test_repro_check.py -q
.\.venv\Scripts\python.exe scripts/repro_check.py --require-tier core --require-tier agent
git add .agents AGENTS.md docs README.md scripts tests
git commit -m "同步自动化最佳实践与确定性验收"
```

### Task 5: 修复当前 13 条批次元数据并运行完整回归

**Files:**
- No tracked source changes expected unless regressions require fixes.
- Runtime state: `.video-subtitle-local/automation-backfill-13/jobs/*/job.json`

**Step 1: 先审计不修复**

```powershell
.\.venv\Scripts\python.exe -m video_subtitle automation-audit --store .\.video-subtitle-local\automation-backfill-13
```

Expected: 报告旧式嵌套 artifact 元数据，但不修改文件。

**Step 2: 安全修复元数据**

```powershell
.\.venv\Scripts\python.exe -m video_subtitle automation-audit --store .\.video-subtitle-local\automation-backfill-13 --repair-paths
```

Expected: 只更新哈希一致的 job artifact path，不移动、不删除 artifact。

**Step 3: 复查 13 条结果**

Expected:

- 13/13 completed；
- 13 个有效 handoff binding；
- 13 个唯一 appmsgid；
- artifact integrity valid；
- published 相关状态仍为 false。

**Step 4: 运行完整门禁**

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe scripts/mcp_smoke.py
npm test
npm run pack:check
.\.venv\Scripts\python.exe scripts/repro_check.py --require-tier core --require-tier agent
```

Expected: 全部 PASS。

**Step 5: 最终提交**

如果完整回归产生必要修复：

```powershell
git add <相关文件>
git commit -m "修正自动化加固回归问题"
```
