# Compile Side-Effect Ownership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every Git-visible file created or modified only by a validated COMPILE task ineligible for commit, regardless of its name, extension, directory, or tracked status.

**Architecture:** Capture an all-path worktree fingerprint baseline in the COMPILE task record, calculate the post-compile delta at validated SubagentStop, and persist non-direct-write paths in the existing agent provenance sidecar. Feed that exact ledger into the pure ownership policy; keep name-based artifact detection as a compatibility fallback.

**Tech Stack:** Python 3 standard library, Git CLI, `unittest`, Mae-Flow Hook/CLI adapters.

## Global Constraints

- The primary rule is provenance-based; artifact names and directories are fallback evidence only.
- Existing CLI, Hook protocol, task-card digest, state compatibility, and legitimate delete/move behavior must remain intact.
- Old `.mae-flow.json.agent-writes` documents containing only `paths` must remain readable.
- A successful later Agent `Write`, `Edit`, or `MultiEdit` supersedes the compile-side-effect record for that path.
- Exact snapshot/comparison/sidecar failures must log and fail open so an otherwise accepted COMPILE remains accepted.
- A normal exact ledger blocks only the affected commit attempt, with recovery that neither deletes files nor creates a persistent lock.
- Production code changes must follow red-green-refactor and include real behavior tests.

---

## File Structure

- Create `scripts/mae_flow_core/quality/compile_side_effects.py`: pure extraction and before/after attribution rules.
- Create `scripts/tests/test_compile_side_effects.py`: focused pure-policy tests.
- Modify `scripts/mae_flow_core/quality/task_cards.py`: persist the detached COMPILE worktree baseline.
- Modify `scripts/mae_flow_core/cli_commands/agent_task.py`: capture the baseline when signing a COMPILE task.
- Modify `scripts/mae_flow_core/cli_commands/source_facts.py`: expose an all-path Git-visible worktree snapshot.
- Modify `scripts/mae_flow_core/adapters/hook_runtime_source.py`: provide the Hook-side equivalent snapshot.
- Modify `scripts/mae_flow_core/adapters/hook_runtime_state.py`: persist compile side effects and let direct edits supersede them.
- Modify `scripts/mae_flow_core/adapters/hook_runtime_contracts.py`: record side effects only after the COMPILE contract accepts.
- Modify `scripts/mae_flow_core/adapters/hook_runtime_dependencies.py`: wire the pure attribution helpers.
- Modify `scripts/mae_flow_core/guard/ownership.py`: add an exact compile-side-effect blocking fact and decision.
- Modify `scripts/mae_flow_core/cli_commands/git_ownership.py`: load the side-effect ledger and classify exact commit candidates.
- Modify `scripts/mae_flow_core/cli_commands/gate.py`: pass the new fact into ownership policy.
- Modify `scripts/tests/test_quality_task_cards.py`, `scripts/tests/test_state_core.py`, `scripts/tests/test_hook_compile_contract.py`, `scripts/tests/test_task_scope.py`, `scripts/tests/test_guard_ownership.py`, `scripts/tests/test_commit_ownership.py`, and `scripts/tests/probe_gate_smoke.py`: protect integration and compatibility behavior.
- Modify `scripts/tests/differential/goldens/phase6.json` through `phase15.json`: record the intentional detached COMPILE snapshot metadata in the existing task-card scenario.
- Modify `MAINTAINERS.md` and `docs/superpowers/mae-flow-refactor-findings.md`: document the corrected provenance invariant and discovered defect.

### Task 1: Pure compile-side-effect attribution

**Files:**
- Create: `scripts/mae_flow_core/quality/compile_side_effects.py`
- Create: `scripts/tests/test_compile_side_effects.py`

**Interfaces:**
- Produces: `successful_direct_write_paths(calls, repository_root) -> tuple[str, ...]`
- Produces: `compile_side_effect_paths(baseline, current, direct_paths) -> tuple[str, ...]`
- Consumes: transcript `ToolCall` values with `name`, `input`, `result_seen`, and `is_error`.

- [ ] **Step 1: Write failing pure-policy tests**

Create literal fixtures covering a new configuration file, a tracked configuration fingerprint change, unchanged pre-existing dirt, failed direct-write calls, successful relative and absolute direct-write calls, and a direct-write path excluded from the side-effect result.

```python
def test_normal_named_compile_outputs_are_attributed_by_delta(self):
    self.assertEqual(
        ("config/generated.properties", "tracked/settings.json"),
        compile_side_effect_paths(
            {"tracked/settings.json": "before", "notes.txt": "same"},
            {
                "config/generated.properties": "new",
                "tracked/settings.json": "after",
                "notes.txt": "same",
            },
            (),
        ),
    )

def test_successful_direct_agent_edits_are_not_compile_side_effects(self):
    calls = (
        ToolCall("1", "Edit", {"file_path": "/repo/tracked/settings.json"},
                 result_seen=True, result="ok"),
        ToolCall("2", "Write", {"file_path": "/repo/failed.json"},
                 result_seen=True, is_error=True, result="failed"),
    )
    direct = successful_direct_write_paths(calls, "/repo")
    self.assertEqual(("tracked/settings.json",), direct)
    self.assertEqual(
        ("config/generated.properties",),
        compile_side_effect_paths(
            {},
            {
                "config/generated.properties": "new",
                "tracked/settings.json": "after",
            },
            direct,
        ),
    )
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
python -m unittest scripts.tests.test_compile_side_effects -v
```

Expected: import failure because `mae_flow_core.quality.compile_side_effects` does not exist.

- [ ] **Step 3: Implement the minimal pure functions**

Normalize repository-relative identity with `/`, reject paths outside the repository, accept only successful `Write`/`Edit`/`MultiEdit` calls, and return sorted deterministic tuples.

```python
def compile_side_effect_paths(baseline, current, direct_paths):
    direct = set(direct_paths)
    return tuple(sorted(
        path for path, fingerprint in current.items()
        if baseline.get(path) != fingerprint and path not in direct
    ))
```

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run:

```bash
python -m unittest scripts.tests.test_compile_side_effects -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the pure attribution unit**

```bash
git add scripts/mae_flow_core/quality/compile_side_effects.py scripts/tests/test_compile_side_effects.py
git commit -m "feat: classify compile side effects by provenance"
```

### Task 2: Capture the COMPILE baseline and persist its side effects

**Files:**
- Modify: `scripts/mae_flow_core/quality/task_cards.py`
- Modify: `scripts/mae_flow_core/cli_commands/agent_task.py`
- Modify: `scripts/mae_flow_core/cli_commands/source_facts.py`
- Modify: `scripts/mae_flow_core/adapters/hook_runtime_source.py`
- Modify: `scripts/mae_flow_core/adapters/hook_runtime_state.py`
- Modify: `scripts/mae_flow_core/adapters/hook_runtime_contracts.py`
- Modify: `scripts/mae_flow_core/adapters/hook_runtime_dependencies.py`
- Modify: `scripts/tests/test_quality_task_cards.py`
- Modify: `scripts/tests/test_state_core.py`
- Modify: `scripts/tests/test_hook_compile_contract.py`
- Modify: `scripts/tests/test_task_scope.py`
- Modify: `scripts/tests/differential/goldens/phase6.json` through `phase15.json`

**Interfaces:**
- Consumes: Task 1 `successful_direct_write_paths` and `compile_side_effect_paths`.
- Produces: task record field `worktree_snapshot: dict[str, str]`.
- Produces: sidecar field `compile_side_effects: dict[str, dict]`.
- Produces: `_worktree_snapshot_since(head) -> dict[str, str]` on the CLI facade and `_worktree_snapshot(head) -> dict[str, str]` on the Hook runtime.

- [ ] **Step 1: Write failing baseline and ledger tests**

Extend `test_task_record_detaches_mutable_inputs` to pass `worktree_snapshot` and prove later mutation does not alter the record. Add Hook/runtime tests that:

- compare a baseline with a new `generated/build.properties` and a modified tracked `config/runtime.json`;
- provide a successful transcript `Edit` for `config/runtime.json`;
- assert only `generated/build.properties` is stored under `compile_side_effects`;
- call `_record_agent_write("generated/build.properties")` and assert that path is removed from `compile_side_effects`;
- load an old sidecar containing only `paths` without error.

Add a COMPILE contract integration test proving the ledger is not written when the compile contract rejects.
Add failure-path coverage proving snapshot and sidecar failures are logged
without rejecting a COMPILE that already passed its contract.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
python -m unittest \
  scripts.tests.test_quality_task_cards \
  scripts.tests.test_state_core \
  scripts.tests.test_hook_compile_contract -v
```

Expected: failures for the missing `worktree_snapshot` argument/field and missing compile-side-effect persistence.

- [ ] **Step 3: Add all-path snapshot adapters**

In `source_facts.py`, fingerprint every path returned by the existing changed-path collector:

```python
def _worktree_snapshot_since(head):
    return {
        path: api._review_path_fingerprint(path)
        for path in _changed_paths_since_head(head)
    }
```

Add the Hook equivalent using `_changed_paths_since(head)` and `_review_path_fingerprint(path)`. Do not apply source-extension filtering.

- [ ] **Step 4: Persist the baseline in COMPILE task metadata**

Add `worktree_snapshot` to `task_record`, copy it with `dict()`, and pass:

```python
worktree_snapshot=(
    api._worktree_snapshot_since(context["task_head"])
    if kind == "COMPILE" else {}
),
```

Do not render this field into the human task-card body or change its digest.

- [ ] **Step 5: Record accepted COMPILE side effects**

Add a runtime method that computes current snapshot, extracts successful direct-write paths from the transcript, computes the pure delta, and atomically updates:

```json
{
  "paths": {},
  "compile_side_effects": {
    "generated/build.properties": {
      "at": "2026-07-30 10:00:00",
      "task_sha256": "...",
      "fingerprint": "..."
    }
  }
}
```

Call it only after `_evaluate_compile_contract(...)` returns accepted. Update `_record_agent_write` so the same atomic sidecar update both records the direct write and removes that path from `compile_side_effects`.
Treat provenance capture as best-effort: log snapshot/comparison/sidecar
failures and return without changing the accepted COMPILE result.

- [ ] **Step 6: Run the focused tests and verify GREEN**

Run:

```bash
python -m unittest \
  scripts.tests.test_quality_task_cards \
  scripts.tests.test_state_core \
  scripts.tests.test_hook_compile_contract -v
```

Expected: all tests pass with no warnings.

- [ ] **Step 7: Commit the COMPILE provenance integration**

```bash
git add \
  scripts/mae_flow_core/quality/task_cards.py \
  scripts/mae_flow_core/cli_commands/agent_task.py \
  scripts/mae_flow_core/cli_commands/source_facts.py \
  scripts/mae_flow_core/adapters/hook_runtime_source.py \
  scripts/mae_flow_core/adapters/hook_runtime_state.py \
  scripts/mae_flow_core/adapters/hook_runtime_contracts.py \
  scripts/mae_flow_core/adapters/hook_runtime_dependencies.py \
  scripts/tests/test_quality_task_cards.py \
  scripts/tests/test_state_core.py \
  scripts/tests/test_hook_compile_contract.py
git commit -m "feat: record compile task side effects"
```

### Task 3: Hard-block exact compile side effects at commit

**Files:**
- Modify: `scripts/mae_flow_core/guard/ownership.py`
- Modify: `scripts/mae_flow_core/cli_commands/git_ownership.py`
- Modify: `scripts/mae_flow_core/cli_commands/gate.py`
- Modify: `scripts/tests/test_guard_ownership.py`
- Modify: `scripts/tests/test_commit_ownership.py`
- Modify: `scripts/tests/probe_gate_smoke.py`

**Interfaces:**
- Consumes: sidecar `compile_side_effects` produced by Task 2.
- Produces: `OwnershipFacts.compile_side_effects: tuple[str, ...]`.
- Produces: blocking rule `bash-compile-side-effects`.
- Changes `_pending_commit_files(...)` return order to `(inherited, foreign_openspec, compile_side_effects, strong_artifacts, unproven_paths, artifact_hints)`.

- [ ] **Step 1: Write failing ownership and real Gate tests**

Add a pure ownership test:

```python
result = decide_ownership(self.facts(
    compile_side_effects=("config/generated.properties",),
))
self.assertEqual("bash-compile-side-effects", result.block.rule)
```

Add repository integration cases for:

- a new normal-looking recorded configuration file;
- an already tracked recorded configuration file;
- an old sidecar without `compile_side_effects`;
- an unrelated ambiguous `dist/app.js` outside a validated COMPILE ledger, which remains warning-only.

Add a real CLI probe where `.mae-flow.json.agent-writes` records
`internal/generated/build.properties`, followed by
`git add ... && git commit ...`; assert a nonzero Gate result and the exact path
in the message.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
python -m unittest \
  scripts.tests.test_guard_ownership \
  scripts.tests.test_commit_ownership -v
python scripts/tests/probe_gate_smoke.py
```

Expected: the new configuration-file commit cases are allowed under the old implementation, so the new assertions fail.

- [ ] **Step 3: Load exact side-effect candidates**

Read `compile_side_effects` defensively from the existing sidecar. Normalize its keys using `_repo_path_identity`. Intersect those paths with exact commit candidates; do not apply extension, directory, new-file, or direct-write conditions.

- [ ] **Step 4: Add the pure hard-block decision**

Insert `compile_side_effects` after foreign OpenSpec and before fallback strong
artifacts in the existing precedence. The `bash-compile-side-effects` message
must list every affected path and distinguish recovery by candidate state:

- staged-only paths: `git restore --staged -- <paths>`;
- same-command-only paths: remove them from `git add`, `git commit -a`, or the
  commit pathspec;
- paths in both groups: do both.

Every recovery preserves the local file. The rule rejects only the current
illegal commit attempt and creates no persistent lock.

Wire the sixth return value through both `OwnershipFacts` construction sites in `gate.py`.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```bash
python -m unittest \
  scripts.tests.test_guard_ownership \
  scripts.tests.test_commit_ownership -v
python scripts/tests/probe_gate_smoke.py
```

Expected: all tests and probes pass; the probe count increases by the new cases.

- [ ] **Step 6: Commit the Gate enforcement**

```bash
git add \
  scripts/mae_flow_core/guard/ownership.py \
  scripts/mae_flow_core/cli_commands/git_ownership.py \
  scripts/mae_flow_core/cli_commands/gate.py \
  scripts/tests/test_guard_ownership.py \
  scripts/tests/test_commit_ownership.py \
  scripts/tests/probe_gate_smoke.py
git commit -m "fix: block compile side effects from commits"
```

### Task 4: Documentation and complete verification

**Files:**
- Modify: `MAINTAINERS.md`
- Modify: `docs/superpowers/mae-flow-refactor-findings.md`
- Modify: `docs/superpowers/specs/2026-07-30-compile-side-effect-ownership-design.md`
- Modify: `docs/superpowers/plans/2026-07-30-compile-side-effect-ownership.md`
- Modify: `scripts/tests/test_compile_side_effects.py`
- Modify: `scripts/tests/test_commit_ownership.py`
- Modify: `scripts/mae_flow_core/cli_commands/gate.py`
- Modify: `scripts/mae_flow_core/guard/ownership.py`

**Interfaces:**
- Consumes: the final rule and test evidence from Tasks 1–3.
- Produces: maintainer guidance and a numbered defect record with root cause, resolution, regression tests, and behavior boundary.

- [ ] **Step 1: Update maintainer guidance and findings**

Replace the old “only newly added high-confidence artifact hard-blocks”
description with the two-layer contract:

1. exact COMPILE provenance always hard-blocks non-direct-write paths;
2. high-confidence naming remains a fallback when exact provenance is absent.

Record the prior behavior as a reproducible guard coverage defect, including the
normal configuration-file and tracked-file cases.

Correct the earlier rejection premise: exact provenance capture failures are
logged and fail open. Document that a normal ledger blocks only the illegal
commit attempt with state-specific recovery, no persistent lock, and no file
deletion.

- [ ] **Step 2: Run formatting and placeholder checks**

Run:

```bash
git diff --check
rg -n "PLACEHOLDER|INCOMPLETE|UNRESOLVED" \
  MAINTAINERS.md \
  docs/superpowers/mae-flow-refactor-findings.md
```

Expected: `git diff --check` succeeds and no newly introduced placeholders are reported.

- [ ] **Step 3: Run all release verification commands**

Run:

```bash
python -m unittest discover -s scripts/tests -p 'test_*.py'
python -W error::ResourceWarning scripts/tests/test_state_core.py
python -W error::ResourceWarning scripts/tests/test_checkpoints.py
python scripts/tests/test_architecture.py
python scripts/tests/differential/runner.py --implementation-root .
python scripts/tests/test_fault_injection.py
python scripts/selftest.py
```

Expected: every command exits 0. Differential changes must be limited to the
intentional compile-side-effect Gate scenarios; unrelated golden behavior must
remain identical.

- [ ] **Step 4: Commit documentation and final proof**

```bash
git add \
  MAINTAINERS.md \
  docs/superpowers/mae-flow-refactor-findings.md \
  docs/superpowers/specs/2026-07-30-compile-side-effect-ownership-design.md \
  docs/superpowers/plans/2026-07-30-compile-side-effect-ownership.md \
  scripts/tests/test_compile_side_effects.py \
  scripts/tests/test_commit_ownership.py \
  scripts/mae_flow_core/cli_commands/gate.py \
  scripts/mae_flow_core/guard/ownership.py
git commit -m "docs: document compile output ownership invariant"
```

- [ ] **Step 5: Review the final branch**

Run:

```bash
git status --short
git log --oneline --decorate -6
git diff HEAD~4..HEAD --stat
```

Expected: clean worktree, six implementation/closure commits after the
design/plan commits (including the Task 2 and Task 3 review-fix commits), and
only files listed in this plan changed.
