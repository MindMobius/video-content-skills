# Video Content Skills Rebrand Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebrand the repository as Video Content Skills and replace the monolithic human-oriented README with an Agent-native, progressively disclosed documentation map while preserving all existing runtime identifiers.

**Architecture:** Keep the repository brand and documentation identity separate from stable runtime contracts. Make README and AGENTS.md thin routers, place maintenance guidance in a dedicated document, retain detailed task execution in canonical Skill files and topic documents, and protect the boundary with static tests.

**Tech Stack:** Markdown, Python/pytest, Python packaging metadata, NPM package metadata, Git, GitHub repository settings.

---

### Task 1: Add documentation architecture regression tests

**Files:**
- Create: `tests/test_project_documentation.py`
- Modify: `tests/test_dsh_bundle.py`
- Modify: `tests/test_skill_distribution.py`

**Step 1: Write the failing README and maintenance tests**

Add tests that assert:

```python
def test_readme_is_a_concise_agent_router() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.startswith("# Video Content Skills\n")
    assert len(readme.splitlines()) <= 180
    for skill_name in EXPECTED_SKILLS:
        assert f".agents/skills/{skill_name}/SKILL.md" in readme
    assert "docs/skill-maintenance.md" in readme
    assert "## Agent 任务路由" in readme
    assert "## 渐进式读取" in readme


def test_skill_maintenance_contract_exists() -> None:
    content = (ROOT / "docs" / "skill-maintenance.md").read_text(encoding="utf-8")
    assert ".agents/skills/" in content
    assert "兼容" in content
    assert "python -m pytest" in content
    assert "npm run pack:check" in content
```

Also assert that README does not contain the former long-form headings `## CLI`, `## MCP`, `## OCR / ASR 调度`, or more than a small number of fenced command blocks.

**Step 2: Update metadata version expectations**

Change the version assertions in `tests/test_dsh_bundle.py` and `tests/test_skill_distribution.py` from `0.7.0` to `0.8.0`, while retaining assertions that the distribution/provider names remain `video-subtitle-skill`.

**Step 3: Run the focused tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_project_documentation.py tests\test_dsh_bundle.py tests\test_skill_distribution.py -q
```

Expected: failure because README, maintenance documentation, version metadata, and repository URLs still use the old project identity.

**Step 4: Commit the failing tests**

```powershell
git add tests/test_project_documentation.py tests/test_dsh_bundle.py tests/test_skill_distribution.py
git commit -m "增加项目文档分层与更名失败用例"
```

### Task 2: Replace README with the Agent-native entry map

**Files:**
- Modify: `README.md`

**Step 1: Rewrite README to the approved outline**

Keep it at no more than 180 lines with these sections:

```markdown
# Video Content Skills

一句话定位和兼容说明。

## 为什么存在
## 能力地图
## Agent 任务路由
## 渐进式读取
## 使用入口
## 维护入口
## 核心边界
## 兼容标识
## 验证
```

The routing table must link directly to all four canonical `SKILL.md` files. The document map must link to active topic documents and `docs/skill-maintenance.md`. Keep only the bootstrap command and the complete verification command group; remove copied CLI/MCP command catalogs.

**Step 2: Run the README-focused test**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_project_documentation.py::test_readme_is_a_concise_agent_router -q
```

Expected: README routing test passes; maintenance test still fails.

**Step 3: Commit**

```powershell
git add README.md
git commit -m "将README改为Agent渐进式入口"
```

### Task 3: Slim AGENTS.md and add the Skill maintenance guide

**Files:**
- Modify: `AGENTS.md`
- Create: `docs/skill-maintenance.md`

**Step 1: Reduce AGENTS.md to repository-wide invariants**

Retain:

- mandatory Skill routing;
- canonical `.agents/skills/` source rule;
- bootstrap entry link;
- immutable evidence boundary;
- OCR scout and full OCR decision rule;
- batch, idempotency, cache and GPU scheduling rules;
- browser authorization and never-publish boundary;
- verification commands;
- Chinese commit message requirement.

Replace detailed runtime installation and tool-specific procedures with direct links to the relevant Skill and topic documents.

**Step 2: Create `docs/skill-maintenance.md`**

Document:

- when to modify an existing Skill versus add a new one;
- frontmatter and `agents/openai.yaml` requirements;
- SKILL.md as the task contract and `references/` as conditional depth;
- avoiding duplicate Skill copies;
- synchronizing CLI/MCP/schema/docs changes;
- compatibility identifiers and migration rules;
- versioning, tests, packaging, reproducibility and commit checklist.

**Step 3: Run documentation tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_project_documentation.py tests\test_skill_distribution.py -q
```

Expected: documentation architecture and Skill discovery tests pass except version-related assertions awaiting metadata updates.

**Step 4: Commit**

```powershell
git add AGENTS.md docs/skill-maintenance.md
git commit -m "精简仓库规则并补充Skill维护指南"
```

### Task 4: Update active documentation terminology and routing

**Files:**
- Modify: `docs/workflow.md`
- Modify: `docs/environment.md`
- Modify: `docs/content-workflow.md`
- Modify: `docs/watch-later-automation.md`
- Modify: `docs/reproducibility.md`
- Modify: `.agents/skills/video-subtitle/SKILL.md`
- Modify: `.agents/skills/video-to-content/SKILL.md`
- Modify: `.agents/skills/video-watch-later-automation/SKILL.md`
- Modify: `.agents/skills/wechat-draft-handoff/SKILL.md`

**Step 1: Update only active project-level identity references**

- Rename `# Video Subtitle Skill 工具架构` to `# Video Content Skills 字幕证据架构`.
- Add short “read when” links where active docs should route to one another.
- Ensure each Skill points to the specific topic document or reference needed for deeper detail.
- Do not rename Skill IDs, CLI commands, schema identifiers, configuration paths, historical plans, or case artifacts.

**Step 2: Check stale active identity references**

Run:

```powershell
git grep -n -I -E "Video Subtitle Skill|MindMobius/video-subtitle-skill" -- README.md AGENTS.md docs ':!docs/plans/*' ':!docs/cases/*' .agents package.json pyproject.toml
```

Expected: no stale project-brand references remain outside explicit compatibility notes.

**Step 3: Run Skill link tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_skill_distribution.py tests\test_project_documentation.py -q
```

Expected: all routing and relative-link checks pass except metadata version assertions if not yet updated.

**Step 4: Commit**

```powershell
git add docs .agents/skills
git commit -m "统一活动文档的项目定位与阅读路由"
```

### Task 5: Update package metadata and compatibility version

**Files:**
- Modify: `package.json`
- Modify: `npm-shrinkwrap.json`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `src/video_subtitle/__init__.py`
- Modify: `scripts/runtime_setup.py`
- Modify: `tests/test_dsh_bundle.py`
- Modify: `tests/test_skill_distribution.py`

**Step 1: Update external descriptions and repository URLs**

Use the description:

```text
Agent-native video evidence and content production skills with auditable subtitle, automation, and draft handoff workflows.
```

Set repository URLs to `https://github.com/MindMobius/video-content-skills` while retaining package name `video-subtitle-skill` and provider identifier `video-subtitle-skill`.

**Step 2: Bump the compatibility release to 0.8.0**

Synchronize:

- `package.json`
- `npm-shrinkwrap.json`
- `pyproject.toml`
- `uv.lock`
- `src/video_subtitle/__init__.py`
- runtime User-Agent version
- version assertions in tests

**Step 3: Run focused metadata tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_dsh_bundle.py tests\test_skill_distribution.py -q
npm run pack:check
```

Expected: synchronized version, stable package/provider names, new repository URL, and valid package output.

**Step 4: Commit**

```powershell
git add package.json npm-shrinkwrap.json pyproject.toml uv.lock src/video_subtitle/__init__.py scripts/runtime_setup.py tests
git commit -m "更新项目元数据并同步零点八版本"
```

### Task 6: Run the complete repository verification

**Files:**
- No expected modifications.

**Step 1: Run Python lint and formatting checks**

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

Expected: pass.

**Step 2: Run Python and MCP tests**

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe scripts/mcp_smoke.py
```

Expected: all tests and smoke checks pass.

**Step 3: Run Node and package checks**

```powershell
npm test
npm run pack:check
```

Expected: all tests pass and package contains required Skills/docs.

**Step 4: Run deterministic reproducibility checks**

```powershell
.\.venv\Scripts\python.exe scripts/repro_check.py --require-tier core --require-tier agent
```

Expected: `ok=true`, core and agent tiers passed.

**Step 5: Confirm clean worktree and review diff**

```powershell
git status --short --branch
git diff main...HEAD --stat
git log --oneline main..HEAD
```

Expected: clean worktree with only the intended rebrand/documentation commits.

### Task 7: Push, rename the GitHub repository, and verify remotes

**Files:**
- Repository setting change only.

**Step 1: Push the feature branch to the current remote**

```powershell
git push -u origin codex/video-content-skills-rebrand
```

Expected: branch is available on GitHub before the repository rename.

**Step 2: Merge the verified branch into main and push**

```powershell
git switch main
git merge --ff-only codex/video-content-skills-rebrand
git push origin main
```

Expected: remote main reaches the verified commit.

**Step 3: Rename the GitHub repository and update metadata**

Using the already authenticated visible GitHub session:

- rename repository to `video-content-skills`;
- set the approved Chinese description;
- add approved Topics;
- do not change visibility, default branch, permissions, or release settings.

**Step 4: Update local remotes**

```powershell
git remote set-url origin git@github.com:MindMobius/video-content-skills.git
git fetch --prune origin
```

Apply this to the main worktree repository configuration; linked worktrees share the same remote.

**Step 5: Verify the final state**

```powershell
git ls-remote origin refs/heads/main
git rev-parse main
git remote -v
```

Expected: remote main and local main SHA match, and origin uses the new repository URL.
