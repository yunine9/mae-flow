# Mae-Flow Advancement Extraction Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans
> to implement this plan task-by-task. Do not use subagents for this phase.

**Goal:** 在不改变任何外部行为和副作用顺序的前提下，把 `advance()` 的动态路由规则迁入
独立、惰性、无副作用的 Workflow 推进策略。

**Architecture:** `scripts/mae_flow_core/workflow/advancement.py` 只读取 flow/state 并逐个
产出 audit/target 事件；`scripts/mae-flow.py` 保留 review、Git、时间、状态保存、
Moonlight 报告和输出。事件惰性消费保证 audit 的时间采集和异常前内存变更顺序与旧实现
一致。

**Tech Stack:** Python 3.8+ 标准库、`unittest`、AST 架构检查、Git CLI、现有 Mae-Flow
selftest 和固定基线差分 harness。

## Global Constraints

- 固定行为基线是 `d5e7d7b2cb5d3def06d21df79fb3069efea94f16`。
- Phase 2 前置提交是 `0a27a287410a8ffbc69871dcf4f0e8c9e10e41db`。
- 生产运行时零新增依赖。
- CLI、Hook、状态 JSON、sidecar、stdout、stderr、退出码、Git 和文件副作用必须兼容。
- audit 文案、字段、顺序和逐条时间采集不得改变。
- `advance()` 的 pre-effect 和 post-effect 不迁移。
- 疑似 Bug 只进入 findings ledger，不混入结构重构。
- 新生产模块不超过 500 行，Workflow 普通函数圈复杂度不超过 15。
- 每个新增生产边界先观察对应测试 RED，再写最小实现。
- 每个任务独立提交。
- 不创建子 Agent；不合并主分支；不推送远端。

---

## File Map

**Create**

- `scripts/mae_flow_core/workflow/advancement.py`：纯推进事件流。
- `scripts/tests/test_workflow_advancement.py`：纯策略和适配器行为测试。
- `scripts/tests/differential/goldens/phase3.json`：包含真实推进场景的固定基线。

**Modify**

- `scripts/mae-flow.py`：导入推进策略，消费事件流，删除重复路由。
- `scripts/tests/architecture_rules.py`：Workflow 函数复杂度和指定函数复杂度检查。
- `scripts/tests/test_architecture.py`：复杂度门禁测试。
- `scripts/tests/architecture_baseline.json`：收紧单体行数并登记 `advance` 上限。
- `scripts/tests/differential/scenarios.py`：新增确定时间的普通 `done` 场景。
- `scripts/tests/differential/runner.py`：默认 golden 切换到 phase 3。
- `scripts/tests/test_differential_harness.py`：验证真实推进与固定基线一致。
- `scripts/selftest.py`：接入新模块和新测试。

---

### Task 1: Pure Advancement Event Stream

**Files:**

- Create: `scripts/tests/test_workflow_advancement.py`
- Create: `scripts/mae_flow_core/workflow/advancement.py`

**Interfaces:**

- Consumes: `workflow.transitions.next_step(step, state, choice_override="")`
- Produces: `TransitionEvent(kind, step, result="", note="")`
- Produces: `TransitionResolutionError(step_id)`
- Produces: `transition_events(flow, state, step_id, step) -> iterator`
- Produces: `PACE_STEPS`

- [ ] **Step 1: Write failing pure-policy tests**

Create `scripts/tests/test_workflow_advancement.py`. Use literal flows and literal expected
`TransitionEvent` lists. Each test must name the incorrect branch it catches:

```python
def test_plain_transition_emits_only_final_target(self):
    self.assertEqual(
        [TransitionEvent("target", "verify")],
        list(transition_events(
            {"steps": {"build": {"next": "verify"}}},
            {"choices": {}},
            "build",
            {"next": "verify"},
        )),
    )

def test_legacy_state_bypasses_new_pace_node(self):
    flow = {
        "steps": {
            "open": {"next": "tw_pace"},
            "tw_pace": {
                "choice_key": "development_pace",
                "next": {"continuous": "change"},
            },
            "change": {"next": "end"},
        },
    }
    self.assertEqual(
        [
            TransitionEvent(
                "audit",
                "tw_pace",
                "legacy:skipped-development-pace",
                "旧版在途状态没有检查点协议标记，保持升级前路径",
            ),
            TransitionEvent("target", "change"),
        ],
        list(transition_events(
            flow, {"choices": {}}, "open", flow["steps"]["open"])),
    )
```

Add literal cases for:

- legacy `delivery_review` bypass;
- active staged and continuous Checkpoint replacement of legacy reviews;
- chained Moonlight human-review bypass;
- Moonlight bypass cycle stopping at the repeated target;
- Moonlight `archive_confirm` deferral;
- Moonlight `push` target override;
- malformed Moonlight bypass raising `TransitionResolutionError` with the exact `step_id`;
- `copy.deepcopy(flow/state)` equality after successful and failing iteration.

For the malformed chained case, consume one valid audit before the exception and assert the yielded audit
literally; this protects lazy ordering rather than just the final error.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_workflow_advancement.py
```

Expected: import failure because `workflow.advancement` does not exist.

- [ ] **Step 3: Implement the minimal pure event stream**

Create `advancement.py` using `dataclasses.dataclass(frozen=True)`:

```python
@dataclass(frozen=True)
class TransitionEvent:
    kind: str
    step: object
    result: str = ""
    note: str = ""


class TransitionResolutionError(Exception):
    def __init__(self, step_id):
        super().__init__(step_id)
        self.step_id = step_id
```

Implement private read-only predicates for Moonlight enabled, protocol enabled and version-1
`development_review`. Implement `transition_events()` in the exact order of the old routing block:

1. initial `next_step`;
2. legacy pace;
3. legacy final review;
4. active Checkpoint legacy-review loop;
5. Moonlight `skip_in_moonlight` loop;
6. Moonlight archive deferral;
7. Moonlight push override;
8. exactly one final target event.

Do not import `time`, `os`, `subprocess` or the monolith. Do not mutate flow/state.

- [ ] **Step 4: Run focused and neighboring tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_workflow_advancement.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_workflow_definition.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_checkpoints.py
```

Expected: all exit 0.

- [ ] **Step 5: Mutation review**

Mentally or temporarily mutate each branch:

- remove one audit;
- choose the wrong Checkpoint note;
- remove Moonlight cycle tracking;
- return the unresolved node instead of raising;
- mutate `state["choices"]`.

Confirm at least one focused test fails for each realistic mutation.

- [ ] **Step 6: Commit**

```bash
git add scripts/mae_flow_core/workflow/advancement.py \
  scripts/tests/test_workflow_advancement.py
git diff --cached --check
git commit -m "refactor: add pure workflow advancement policy"
```

---

### Task 2: Convert `advance()` into the Side-Effect Adapter

**Files:**

- Modify: `scripts/tests/test_workflow_advancement.py`
- Modify: `scripts/mae-flow.py`

**Interfaces:**

- Consumes: `workflow_advancement.transition_events(...)`
- Preserves: `advance(flow, st, sid, step, tag, note="")`

- [ ] **Step 1: Add a failing adapter-boundary test**

Dynamic-load the real `scripts/mae-flow.py` in the test. In a temporary directory, run the real
`advance()` with real state persistence and captured stdout. Temporarily replace only
`workflow_advancement.transition_events` with a generator that yields:

```python
TransitionEvent(
    "audit",
    "compat",
    "compat:skipped",
    "literal audit",
)
TransitionEvent("target", "end")
```

Give the source step a different real `next`, then assert observable state:

- completion history is first;
- injected audit is second with all literal fields and a timestamp;
- persisted `current == "end"`;
- `step_heads["end"]` exists;
- stdout contains the original `sid tag → 进入 end` line.

Do not assert mock call counts. This test protects that the adapter consumes the strategy rather than
retaining a second routing implementation.

- [ ] **Step 2: Run the adapter test and verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  scripts/tests/test_workflow_advancement.py \
  WorkflowAdvanceAdapterTests.test_advance_consumes_policy_events
```

Expected: failure because the monolith does not expose/use `workflow_advancement`.

- [ ] **Step 3: Migrate the routing block**

In `scripts/mae-flow.py`:

1. import `workflow.advancement as workflow_advancement`;
2. assign `PACE_STEPS = workflow_advancement.PACE_STEPS`;
3. delete the local `LEGACY_CODE_REVIEW_STEPS`;
4. replace the routing block from initial `_next_from_step()` through the Moonlight push target override
   with event consumption;
5. append each audit using the existing literal shape and a fresh `time.strftime`;
6. convert `TransitionResolutionError` to the exact old `die(..., 2)` message;
7. keep `_moonlight_resolve_kind`, pushed time/HEAD, `current`, `step_heads`, save, report and output in
   their existing order after target resolution.

The adapter must not reconstruct pace, Checkpoint, Moonlight bypass or archive routing conditions.

- [ ] **Step 4: Run focused tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_workflow_advancement.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_checkpoints.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_workflow_definition.py
```

Expected: all exit 0.

- [ ] **Step 5: Compare the extracted function manually**

Use `git diff 0a27a287 -- scripts/mae-flow.py` and verify:

- pre-effects before `st.pop("unlock", None)` are unchanged;
- completion history append is unchanged;
- post-effects beginning with Moonlight push metadata are unchanged except that `nxt` comes from target;
- all deleted audit strings occur exactly once in `advancement.py`;
- no product behavior or error wording changed.

- [ ] **Step 6: Commit**

```bash
git add scripts/mae-flow.py scripts/tests/test_workflow_advancement.py
git diff --cached --check
git commit -m "refactor: delegate workflow advancement routing"
```

---

### Task 3: Enforce the New Complexity Boundary

**Files:**

- Modify: `scripts/tests/architecture_rules.py`
- Modify: `scripts/tests/test_architecture.py`
- Modify: `scripts/tests/architecture_baseline.json`

**Interfaces:**

- Produces: `function_complexity(path, function_name) -> int`
- Produces: `workflow_complexity_violations(root, maximum=15) -> list[str]`

- [ ] **Step 1: Add failing architecture tests**

Add literal fixture tests showing:

- a Workflow function with sixteen decision points is reported;
- a small generator with branches is accepted;
- repository Workflow modules have no violations;
- the configured `advance` complexity maximum is enforced from
  `architecture_baseline.json`.

Use AST nodes, not source grep. Count `if`, `for`, `while`, exception handlers, conditional expressions,
comprehension filters and boolean decision operands consistently.

- [ ] **Step 2: Run and verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_architecture.py
```

Expected: import failure for the new complexity helpers.

- [ ] **Step 3: Implement the minimal AST checks**

Implement `function_complexity()` and `workflow_complexity_violations()`. Restrict the repository-wide
policy scan to `scripts/mae_flow_core/workflow/**/*.py`.

After measuring the migrated `advance()`, add an explicit maximum to the baseline JSON and reduce
`scripts/mae-flow.py` `max_lines` to its current post-extraction line count. Do not loosen any existing
maximum.

- [ ] **Step 4: Run architecture and policy tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_architecture.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_workflow_advancement.py
```

Expected: both exit 0.

- [ ] **Step 5: Commit**

```bash
git add scripts/tests/architecture_rules.py \
  scripts/tests/test_architecture.py \
  scripts/tests/architecture_baseline.json
git diff --cached --check
git commit -m "test: enforce advancement complexity boundary"
```

---

### Task 4: Add a Fixed-Baseline `done` Differential Scenario

**Files:**

- Modify: `scripts/tests/differential/scenarios.py`
- Modify: `scripts/tests/test_differential_harness.py`
- Create: `scripts/tests/differential/goldens/phase3.json`
- Modify: `scripts/tests/differential/runner.py`

- [ ] **Step 1: Add the scenario and failing golden assertion**

Add `ordinary_advance`:

1. prepare the deterministic Git repository;
2. write a complete state at `current="rf_verify"` with workflow `tweak`, empty branch constraint and fixed
   timestamps;
3. invoke the real script through a small Python `runpy` wrapper that fixes `time.strftime` to
   `"2026-07-29 10:00:00"` and then executes public argv `done`;
4. capture the real persisted state, files, stdout, stderr, exit code and Git snapshot.

Add a test loading `phase3.json` and asserting `ordinary_advance`.

- [ ] **Step 2: Run and verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_differential_harness.py
```

Expected: missing `phase3.json` or missing `ordinary_advance` golden.

- [ ] **Step 3: Generate phase 3 golden from the fixed behavior baseline**

Create a temporary detached worktree at
`d5e7d7b2cb5d3def06d21df79fb3069efea94f16`, then run the current differential runner with that directory
as `--implementation-root` and `phase3.json` as `--write-goldens`.

Verify the new golden records:

- return code 0;
- `current == "rf_compile"`;
- one `rf_verify / done` history record;
- original transition stdout;
- deterministic state-file hash.

Remove only the temporary detached worktree after successful generation.

- [ ] **Step 4: Switch the default and compare the refactor**

Update `DEFAULT_GOLDENS` to `phase3.json`, then run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_differential_harness.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/differential/runner.py \
  --implementation-root .
```

Expected: both exit 0 with no diff output.

- [ ] **Step 5: Commit**

```bash
git add scripts/tests/differential/scenarios.py \
  scripts/tests/differential/runner.py \
  scripts/tests/test_differential_harness.py \
  scripts/tests/differential/goldens/phase3.json
git diff --cached --check
git commit -m "test: lock advancement behavior to fixed baseline"
```

---

### Task 5: Integrate the Phase 3 Safety Suite

**Files:**

- Modify: `scripts/selftest.py`

- [ ] **Step 1: Add a failing selftest integration assertion**

Extend `ArchitectureTests.test_selftest_runs_refactor_safety_suites` so it also requires
`test_workflow_advancement.py`.

- [ ] **Step 2: Run and verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_architecture.py
```

Expected: failure because selftest does not reference the new suite.

- [ ] **Step 3: Wire the new module and test into selftest**

Add both new Python paths to the syntax list. Run `test_workflow_advancement.py` explicitly next to the
existing Workflow definition suite and report it as `Workflow 推进策略与适配器回归`.

- [ ] **Step 4: Run focused selftest integration**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_architecture.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/selftest.py
```

Expected: both exit 0 and selftest ends with `全部通过`.

- [ ] **Step 5: Commit**

```bash
git add scripts/selftest.py scripts/tests/test_architecture.py
git diff --cached --check
git commit -m "test: integrate phase 3 advancement safety suite"
```

---

### Task 6: Final Verification and Review

- [ ] **Step 1: Run all unit tests**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s scripts/tests -p 'test_*.py'
```

Expected: all tests pass.

- [ ] **Step 2: Run the product selftest**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/selftest.py
```

Expected: exit 0 and `全部通过`.

- [ ] **Step 3: Run full fixed-baseline differential**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/differential/runner.py \
  --implementation-root .
```

Expected: exit 0 and no diff output.

- [ ] **Step 4: Run architecture and focused progression tests**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_architecture.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_workflow_advancement.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/test_checkpoints.py
```

Expected: all exit 0.

- [ ] **Step 5: Review the complete phase diff**

Run:

```bash
git diff --check 0a27a287..HEAD
git diff --stat 0a27a287..HEAD
git log --oneline 0a27a287..HEAD
git status --short --branch
```

Review every production hunk against the phase 2 `advance()` and confirm:

- no pre/post side effect moved across another side effect;
- all routing strings and conditions moved exactly once;
- findings ledger contains any newly discovered product issue;
- no unrelated user changes entered the branch;
- worktree is clean.

- [ ] **Step 6: Freeze the result**

Record the final commit hash and verification evidence. Do not merge, rebase, push or delete the worktree
without explicit user authorization.
