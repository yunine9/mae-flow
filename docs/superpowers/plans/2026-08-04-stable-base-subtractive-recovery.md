# Stable-Base Subtractive Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover Mae-Flow's production stability from `d32ccfb`, then make only the approved subtractive changes: Story replaces the heavy pre-code document chain, local work packages/domain documentation are retained, agent-return rigidity is removed, and the stable Grill/Chain/configuration/quality behavior remains intact.

**Architecture:** Treat `d32ccfb` and its 1,062-test suite as the executable baseline. Change one seam at a time behind characterization tests: project-local bootstrap, document paths, flow graph, agent lifecycle observations, delivery manifest, and Lean-state recovery. Do not import the Lean runtime or replace the legacy composition root. Every user-facing command is generated from the same parser model and parser-tested before release.

**Tech Stack:** Python 3.8+, `argparse`, JSON state files, Markdown workflow resources, CodeAgent hooks, `unittest`, Git worktrees, Windows Git Bash compatibility.

## Global Constraints

- Implement on `recovery/stable-subtractive-refactor`, based on `d32ccfb`.
- Preserve the old Chinese configuration card, old Interactive Grill, old Chain, old candidate ownership, old changed-scope Lightcheck, old CodeCheck/UT repair loops, and the synchronous compile behavior from `395d111`.
- Do not copy `lean_runtime.py`, `lean_cli.py`, `lean_hooks.py`, or the six-phase Lean state machine into the recovery branch.
- Spec and Grill artifacts live only in `.mae-flow-work/<ticket>/`; only reconciled domain documentation under `docs/specs/` is eligible for Git delivery.
- Story is the only reviewed pre-code design artifact. There is no independent Design, Test Blueprint, Roadmap, or detailed Build Plan gate.
- An agent completion is lifecycle evidence only. Never parse fixed result markers, tokens, task-card hashes, source hashes, reviewer digests, or numeric result formats.
- Preserve PreToolUse path/safety authorization. This plan relaxes subagent return validation, not source ownership or Git boundaries.
- Staged pace stops after every CP. Continuous pace stops once after all CPs. Only the user-selected configuration controls this behavior.
- A compile round is one synchronous invocation. No background job, PID polling, log tailing, `sleep`, or unchanged-input retry.
- Lightcheck remains advisory and fail-open. It scans old automatically-derived candidate scope; it never requires `--file`.
- No destructive migration: a Lean v3 state is byte-for-byte backed up before any stable-state write.
- Complete each task as a small commit after its focused tests pass. Do not combine unrelated tasks.

---

### Task 1: Lock the stable behavioral baseline

**Files:**
- Create: `scripts/tests/stable_recovery_contract.json`
- Create: `scripts/tests/test_stable_recovery_contract.py`
- Modify: `scripts/tests/selftest_suites.py`
- Modify: `scripts/selftest.py`

**Interfaces:**
- Consumes: repository resources, `flow/flow.json`, parser commands, agent names, and baseline Git metadata.
- Produces: a machine-readable allowlist of preserved behavior and approved deltas.

- [ ] **Step 1: Write the recovery contract fixture**

Add exact invariants rather than broad snapshots:

```json
{
  "baseline_commit": "d32ccfb",
  "required_agents": [
    "grill-critic-agent",
    "story-generator-agent",
    "craft-reviewer-agent",
    "cp-implementer-agent",
    "compile-agent",
    "codecheck-fix-agent",
    "ut-generator-agent"
  ],
  "planned_removed_agents": [
    "test-design-agent",
    "cp-task-analyst-agent"
  ],
  "preserved_cli_commands": [
    "lightcheck",
    "checkpoint",
    "action",
    "agent-task"
  ],
  "preserved_resources": [
    "skills/mae-flow/assets/CHAIN-TEMPLATE.md",
    "skills/mae-flow/assets/GRILL-PREP-TEMPLATE.md"
  ],
  "forbidden_runtime_modules": [
    "lean_runtime.py",
    "lean_cli.py",
    "lean_hooks.py"
  ]
}
```

- [ ] **Step 2: Write a failing contract test**

The test must read the fixture, assert required files exist, removed agents are absent, forbidden Lean modules are not imported by `scripts/mae_flow_core/cli_runtime.py`, and the parser still exposes every preserved command.

```python
class StableRecoveryContractTests(unittest.TestCase):
    def test_declared_stable_capabilities_are_present(self):
        contract = load_contract()
        self.assertEqual(parse_args(["lightcheck", "--quiet"]).cmd, "lightcheck")
        self.assertEqual(parse_args(["checkpoint", "status"]).cmd, "checkpoint")
        for resource in contract["preserved_resources"]:
            self.assertTrue((ROOT / resource).is_file())
        for agent in contract["required_agents"]:
            self.assertTrue((ROOT / "agents" / f"{agent}.md").is_file())
```

- [ ] **Step 3: Verify the characterization test is GREEN**

Run:

```bash
PYTHONPATH=scripts:scripts/tests python -m unittest -v test_stable_recovery_contract
```

Expected: all assertions pass against the untouched stable baseline. The test records the two planned removals as present-at-baseline rather than pretending the future state already exists.

- [ ] **Step 4: Register the suite without weakening old tests**

Add `test_stable_recovery_contract` to the regular self-test suite. Do not remove or rename an existing test suite to make the count pass.

- [ ] **Step 5: Record the untouched baseline result**

Run:

```bash
PYTHONPATH=scripts:scripts/tests python -m unittest discover -s scripts/tests -p 'test_*.py'
```

Expected before implementation: the original 1,062 tests plus the new characterization test all pass.

- [ ] **Step 6: Commit the characterization boundary**

```bash
git add scripts/tests/stable_recovery_contract.json scripts/tests/test_stable_recovery_contract.py scripts/tests/selftest_suites.py scripts/selftest.py
git commit -m "test: lock stable workflow recovery contract"
```

---

### Task 2: Add the project-local launcher, resources, and readable work packages

**Files:**
- Modify: `hooks/dispatch.py`
- Modify: `scripts/mae_flow_core/cli_runtime.py`
- Modify: `scripts/mae_flow_core/orchestration/documents.py`
- Create: `scripts/mae_flow_core/orchestration/work_package.py`
- Modify: `scripts/tests/test_hook_protocol.py`
- Modify: `scripts/tests/test_lean_documents.py`
- Create: `scripts/tests/test_project_resources.py`

**Interfaces:**
- `install_project_launcher(project_root: Path, plugin_root: Path) -> Path`
- `materialize_plugin_resources(project_root: Path, plugin_root: Path) -> tuple[Path, ...]`
- `resolve_ticket_segment(project_root: Path, ticket: str) -> str`
- `ensure_work_package(project_root: Path, ticket: str) -> WorkPackagePaths`

- [ ] **Step 1: Write failing launcher and resource tests**

Cover these exact behaviors:

```python
def test_launcher_uses_codeagent_plugin_root_only(self):
    launcher = install_project_launcher(self.root, self.plugin_root)
    content = launcher.read_text(encoding="utf-8")
    self.assertIn("CODEAGENT3_PLUGIN_ROOT", content)
    self.assertNotIn("CLAUDE_PLUGIN_ROOT", content)

def test_plugin_resources_are_materialized_project_locally(self):
    paths = materialize_plugin_resources(self.root, self.plugin_root)
    self.assertIn(self.root / ".mae-flow-work/plugin-resources/guidance/grill.md", paths)
```

The launcher target is `.mae-flow-work/bin/mae-flow.py`; copied resources live under `.mae-flow-work/plugin-resources/`. Use atomic replacement for both.

- [ ] **Step 2: Write failing ticket-path tests**

Assert `REQ-123` maps to `.mae-flow-work/REQ-123`, while Windows-reserved, path-separator, and case-insensitive collision cases receive an eight-character SHA-256 suffix. Store the original ticket in `.ticket-id` and reuse the directory only when the marker matches.

```python
self.assertEqual(resolve_ticket_segment(root, "REQ-123"), "REQ-123")
self.assertRegex(resolve_ticket_segment(root, "CON"), r"^CON-[0-9a-f]{8}$")
```

- [ ] **Step 3: Verify the focused tests fail**

```bash
PYTHONPATH=scripts:scripts/tests python -m unittest -v \
  test_hook_protocol test_lean_documents test_project_resources
```

Expected: launcher/resources and readable ticket assertions fail against the old layout.

- [ ] **Step 4: Port only the stable bootstrap seams**

Port the launcher/resource-copy behavior from current main into the old `hooks/dispatch.py` and legacy `cli_runtime.py`. Keep old `HookRuntimeAdapter`, old command dispatch, old config/Grill/Chain paths, and old PreToolUse authorization intact.

```python
RESOURCE_FILES = (
    "runtime/guidance/grill.md",
    "skills/mae-flow/assets/GRILL-PREP-TEMPLATE.md",
)
```

Resolve the plugin root from the running script location first and `CODEAGENT3_PLUGIN_ROOT` second. Never fall back to a Claude-named variable or `/scripts/mae-flow.py`.

- [ ] **Step 5: Implement work-package collision handling**

`ensure_work_package` must create the directory, atomically write `.ticket-id`, and return paths for `spec.md`, `grill.md`, `story.md`, `decisions.md`, and `ut-handoff.md`. It must not create a `docs/mae-flow/requirements/` durable copy.

- [ ] **Step 6: Run focused and architecture tests**

```bash
PYTHONPATH=scripts:scripts/tests python -m unittest -v \
  test_hook_protocol test_lean_documents test_project_resources test_architecture
```

Expected: all pass, with no legacy Hook protocol regression.

- [ ] **Step 7: Commit the bootstrap seam**

```bash
git add hooks/dispatch.py scripts/mae_flow_core/cli_runtime.py \
  scripts/mae_flow_core/orchestration/documents.py \
  scripts/mae_flow_core/orchestration/work_package.py \
  scripts/tests/test_hook_protocol.py scripts/tests/test_lean_documents.py \
  scripts/tests/test_project_resources.py
git commit -m "feat: add stable project-local workflow bootstrap"
```

---

### Task 3: Make Spec local and domain documentation durable

**Files:**
- Modify: `scripts/mae_flow_core/cli_parser.py`
- Create: `scripts/mae_flow_core/cli_commands/local_spec.py`
- Create: `scripts/mae_flow_core/cli_commands/domain_docs.py`
- Modify: `scripts/mae_flow_core/orchestration/documents.py`
- Create: `scripts/mae_flow_core/orchestration/behavior_baseline.py`
- Modify: `flow/steps/open.md`
- Create: `docs/specs/index.md`
- Create: `scripts/tests/test_local_spec.py`
- Create: `scripts/tests/test_behavior_baseline.py`
- Create: `scripts/tests/test_domain_docs.py`

**Interfaces:**
- `local-spec init|validate|show`
- `domain-docs context|reconcile|show`
- `load_relevant_domain_context(project_root: Path, terms: Sequence[str]) -> DomainContext`
- `reconcile_domain_doc(project_root: Path, domain: str, candidate: str) -> ReconcileResult`

- [ ] **Step 1: Write parser and local-artifact tests**

Parser tests must prove every emitted command round-trips through the production `parse_args(argv)` entry. Artifact tests must prove:

```python
paths = ensure_work_package(root, "REQ-123")
self.assertEqual(paths.spec, root / ".mae-flow-work/REQ-123/spec.md")
self.assertFalse((root / "docs/mae-flow/requirements").exists())
```

`local-spec validate` checks that scope, observable behavior, acceptance criteria, exclusions, and Grill decision references are non-empty. It validates content; it never publishes the file.

- [ ] **Step 2: Write domain index and reconciliation tests**

Use `docs/specs/index.md` as a lightweight router with domain, keywords, and document path. Test relevant-only loading, new/updated/unchanged reconciliation, and manifest eligibility only for new/updated files.

```markdown
| Domain | Keywords | Document |
| --- | --- | --- |
| radio-access | NRPRACH, SUL, PRACH | docs/specs/radio-access.md |
```

- [ ] **Step 3: Verify RED**

```bash
PYTHONPATH=scripts:scripts/tests python -m unittest -v \
  test_local_spec test_behavior_baseline test_domain_docs
```

Expected: commands and local/durable path distinctions are absent.

- [ ] **Step 4: Implement commands in the legacy parser**

Add both commands to `cli_parser.py` and dispatch them from the old composition root. Reuse pure functions from `documents.py` and `behavior_baseline.py`; do not call the Lean CLI.

```python
local_spec.add_argument("action", choices=("init", "validate", "show"))
domain_docs.add_argument("action", choices=("context", "reconcile", "show"))
```

All normal output is concise Chinese and includes the exact local path.

- [ ] **Step 5: Update the old `open` guidance**

Keep old Grill entry and behavior. Replace OpenSpec publication wording with: initialize local Spec, read only relevant indexed domain context, perform code investigation, complete old Grill, and make `grill.md` a required Spec input.

- [ ] **Step 6: Verify focused behavior**

```bash
PYTHONPATH=scripts:scripts/tests python -m unittest -v \
  test_command_dispatch test_local_spec test_behavior_baseline test_domain_docs
```

- [ ] **Step 7: Commit local and durable documentation boundaries**

```bash
git add scripts/mae_flow_core/cli_parser.py scripts/mae_flow_core/cli_commands/local_spec.py \
  scripts/mae_flow_core/cli_commands/domain_docs.py \
  scripts/mae_flow_core/orchestration/documents.py \
  scripts/mae_flow_core/orchestration/behavior_baseline.py flow/steps/open.md \
  docs/specs/index.md scripts/tests/test_local_spec.py \
  scripts/tests/test_behavior_baseline.py scripts/tests/test_domain_docs.py
git commit -m "feat: separate local specs from domain documentation"
```

---

### Task 4: Replace the heavy pre-code chain with mandatory Story

**Files:**
- Modify: `flow/flow.json`
- Delete: `flow/steps/design.md`
- Delete: `flow/steps/test_blueprint.md`
- Delete: `flow/steps/story_ask.md`
- Delete: `flow/steps/build_plan.md`
- Modify: `flow/steps/story.md`
- Modify: `flow/steps/build_pace.md`
- Modify: `skills/mae-flow/assets/STORY-TEMPLATE.md`
- Modify: `agents/story-generator-agent.md`
- Modify: `agents/craft-reviewer-agent.md`
- Delete: `agents/test-design-agent.md`
- Delete: `agents/cp-task-analyst-agent.md`
- Modify: `skills/mae-flow/SKILL.md`
- Modify: `scripts/tests/test_workflow_definition.py`
- Modify: `scripts/tests/test_stable_recovery_contract.py`
- Create: `scripts/tests/test_story_contract.py`

**Interfaces:**
- Full-flow edge: `open -> story -> build_pace -> build`
- Story generator inputs: local `spec.md`, local `grill.md`, relevant `docs/specs/*.md`, and investigated code paths.
- Story reviewer inputs: the same inputs plus generated `story.md`.

- [ ] **Step 1: Write the flow-graph test first**

Assert the exact required edge sequence, mandatory Story, and absence of the four removed gates.

```python
self.assertEqual(next_step("open"), "story")
self.assertEqual(next_step("story"), "build_pace")
for removed in ("design", "test_blueprint", "story_ask", "build_plan"):
    self.assertNotIn(removed, flow["steps"])
```

- [ ] **Step 2: Write Story semantic tests**

Require these independent sections in the template and generated artifact contract:

1. 业务目标与范围
2. Grill 决策与未决项
3. 可观察行为与验收条件
4. 性能规格（仅容量、时延、吞吐、并发、资源上限）
5. 对外及跨组件接口设计
6. 关键函数与方法修改详述
7. 数据与兼容性
8. 测试设计
9. CP 划分与轻量实施说明
10. 风险、回滚与领域文档影响

The tests must reject function-level changes under interface design and must require a traceable Grill question/decision reference.

- [ ] **Step 3: Verify RED**

```bash
PYTHONPATH=scripts:scripts/tests python -m unittest -v \
  test_workflow_definition test_story_contract test_stable_recovery_contract
```

- [ ] **Step 4: Simplify the graph and delete obsolete resources**

Make Story mandatory in Full flow. Preserve hotfix/tweak/review paths unless a path explicitly enters Full Story generation. Delete only the four obsolete step files and two approved agents.
Change the contract key from `planned_removed_agents` to `removed_agents` in the same commit, and update its assertion from present-at-baseline to absent-after-recovery.

- [ ] **Step 5: Update Story agents without introducing a second review loop**

The generator reads exact paths from its task card and produces one `story.md`. The craft reviewer performs one design review and records CLEAR/ISSUE as ordinary lifecycle detail. A later file timestamp or byte change must never automatically invoke the reviewer again.

```markdown
必须读取：任务卡给出的 spec.md、grill.md、相关领域文档和代码路径。
一次设计检视完成后返回；后续 Story 变更由用户决定是否主动复检，流程不得因摘要或时间戳自动回退。
```

- [ ] **Step 6: Enforce pace behavior in `build_pace`**

Persist the user's `staged|continuous|adjust` choice. Staged emits a user checkpoint after each CP; Continuous emits no inter-CP checkpoint; Adjust returns to CP editing before construction. No agent may rewrite this value.

- [ ] **Step 7: Run graph, Story, and legacy path tests**

```bash
PYTHONPATH=scripts:scripts/tests python -m unittest -v \
  test_workflow_definition test_story_contract test_workflow_advancement \
  test_stable_recovery_contract
```

- [ ] **Step 8: Commit the subtractive flow change**

```bash
git add -A flow agents skills/mae-flow scripts/tests/test_workflow_definition.py \
  scripts/tests/test_story_contract.py scripts/tests/test_stable_recovery_contract.py
git commit -m "refactor: make story the sole pre-code design artifact"
```

---

### Task 5: Replace strict agent receipts with lifecycle observations

**Files:**
- Create: `scripts/mae_flow_core/workflow/agent_observations.py`
- Modify: `scripts/mae_flow_core/application/hooks/agent_completion.py`
- Modify: `scripts/mae_flow_core/application/hooks/task_cards.py`
- Modify: `scripts/mae_flow_core/workflow/agent_evidence.py`
- Modify: `scripts/mae_flow_core/adapters/hook_runtime_contracts.py`
- Modify: `hooks/dispatch.py`
- Modify: `agents/*.md`
- Create: `scripts/tests/test_agent_observations.py`
- Modify: `scripts/tests/test_hook_agent_completion.py`
- Modify: `scripts/tests/test_hook_task_card_contracts.py`
- Modify: `scripts/tests/test_agent_evidence.py`
- Modify: `scripts/tests/test_hook_tool_transcript.py`

**Interfaces:**
- `record_agent_started(state_path, kind, step, invocation_id, at) -> AgentObservation`
- `record_agent_finished(state_path, invocation_id, lifecycle, at, detail="") -> AgentObservation`
- `has_finished_observation(state_path, kind, step) -> bool`
- Lifecycle values: `started`, `returned`, `interrupted`, `timeout`.

- [ ] **Step 1: Write observation persistence tests**

Use the sidecar `.mae-flow.json.agent-observations`. Require atomic append semantics, idempotence by `invocation_id + lifecycle`, and tolerance of arbitrary natural-language detail.

```python
record_agent_started(path, "reviewer", "story", "run-1", "2026-08-04T10:00:00Z")
record_agent_finished(path, "run-1", "returned", "2026-08-04T10:01:00Z", "CLEAR；无新增问题")
self.assertTrue(has_finished_observation(path, "reviewer", "story"))
```

- [ ] **Step 2: Replace receipt-format tests with opaque-return tests**

The Hook must accept returned text with no marker, multiple languages, Markdown, empty assistant text, and non-numeric summaries. It must not search for `_RESULT`, `TASK_CARD_SHA256`, token, SHA, digest, `status=`, or fixed line counts.

- [ ] **Step 3: Keep path authorization tests unchanged**

Run the PreToolUse write-boundary suites before editing runtime code and record their passing names. These are safety contracts and must remain green throughout this task.

- [ ] **Step 4: Verify RED for completion behavior**

```bash
PYTHONPATH=scripts:scripts/tests python -m unittest -v \
  test_agent_observations test_hook_agent_completion \
  test_hook_task_card_contracts test_agent_evidence
```

- [ ] **Step 5: Implement lifecycle-only recording**

PreToolUse Agent records `started`. SubagentStop records `returned`, `interrupted`, or `timeout` from Hook lifecycle metadata and stores assistant text only as optional diagnostic detail. It never converts content into acceptance/rejection.

- [ ] **Step 6: Simplify task cards without reducing input clarity**

Keep agent kind, purpose, exact project root, exact artifact paths, CP identifier, allowed source scope, and expected user-visible outcome. Remove task-card SHA, HEAD/source freshness digest, return token, fixed marker, and retry instructions.

- [ ] **Step 7: Adapt flow evidence to observations**

Any old gate that required “agent ran” checks `has_finished_observation`. Artifact/content checks remain explicit workflow checks where still required; they are not inferred from agent prose.

- [ ] **Step 8: Delete obsolete output-contract parsing**

Remove or reduce `hook_runtime_contracts.py` to structural event decoding only. No completion path may reject a returned agent because of its wording or formatting.

- [ ] **Step 9: Run all Hook suites**

```bash
PYTHONPATH=scripts:scripts/tests python -m unittest discover \
  -s scripts/tests -p 'test_hook_*.py'
```

Expected: all Hook tests pass; source/Git boundaries remain strict, completion text remains opaque.

- [ ] **Step 10: Commit the lifecycle seam**

```bash
git add scripts/mae_flow_core/workflow/agent_observations.py \
  scripts/mae_flow_core/application/hooks scripts/mae_flow_core/workflow/agent_evidence.py \
  scripts/mae_flow_core/adapters/hook_runtime_contracts.py hooks/dispatch.py agents scripts/tests
git commit -m "refactor: observe agent lifecycle without parsing returns"
```

---

### Task 6: Bind quality agents to exact inputs and real execution

**Files:**
- Modify: `agents/craft-reviewer-agent.md`
- Modify: `agents/compile-agent.md`
- Modify: `agents/codecheck-fix-agent.md`
- Modify: `agents/ut-generator-agent.md`
- Modify: `flow/steps/verify_ponytail.md`
- Modify: `scripts/mae_flow_core/application/quality/task_cards.py`
- Modify: `scripts/tests/test_compile_wait_instructions.py`
- Modify: `scripts/tests/test_hook_compile_contract.py`
- Modify: `scripts/tests/test_hook_codecheck_contract.py`
- Modify: `scripts/tests/test_hook_unit_test_contract.py`
- Create: `scripts/tests/test_quality_task_inputs.py`

**Interfaces:**
- Reviewer task inputs: exact `spec.md`, `grill.md`, `story.md`, candidate source files, and diff base.
- Compile observation key: normalized build-input snapshot, not a task-card/source SHA receipt.
- CodeCheck fixer runs only for actual warnings.
- UT generator retains one logical invocation and its old internal batching.

- [ ] **Step 1: Write exact-input task-card tests**

Assert every quality card contains absolute or repository-root-relative paths for all inputs. A card that says only “结合 Spec 和 Story” must fail.

```python
self.assertIn(".mae-flow-work/REQ-123/spec.md", card)
self.assertIn(".mae-flow-work/REQ-123/story.md", card)
self.assertIn("src/radio/prach.cpp", card)
```

- [ ] **Step 2: Write real-execution tests**

Cover CodeCheck zero-warning skip, warning-triggered fixer, compile agent invocation, UT logical invocation, timeout as failure, and unchanged build inputs reusing the completed result.

- [ ] **Step 3: Verify RED**

```bash
PYTHONPATH=scripts:scripts/tests python -m unittest -v \
  test_quality_task_inputs test_hook_compile_contract \
  test_hook_codecheck_contract test_hook_unit_test_contract
```

- [ ] **Step 4: Update task-card builders and agent guidance**

Do not rely on an agent finding artifacts by search. Render every path into the card. Preserve one synchronous compile call with the host's longest supported timeout, targeting ten minutes.

```markdown
一轮编译只执行一次同步构建。命令返回即完成；timeout/transport failure 如实记录为失败。
禁止后台执行、PID 查询、日志轮询、sleep，以及构建输入未变化时重复执行。
```

- [ ] **Step 5: Remove Lightcheck auto-pass wording from the quality step**

The quality step must execute Lightcheck against old auto-derived candidate scope. An empty scope reports “本次没有候选源码变更” rather than “未提供精确文件，自动放行”. Compile and CodeCheck remain explicit real actions, not inferred from Lightcheck.

- [ ] **Step 6: Run focused quality suites**

```bash
PYTHONPATH=scripts:scripts/tests python -m unittest -v \
  test_compile_wait_instructions test_quality_task_inputs \
  test_hook_compile_contract test_hook_codecheck_contract \
  test_hook_unit_test_contract test_quality_selection
```

- [ ] **Step 7: Commit quality execution fixes**

```bash
git add agents flow/steps/verify_ponytail.md \
  scripts/mae_flow_core/application/quality/task_cards.py scripts/tests
git commit -m "fix: bind quality work to exact artifacts and executions"
```

---

### Task 7: Preserve old Lightcheck scope with nesting and magic-number checks

**Files:**
- Modify: `scripts/mae_flow_core/cli_commands/lightcheck.py`
- Modify: `scripts/mae_flow_core/lightcheck_analysis.py`
- Modify: `scripts/mae_flow_core/lightcheck_functions.py`
- Modify: `scripts/mae_flow_core/lightcheck_nesting.py`
- Modify: `scripts/tests/test_lightcheck.py`
- Create: `scripts/tests/test_lightcheck_scope_contract.py`

**Interfaces:**
- `lightcheck [--quiet]` only; no `--file` input contract.
- Scope derives from old commit candidates and changed lines/touched functions.
- Findings: `MF-NEST-5`, high-confidence magic number, parameters over five, effective function lines over fifty, and line length over 120.

- [ ] **Step 1: Add regression tests around the already-working old analyzer**

Assert the parser rejects `lightcheck --file`, startup-dirty files are excluded until explicitly adopted, unchanged lines/functions are excluded, and analyzer exceptions return success with a diagnostic.

- [ ] **Step 2: Lock metric semantics**

Require exact nesting depth five to pass and six to warn. Parallel branches, boolean operators, and ternary expressions do not accumulate depth. Require high-confidence magic-number findings while excluding named constants, macros, enums, comments, strings, tests/fixtures, and same-line business explanations.

- [ ] **Step 3: Run tests before edits**

```bash
PYTHONPATH=scripts:scripts/tests python -m unittest -v \
  test_lightcheck test_lightcheck_scope_contract
```

Expected: most old analyzer tests already pass; only missing scope/wording assertions fail. If an established metric test fails, diagnose instead of replacing the old implementation.

- [ ] **Step 4: Make only compatibility corrections**

Do not port current `lean_lightcheck.py`. Keep old candidate discovery and changed-line filtering. Add only the approved exclusion/diagnostic adjustments exposed by the new tests.

- [ ] **Step 5: Run Lightcheck and ownership suites**

```bash
PYTHONPATH=scripts:scripts/tests python -m unittest -v \
  test_lightcheck test_lightcheck_scope_contract \
  test_commit_ownership test_guard_ownership
```

- [ ] **Step 6: Commit the Lightcheck contract**

```bash
git add scripts/mae_flow_core/cli_commands/lightcheck.py \
  scripts/mae_flow_core/lightcheck_analysis.py \
  scripts/mae_flow_core/lightcheck_functions.py \
  scripts/mae_flow_core/lightcheck_nesting.py \
  scripts/tests/test_lightcheck.py scripts/tests/test_lightcheck_scope_contract.py
git commit -m "test: preserve scoped advisory lightcheck behavior"
```

---

### Task 8: Add an exact user-confirmed delivery manifest

**Files:**
- Modify: `scripts/mae_flow_core/cli_parser.py`
- Create: `scripts/mae_flow_core/cli_commands/delivery_manifest.py`
- Modify: `scripts/mae_flow_core/guard/manifest.py`
- Modify: `scripts/mae_flow_core/guard/ownership.py`
- Modify: `flow/steps/delivery_review.md`
- Modify: `scripts/tests/test_delivery_manifest.py`
- Modify: `scripts/tests/test_commit_ownership.py`
- Create: `scripts/tests/test_delivery_confirmation.py`

**Interfaces:**
- `manifest set --file PATH --message TEXT --target BRANCH [--adopt-dirty PATH=DECISION]`
- `manifest show`
- `manifest confirm --message-id ID`
- State field `delivery_manifest` contains `files`, `commit_message`, `target_branch`, `adopted_dirty`, and `confirmed`; it contains no digest or receipt token.

- [ ] **Step 1: Write exact-file and adoption tests**

Require each startup-dirty file to have an explicit natural-language adoption decision before it can enter the manifest. Reject files outside old candidate ownership. Stage only the confirmed list.

- [ ] **Step 2: Write reconfirmation tests**

After confirmation, any file/message/target change sets `confirmed` to false exactly once. An unchanged `manifest set` remains confirmed and must not ask the user again.

- [ ] **Step 3: Verify RED**

```bash
PYTHONPATH=scripts:scripts/tests python -m unittest -v \
  test_delivery_manifest test_commit_ownership test_delivery_confirmation
```

- [ ] **Step 4: Implement the manifest on top of old ownership**

Use `guard/ownership.py` as the source of truth for candidates. `guard/manifest.py` stores the human-readable manifest without canonical-JSON digests, DeliveryReceipt, fixed Git command, or PostToolUse receipt chain.

```python
manifest = {
    "files": sorted(files),
    "commit_message": message,
    "target_branch": target,
    "adopted_dirty": adopted_dirty,
    "confirmed": False,
}
```

- [ ] **Step 5: Generate command help from the parser**

The delivery step calls the same parser/help renderer used by `mae-flow --help`. Add a test that every command printed by `delivery_review.md` parses successfully.

- [ ] **Step 6: Verify Git boundaries**

```bash
PYTHONPATH=scripts:scripts/tests python -m unittest -v \
  test_delivery_manifest test_delivery_confirmation \
  test_commit_ownership test_guard_ownership test_guard_gate test_guard_bash
```

- [ ] **Step 7: Commit the delivery boundary**

```bash
git add scripts/mae_flow_core/cli_parser.py \
  scripts/mae_flow_core/cli_commands/delivery_manifest.py \
  scripts/mae_flow_core/guard/manifest.py scripts/mae_flow_core/guard/ownership.py \
  flow/steps/delivery_review.md scripts/tests
git commit -m "feat: add exact user-confirmed delivery manifest"
```

---

### Task 9: Recover in-flight Lean v3 state safely into stable v2

**Files:**
- Replace: `scripts/mae_flow_core/cli_commands/lean_migration.py`
- Modify: `scripts/mae_flow_core/orchestration/migration.py`
- Modify: `scripts/mae_flow_core/cli_runtime.py`
- Modify: `scripts/mae_flow_core/cli_parser.py`
- Modify: `scripts/tests/test_lean_migration.py`
- Create: `scripts/tests/test_stable_state_recovery.py`

**Interfaces:**
- First call: `migrate-flow` creates a byte-for-byte backup and prints a Chinese recovery card; it does not replace active state.
- Confirmed call: `migrate-flow --confirm --message-id ID` writes stable v2 state at a mapped safe boundary.
- `current` detects Lean v3 and prints the same recovery card instead of crashing or silently rewriting.

- [ ] **Step 1: Write detection, backup, and non-mutation tests**

Given a Lean v3 `.mae-flow.json`, assert the first call creates `.mae-flow-work/state-backups/<timestamp>-lean-v3.json`, preserves exact bytes, and leaves the original state unchanged.

- [ ] **Step 2: Write semantic mapping tests**

Import only ticket, user configuration, branch, startup dirt, confirmed artifact paths, and last safe human boundary. Never import task tokens, hashes, reviewer digests, source fingerprints, or delivery receipts.

Use these conservative mappings:

```python
SAFE_BOUNDARY_BY_PHASE = {
    "startup": "config_confirm",
    "spec": "open",
    "story": "story",
    "construction": "build_pace",
    "quality": "verify_ponytail",
    "delivery": "delivery_review",
}
```

Completed/exited Lean state is archived and starts no active stable flow. Ambiguous phase/artifact mappings leave state and work files untouched and return Chinese recovery advice.

- [ ] **Step 3: Verify RED**

```bash
PYTHONPATH=scripts:scripts/tests python -m unittest -v \
  test_lean_migration test_stable_state_recovery
```

- [ ] **Step 4: Reverse the old migration direction**

Replace the v2-to-Lean adapter with a Lean-v3-to-stable-v2 adapter. Keep the early command interception in the legacy composition root, but make it read-only until `--confirm --message-id` matches a recorded natural-language user confirmation.

- [ ] **Step 5: Test interruption and idempotence**

An interruption after backup but before state replacement is safe. Repeating the confirmed migration must reuse the backup/proposal and produce the same stable semantic state without duplicate work-package files.

- [ ] **Step 6: Run recovery and legacy-state suites**

```bash
PYTHONPATH=scripts:scripts/tests python -m unittest -v \
  test_lean_migration test_stable_state_recovery test_state_core \
  test_cli_runtime_facade
```

- [ ] **Step 7: Commit recovery compatibility**

```bash
git add scripts/mae_flow_core/cli_commands/lean_migration.py \
  scripts/mae_flow_core/orchestration/migration.py \
  scripts/mae_flow_core/cli_runtime.py scripts/mae_flow_core/cli_parser.py \
  scripts/tests/test_lean_migration.py scripts/tests/test_stable_state_recovery.py
git commit -m "feat: recover lean state into the stable workflow"
```

---

### Task 10: Prove command/prompt agreement and graph liveness

**Files:**
- Create: `scripts/mae_flow_core/workflow/command_catalog.py`
- Modify: `scripts/mae_flow_core/cli_parser.py`
- Modify: `scripts/mae_flow_core/application/quality/task_cards.py`
- Create: `scripts/tests/test_command_prompt_agreement.py`
- Create: `scripts/tests/test_flow_liveness.py`
- Modify: `scripts/tests/test_workflow_definition.py`
- Modify: `scripts/tests/selftest_suites.py`

**Interfaces:**
- `render_command(command_id: str, context: Mapping[str, str]) -> list[str]`
- `parse_rendered_command(argv: Sequence[str]) -> argparse.Namespace`
- `enumerate_nonterminal_states(flow, configurations) -> Iterable[FlowState]`

- [ ] **Step 1: Centralize production command rendering**

Create named command builders for every command printed in steps, task cards, errors, and recovery cards. Builders return argv first; shell display is derived from argv. Do not maintain duplicate free-form examples.

- [ ] **Step 2: Write exhaustive parser-agreement tests**

Render every catalog command with a real fixture context and feed argv to the production parser. Explicitly cover Grill question metadata (`--key`, `--parent`, `--evidence`, `--impact`, `--recommendation`), capability observations, delivery manifest, and migration confirmation.

- [ ] **Step 3: Write graph liveness tests**

Enumerate Full staged/continuous/adjust, hotfix, tweak, review, optional code-review enabled/disabled, and quality warning/no-warning paths. Assert every nonterminal state has at least one parser-valid executable next action, and no automatic transition returns to a completed Story review.

Also assert:

- one user decision cannot be consumed by two consecutive confirmation gates;
- staged has exactly one checkpoint per CP;
- continuous has no inter-CP checkpoint;
- reviewer completion cannot trigger reviewer scheduling;
- a command failure returns actionable Chinese help produced by the parser.

- [ ] **Step 4: Verify RED before catalog integration**

```bash
PYTHONPATH=scripts:scripts/tests python -m unittest -v \
  test_command_prompt_agreement test_flow_liveness test_workflow_definition
```

- [ ] **Step 5: Replace free-form production examples**

Use `command_catalog.py` everywhere a runnable command is shown. Documentation examples may remain prose, but release tests must extract and parser-check all fenced `mae-flow`/`python ... mae-flow.py` commands in operational resources.

- [ ] **Step 6: Run liveness and parser suites**

```bash
PYTHONPATH=scripts:scripts/tests python -m unittest -v \
  test_command_prompt_agreement test_flow_liveness \
  test_command_dispatch test_cli_runtime_facade test_workflow_definition
```

- [ ] **Step 7: Commit the no-deadlock contract**

```bash
git add scripts/mae_flow_core/workflow/command_catalog.py \
  scripts/mae_flow_core/cli_parser.py scripts/mae_flow_core/application/quality/task_cards.py \
  scripts/tests/test_command_prompt_agreement.py scripts/tests/test_flow_liveness.py \
  scripts/tests/test_workflow_definition.py scripts/tests/selftest_suites.py
git commit -m "test: enforce workflow command agreement and liveness"
```

---

### Task 11: Run end-to-end recovery verification and prepare integration

**Files:**
- Modify: `FIELD-TEST.md`
- Modify: `MAINTAINERS.md`
- Modify: `CHANGELOG.md`
- Create: `docs/superpowers/plans/2026-08-04-stable-base-recovery-evidence.md`

**Interfaces:**
- Automated gate: all repository tests plus self-test.
- Windows CodeAgent field gate: real Hook, shell, compile, CodeCheck, UT, Chain, Git candidate, and migration behavior.
- Integration topology: recovery tree remains first-parent content; current Lean main is merged only as the second parent.

- [ ] **Step 1: Run the complete automated suite**

```bash
PYTHONPATH=scripts:scripts/tests python -m unittest discover -s scripts/tests -p 'test_*.py'
python scripts/selftest.py
```

Expected: all tests pass. Record the exact test count, elapsed time, Python version, and commit SHA in the evidence file. The count must be greater than 1,062; no old suite may be deleted merely to pass.

- [ ] **Step 2: Run differential baseline checks**

For every behavior not listed as an intentional delta in `stable_recovery_contract.json`, compare exit code, state transition, file writes, and user-visible semantic result against a clean `d32ccfb` worktree.

- [ ] **Step 3: Run Windows CodeAgent end-to-end scenarios**

Record commands and outcomes for:

1. Full + Staged with at least two CPs and one stop per CP.
2. Full + Continuous with no inter-CP stop and one final review.
3. Full Grill with branching questions and Grill decisions visible in Story.
4. Hotfix, tweak, and review paths.
5. Cross-repository Chain unchanged from the old workflow.
6. Code review enabled and disabled.
7. Compile success, real compile failure, and host timeout without polling.
8. CodeCheck zero warning and real-warning repair.
9. UT generation, internal batching, and defect repair.
10. Lean v3 recovery, interruption after backup, and idempotent confirmation.
11. Startup-dirty adoption, exact manifest reconfirmation, exact staging, commit, and push.
12. Plugin installed where only CodeAgent variables/paths are available.

- [ ] **Step 4: Inspect the final diff for accidental Lean replacement**

```bash
git diff --stat d32ccfb...HEAD
git diff --name-status d32ccfb...HEAD
git grep -n 'CLAUDE_PLUGIN_ROOT\|lean_runtime\|TASK_CARD_SHA256\|_RESULT\|sleep [0-9]'
```

Expected: no Claude plugin-root dependency, no Lean runtime import, no task-card/result-marker contract, and no compile polling instruction. Any remaining `_RESULT` occurrence must be a historical migration fixture explicitly asserted as non-production.

- [ ] **Step 5: Update operational documentation**

Document the simplified Full path, local/durable artifact boundary, seven agents, lifecycle-only Hook completion, exact delivery manifest, old Lightcheck semantics, stable compile behavior, and Lean recovery procedure in concise Chinese.

- [ ] **Step 6: Commit release evidence**

```bash
git add FIELD-TEST.md MAINTAINERS.md CHANGELOG.md \
  docs/superpowers/plans/2026-08-04-stable-base-recovery-evidence.md
git commit -m "docs: record stable workflow recovery evidence"
```

- [ ] **Step 7: Create the safety tag and integration commit**

After verifying remote main still points to the reviewed Lean head, create an annotated backup tag for that exact remote commit. Merge remote main into the recovery branch with `--no-ff -s ours` only after confirming the recovery tree is clean and the full suite passes, so current Lean history is the second parent while the recovery tree remains unchanged.

```bash
git fetch origin
git tag -a pre-stable-recovery-2026-08-04 origin/main -m "Backup before stable-base recovery"
git merge --no-ff -s ours origin/main -m "merge: retain lean history behind stable recovery"
```

Run the complete automated suite again after the merge commit. Push the backup tag and recovery branch, then fast-forward main to the reviewed recovery commit. Never force-push.

- [ ] **Step 8: Verify the remote result**

```bash
git fetch origin
git rev-parse HEAD
git rev-parse origin/main
git status --short --branch
```

Expected: local HEAD equals `origin/main`, the worktree is clean, the backup tag exists remotely, and the integration commit has two parents.

## Final Acceptance Checklist

- [ ] Old configuration card, Chinese display, Grill, Chain, ownership, Lightcheck scope, CodeCheck/UT behavior, and compile synchronization remain available.
- [ ] Full flow has one reviewed Story and no separate Design/Test Blueprint/Roadmap/Build Plan gate.
- [ ] Grill decisions are mandatory Story inputs.
- [ ] Story section semantics match the approved business/performance/interface/function distinctions.
- [ ] Staged and Continuous CP behavior is deterministic and user-selected.
- [ ] Agent returns cannot deadlock the flow because of text, marker, token, hash, fingerprint, or digest mismatch.
- [ ] Quality agents receive exact Spec/Grill/Story/source paths and execute real compile/CodeCheck/UT work.
- [ ] Work directories are readable, Spec stays local, and only reconciled domain docs are durable.
- [ ] Every production command shown to an agent parses successfully.
- [ ] Every nonterminal state has a valid next action; no double confirmation or automatic re-review loop exists.
- [ ] Lean v3 state is recoverable without destructive overwrite.
- [ ] Complete automated and Windows CodeAgent evidence is recorded before main changes.
