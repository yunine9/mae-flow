# Opaque Compile Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make opaque `build-fix` executions reusable across report correction and make staged Full checkpoint risk acceptance snapshot-safe, without parsing Maven/g++ output or weakening repository-integrity gates.

**Architecture:** Add a pure COMPILE receipt model beside existing UT/CodeCheck receipts, then wire it into the Hook before report evaluation.  Make COMPILE report fields diagnostic while retaining actual invocation, host-error, task-card, source-scope and shrink checks.  Extend risk acceptance with the same pre-commit source-snapshot binding used by COMPILE tokens.

**Tech Stack:** Python 3.8+, `unittest`, Git, Claude Code Hook JSONL protocol; Windows runtime via Git Bash.

## Global Constraints

- Windows-only production target; Python subprocess text mode must use explicit UTF-8.
- Treat `build-fix`/Maven/g++ output and exit semantics as opaque.
- Do not change UT or CodeCheck contract strictness in this change.
- No raw proprietary compiler output may be persisted in receipts.
- No production behavior change without a failing regression test first.
- A source, task-card, issuance, configured-route, or terminal-status change invalidates reusable evidence.

---

### Task 1: Pure opaque COMPILE contract and receipt model

**Files:**
- Modify: `scripts/mae_flow_core/application/hooks/receipts.py`
- Modify: `scripts/mae_flow_core/quality/compile_contract.py`
- Modify: `scripts/mae_flow_core/quality/agent_reports.py`
- Test: `scripts/tests/test_hook_receipts.py`
- Test: `scripts/tests/test_hook_compile_contract.py`

**Interfaces:**
- Produces: `plan_compile_run_receipt(task, context, build, status, result)`.
- Produces: `reusable_compile_run_receipt(receipt, task, expected_build, status, ...)`.
- Consumes: `AgentContractContext.reusable_receipts["COMPILE_RUN"]`.
- Preserves: `SHRINK_EXEMPT` enforcement from Hook-calculated `compile_net`.

- [ ] **Step 1: Write failing receipt tests**

Add literal-behavior tests proving that a receipt stores the task issuance ID,
route, status and only a result digest; that the same task/snapshot can reuse
it; and that changed issuance, route, status or snapshot rejects it.

```python
receipt = plan_compile_run_receipt(
    {"step": "build", "sha256": "task", "issuance_id": "issue-1"},
    ReceiptContext("now", "head", {"src/a.cpp": "fingerprint"}),
    "build-fix",
    "OK",
    "opaque proprietary result",
)
self.assertNotIn("opaque proprietary result", repr(receipt))
self.assertEqual("issue-1", receipt["task_issuance_id"])
```

- [ ] **Step 2: Run the receipt tests and verify RED**

Run: `PYTHONPATH=scripts:scripts/tests python3 -m unittest -v test_hook_receipts`

Expected: import or attribute failure for the new COMPILE receipt functions.

- [ ] **Step 3: Implement the minimal pure receipt functions**

Add a SHA-256 result digest, explicit task issuance/checkpoint/build/status
bindings, and reuse checks built on the existing `_fresh` helper.  Preserve the
existing UT and CodeCheck receipt shapes.

- [ ] **Step 4: Run the receipt tests and verify GREEN**

Run: `PYTHONPATH=scripts:scripts/tests python3 -m unittest -v test_hook_receipts`

Expected: all receipt tests pass.

- [ ] **Step 5: Write failing opaque-provider contract tests**

Add tests proving:

```python
decision = evaluate_compile_contract(context(
    report="diagnostic prose is optional",
    calls=[skill_call("build-fix", result="opaque")],
    status="OK",
))
self.assertTrue(decision.accepted)
```

Also prove a missing configured invocation, a host `is_error`, changed status,
and an unexplained negative `compile_net` still reject.  Add a receipt-only
case with no current Skill call and a matching `COMPILE_RUN` receipt.

- [ ] **Step 6: Run the contract tests and verify RED**

Run: `PYTHONPATH=scripts:scripts/tests python3 -m unittest -v test_hook_compile_contract`

Expected: the minimal opaque report and receipt-only cases fail under the old
mandatory `EXECUTED_BUILD`/`BUILD_ERRORS` rules.

- [ ] **Step 7: Implement the minimal opaque contract**

Make `EXECUTED_BUILD` and `BUILD_ERRORS` optional diagnostics.  Accept only a
real matching call or a matching receipt; keep host-error, missing-call and
shrink rejection.  Add `SHRINK_EXEMPT` to `REPORT_FIELDS` only if needed for
flexible parsing; do not parse provider output.

- [ ] **Step 8: Run focused tests and commit Task 1**

Run:

```bash
PYTHONPATH=scripts:scripts/tests python3 -m unittest -v \
  test_hook_receipts test_hook_compile_contract
```

Expected: all focused tests pass.

Commit:

```bash
git add scripts/mae_flow_core/application/hooks/receipts.py \
  scripts/mae_flow_core/quality/compile_contract.py \
  scripts/mae_flow_core/quality/agent_reports.py \
  scripts/tests/test_hook_receipts.py \
  scripts/tests/test_hook_compile_contract.py
git commit -m "fix: make opaque compile evidence reusable"
```

### Task 2: Persist and reuse COMPILE execution before report rejection

**Files:**
- Modify: `scripts/mae_flow_core/adapters/hook_runtime_dependencies.py`
- Modify: `scripts/mae_flow_core/adapters/hook_runtime_contract_support.py`
- Modify: `scripts/mae_flow_core/adapters/hook_runtime_contracts.py`
- Test: `scripts/tests/test_hook_compile_contract.py`

**Interfaces:**
- Produces: `HookContractSupportMixin._record_compile_run_receipt(task, status, tool_calls)`.
- Produces: `HookContractSupportMixin._reusable_compile_run_receipt(task, status)`.
- Consumes: `.mae-flow.json.agent-evidence["COMPILE_RUN"]`.
- Consumes: Task 1 receipt functions.

- [ ] **Step 1: Write a failing cross-transcript recovery test**

Use a real temporary Git repository and runtime adapter.  First invoke
`_compile_contract` with a visible `build-fix` Skill call and an intentionally
missing shrink exemption so the contract rejects after execution.  Then invoke
it again with no Skill call, the same task/source/status, and a corrected
report.  Assert that the second call succeeds using `COMPILE_RUN` and that the
receipt contains no raw result.

- [ ] **Step 2: Run the recovery test and verify RED**

Run: `PYTHONPATH=scripts:scripts/tests python3 -m unittest -v test_hook_compile_contract`

Expected: no `COMPILE_RUN` receipt exists and the second transcript is rejected
for a missing Skill invocation.

- [ ] **Step 3: Implement receipt persistence and reuse**

Capture matching visible execution after task/scope validation and before the
final contract decision.  For pre-commit tasks, build `ReceiptContext` with
`_source_snapshot(task["head"])`.  Supply a fresh receipt to the pure contract
whenever the current transcript lacks a matching call.  Log reuse without
printing raw provider output.

- [ ] **Step 4: Run focused Hook tests and verify GREEN**

Run:

```bash
PYTHONPATH=scripts:scripts/tests python3 -m unittest -v \
  test_hook_compile_contract test_hook_agent_completion \
  test_hook_task_card_contracts
```

Expected: all tests pass, including cross-transcript recovery.

- [ ] **Step 5: Commit Task 2**

```bash
git add scripts/mae_flow_core/adapters/hook_runtime_dependencies.py \
  scripts/mae_flow_core/adapters/hook_runtime_contract_support.py \
  scripts/mae_flow_core/adapters/hook_runtime_contracts.py \
  scripts/tests/test_hook_compile_contract.py
git commit -m "fix: preserve compile execution across report retries"
```

### Task 3: Make staged-checkpoint risk acceptance snapshot-aware

**Files:**
- Modify: `scripts/mae_flow_core/cli_commands/done_status.py`
- Modify: `scripts/mae_flow_core/cli_commands/checkpoint_facts.py`
- Test: `scripts/tests/test_confirmation_receipts.py`
- Test: `scripts/tests/test_agent_evidence.py`

**Interfaces:**
- Produces: risk record field `source_snapshot` for `precommit_review` tasks.
- Consumes: `api._source_snapshot_since(task["head"], state, flow)`.
- Preserves: clean-worktree requirement for non-precommit risk acceptance.

- [ ] **Step 1: Write a failing staged Full risk-acceptance test**

Create a real temporary Git repository whose current state is `build`, with an
active staged CP1, a pre-commit COMPILE task and one uncommitted C++ change.
Capture a real user authorization message, run `accept-risk compile`, and
assert success plus a frozen `source_snapshot`.  Assert `_risk_acceptance`
passes before further edits and fails after another source edit.

- [ ] **Step 2: Run the risk tests and verify RED**

Run:

```bash
PYTHONPATH=scripts:scripts/tests python3 -m unittest -v \
  test_confirmation_receipts test_agent_evidence
```

Expected: `accept-risk` exits 2 with the old uncommitted-source rejection.

- [ ] **Step 3: Implement snapshot-aware authorization**

In `cmd_accept_risk`, permit dirty source only for a current task explicitly
marked `precommit_review`; capture the exact source snapshot and bind the task
issuance.  In `_risk_acceptance`, compare snapshots for this record shape and
fall back to the existing HEAD-based rule for old/post-commit records.

Print `checkpoint ready <CP>` when the active COMPILE task belongs to a coding
checkpoint; otherwise retain the `done` guidance.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the command from Step 2.  Expected: all tests pass and mutation of the
source snapshot invalidates the authorization.

- [ ] **Step 5: Commit Task 3**

```bash
git add scripts/mae_flow_core/cli_commands/done_status.py \
  scripts/mae_flow_core/cli_commands/checkpoint_facts.py \
  scripts/tests/test_confirmation_receipts.py \
  scripts/tests/test_agent_evidence.py
git commit -m "fix: bind checkpoint compile risk to worktree snapshot"
```

### Task 4: Full one-checkpoint Hook/state-machine integration

**Files:**
- Create: `scripts/tests/test_full_checkpoint_compile_recovery.py`
- Modify: `flow/steps/build.md`
- Modify: `agents/compile-agent.md`
- Modify: `CHANGELOG.md`
- Modify: `FIELD-TEST.md`

**Interfaces:**
- Exercises: Hook `subagentstop` -> COMPILE token/receipt -> `checkpoint ready`.
- Exercises: snapshot risk acceptance -> `checkpoint ready`.
- Documents: optional diagnostics and opaque-provider evidence wording.

- [ ] **Step 1: Write a failing end-to-end regression**

Build a temporary one-CP staged Full state with a real Git worktree and a
synthetic Hook transcript whose tool block is a `Skill` call for `build-fix`.
Assert that a minimal OK report issues a COMPILE token and that
`checkpoint ready CP1` reaches `review_pending` when CODE Reviewer is disabled.
Add a second path where no transcript evidence exists but snapshot-bound user
risk authorization reaches the same state.  Mutating the C++ file after either
proof must reject `checkpoint ready`.

- [ ] **Step 2: Run the integration test and verify RED**

Run:

```bash
PYTHONPATH=scripts:scripts/tests python3 -m unittest -v \
  test_full_checkpoint_compile_recovery
```

Expected: old mandatory report fields or old risk acceptance prevent at least
one route from reaching `review_pending`.

- [ ] **Step 3: Complete any minimal adapter wiring exposed by the test**

Only change production code when the integration test demonstrates a missing
connection.  Do not add tool-output parsing or new state-machine states.

- [ ] **Step 4: Update operator and Agent documentation**

State that `build-fix` owns compile success semantics, `EXECUTED_BUILD` and
`BUILD_ERRORS` are diagnostic, unchanged execution is reusable, and the risk
fallback binds the staged snapshot.  Mark automated coverage separately from
the still-required Windows field canary; do not mark unperformed field tests
as passed.

- [ ] **Step 5: Run the focused integration suite and commit Task 4**

Run:

```bash
PYTHONPATH=scripts:scripts/tests python3 -m unittest -v \
  test_full_checkpoint_compile_recovery test_checkpoint_quality \
  test_delivery_checkpoint_use_cases test_delivery_checkpoint_navigation \
  test_hook_compile_contract test_hook_agent_completion \
  test_hook_task_card_contracts test_confirmation_receipts
```

Expected: all tests pass.

Commit:

```bash
git add scripts/tests/test_full_checkpoint_compile_recovery.py \
  flow/steps/build.md agents/compile-agent.md CHANGELOG.md FIELD-TEST.md
git commit -m "test: cover Full checkpoint compile recovery"
```

### Task 5: Full verification and delivery

**Files:**
- Verify only: complete repository.

**Interfaces:**
- Produces: evidence for merge/push readiness.

- [ ] **Step 1: Run the full unit suite**

Run: `python3 -m unittest discover -s scripts/tests`

Expected: exit 0 with zero failures.

- [ ] **Step 2: Run repository self-test**

Run: `python3 scripts/selftest.py`

Expected: exit 0 and all self-tests pass.

- [ ] **Step 3: Run syntax and whitespace checks**

Run:

```bash
python3 -m compileall -q scripts/mae_flow_core scripts/tests
git diff --check
```

Expected: both commands exit 0 with no output from `git diff --check`.

- [ ] **Step 4: Review the exact diff and commit remaining documentation**

Run:

```bash
git status --short
git diff --stat main...HEAD
git diff main...HEAD
```

Confirm the diff changes no UT/CodeCheck semantics and persists no raw build
output.  Commit any final documentation-only adjustments with:

```bash
git add docs/superpowers/specs/2026-07-31-opaque-compile-evidence-design.md \
  docs/superpowers/plans/2026-07-31-opaque-compile-evidence.md
git commit -m "docs: describe opaque compile evidence recovery"
```

- [ ] **Step 5: Integrate and push only after fresh verification**

Fast-forward the requested target branch without rewriting history, then use a
normal `git push`.  Report the exact verification outputs and pushed commit.
