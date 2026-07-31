# Lightcheck Structural Nesting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Lightcheck's McCabe branch-count warning with a maximum structural nesting-depth warning.

**Architecture:** A focused analyzer computes `max_control_nesting` from Lizard's language-aware tokens for brace-based languages and Python's AST for Python. The existing Lightcheck pipeline continues to own changed scope, baseline comparison, reporting, and fail-open behavior. The metric is consumed through the existing function-rule table.

**Tech Stack:** Python 3, vendored Lizard 1.23.0, `unittest`.

## Global Constraints

- Parallel control statements must not accumulate complexity.
- Boolean operators and ternary expressions must not increase nesting.
- Exact depth 5 is allowed; only depth greater than 5 reports.
- Keep all current supported languages and fail-open behavior.
- Remove `MF-CC-5`; do not run both metrics.

---

### Task 1: Structural nesting metric

**Files:**
- Create: `scripts/mae_flow_core/lightcheck_nesting.py`
- Modify: `scripts/mae_flow_core/lightcheck_source.py`
- Modify: `scripts/mae_flow_core/lightcheck_analysis.py`
- Modify: `scripts/mae_flow_core/lightcheck_functions.py`
- Test: `scripts/tests/test_lightcheck.py`

**Interfaces:**
- Consumes: Lizard `FileAnalyzer`, language readers, and function nesting state.
- Produces: `annotate_control_nesting(...)` and per-function integer `max_control_nesting`.

- [x] **Step 1: Write failing behavioral tests**

Add fixtures that assert parallel branches and compound conditions do not
produce a nesting finding, while six truly nested controls produce
`MF-NEST-5` for C++, JavaScript, and Python.

- [x] **Step 2: Verify the tests fail for the old McCabe behavior**

Run:

```bash
python -m unittest scripts.tests.test_lightcheck
```

Expected: parallel-branch tests fail because `MF-CC-5` is still reported, and
nested-depth expectations fail because `MF-NEST-5` does not exist.

- [x] **Step 3: Add the structural analyzer and wire the metric**

Implement:

```python
def annotate_control_nesting(lizard, path, source, functions):
    ...
```

Store `max_control_nesting` in `_function_metrics` and replace the function rule
with:

```python
("MF-NEST-5", "control_nesting", NESTING_LIMIT,
 "函数控制结构嵌套深度超过 5")
```

- [x] **Step 4: Verify Lightcheck tests pass**

Run:

```bash
python -m unittest scripts.tests.test_lightcheck
```

Expected: all Lightcheck tests pass.

### Task 2: Public contract and full regression

**Files:**
- Modify: `README.md`
- Modify: `MAINTAINERS.md`
- Modify: `scripts/tests/test_lightcheck.py`

**Interfaces:**
- Consumes: `MF-NEST-5` result from Task 1.
- Produces: accurate user-facing and maintainer-facing metric semantics.

- [x] **Step 1: Update public wording**

Replace references to `McCabe 圈复杂度超过 5` with
`控制结构嵌套深度超过 5`, explicitly noting that parallel branches do not
accumulate.

- [x] **Step 2: Run targeted and complete verification**

Run:

```bash
python -m unittest scripts.tests.test_lightcheck
python scripts/selftest.py
```

Expected: targeted tests and the complete self-test suite exit 0.

- [ ] **Step 3: Commit and push**

Commit all implementation, regression tests, and documentation together, then
push `main` after verifying the worktree is clean and synchronized.
