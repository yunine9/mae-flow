# Mae-Flow Refactor Stage 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a machine-checked completion contract, broaden the immutable behavior Oracle, and add reusable fault injection before moving more production responsibilities.

**Architecture:** Stage 0 changes test infrastructure and documentation only. A JSON completion contract defines final architecture targets, a coverage catalog maps every black-box scenario to a domain and runtime mode, and Phase-10 adds characterization scenarios without changing any Phase-9 value. Fault injection remains a test utility and proves current StateStore failure semantics before adapters are extracted.

**Tech Stack:** Python 3 standard library, `unittest`, subprocess-based CLI/Hook fixtures, JSON golden snapshots, Git.

## Global Constraints

- Phase-9 stdout, stderr, exit codes, state, sidecars, files, Git state, and operation ordering are immutable.
- New characterization scenarios may be added, but every Phase-9 scenario value must remain byte-for-byte equal after JSON parsing.
- Stage 0 must not modify production entrypoints or `mae_flow_core` product modules.
- Every new test must be observed failing before its implementation is added.
- Dynamic values may be normalized only by explicit replacements in `differential/normalize.py`.
- No golden may be updated to hide an unexplained behavior difference.
- `scripts/mae-flow.py` final target is at most 1,500 lines; `hooks/dispatch.py` final target is at most 800 lines.
- New business modules in later stages are at most 500 lines and complexity 15 unless an audited exception exists.
- Do not push or merge without explicit authorization.

## File Map

- Create `scripts/tests/refactor_completion_contract.json`: machine-readable final targets, ordered stages, domains, and required observable dimensions.
- Create `scripts/tests/refactor_completion.py`: schema and repository consistency validation for the completion contract.
- Create `scripts/tests/test_refactor_completion.py`: tests for exact targets, stage ordering, monotonic baselines, and coverage linkage.
- Create `scripts/tests/differential/coverage.json`: every scenario's domain, runtime mode, workflow, transition, delivery mode, and fault class.
- Create `scripts/tests/differential/coverage.py`: coverage catalog loading and validation.
- Create `scripts/tests/differential/stage0_scenarios.py`: new deterministic Runtime, Delivery, Quality, Ownership, and Hook scenario builders.
- Modify `scripts/tests/differential/scenarios.py`: register Stage-0 builders without changing existing builders.
- Create `scripts/tests/differential/goldens/phase10.json`: Phase-9 snapshots plus only the new characterization keys.
- Modify `scripts/tests/differential/runner.py`: default to Phase-10 after its immutability check exists.
- Modify `scripts/tests/test_differential_harness.py`: enforce Phase-9 preservation, Phase-10 scenario coverage, and coverage metadata.
- Create `scripts/tests/fault_injection.py`: reusable deterministic failure-on-Nth-call context manager for unit tests.
- Create `scripts/tests/test_fault_injection.py`: utility tests and StateStore atomic replacement failure characterization.
- Modify `scripts/selftest.py`: run the two new Stage-0 suites.
- Modify `docs/refactor-architecture.md`: describe the completion contract, coverage catalog, and golden evolution rule.

---

### Task 1: Machine-readable completion contract

**Files:**
- Create: `scripts/tests/refactor_completion_contract.json`
- Create: `scripts/tests/refactor_completion.py`
- Create: `scripts/tests/test_refactor_completion.py`

**Interfaces:**
- Produces: `load_contract(path: str) -> dict`
- Produces: `validate_contract(root: str, contract: dict) -> list[str]`
- Produces: JSON keys `schema`, `behavior_baseline`, `final_targets`, `stages`, `domains`, `observables`

- [ ] **Step 1: Write the failing schema and target tests**

Create `scripts/tests/test_refactor_completion.py` with:

```python
import json
import os
import sys
import tempfile
import unittest

TESTS = os.path.abspath(os.path.dirname(__file__))
ROOT = os.path.abspath(os.path.join(TESTS, "..", ".."))
if TESTS not in sys.path:
    sys.path.insert(0, TESTS)

from refactor_completion import load_contract, validate_contract


class RefactorCompletionContractTests(unittest.TestCase):
    def test_repository_contract_has_strict_final_targets(self):
        contract = load_contract(os.path.join(
            TESTS, "refactor_completion_contract.json"))
        self.assertEqual(1, contract["schema"])
        self.assertEqual("phase9", contract["behavior_baseline"])
        self.assertEqual(
            {
                "scripts/mae-flow.py": 1500,
                "hooks/dispatch.py": 800,
            },
            contract["final_targets"]["max_entrypoint_lines"],
        )
        self.assertEqual(
            500, contract["final_targets"]["max_business_module_lines"])
        self.assertEqual(
            15, contract["final_targets"]["max_policy_complexity"])
        self.assertEqual(list(range(10)), [
            item["id"] for item in contract["stages"]])
        self.assertEqual([], validate_contract(ROOT, contract))

    def test_contract_rejects_target_above_current_monolith_baseline(self):
        with open(
                os.path.join(TESTS, "refactor_completion_contract.json"),
                encoding="utf-8") as stream:
            contract = json.load(stream)
        contract["final_targets"]["max_entrypoint_lines"][
            "scripts/mae-flow.py"] = 20000
        self.assertIn(
            "scripts/mae-flow.py: final target 20000 must be below "
            "current architecture baseline 10408",
            validate_contract(ROOT, contract),
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
python scripts/tests/test_refactor_completion.py
```

Expected: `ModuleNotFoundError: No module named 'refactor_completion'`.

- [ ] **Step 3: Add the exact completion contract**

Create `scripts/tests/refactor_completion_contract.json`:

```json
{
  "schema": 1,
  "behavior_baseline": "phase9",
  "final_targets": {
    "max_entrypoint_lines": {
      "scripts/mae-flow.py": 1500,
      "hooks/dispatch.py": 800
    },
    "max_business_module_lines": 500,
    "max_policy_complexity": 15,
    "private_monolith_test_imports": 0
  },
  "stages": [
    {"id": 0, "name": "oracle"},
    {"id": 1, "name": "evidence"},
    {"id": 2, "name": "guard-permit-ownership"},
    {"id": 3, "name": "delivery"},
    {"id": 4, "name": "quality"},
    {"id": 5, "name": "hook-agent-contracts"},
    {"id": 6, "name": "cli-commands"},
    {"id": 7, "name": "adapters-cleanup"},
    {"id": 8, "name": "large-core-split"},
    {"id": 9, "name": "final-proof"}
  ],
  "domains": [
    "runtime", "workflow", "evidence", "gate", "ownership",
    "delivery", "quality", "hook", "state", "platform"
  ],
  "observables": [
    "stdout", "stderr", "returncode", "files", "state", "git"
  ]
}
```

- [ ] **Step 4: Implement the minimal validator**

Create `scripts/tests/refactor_completion.py`:

```python
import json
import os


def load_contract(path):
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def validate_contract(root, contract):
    errors = []
    if contract.get("schema") != 1:
        errors.append("schema must be 1")
    if contract.get("behavior_baseline") != "phase9":
        errors.append("behavior_baseline must be phase9")
    stages = contract.get("stages", [])
    if [item.get("id") for item in stages] != list(range(10)):
        errors.append("stages must be ordered 0 through 9")
    baseline_path = os.path.join(
        root, "scripts", "tests", "architecture_baseline.json")
    with open(baseline_path, encoding="utf-8") as stream:
        baseline = json.load(stream)
    targets = contract.get("final_targets", {}).get(
        "max_entrypoint_lines", {})
    for relative, maximum in sorted(targets.items()):
        current = baseline.get("max_lines", {}).get(relative)
        if current is None:
            errors.append(relative + ": missing current architecture baseline")
        elif not isinstance(maximum, int) or maximum >= current:
            errors.append(
                "%s: final target %s must be below current architecture "
                "baseline %s" % (relative, maximum, current))
    required_domains = {
        "runtime", "workflow", "evidence", "gate", "ownership",
        "delivery", "quality", "hook", "state", "platform",
    }
    if set(contract.get("domains", [])) != required_domains:
        errors.append("domains do not match the completion roadmap")
    if set(contract.get("observables", [])) != {
            "stdout", "stderr", "returncode", "files", "state", "git"}:
        errors.append("observable dimensions are incomplete")
    return errors
```

- [ ] **Step 5: Run Task 1 tests**

Run:

```bash
python scripts/tests/test_refactor_completion.py
python scripts/tests/test_architecture.py
```

Expected: both suites pass.

- [ ] **Step 6: Commit Task 1**

```bash
git add scripts/tests/refactor_completion.py \
  scripts/tests/refactor_completion_contract.json \
  scripts/tests/test_refactor_completion.py
git commit -m "test: encode refactor completion contract"
```

### Task 2: Differential coverage catalog

**Files:**
- Create: `scripts/tests/differential/coverage.json`
- Create: `scripts/tests/differential/coverage.py`
- Modify: `scripts/tests/test_refactor_completion.py`

**Interfaces:**
- Consumes: `SCENARIOS: dict[str, Callable]`
- Produces: `load_coverage(path: str) -> dict`
- Produces: `validate_coverage(catalog: dict, scenario_names: set[str]) -> list[str]`

- [ ] **Step 1: Add failing coverage validation tests**

Append to `scripts/tests/test_refactor_completion.py`:

```python
from differential.coverage import load_coverage, validate_coverage
from differential.scenarios import SCENARIOS


class DifferentialCoverageContractTests(unittest.TestCase):
    def test_phase9_scenarios_have_complete_coverage_metadata(self):
        coverage = load_coverage(os.path.join(
            TESTS, "differential", "coverage.json"))
        self.assertEqual(
            [],
            validate_coverage(coverage, set(SCENARIOS)),
        )

    def test_coverage_rejects_unknown_domain_and_missing_scenario(self):
        coverage = {
            "schema": 1,
            "scenarios": {
                "ghost": {
                    "domain": "unknown",
                    "runtime": "inactive",
                    "workflow": "none",
                    "transition": "none",
                    "delivery": "none",
                    "fault": "none"
                }
            }
        }
        self.assertEqual(
            [
                "coverage missing registered scenario action_status",
                "coverage references unknown scenario ghost",
                "ghost: unknown domain unknown",
            ],
            validate_coverage(coverage, {"action_status"}),
        )
```

- [ ] **Step 2: Run the coverage tests and verify RED**

Run:

```bash
python scripts/tests/test_refactor_completion.py
```

Expected: import failure for `differential.coverage`.

- [ ] **Step 3: Implement the catalog validator**

Create `scripts/tests/differential/coverage.py`:

```python
import json


DOMAINS = {
    "runtime", "workflow", "evidence", "gate", "ownership",
    "delivery", "quality", "hook", "state", "platform",
}
FIELDS = {
    "domain", "runtime", "workflow", "transition", "delivery", "fault",
}


def load_coverage(path):
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def validate_coverage(catalog, scenario_names):
    errors = []
    entries = catalog.get("scenarios", {})
    for name in sorted(scenario_names - set(entries)):
        errors.append("coverage missing registered scenario " + name)
    for name in sorted(set(entries) - scenario_names):
        errors.append("coverage references unknown scenario " + name)
    for name, metadata in sorted(entries.items()):
        missing = sorted(FIELDS - set(metadata))
        if missing:
            errors.append(
                "%s: missing fields %s" % (name, ",".join(missing)))
        if metadata.get("domain") not in DOMAINS:
            errors.append(
                "%s: unknown domain %s" % (
                    name, metadata.get("domain")))
    return errors
```

- [ ] **Step 4: Create coverage metadata for all 12 Phase-9 scenarios**

Create `scripts/tests/differential/coverage.json` with schema `1` and these exact mappings:

```json
{
  "schema": 1,
  "scenarios": {
    "action_status": {"domain": "quality", "runtime": "inactive", "workflow": "none", "transition": "none", "delivery": "standalone", "fault": "none"},
    "active_gate_edit": {"domain": "gate", "runtime": "flow", "workflow": "full", "transition": "none", "delivery": "none", "fault": "none"},
    "combined_git_add_flags": {"domain": "ownership", "runtime": "flow", "workflow": "full", "transition": "none", "delivery": "none", "fault": "none"},
    "compile_task_card": {"domain": "quality", "runtime": "flow", "workflow": "full", "transition": "none", "delivery": "none", "fault": "none"},
    "corrupt_state_doctor": {"domain": "state", "runtime": "corrupt", "workflow": "none", "transition": "none", "delivery": "none", "fault": "corrupt-json"},
    "dangerous_gate_bash": {"domain": "gate", "runtime": "flow", "workflow": "full", "transition": "none", "delivery": "none", "fault": "none"},
    "evidence_rejection": {"domain": "evidence", "runtime": "flow", "workflow": "review", "transition": "rejection", "delivery": "none", "fault": "none"},
    "inactive_pretooluse_bypass": {"domain": "hook", "runtime": "inactive", "workflow": "none", "transition": "none", "delivery": "none", "fault": "none"},
    "moonlight_finalize": {"domain": "delivery", "runtime": "flow", "workflow": "review", "transition": "finalize", "delivery": "moonlight", "fault": "none"},
    "ordinary_advance": {"domain": "workflow", "runtime": "flow", "workflow": "tweak", "transition": "normal", "delivery": "none", "fault": "none"},
    "terminal_status": {"domain": "runtime", "runtime": "flow-terminal", "workflow": "tweak", "transition": "none", "delivery": "none", "fault": "none"},
    "workflow_steps": {"domain": "workflow", "runtime": "inactive", "workflow": "all", "transition": "graph", "delivery": "all", "fault": "none"}
  }
}
```

- [ ] **Step 5: Run Task 2 tests**

Run:

```bash
python scripts/tests/test_refactor_completion.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit Task 2**

```bash
git add scripts/tests/differential/coverage.py \
  scripts/tests/differential/coverage.json \
  scripts/tests/test_refactor_completion.py
git commit -m "test: catalog differential behavior coverage"
```

### Task 3: Runtime and State characterization scenarios

**Files:**
- Create: `scripts/tests/differential/stage0_scenarios.py`
- Modify: `scripts/tests/differential/scenarios.py`
- Modify: `scripts/tests/differential/coverage.json`
- Modify: `scripts/tests/test_differential_harness.py`

**Interfaces:**
- Consumes: `_prepare_repository(project) -> env` from `differential.scenarios`
- Produces: scenario builders `direct_current`, `standalone_action_status`, `corrupt_exit_repair`, `terminal_pretooluse_bypass`
- Every builder returns `(invocation: dict, replacements: dict)`

- [ ] **Step 1: Write failing registration and behavior tests**

Add to `DifferentialRunnerTests` in `test_differential_harness.py`:

```python
    def test_stage0_runtime_scenarios_are_registered(self):
        from differential.scenarios import SCENARIOS
        self.assertTrue({
            "direct_current",
            "standalone_action_status",
            "corrupt_exit_repair",
            "terminal_pretooluse_bypass",
        }.issubset(SCENARIOS))
```

- [ ] **Step 2: Run and verify RED**

Run:

```bash
python scripts/tests/test_differential_harness.py
```

Expected: the new set is not a subset of `SCENARIOS`.

- [ ] **Step 3: Add shared deterministic fixture helpers**

Create `scripts/tests/differential/stage0_scenarios.py` with:

```python
import json
import os
import sys


def write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")


def cli(implementation_root, env, *arguments):
    return {
        "argv": [
            sys.executable,
            os.path.join(implementation_root, "scripts", "mae-flow.py"),
            *arguments,
        ],
        "stdin": "",
        "env": env,
    }, {}


def hook(implementation_root, env, event, payload):
    return {
        "argv": [
            sys.executable,
            os.path.join(implementation_root, "hooks", "dispatch.py"),
            event,
        ],
        "stdin": json.dumps(payload, ensure_ascii=False) + "\n",
        "env": env,
    }, {}
```

- [ ] **Step 4: Implement four scenario builders**

In the same file, add functions that receive
`(project, implementation_root, prepare_repository)`:

```python
def direct_current(project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    write_json(os.path.join(project, ".mae-flow.json.exited"), {
        "schema_version": 2,
        "revision": 1,
        "status": "exited",
        "snapshot": ".mae-flow-work/exited/REQ-DIFF.json",
    })
    return cli(implementation_root, env, "current")


def standalone_action_status(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    write_json(
        os.path.join(
            project, ".mae-flow-work", "standalone-action.json"),
        {
            "schema_version": 2,
            "revision": 1,
            "kind": "ut",
            "id": "diff-action",
            "expires_epoch": 4102444800,
            "work_dir": os.path.join(
                project, ".mae-flow-work", "standalone", "diff-action"),
            "tokens": {},
            "rejections": {},
            "quality": {},
        },
    )
    return cli(implementation_root, env, "action", "status")


def corrupt_exit_repair(project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    with open(
            os.path.join(project, ".mae-flow.json.exited"),
            "w", encoding="utf-8", newline="\n") as stream:
        stream.write("{broken-exit")
    return cli(implementation_root, env, "doctor", "--repair-state")


def terminal_pretooluse_bypass(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    write_json(os.path.join(project, ".mae-flow.json"), {
        "schema_version": 2,
        "revision": 1,
        "updated_at": "2026-07-29 10:00:00",
        "current": "end",
        "config": {"单号": "REQ-DIFF", "分支名": "main"},
        "choices": {"workflow": "tweak"},
        "history": [],
        "started": "2026-07-29 10:00:00",
    })
    return hook(
        implementation_root,
        env,
        "pretooluse",
        {
            "cwd": project,
            "tool_name": "Bash",
            "tool_input": {"command": "git reset --hard"},
        },
    )
```

The literal `4102444800` is 2100-01-01 and keeps the snapshot deterministic.

- [ ] **Step 5: Register the scenarios**

At the end of `differential/scenarios.py`, import the four builders and add thin
wrappers that pass `_prepare_repository`; then add all four names to `SCENARIOS`.
Do not edit any existing scenario builder.

- [ ] **Step 6: Add exact coverage entries**

Add to `coverage.json`:

```json
"direct_current": {"domain": "runtime", "runtime": "direct", "workflow": "none", "transition": "none", "delivery": "none", "fault": "none"},
"standalone_action_status": {"domain": "runtime", "runtime": "standalone", "workflow": "none", "transition": "none", "delivery": "standalone", "fault": "none"},
"corrupt_exit_repair": {"domain": "state", "runtime": "corrupt", "workflow": "none", "transition": "repair", "delivery": "none", "fault": "corrupt-json"},
"terminal_pretooluse_bypass": {"domain": "hook", "runtime": "flow-terminal", "workflow": "tweak", "transition": "none", "delivery": "none", "fault": "none"}
```

- [ ] **Step 7: Run new scenarios without a golden**

Run each through `run_scenario(ROOT, name)` from a short `python -c` command and
confirm all return snapshots without timeout or nondeterministic paths.

- [ ] **Step 8: Commit Task 3**

```bash
git add scripts/tests/differential/stage0_scenarios.py \
  scripts/tests/differential/scenarios.py \
  scripts/tests/differential/coverage.json \
  scripts/tests/test_differential_harness.py
git commit -m "test: characterize runtime mode boundaries"
```

### Task 4: Delivery, Quality, Ownership, and Hook characterization

**Files:**
- Modify: `scripts/tests/differential/stage0_scenarios.py`
- Modify: `scripts/tests/differential/scenarios.py`
- Modify: `scripts/tests/differential/coverage.json`
- Modify: `scripts/tests/test_differential_harness.py`

**Interfaces:**
- Produces scenario builders:
  `checkpoint_status`, `moonlight_report_issue`,
  `active_pretooluse_edit`, `subagentstop_missing_task_card`

- [ ] **Step 1: Add failing registration test**

Add to `DifferentialRunnerTests`:

```python
    def test_stage0_domain_scenarios_are_registered(self):
        from differential.scenarios import SCENARIOS
        self.assertTrue({
            "checkpoint_status",
            "moonlight_report_issue",
            "active_pretooluse_edit",
            "subagentstop_missing_task_card",
        }.issubset(SCENARIOS))
```

- [ ] **Step 2: Run and verify RED**

Run:

```bash
python scripts/tests/test_differential_harness.py
```

Expected: the registration assertion fails.

- [ ] **Step 3: Implement `checkpoint_status`**

Use a flow state at `tw_change` with workflow `tweak` and:

```python
"development_review": {
    "mode": "staged",
    "current_index": 0,
    "checkpoints": [
        {
            "id": "CP1",
            "title": "core behavior",
            "status": "coding",
            "base": "<current fixture HEAD>"
        }
    ]
}
```

Obtain the literal fixture HEAD with:

```python
subprocess.run(
    ["git", "rev-parse", "HEAD"],
    cwd=project, text=True, capture_output=True, check=True).stdout.strip()
```

Invoke `mae-flow.py checkpoint status`. The runner already normalizes the
fixture repository HEAD through the Git snapshot; do not add a broad hash
normalizer.

- [ ] **Step 4: Implement `moonlight_report_issue`**

Write a deterministic flow state at `moonlight_review` with workflow `review`
and:

```python
"moonlight": {
    "enabled": true,
    "cycle": 2,
    "issues": [
        {
            "id": "ML-001",
            "category": "environment",
            "reason": "deterministic fixture failure",
            "step": "rf_ut"
        }
    ]
}
```

Use Python `True`, not JSON `true`, in the implementation. Invoke
`mae-flow.py moonlight report`.

- [ ] **Step 5: Implement `active_pretooluse_edit`**

Write an active `build` flow state and send Hook event:

```python
{
    "cwd": project,
    "tool_name": "Edit",
    "tool_input": {"file_path": "<project>/README.md"}
}
```

Invoke `hooks/dispatch.py pretooluse`. This differs from `active_gate_edit`
because it freezes Hook protocol mapping, not the CLI gate command.

- [ ] **Step 6: Implement `subagentstop_missing_task_card`**

Write an active `build` flow state with no `agent_tasks`, then invoke
`hooks/dispatch.py subagentstop` with:

```python
{
    "cwd": project,
    "agent_type": "compile-agent",
    "last_assistant_message": "COMPILE_RESULT: OK"
}
```

The scenario must preserve the real rejection output and must not fabricate a
task card, transcript, or token.

- [ ] **Step 7: Register and catalog the scenarios**

Add all four names to `SCENARIOS` and add these coverage entries:

```json
"checkpoint_status": {"domain": "delivery", "runtime": "flow", "workflow": "tweak", "transition": "none", "delivery": "checkpoint-staged", "fault": "none"},
"moonlight_report_issue": {"domain": "delivery", "runtime": "flow", "workflow": "review", "transition": "report", "delivery": "moonlight", "fault": "recorded-issue"},
"active_pretooluse_edit": {"domain": "gate", "runtime": "flow", "workflow": "full", "transition": "none", "delivery": "none", "fault": "none"},
"subagentstop_missing_task_card": {"domain": "quality", "runtime": "flow", "workflow": "full", "transition": "rejection", "delivery": "none", "fault": "missing-task-card"}
```

- [ ] **Step 8: Run the four scenarios directly**

Expected: all return within 30 seconds, no absolute temporary path remains
outside explicit `<PROJECT>` / `<IMPLEMENTATION>` replacements.

- [ ] **Step 9: Commit Task 4**

```bash
git add scripts/tests/differential/stage0_scenarios.py \
  scripts/tests/differential/scenarios.py \
  scripts/tests/differential/coverage.json \
  scripts/tests/test_differential_harness.py
git commit -m "test: characterize remaining refactor domains"
```

### Task 5: Phase-10 immutable golden

**Files:**
- Create: `scripts/tests/differential/goldens/phase10.json`
- Modify: `scripts/tests/differential/runner.py`
- Modify: `scripts/tests/test_differential_harness.py`
- Modify: `scripts/tests/test_refactor_completion.py`

**Interfaces:**
- Phase-10 contains all Phase-9 keys with identical values plus exactly the
  eight Stage-0 scenario keys from Tasks 3–4.

- [ ] **Step 1: Write the failing immutability test**

Add:

```python
    def test_phase10_preserves_every_phase9_snapshot(self):
        phase9 = load_goldens(os.path.join(
            ROOT, "scripts", "tests", "differential",
            "goldens", "phase9.json"))
        phase10 = load_goldens(os.path.join(
            ROOT, "scripts", "tests", "differential",
            "goldens", "phase10.json"))
        self.assertEqual(set(phase9), set(phase10) - {
            "direct_current",
            "standalone_action_status",
            "corrupt_exit_repair",
            "terminal_pretooluse_bypass",
            "checkpoint_status",
            "moonlight_report_issue",
            "active_pretooluse_edit",
            "subagentstop_missing_task_card",
        })
        for name, expected in phase9.items():
            with self.subTest(name=name):
                self.assertEqual(expected, phase10[name])
```

- [ ] **Step 2: Run and verify RED**

Expected: `FileNotFoundError` for `phase10.json`.

- [ ] **Step 3: Generate Phase-10 once from the current behavior**

Run:

```bash
python scripts/tests/differential/runner.py \
  --implementation-root . \
  --write-goldens scripts/tests/differential/goldens/phase10.json
```

- [ ] **Step 4: Verify the golden delta before accepting it**

Run the immutability test. If any Phase-9 value differs, delete Phase-10 and
investigate; do not update Phase-9 and do not add normalization.

- [ ] **Step 5: Switch the runner default and add Phase-10 behavior test**

Change `DEFAULT_GOLDENS` to `phase10.json`. Add a test that loads Phase-10,
runs every new scenario, and calls `assert_matches_golden`.

- [ ] **Step 6: Validate the coverage catalog against Phase-10**

Add a separate assertion that `set(load_goldens(phase10_path)) == set(SCENARIOS)`.
Keep the coverage validator independent of golden creation so Tasks 3 and 4
remain green before Phase-10 is generated, and keep the explicit Phase-9
preservation test.

- [ ] **Step 7: Run Task 5 verification**

```bash
python scripts/tests/test_differential_harness.py
python scripts/tests/test_refactor_completion.py
python scripts/tests/differential/runner.py --implementation-root .
```

Expected: all pass; runner emits no diff.

- [ ] **Step 8: Commit Task 5**

```bash
git add scripts/tests/differential/goldens/phase10.json \
  scripts/tests/differential/runner.py \
  scripts/tests/test_differential_harness.py \
  scripts/tests/test_refactor_completion.py
git commit -m "test: lock stage zero behavior oracle"
```

### Task 6: Reusable fault injection and StateStore failure Oracle

**Files:**
- Create: `scripts/tests/fault_injection.py`
- Create: `scripts/tests/test_fault_injection.py`

**Interfaces:**
- Produces:
  `fail_on_call(owner: object, attribute: str, call_number: int, exception: BaseException)`
  as a context manager yielding the patched mock.

- [ ] **Step 1: Write failing utility and StateStore tests**

Create `scripts/tests/test_fault_injection.py`:

```python
import glob
import os
import sys
import tempfile
import unittest

TESTS = os.path.abspath(os.path.dirname(__file__))
SCRIPTS = os.path.abspath(os.path.join(TESTS, ".."))
if TESTS not in sys.path:
    sys.path.insert(0, TESTS)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from fault_injection import fail_on_call
from mae_flow_core import state_store


class FaultInjectionTests(unittest.TestCase):
    def test_fail_on_call_delegates_before_and_after_selected_call(self):
        class Target:
            def invoke(self, value):
                return value * 2

        target = Target()
        with fail_on_call(
                target, "invoke", 2, OSError("selected failure")):
            self.assertEqual(2, target.invoke(1))
            with self.assertRaisesRegex(OSError, "selected failure"):
                target.invoke(2)
            self.assertEqual(6, target.invoke(3))

    def test_atomic_replace_failure_preserves_original_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "state.json")
            state_store.atomic_write_json(path, {"value": "old"})
            with fail_on_call(
                    state_store, "_replace_with_retry", 1,
                    OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    state_store.atomic_write_json(path, {"value": "new"})
            self.assertEqual({"value": "old"}, state_store.read_json(path))
            self.assertEqual([], glob.glob(path + ".tmp.*"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run and verify RED**

Expected: import failure for `fault_injection`.

- [ ] **Step 3: Implement the minimal context manager**

Create `scripts/tests/fault_injection.py`:

```python
from contextlib import contextmanager
from unittest import mock


@contextmanager
def fail_on_call(owner, attribute, call_number, exception):
    if call_number < 1:
        raise ValueError("call_number must be at least 1")
    original = getattr(owner, attribute)
    calls = {"count": 0}

    def invoke(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == call_number:
            raise exception
        return original(*args, **kwargs)

    with mock.patch.object(owner, attribute, side_effect=invoke) as patched:
        yield patched
```

- [ ] **Step 4: Add the invalid call-number test**

Add:

```python
    def test_fail_on_call_rejects_non_positive_call_number(self):
        with self.assertRaisesRegex(
                ValueError, "call_number must be at least 1"):
            with fail_on_call(os.path, "exists", 0, OSError("unused")):
                pass
```

- [ ] **Step 5: Run Task 6 tests**

```bash
python scripts/tests/test_fault_injection.py
python scripts/tests/test_state_core.py
```

Expected: all tests pass; no temp file remains.

- [ ] **Step 6: Commit Task 6**

```bash
git add scripts/tests/fault_injection.py scripts/tests/test_fault_injection.py
git commit -m "test: add deterministic fault injection oracle"
```

### Task 7: Selftest wiring and Stage-0 documentation

**Files:**
- Modify: `scripts/selftest.py`
- Modify: `scripts/tests/test_architecture.py`
- Modify: `docs/refactor-architecture.md`

**Interfaces:**
- `scripts/selftest.py` must run `test_refactor_completion.py` and
  `test_fault_injection.py`.
- Architecture tests must fail if either suite is removed from selftest.

- [ ] **Step 1: Add failing architecture assertions**

In `test_selftest_runs_refactor_safety_suites`, add:

```python
self.assertIn("test_refactor_completion.py", text)
self.assertIn("test_fault_injection.py", text)
```

- [ ] **Step 2: Run and verify RED**

Run:

```bash
python scripts/tests/test_architecture.py
```

Expected: failure because both filenames are absent from `selftest.py`.

- [ ] **Step 3: Register both suites in selftest**

Add both files to the selftest syntax file list and subprocess suite list using
labels:

- `重构完成契约与覆盖清单`
- `故障注入与原子写失败回归`

Keep them next to the existing differential and architecture suites.

- [ ] **Step 4: Document Stage-0 safety infrastructure**

Append to the behavior safety section of `docs/refactor-architecture.md`:

- Phase-10 extends Phase-9 only with Stage-0 characterization scenarios;
- `refactor_completion_contract.json` contains final targets and cannot be
  relaxed to match current code;
- `coverage.json` must describe every registered scenario and golden;
- `fault_injection.py` is test-only and production code must not import it.

- [ ] **Step 5: Run focused verification**

```bash
python scripts/tests/test_architecture.py
python scripts/tests/test_refactor_completion.py
python scripts/tests/test_fault_injection.py
python scripts/tests/test_differential_harness.py
python scripts/tests/differential/runner.py --implementation-root .
```

Expected: all pass and differential runner emits no output.

- [ ] **Step 6: Commit Task 7**

```bash
git add scripts/selftest.py scripts/tests/test_architecture.py \
  docs/refactor-architecture.md
git commit -m "test: integrate stage zero safety gates"
```

### Task 8: Full Stage-0 verification and review

**Files:**
- No planned source changes

**Interfaces:**
- Verifies the complete Stage-0 branch as an independently reviewable delivery.

- [ ] **Step 1: Run whitespace and repository checks**

```bash
git diff --check main...HEAD
git status --short
```

Expected: no whitespace errors; only intended committed changes.

- [ ] **Step 2: Run the full release selftest**

```bash
python scripts/selftest.py
```

Expected: exit `0` and final line `全部通过 ✅`.

- [ ] **Step 3: Run the complete differential comparison again**

```bash
python scripts/tests/differential/runner.py --implementation-root .
```

Expected: exit `0`, no output.

- [ ] **Step 4: Run ResourceWarning-sensitive State/Checkpoint suites**

```bash
python -W error::ResourceWarning scripts/tests/test_state_core.py
python -W error::ResourceWarning scripts/tests/test_checkpoints.py
```

Expected: both pass with no `ResourceWarning`.

- [ ] **Step 5: Request code review**

Review range: `main...HEAD`.

Review requirements:

- no product module changed;
- every Phase-9 snapshot remains identical;
- every scenario has coverage metadata;
- fault injection exercises real StateStore behavior;
- final targets cannot be silently relaxed;
- no Critical or Important finding remains.

- [ ] **Step 6: Fix any review findings with TDD**

For each valid finding, add or adjust the failing test first, verify RED, make
the smallest fix, verify GREEN, and commit separately.

- [ ] **Step 7: Repeat final verification**

Repeat Steps 1–4 after the last review fix. Do not claim Stage 0 complete using
an earlier test run.

- [ ] **Step 8: Record Stage-0 completion**

Update the working plan status only after every command above is green. Keep the
branch local and proceed to the Stage-1 Evidence design; do not merge or push
without authorization.
