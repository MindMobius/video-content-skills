# Source-Aware Expression Audit Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a source-aware, minimally invasive expression review gate to `source_faithful_full` Content without introducing a new product, Skill, runtime dependency, or automatic style rewriter.

**Architecture:** Extend the existing `video-to-content` progressive documentation with one focused reference. Persist the Agent-authored review inside `Content.audit.expression_audit`, then validate only deterministic contract facts: required scope, approved policy, valid decisions, source-origin boundary, and final-document target alignment. Existing material-section, visual-plan, media, and raw-transcript checks remain the authority for completeness.

**Tech Stack:** Python 3.10+, pytest, Markdown Agent Skills, existing `video_content.content` validation.

---

### Task 1: Lock the documentation contract with failing tests

**Files:**
- Modify: `tests/test_source_faithful_content_skill.py`
- Modify: `tests/test_project_documentation.py`

**Step 1: Add Skill-reference assertions**

Require `video-to-content/SKILL.md` to route `references/source-aware-expression-audit.md`, and require the reference to state:

```text
source-aware
Agent 新增
来源真实表达
信息密度
命中即修改
expression_audit
```

**Step 2: Add repository-document assertions**

Require README/AGENTS or maintenance documentation to distinguish source-aware review from a fixed house style and to mention `expression_audit`.

**Step 3: Register the two new plan documents**

Update the exact `docs/plans` assertion for the 2026-08-28 design and implementation plan.

**Step 4: Run the targeted tests and confirm failure**

```powershell
python -m pytest tests/test_source_faithful_content_skill.py tests/test_project_documentation.py -q
```

Expected: FAIL because the new reference and routing text do not exist yet.

### Task 2: Add the progressive Skill guidance

**Files:**
- Create: `.agents/skills/video-to-content/references/source-aware-expression-audit.md`
- Modify: `.agents/skills/video-to-content/SKILL.md`
- Modify: `.agents/skills/video-to-content/references/content-acceptance.md`
- Modify: `.agents/skills/video-to-content/references/source-faithful-adaptation.md`
- Modify: `.agents/skills/watch-later-to-wechat/SKILL.md`

**Step 1: Write the focused reference**

Define the source-priority decision order, safe rule families, non-triggers, minimal-edit procedure, `expression_audit` example, and final recheck.

**Step 2: Route it progressively**

Read the reference after a complete source-faithful draft exists and before final `content_save`/`content_validate`. Do not load it during Evidence or Transcript work.

**Step 3: Update Content acceptance**

State that expression review cannot justify detail loss, structural reorder, frame removal, or rewriting source-owned speech.

**Step 4: Run the targeted documentation tests**

```powershell
python -m pytest tests/test_source_faithful_content_skill.py tests/test_project_documentation.py tests/test_agent_skill_routing.py tests/test_skill_distribution.py -q
```

Expected: PASS after Task 4 documentation synchronization is complete; otherwise only repository-wide wording assertions may remain.

### Task 3: Add failing Content-contract tests

**Files:**
- Modify: `tests/test_written_adaptation_contract.py`
- Modify: `tests/test_transcript_content_service.py`

**Step 1: Add a valid audit fixture**

Create a small helper returning a no-op `expression_audit` with all required targets and checks.

**Step 2: Require the audit**

Create `source_faithful_full` Content without `expression_audit` and assert:

```python
assert result["validation"]["valid"] is False
assert any("expression_audit" in error for error in result["validation"]["errors"])
```

**Step 3: Reject source-expression rewrites**

Create a `revised` item whose `origin` is `source_expression`; require validation failure.

**Step 4: Reject stale audit text**

Create an item whose `after` does not equal the final title, summary, or block text; require validation failure.

**Step 5: Confirm a no-op audit passes**

Keep the publication-ready source wording test valid with `items=[]`.

**Step 6: Run tests and confirm failure**

```powershell
python -m pytest tests/test_written_adaptation_contract.py tests/test_transcript_content_service.py -q
```

Expected: new negative tests FAIL before validator implementation.

### Task 4: Implement the deterministic expression-audit validator

**Files:**
- Modify: `src/video_content/content.py`

**Step 1: Add stable constants**

Define the policy, required review targets, required checks, allowed rules, decisions, origins, and text-bearing block types.

**Step 2: Validate `expression_audit`**

Add `_expression_audit_errors(document, audit)` and invoke it from the `source_faithful_full` profile contract.

Validate:

```text
status=passed|approved
reviewed_by=agent
policy=source_aware_minimal
required reviewed_targets present
all required checks are true
items is a list
rule/decision/origin/target/reason are valid
after equals the final target text
revised: before != after and origin is not source_expression
retained: before == after
```

**Step 3: Keep semantic judgment out of code**

Do not add regex scoring, automatic rewriting, hit-count thresholds, lexical-overlap targets, or punctuation quotas.

**Step 4: Run the focused contract tests**

```powershell
python -m pytest tests/test_written_adaptation_contract.py tests/test_transcript_content_service.py -q
```

Expected: PASS.

### Task 5: Synchronize fixtures and repository documentation

**Files:**
- Modify: `scripts/repro_check.py`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `docs/architecture.md`
- Modify: `docs/skill-maintenance.md`
- Modify: `tests/test_project_documentation.py`

**Step 1: Update reproducibility fixtures**

Add a valid no-op `expression_audit` to the core/agent repro Content fixture.

**Step 2: Update concise repository promises**

Describe the review as cleaning only Agent-added carrier language while preserving source expression and professional detail.

**Step 3: Record the real failure lesson**

Document that factual completeness can coexist with repetitive Agent scaffolding; the fix is a source-aware review plus deterministic audit receipt, not a universal rewrite prompt.

**Step 4: Run documentation and repro tests**

```powershell
python -m pytest tests/test_source_faithful_content_skill.py tests/test_project_documentation.py tests/test_repro_check.py -q
python scripts/repro_check.py --require-tier core --require-tier agent
```

Expected: PASS.

### Task 6: Validate the canonical Skill and full repository

**Files:**
- Modify only if verification exposes a real defect.

**Step 1: Validate the Skill structure**

```powershell
python C:\Users\RK\.codex\skills\.system\skill-creator\scripts\quick_validate.py .agents\skills\video-to-content
```

Expected: validation succeeds.

**Step 2: Run required repository verification**

```powershell
python -m ruff check .
python -m ruff format --check .
python -m pytest
python scripts/mcp_smoke.py
npm test
npm run pack:check
python scripts/repro_check.py --require-tier core --require-tier agent
```

Add the media tier when FFmpeg/FFprobe is available.

**Step 3: Inspect final changes**

```powershell
git diff --check
git status --short --branch
```

Expected: only intentional source, Skill, documentation, plan, and test changes.
