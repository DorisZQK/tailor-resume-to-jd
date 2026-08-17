# README and Main Merge Design

## Goal

Document the `tailor-resume-to-jd` skill for GitHub users, merge the completed
`agent/remove-public-company-research` work into `main`, and publish the tested
result to `origin/main`.

## Scope

- Add a root `README.md` with a Chinese-first presentation and a short English
  overview.
- Explain the project's purpose, evidence-constrained behavior, workflow,
  installation, usage, required inputs, outputs, privacy rules, validation, and
  repository structure.
- State that public company or business research happens only when the user
  explicitly requests it.
- Preserve `scripts/__pycache__/` as an untracked local artifact and exclude it
  from commits.
- Merge `agent/remove-public-company-research` into `main` only after the full
  feature-branch test suite passes.
- Run the full test suite again on the merged `main` before pushing
  `origin/main`.

## README Structure

1. Project title and concise English summary.
2. Chinese project positioning and key benefits.
3. Core principles: truthful evidence, JD alignment, editable one-page A4
   output, and privacy.
4. End-to-end workflow.
5. Installation and invocation.
6. Required inputs and exact final outputs.
7. Validation and testing commands.
8. Repository structure.
9. Limitations and public-research opt-in behavior.

## Integration Strategy

1. Run the repository's Python test suite on the feature branch.
2. Add and commit only `README.md` after reviewing it against the current skill
   contract and scripts.
3. Merge the feature branch into local `main` without rewriting history.
4. Run the same full test suite on `main`.
5. Push `main` to `origin` only when the merged suite is green.

## Failure Handling

- If feature-branch tests fail, stop before writing or merging unrelated fixes.
- If the merge conflicts, resolve only files in the approved scope and rerun
  tests.
- If merged-main tests fail, do not push.
- If the push is rejected because the remote moved, stop and inspect rather
  than force-pushing.

## Success Criteria

- The root README accurately reflects the current eight-stage skill workflow.
- The README contains no placeholder repository links or unsupported claims.
- The feature branch and merged `main` both pass the complete test suite.
- `origin/main` points to the tested merged commit.
- `scripts/__pycache__/` remains untracked and uncommitted.
