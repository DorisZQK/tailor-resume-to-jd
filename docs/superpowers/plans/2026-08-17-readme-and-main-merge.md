# README and Main Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an accurate Chinese-first README, merge `agent/remove-public-company-research` into `main`, and push the fully tested result to `origin/main`.

**Architecture:** Documentation is derived directly from the current `SKILL.md`, renderer, validator, and tests so it cannot promise unsupported behavior. Integration uses a normal non-force merge, with the complete Python test suite run before and after merging.

**Tech Stack:** Markdown, Git, Python 3 `unittest`, Node.js validator documentation

## Global Constraints

- Public company or business research is opt-in only when the user explicitly requests it.
- The README is Chinese-first with a short English overview.
- Do not add dependencies or modify runtime behavior.
- Do not stage or commit `scripts/__pycache__/`.
- Do not push unless the merged `main` passes the complete test suite.
- Never force-push if the remote has moved.

---

### Task 1: Verify the Feature Branch and Add Project Documentation

**Files:**
- Create: `README.md`
- Create: `docs/superpowers/plans/2026-08-17-readme-and-main-merge.md`
- Reference: `SKILL.md`
- Reference: `agents/openai.yaml`
- Reference: `references/candidate-profile-schema.md`
- Reference: `scripts/build_resume.py`
- Reference: `scripts/validate_resume.mjs`
- Test: `scripts/test_build_resume.py`

**Interfaces:**
- Consumes: the eight-stage workflow and exact output contract in `SKILL.md`
- Produces: a root GitHub README describing the current package without changing runtime behavior

- [ ] **Step 1: Run the complete feature-branch unit test suite**

Run:

```powershell
python scripts/test_build_resume.py -v
```

Expected: exit code `0` and all tests report `OK`.

- [ ] **Step 2: Write the README**

Create `README.md` with these exact sections:

```markdown
# tailor-resume-to-jd

> Evidence-constrained resume tailoring for a complete JD, producing a traceable analysis report and an editable one-page A4 HTML resume.

## 项目简介
## 核心特点
## 工作流程
## 安装
## 使用方法
## 输入要求
## 输出结果
## 真实性、隐私与安全
## 验证与测试
## 项目结构
## 使用限制
```

Document the invocation `$tailor-resume-to-jd`, the required company, role, complete JD, and authorized candidate materials. Name the exact outputs `JD分析与修改依据.md` and `<company>-<role>-简历.html`. State that the printable resume uses only verified evidence, validation requires empty-photo and test-photo one-page A4 states, candidate data stays outside the skill folder, and public company research is performed only on explicit request.

- [ ] **Step 3: Review documentation accuracy and formatting**

Run:

```powershell
rg -n "Research culture|Browse current public information automatically|TBD|TODO|yourname" README.md
git diff --check
```

Expected: the search returns no matches and `git diff --check` returns no errors.

- [ ] **Step 4: Run the complete test suite again**

Run:

```powershell
python scripts/test_build_resume.py -v
```

Expected: exit code `0` and all tests report `OK`.

- [ ] **Step 5: Commit the README and implementation plan**

Run:

```powershell
git add -- README.md docs/superpowers/plans/2026-08-17-readme-and-main-merge.md
git commit -m "docs: add project README"
```

Expected: one documentation commit; `scripts/__pycache__/` remains untracked.

### Task 2: Merge, Re-verify, and Publish Main

**Files:**
- Merge: `agent/remove-public-company-research` into `main`
- Verify: `README.md`, `SKILL.md`, `scripts/test_build_resume.py`

**Interfaces:**
- Consumes: the tested feature branch from Task 1
- Produces: a tested local and remote `main` containing the refactor and README

- [ ] **Step 1: Fetch and confirm remote state without changing history**

Run:

```powershell
git fetch origin
git status --short --branch
git log --oneline --left-right main...origin/main
```

Expected: the working tree contains only the known untracked `scripts/__pycache__/`; any unexpected remote divergence stops the task for inspection.

- [ ] **Step 2: Merge the feature branch into local main**

Run:

```powershell
git switch main
git merge --no-ff agent/remove-public-company-research
```

Expected: the merge finishes without unresolved conflicts.

- [ ] **Step 3: Run the complete merged-main test suite**

Run:

```powershell
python scripts/test_build_resume.py -v
```

Expected: exit code `0` and all tests report `OK`. A failure blocks the push.

- [ ] **Step 4: Verify merge contents and excluded artifacts**

Run:

```powershell
git status --short --branch
git log --oneline --decorate -5
git diff --check origin/main..main
git ls-files scripts/__pycache__
```

Expected: `scripts/__pycache__/` is not tracked, the intended commits are on `main`, and there are no whitespace errors.

- [ ] **Step 5: Push the tested main branch**

Run:

```powershell
git push origin main
```

Expected: a normal fast-forward update of `origin/main`; do not retry with force if rejected.

- [ ] **Step 6: Confirm local and remote main match**

Run:

```powershell
git fetch origin
git rev-parse main
git rev-parse origin/main
git status --short --branch
```

Expected: `main` and `origin/main` resolve to the same commit, with only the pre-existing untracked `scripts/__pycache__/` remaining.
