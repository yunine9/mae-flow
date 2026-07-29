# Mae-Flow Refactor Findings Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close MF-RF-001, MF-RF-002, and MF-RF-003 with isolated regression tests and no unrelated observable behavior changes.

**Architecture:** Managed file I/O becomes shared infrastructure used by CLI and Hook adapters. Workflow metadata declares dynamic and compatibility entries for static graph validation. Git add intent reuses the existing combined-short-option parser already used by commit intent.

**Tech Stack:** Python 3.9 standard library, `unittest`, AST architecture checks, Git CLI, Mae-Flow differential harness.

## Global Constraints

- Fixed behavior baseline remains `d5e7d7b2cb5d3def06d21df79fb3069efea94f16`.
- Windows/Git Bash encoding, path, lock, and file-release semantics remain first-class.
- Every production change requires a test observed RED before implementation.
- Only the combined Git add flag scenario may intentionally differ from phase 8 behavior.
- Existing compatibility bridges remain unless a test proves they are unused.
- No merge and no push.

---

### Task 1: Managed Runtime File I/O

**Files:**
- Create: `scripts/mae_flow_core/file_io.py`
- Create: `scripts/tests/test_file_io.py`
- Modify: `scripts/tests/architecture_rules.py`
- Modify: `scripts/tests/test_architecture.py`
- Modify: `scripts/tests/test_checkpoints.py`
- Modify: `scripts/mae-flow.py`
- Modify: `hooks/dispatch.py`
- Modify: `scripts/comet_compat.py`
- Modify: `scripts/statusline.py`
- Modify: `scripts/selftest.py`

**Interfaces:**
- Produces: `read_text(path, encoding="utf-8", errors=None, limit=-1) -> str`
- Produces: `read_bytes(path, limit=-1) -> bytes`
- Produces: `read_lines(path, encoding="utf-8", errors=None) -> list[str]`
- Produces: `load_json(path, encoding="utf-8", errors=None) -> object`
- Produces: `write_text(path, text, encoding="utf-8", errors=None, newline=None, mode="w") -> int`
- Produces: `unmanaged_runtime_open_violations(root) -> list[str]`

- [ ] **Step 1: Write failing managed-I/O tests**

Add real temporary-file tests:

```python
def test_read_write_and_json_helpers_close_their_streams(self):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        write_text(self.text_path, "一\n", newline="\n")
        write_text(self.text_path, "二\n", newline="\n", mode="a")
        self.assertEqual("一\n二\n", read_text(self.text_path))
        self.assertEqual(["一\n", "二\n"], read_lines(self.text_path))
        self.assertEqual("一\n二\n".encode("utf-8"), read_bytes(self.text_path))
        self.assertEqual({"值": 1}, load_json(self.json_path))
        gc.collect()
    self.assertEqual([], [
        item for item in caught
        if issubclass(item.category, ResourceWarning)
    ])
```

- [ ] **Step 2: Run the helper test and verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest scripts.tests.test_file_io
```

Expected: import failure for missing `mae_flow_core.file_io`.

- [ ] **Step 3: Implement the minimal managed-I/O module**

Each helper must use `with open(...) as stream`. `load_json()` must call
`json.load(stream)` so JSON decode exceptions and numeric behavior remain unchanged.

- [ ] **Step 4: Run the helper test and verify GREEN**

Run the command from Step 2. Expected: all tests pass with no warnings.

- [ ] **Step 5: Add failing runtime lifecycle gates**

Add an AST rule that scans these production entrypoints:

```python
RUNTIME_ENTRYPOINTS = (
    "scripts/mae-flow.py",
    "hooks/dispatch.py",
    "scripts/comet_compat.py",
    "scripts/statusline.py",
)
```

It must report every builtin `open()` not owned by a `with` context. Add an
integration test that launches the three warning-producing Checkpoint cases with
`-W always::ResourceWarning` and asserts neither stdout nor stderr contains
`ResourceWarning`.

- [ ] **Step 6: Run lifecycle gates and verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  scripts.tests.test_architecture \
  scripts.tests.test_file_io
```

Expected: unmanaged runtime opens are reported and the Checkpoint subprocess emits
warnings from `.tokens`, `.usermsg`, step Markdown, and its module-level flow load.

- [ ] **Step 7: Migrate production runtime reads and writes**

Replace unmanaged reads with `read_text`, `read_bytes`, `read_lines`, or `load_json`;
replace unmanaged immediate writes/appends with `write_text`. Keep explicit
context-manager operations unchanged. Convert the Checkpoint module-level
`json.load(open(...))` fixture to a context manager.

- [ ] **Step 8: Verify lifecycle GREEN and regressions**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  scripts.tests.test_file_io \
  scripts.tests.test_architecture \
  scripts.tests.test_checkpoints
```

Expected: all tests pass, no `ResourceWarning`, and the architecture rule reports
zero unmanaged production opens.

- [ ] **Step 9: Commit**

```bash
git add scripts/mae_flow_core/file_io.py scripts/tests/test_file_io.py \
  scripts/tests/architecture_rules.py scripts/tests/test_architecture.py \
  scripts/tests/test_checkpoints.py scripts/mae-flow.py hooks/dispatch.py \
  scripts/comet_compat.py scripts/statusline.py scripts/selftest.py
git commit -m "fix: close unmanaged runtime file handles"
```

### Task 2: Declared Dynamic Workflow Graph

**Files:**
- Modify: `scripts/mae_flow_core/workflow/transitions.py`
- Modify: `scripts/mae_flow_core/workflow/definition.py`
- Modify: `scripts/tests/test_workflow_definition.py`
- Modify: `flow/flow.json`
- Modify: `scripts/selftest.py`

**Interfaces:**
- Extends: `transition_targets(step: dict) -> tuple`
- Produces: `workflow_graph_errors(definition: dict) -> list[str]`

- [ ] **Step 1: Write failing dynamic-edge tests**

Add literal tests proving:

```python
self.assertEqual(
    ("normal", "compile", "recompile", "morning"),
    transition_targets({
        "next": "normal",
        "source_change_next": "compile",
        "source_change_recheck": "recompile",
        "dynamic_next": ["morning", "normal"],
    }),
)
```

Add graph fixtures where an undeclared isolated step reports
`unreachable step: orphan`, a named compatibility entry is accepted, and an unknown
compatibility entry reports an error. Assert the repository graph has no errors.

- [ ] **Step 2: Run and verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  scripts.tests.test_workflow_definition
```

Expected: dynamic targets are absent and `workflow_graph_errors` cannot be imported.

- [ ] **Step 3: Implement graph declarations**

Extend target enumeration with `source_change_next`, `source_change_recheck`, and
`dynamic_next`, preserving first occurrence order. Implement breadth-first
reachability from `start` plus `compatibility_entries`, validating all declared
entries and targets.

Update `flow.json`:

```json
"compatibility_entries": ["rf_verify"]
```

and on `push`:

```json
"dynamic_next": ["moonlight_review"]
```

- [ ] **Step 4: Connect selftest and verify GREEN**

Make selftest combine `definition_errors()` and `workflow_graph_errors()`. Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  scripts.tests.test_workflow_definition \
  scripts.tests.test_architecture
```

Expected: all tests pass and the repository graph has zero unregistered entries.

- [ ] **Step 5: Commit**

```bash
git add scripts/mae_flow_core/workflow/transitions.py \
  scripts/mae_flow_core/workflow/definition.py \
  scripts/tests/test_workflow_definition.py flow/flow.json scripts/selftest.py
git commit -m "fix: declare dynamic workflow entries"
```

### Task 3: Combined Git Add Flags

**Files:**
- Modify: `scripts/mae_flow_core/foundation/git_intent.py`
- Modify: `scripts/tests/test_task_scope.py`
- Modify: `scripts/tests/differential/scenarios.py`
- Modify: `scripts/tests/differential/runner.py`
- Create: `scripts/tests/differential/goldens/phase9.json`

**Interfaces:**
- Corrects: `git_add_intent(tokens: list[str]) -> dict`

- [ ] **Step 1: Write failing pure and adapter tests**

Extend the literal Git intent matrix:

```python
(
    "git add -fu",
    [{
        "pathspecs": ["."],
        "force": True,
        "tracked_only": True,
        "all": False,
    }],
)
```

Also cover `-uf -- src/a.cpp` and `-Af`. Assert both the shared parser and the
CLI compatibility bridge return the literal expectations.

- [ ] **Step 2: Run and verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  scripts.tests.test_task_scope.TaskScopeTests.test_shared_git_intent_matrix
```

Expected: combined flags report `force=False`, `tracked_only=False`, and no default
pathspec.

- [ ] **Step 3: Implement minimal flag expansion**

In `git_add_intent()` compute `short_flags = short_option_flags(tokens)` and use
membership of `f`, `u`, and uppercase `A`, while retaining long-option checks.

- [ ] **Step 4: Run pure and Gate regressions**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  scripts.tests.test_task_scope \
  scripts.tests.test_guard_intent
```

Expected: all tests pass.

- [ ] **Step 5: Add approved behavior differential**

Add a deterministic active-Gate scenario using `git add -fu && git commit ...`.
Generate phase 9 from the corrected implementation, then compare phase 8 and phase 9
JSON: existing scenario values must be identical and only the new scenario key may
be added. Verify the fixed baseline fails the new scenario while the current
implementation matches phase 9.

- [ ] **Step 6: Commit**

```bash
git add scripts/mae_flow_core/foundation/git_intent.py \
  scripts/tests/test_task_scope.py scripts/tests/differential/scenarios.py \
  scripts/tests/differential/runner.py \
  scripts/tests/differential/goldens/phase9.json
git commit -m "fix: parse combined git add flags"
```

### Task 4: Findings and Final Verification

**Files:**
- Modify: `docs/superpowers/mae-flow-refactor-findings.md`
- Modify: `docs/refactor-architecture.md`
- Modify: `scripts/tests/architecture_baseline.json` only if refactoring reduced a measured limit

**Interfaces:**
- Closes: MF-RF-001, MF-RF-002, MF-RF-003

- [ ] **Step 1: Update findings with test evidence and commits**

Mark each item resolved, retain its original reproduction, and record the regression
test and behavior-change boundary. Keep MF-RF-004 resolved.

- [ ] **Step 2: Run complete verification**

Run:

```bash
git diff --check
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts/tests -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 python3 scripts/selftest.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/differential/runner.py \
  --implementation-root . \
  --goldens scripts/tests/differential/goldens/phase9.json
```

Expected: every command exits 0, unittest output contains no `ResourceWarning`, and
the differential emits no output.

- [ ] **Step 3: Review and commit closeout**

Review all changes against the design, confirm the worktree contains no unrelated
files, then commit:

```bash
git add docs/superpowers/mae-flow-refactor-findings.md \
  docs/refactor-architecture.md scripts/tests/architecture_baseline.json
git commit -m "docs: close refactor findings"
```
