# Source-faithful Video Adaptation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make source-faithful oral-to-written adaptation the default behavior of `video-to-content`, while keeping deeper rewriting available only when the user explicitly requests it.

**Architecture:** Keep the six-product model and all Python content contracts unchanged. Encode the editorial boundary in the repository instructions, canonical Skill, progressive references, Agent prompt, documentation contract tests, and a local non-destructive regression using an existing verified Transcript and source video.

**Tech Stack:** Markdown Skill documentation, YAML Agent metadata, pytest documentation-contract tests, existing local Transcript/Evidence, Git.

---

## Execution constraints

- Work in `D:\codeideo-subtitle-skill-source-faithful` on `codex/source-faithful-adaptation`.
- Do not add a Style product, style engine, schema field, or deterministic prose score.
- Do not overwrite existing Content, Draft Receipt, or WeChat drafts.
- Keep `.agents/skills/` as the only canonical Skill source.
- Use concise Chinese commit messages.

### Task 1: Add a failing source-faithful documentation contract

**Files:**
- Create: `tests/test_source_faithful_content_skill.py`

**Step 1: Write the failing test**

Assert that:

```python
assert "source-faithful-adaptation.md" in skill
assert "explicitly requested" in skill
assert "source structure" in skill
assert "source-faithful" in agent_prompt
assert "来源忠实" in agents_md
assert "高保真" in readme
assert "新增比喻" in reference
assert "人物身份" in traceability
assert "不是新的作者" in wechat_reference
```

Also assert the source-faithful reference exists and the four canonical Skill names remain unchanged.

**Step 2: Run the targeted test and verify failure**

Run:

```powershell
python -m pytest tests/test_source_faithful_content_skill.py -q
```

Expected: FAIL because the new reference and language do not yet exist.

**Step 3: Commit the failing test**

```powershell
git add tests/test_source_faithful_content_skill.py
git commit -m "测试来源忠实内容契约"
```

### Task 2: Make source-faithful adaptation canonical in the Skill

**Files:**
- Modify: `.agents/skills/video-to-content/SKILL.md`
- Create: `.agents/skills/video-to-content/references/source-faithful-adaptation.md`
- Modify: `.agents/skills/video-to-content/references/traceability.md`
- Modify: `.agents/skills/video-to-content/references/wechat-article.md`
- Modify: `.agents/skills/video-to-content/agents/openai.yaml`

**Step 1: Update the Skill entry point**

- Change the description to a source-faithful carrier edition.
- Route Agents to `source-faithful-adaptation.md` before carrier-specific references.
- Replace “design a carrier-appropriate structure” with reconstruction of the source structure.
- State that summary, audience rewrite, style imitation, new analogy, new thesis, and material reorder require an explicit user request.
- Extend the audit with source structure, speaker roles, source voice, omissions, and editorial additions.

**Step 2: Add the progressive reference**

Document:

- the ephemeral source map;
- allowed oral-to-written edits;
- prohibited default rewrites;
- title, summary, heading, translation, image, and omission rules;
- source-faithful audit questions;
- handling of loosely structured videos without inventing a thesis.

**Step 3: Tighten traceability and WeChat rules**

- Require material paragraphs to map to Transcript/Evidence ranges.
- Preserve speaker identity, counterexamples, source sequence, professional density, uncertainty, and source-owned metaphors.
- Define WeChat as a carrier, not a new author.

**Step 4: Update the Agent default prompt**

Use wording equivalent to:

```text
Use $video-to-content to create a source-faithful written edition of this verified Transcript in the requested carrier.
```

**Step 5: Run the targeted test**

```powershell
python -m pytest tests/test_source_faithful_content_skill.py -q
```

Expected: remaining failures only for global documentation, if any.

**Step 6: Commit**

```powershell
git add .agents/skills/video-to-content tests/test_source_faithful_content_skill.py
git commit -m "确立来源忠实内容转换规则"
```

### Task 3: Synchronize repository-wide documentation

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/skill-maintenance.md`

**Step 1: Update repository instructions**

Add a content boundary stating that Content defaults to a faithful written edition. Permit transcription repair and carrier adaptation; prohibit unrequested reauthoring.

**Step 2: Update the README product promise**

Describe the product as high-fidelity migration of verified video expression into requested carriers. Keep the README short and Agent-oriented.

**Step 3: Update architecture and maintenance guidance**

Clarify that Agent composition preserves source structure and voice, and that content changes must update the source-faithful reference and contract test.

**Step 4: Run documentation tests**

```powershell
python -m pytest tests/test_source_faithful_content_skill.py tests/test_project_documentation.py tests/test_agent_skill_routing.py tests/test_skill_distribution.py -q
```

Expected: PASS.

**Step 5: Commit**

```powershell
git add AGENTS.md README.md docs/architecture.md docs/skill-maintenance.md
git commit -m "统一高保真书面化项目口径"
```

### Task 4: Run a non-destructive real-content regression

**Files outside Git:**
- Read: `D:\codeideo-content-state\jobs\job_20260817T211049_30dfd3f93086rtifacts	ranscriptrt_952f1bf04503545c70e9306b.json`
- Read: `D:\codeideo-content-state\jobs\job_20260817T211049_30dfd3f93086rtifacts\source_videort_350c9928bd448a7939c60c65.mp4`
- Create under ignored local state: `.video-content-local/editorial-experiments/job_20260817T211049_30dfd3f93086/source-map.md`
- Create under ignored local state: `.video-content-local/editorial-experiments/job_20260817T211049_30dfd3f93086/source-faithful-article.md`
- Create under ignored local state: `.video-content-local/editorial-experiments/job_20260817T211049_30dfd3f93086/source-faithful-audit.md`

**Step 1: Inspect the source video structure**

Generate and inspect a timestamped contact sheet covering the opening, interviews, survey charts, counterexample, recommendations, and conclusion.

**Step 2: Build the ephemeral source map**

Record source type, speaker roles, section order, source-owned analogies, material caveats, visual references, and intentional omissions.

**Step 3: Produce the written edition**

Preserve the investigation/interview sequence. Remove only spoken noise, repair translation, and add minimal written transitions. Do not promote the “5 p.m. lights” detail into the title or central thesis.

**Step 4: Audit every material section**

Map each section to Transcript ranges and record omissions. Confirm no new thesis, analogy, causality, certainty, or speaker merger.

**Step 5: Verify no persistent product changed**

```powershell
git status --short
```

Expected: only repository implementation files are tracked; existing external Content and Draft Receipt hashes are untouched.

### Task 5: Run full verification and integrate

**Files:**
- Modify only as required by failures.

**Step 1: Run the required verification**

```powershell
python -m ruff check .
python -m ruff format --check .
python -m pytest
python scripts/mcp_smoke.py
npm test
npm run pack:check
python scripts/repro_check.py --require-tier core --require-tier agent
```

If FFmpeg and FFprobe are available, also run:

```powershell
python scripts/repro_check.py --require-tier core --require-tier agent --require-tier media
```

Expected: all offline checks pass. Do not run the `live` WeChat tier.

**Step 2: Check the final diff**

```powershell
git diff --check
git status --short --branch
git log --oneline main..HEAD
```

**Step 3: Commit any verification fixes**

Use a concise Chinese message only when files changed.

**Step 4: Fast-forward local main**

After confirming the main worktree is clean and still at the common base:

```powershell
git -C D:\codeideo-subtitle-skill merge --ff-only codex/source-faithful-adaptation
```

Do not push unless separately requested.
