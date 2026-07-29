# Mae-Flow Workflow Extraction Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变任何外部行为的前提下，把流程定义加载、静态校验和纯下一步解析迁入独立 Workflow 策略层。

**Architecture:** 保留 `scripts/mae-flow.py` 的四个既有私有入口作为兼容适配器，新规则进入 `scripts/mae_flow_core/workflow/`。运行时仍使用原始字典，不新增校验拒绝路径；静态校验只接入 selftest，差分测试用固定基线锁定 `steps` 的逐字节输出。

**Tech Stack:** Python 3.8+ 标准库、`unittest`、AST 架构检查、Git CLI、现有 Mae-Flow selftest。

## Global Constraints

- 生产运行时零新增依赖。
- CLI、Hook、状态 JSON、sidecar、stdout、stderr、退出码和 Git/文件副作用必须兼容固定基线 `d5e7d7b2cb5d3def06d21df79fb3069efea94f16`。
- Windows/Git Bash 是一等环境；不得引入仅 POSIX 可用的路径或进程语义。
- 运行时加载 `flow.json` 时不得新增静态校验失败路径；额外校验只在 selftest 中执行。
- 疑似 Bug 只进入 findings ledger，不混入结构迁移提交。
- 新生产模块不超过 500 行，普通函数圈复杂度不超过 15。
- 每个生产改动必须先观察对应测试 RED，再写最小实现。
- 每个任务独立提交；`scripts/mae-flow.py` 的兼容包装不得保留第二份规则。
- 不创建或使用子 Agent；用户已授权当前会话内联执行。

---

## File Map

**Create**

- `scripts/mae_flow_core/workflow/__init__.py`：Workflow 包边界。
- `scripts/mae_flow_core/workflow/transitions.py`：静态目标、下一步和工作流链纯函数。
- `scripts/mae_flow_core/workflow/definition.py`：JSON 加载和静态结构校验。
- `scripts/tests/test_workflow_definition.py`：纯策略、定义校验和旧包装委托测试。
- `scripts/tests/differential/goldens/phase2.json`：包含第二阶段 `steps` 场景的固定基线。

**Modify**

- `scripts/mae-flow.py`：四个既有入口改为 Workflow 模块薄委托。
- `scripts/selftest.py`：语法检查、新单测和流程定义校验接入。
- `scripts/tests/architecture_rules.py`：Workflow 策略副作用与新模块行数门禁。
- `scripts/tests/test_architecture.py`：新增策略层门禁的 RED/GREEN 用例。
- `scripts/tests/differential/scenarios.py`：新增无状态 `steps` 黑盒场景。
- `scripts/tests/differential/runner.py`：默认使用 phase2 golden。
- `scripts/tests/test_differential_harness.py`：验证新增场景与固定基线一致。

---

### Task 1: Pure Workflow Transition Policy

**Files:**

- Create: `scripts/mae_flow_core/workflow/__init__.py`
- Create: `scripts/mae_flow_core/workflow/transitions.py`
- Create: `scripts/tests/test_workflow_definition.py`

**Interfaces:**

- Produces: `transition_targets(step: dict) -> tuple`
- Produces: `next_step(step: dict, state: dict, choice_override: str = "") -> object`
- Produces: `resolved_next(flow: dict, state: dict, step_id: str) -> object`
- Produces: `workflow_chain(flow: dict, workflow: str) -> list`

- [ ] **Step 1: Write failing transition tests**

Create `scripts/tests/test_workflow_definition.py` with imports from
`mae_flow_core.workflow.transitions` and tests using hand-written fixtures:

```python
class WorkflowTransitionTests(unittest.TestCase):
    def test_transition_targets_preserves_declared_order(self):
        self.assertEqual(
            ("build", "skip"),
            transition_targets({"next": {"yes": "build", "no": "skip"}}),
        )

    def test_next_step_resolves_plain_next_and_state_choices(self):
        self.assertEqual(
            "build",
            next_step({"next": "build"}, {"choices": {}}),
        )
        self.assertEqual(
            "hotfix-open",
            next_step(
                {
                    "next_by": "workflow",
                    "next": {
                        "full": "design",
                        "hotfix": "hotfix-open",
                    },
                },
                {"choices": {"workflow": "hotfix"}},
            ),
        )
        self.assertEqual(
            "revise",
            next_step(
                {
                    "choice_key": "review",
                    "next": {"continue": "verify", "revise": "revise"},
                },
                {"choices": {"review": "continue"}},
                "revise",
            ),
        )

    def test_next_step_returns_none_for_missing_or_malformed_choice(self):
        step = {
            "choice_key": "review",
            "next": {"continue": "verify"},
        }
        self.assertIsNone(next_step(step, {"choices": {}}))
        self.assertIsNone(next_step(step, {"choices": []}))

    def test_resolved_next_uses_empty_step_for_unknown_history_entry(self):
        self.assertIsNone(
            resolved_next(
                {"steps": {"build": {"next": "verify"}}},
                {"choices": {}},
                "missing",
            )
        )

    def test_workflow_chain_selects_workflow_and_complete_optional_branch(self):
        flow = {
            "start": "start",
            "steps": {
                "start": {
                    "next_by": "workflow",
                    "next": {"full": "ask", "hotfix": "fix"},
                },
                "ask": {"next": {"yes": "design", "no": "fix"}},
                "design": {"next": "end"},
                "fix": {"next": "end"},
                "end": {"terminal": True},
            },
        }
        self.assertEqual(
            ["start", "ask", "design", "end"],
            workflow_chain(flow, "full"),
        )
        self.assertEqual(
            ["start", "fix", "end"],
            workflow_chain(flow, "hotfix"),
        )

    def test_workflow_chain_stops_at_first_cycle(self):
        flow = {
            "start": "one",
            "steps": {
                "one": {"next": "two"},
                "two": {"next": "one"},
            },
        }
        self.assertEqual(["one", "two"], workflow_chain(flow, "full"))
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_workflow_definition.py
```

Expected: import failure because `mae_flow_core.workflow` does not exist.

- [ ] **Step 3: Implement the minimal pure policy**

Create `scripts/mae_flow_core/workflow/__init__.py` with only a package
docstring. Create `transitions.py` with:

```python
"""Pure transition policy for Mae-Flow workflow definitions."""


def transition_targets(step):
    nxt = step.get("next")
    if isinstance(nxt, dict):
        return tuple(nxt.values())
    return (nxt,) if nxt else ()


def next_step(step, state, choice_override=""):
    nxt = step.get("next")
    try:
        if step.get("next_by"):
            return nxt[state.get("choices", {}).get(step["next_by"])]
        if isinstance(nxt, dict):
            choice = (
                choice_override
                or state.get("choices", {}).get(step.get("choice_key"))
            )
            return nxt[choice]
    except Exception:
        return None
    return nxt


def resolved_next(flow, state, step_id):
    step = flow.get("steps", {}).get(step_id, {})
    return next_step(step, state)


def workflow_chain(flow, workflow):
    chain = []
    step_id = flow["start"]
    seen = set()
    while step_id and step_id not in seen:
        seen.add(step_id)
        chain.append(step_id)
        step = flow["steps"][step_id]
        nxt = step.get("next")
        if step.get("next_by"):
            nxt = nxt.get(workflow) if isinstance(nxt, dict) else nxt
        elif isinstance(nxt, dict):
            nxt = nxt.get("yes") or next(iter(nxt.values()))
        step_id = nxt
    return chain
```

- [ ] **Step 4: Run focused and neighboring tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_workflow_definition.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_checkpoints.py
```

Expected: both commands exit 0.

- [ ] **Step 5: Commit**

```bash
git add scripts/mae_flow_core/workflow scripts/tests/test_workflow_definition.py
git diff --cached --check
git commit -m "refactor: add pure workflow transitions"
```

---

### Task 2: Workflow Definition Loading and Static Validation

**Files:**

- Create: `scripts/mae_flow_core/workflow/definition.py`
- Modify: `scripts/tests/test_workflow_definition.py`

**Interfaces:**

- Consumes: `transition_targets(step) -> tuple`
- Produces: `load_definition(path: str) -> dict`
- Produces: `definition_errors(definition: object, steps_dir: str = None) -> list[str]`

- [ ] **Step 1: Add failing definition tests**

Add tests with literal expected errors:

```python
class WorkflowDefinitionTests(unittest.TestCase):
    def test_load_definition_preserves_unknown_fields(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "flow.json")
            with open(path, "w", encoding="utf-8") as stream:
                json.dump(
                    {
                        "start": "end",
                        "steps": {"end": {"terminal": True}},
                        "future_field": {"keep": 7},
                    },
                    stream,
                )
            self.assertEqual(
                {"keep": 7},
                load_definition(path)["future_field"],
            )

    def test_definition_errors_reports_unknown_start_and_edge(self):
        self.assertEqual(
            [
                "start references unknown step: missing",
                "step begin references unknown step: gone",
            ],
            definition_errors(
                {
                    "start": "missing",
                    "steps": {
                        "begin": {"next": {"yes": "gone"}},
                        "end": {"terminal": True},
                    },
                }
            ),
        )

    def test_definition_errors_reports_missing_step_document(self):
        with tempfile.TemporaryDirectory() as steps_dir:
            self.assertEqual(
                ["step begin is missing document: begin.md"],
                definition_errors(
                    {
                        "start": "begin",
                        "steps": {
                            "begin": {"next": "end"},
                            "end": {"terminal": True},
                        },
                    },
                    steps_dir,
                ),
            )

    def test_repository_definition_is_valid(self):
        definition = load_definition(
            os.path.join(ROOT, "flow", "flow.json")
        )
        self.assertEqual(
            [],
            definition_errors(
                definition,
                os.path.join(ROOT, "flow", "steps"),
            ),
        )
```

- [ ] **Step 2: Run and verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_workflow_definition.py
```

Expected: import failure for `mae_flow_core.workflow.definition`.

- [ ] **Step 3: Implement loading and validation**

Create `definition.py`. `definition_errors` must:

1. Return `["flow root must be an object"]` for non-dict roots.
2. Return `["steps must be an object"]` when `steps` is not a dict.
3. Report an unknown `start`.
4. Report any non-dict step.
5. Report unsupported `next` types and non-string targets.
6. Report targets absent from `steps`.
7. When `steps_dir` is provided, report each nonterminal step without
   `<step_id>.md`.
8. Return a sorted list so diagnostics are deterministic.

Use `transition_targets()` rather than reimplementing edge enumeration.
Do not print, exit, mutate input, or catch `open/json.load` exceptions.

- [ ] **Step 4: Run focused tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_workflow_definition.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/mae_flow_core/workflow/definition.py scripts/tests/test_workflow_definition.py
git diff --cached --check
git commit -m "refactor: validate workflow definitions"
```

---

### Task 3: Migrate Stable Entrypoints to Thin Delegates

**Files:**

- Modify: `scripts/mae-flow.py`
- Modify: `scripts/tests/test_workflow_definition.py`

**Interfaces:**

- Consumes: all interfaces from Tasks 1 and 2.
- Preserves: `load_flow`, `_next_from_step`, `_resolved_next`,
  `_workflow_chain`.

- [ ] **Step 1: Add delegate behavior tests**

Load `scripts/mae-flow.py` with `importlib.util`. For each stable wrapper,
temporarily replace the corresponding module function with a fake that
returns a unique sentinel. Assert the wrapper returns that sentinel and the
fake receives the original arguments. Name the tests:

- `test_load_flow_delegates_to_workflow_definition`
- `test_next_from_step_delegates_to_transition_policy`
- `test_resolved_next_delegates_to_transition_policy`
- `test_workflow_chain_delegates_to_transition_policy`

These tests catch the concrete regression where rule logic remains or grows
back inside the monolith.

- [ ] **Step 2: Run and verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_workflow_definition.py
```

Expected: four delegation tests fail because the old private implementations
do not call the Workflow modules.

- [ ] **Step 3: Replace implementations with delegates**

Import modules:

```python
from mae_flow_core.workflow import definition as workflow_definition
from mae_flow_core.workflow import transitions as workflow_transitions
```

Replace bodies:

```python
def load_flow():
    return workflow_definition.load_definition(FLOW_PATH)


def _next_from_step(step, st, choice_override=""):
    return workflow_transitions.next_step(step, st, choice_override)


def _resolved_next(flow, st, sid):
    return workflow_transitions.resolved_next(flow, st, sid)


def _workflow_chain(flow, wf):
    return workflow_transitions.workflow_chain(flow, wf)
```

Keep existing function names, signatures and docstrings.

- [ ] **Step 4: Run transition, checkpoint and differential tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_workflow_definition.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_checkpoints.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/differential/runner.py --implementation-root .
```

Expected: all commands exit 0.

- [ ] **Step 5: Commit**

```bash
git add scripts/mae-flow.py scripts/tests/test_workflow_definition.py
git diff --cached --check
git commit -m "refactor: delegate workflow resolution"
```

---

### Task 4: Workflow Architecture and Selftest Gates

**Files:**

- Modify: `scripts/tests/architecture_rules.py`
- Modify: `scripts/tests/test_architecture.py`
- Modify: `scripts/selftest.py`

**Interfaces:**

- Produces: `assert_policy_dependencies(root) -> list[str]`
- Produces: `new_module_size_violations(root, maximum=500) -> list[str]`

- [ ] **Step 1: Add failing architecture tests**

Create temporary Workflow fixtures and assert:

```python
def test_workflow_rejects_aliased_process_calls(self):
    root = self._write_core_fixture(
        "workflow",
        "import subprocess as sp\nsp.run(['git', 'status'])\n",
    )
    self.assertEqual(
        [
            "scripts/mae_flow_core/workflow/fixture.py:2: "
            "forbidden call subprocess.run"
        ],
        assert_policy_dependencies(root),
    )

def test_new_core_module_rejects_more_than_500_lines(self):
    root = self._write_core_fixture(
        "workflow",
        "value = 1\n" * 501,
    )
    self.assertEqual(
        [
            "scripts/mae_flow_core/workflow/fixture.py: "
            "501 lines exceeds 500"
        ],
        new_module_size_violations(root),
    )
```

Generalize the existing fixture helper so it accepts the package directory.

- [ ] **Step 2: Run and verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_architecture.py
```

Expected: import failure or missing functions for the two new rules.

- [ ] **Step 3: Implement reusable AST and size checks**

Reuse `_import_aliases` and `_resolved_call_name`. Scan
`scripts/mae_flow_core/workflow/**/*.py` for `FORBIDDEN_CALLS`. Scan production
files under `scripts/mae_flow_core/`, excluding `__init__.py` and the explicit
pre-refactor oversized allowlist (`capabilities.py`, `lightcheck.py`,
`specengine.py`), and return deterministic line-limit diagnostics. The
allowlist only prevents this phase from absorbing old debt; no new file may be
added to it.

- [ ] **Step 4: Wire Workflow checks into selftest**

Add the three Workflow production files and
`scripts/tests/test_workflow_definition.py` to syntax checks. Run the new
test file as `Workflow 定义与转移策略回归`.

After loading `flow/flow.json`, call:

```python
from mae_flow_core.workflow.definition import definition_errors

flow_errors = definition_errors(
    flow,
    os.path.join(ROOT, "flow", "steps"),
)
check("流程定义结构有效", not flow_errors, str(flow_errors))
```

Keep all existing selftest checks and labels.

- [ ] **Step 5: Run focused gates**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_architecture.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_workflow_definition.py
```

Expected: both commands exit 0.

- [ ] **Step 6: Commit**

```bash
git add scripts/tests/architecture_rules.py scripts/tests/test_architecture.py scripts/selftest.py
git diff --cached --check
git commit -m "test: enforce workflow policy boundaries"
```

---

### Task 5: Phase 2 Public-Behavior Golden

**Files:**

- Modify: `scripts/tests/differential/scenarios.py`
- Modify: `scripts/tests/differential/runner.py`
- Modify: `scripts/tests/test_differential_harness.py`
- Create: `scripts/tests/differential/goldens/phase2.json`

**Interfaces:**

- Produces scenario: `workflow_steps`
- Preserves: phase1 golden and all existing phase1 tests.

- [ ] **Step 1: Verify baseline implementation has no product drift**

Run:

```bash
git diff --exit-code d5e7d7b2cb5d3def06d21df79fb3069efea94f16..main -- scripts hooks flow
```

Expected: exit 0. This proves the main checkout is a valid fixed-baseline
implementation for golden generation.

- [ ] **Step 2: Add the scenario and failing golden test**

The scenario prepares the deterministic repository and invokes:

```python
[
    sys.executable,
    os.path.join(implementation_root, "scripts", "mae-flow.py"),
    "steps",
]
```

It creates no state file. Register it as `workflow_steps`.

Add `test_phase2_workflow_steps_matches_fixed_baseline`, loading
`goldens/phase2.json` and comparing `workflow_steps`. Change the runner
default from `phase1.json` to `phase2.json`.

- [ ] **Step 3: Run and verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_differential_harness.py
```

Expected: failure because `phase2.json` does not exist.

- [ ] **Step 4: Generate phase2 golden from fixed baseline**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/differential/runner.py \
  --implementation-root /Users/liaoxiang/dev/comet/mae-flow \
  --write-goldens scripts/tests/differential/goldens/phase2.json
```

Review the new `workflow_steps` stdout and confirm it contains all four
workflow headings and no unexpected normalization.

- [ ] **Step 5: Compare candidate and run tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/differential/runner.py --implementation-root .
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_differential_harness.py
```

Expected: both commands exit 0.

- [ ] **Step 6: Commit**

```bash
git add scripts/tests/differential scripts/tests/test_differential_harness.py
git diff --cached --check
git commit -m "test: capture workflow behavior oracle"
```

---

### Task 6: Final Phase Verification and Findings Review

**Files:**

- Modify only if a newly reproduced pre-existing issue exists:
  `docs/superpowers/mae-flow-refactor-findings.md`

**Interfaces:**

- Consumes all prior tasks.
- Produces a clean, verified phase-2 branch.

- [ ] **Step 1: Run all unit tests**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts/tests -p 'test_*.py'
```

Expected: exit 0 with no failures.

- [ ] **Step 2: Run project selftest**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/selftest.py
```

Expected: exit 0 and final line `全部通过 ✅`.

- [ ] **Step 3: Run independent behavior and architecture gates**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/differential/runner.py --implementation-root .
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_architecture.py
python3 runtime/vendor/lizard/lizard.py scripts/mae_flow_core/workflow
```

Expected: no behavior diff, architecture tests pass, and no complexity
threshold exceeds 15.

- [ ] **Step 4: Review the complete phase diff**

```bash
git diff --check 2bca515..HEAD
git diff --stat 2bca515..HEAD
git status --short --branch
```

Confirm:

- no product behavior fixes are mixed in;
- old wrappers are thin delegates;
- no uncommitted files remain;
- findings ledger contains any newly reproduced baseline issue.

- [ ] **Step 5: Preserve the branch**

Keep `refactor/mae-flow-phase-2` and its linked worktree. Do not merge, push,
or remove the worktree without explicit user authorization.
