# Unified Quality Change Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify every code/test/build change behind verification, one human review and one exact commit in normal mode, while keeping Moonlight unattended and bounding Ponytail, CodeCheck and UT execution.

**Architecture:** Keep the existing JSON workflow and evidence adapters, but add one reusable quality-review/quality-commit corridor whose resume target is persisted as semantic state. Quality steps report the kind of dirty change and route through that corridor; Moonlight resolves the same corridor automatically. UT batching becomes one logical session with accumulated test outputs, and CodeCheck/Ponytail limits are explicit counters rather than prompt-only conventions.

**Tech Stack:** Python 3 standard library, JSON workflow definitions, Markdown agent/step resources, unittest, existing Mae-Flow hook/evidence adapters.

## Global Constraints

- Ponytail runs at most once per requirement.
- CodeCheck runs at most two scan/fix/recheck rounds.
- UT uses one Agent for small scopes and 3-5 changed methods per fresh Agent for large scopes, with no per-batch commits or user gates.
- Normal mode reviews every source/test/build diff before an exact commit.
- Moonlight never waits for routine human review and advances until a real external hard blocker.
- Agent reports remain natural language; no result tokens, document digests or fingerprint-driven re-review.
- Construction CP and implementation sub-agents remain removed.

---

### Task 1: Encode the unified quality graph contract

**Files:**
- Modify: `flow/flow.json`
- Create: `flow/steps/quality_review.md`
- Create: `flow/steps/quality_commit.md`
- Create: `flow/steps/quality_rework.md`
- Modify: `flow/steps/build_review.md`
- Modify: `flow/steps/build_commit.md`
- Test: `scripts/tests/test_spec2code_workflow.py`
- Test: `scripts/tests/test_flow_liveness.py`

**Interfaces:**
- Consumes: workflow step fields `next`, `next_by`, `choice_key`, `skip_in_moonlight`.
- Produces: shared steps `quality_review`, `quality_rework`, `quality_commit` and declared dynamic resume targets.

- [ ] **Step 1: Write failing graph tests**

Add tests asserting that every source/test/build-writing quality step reaches `quality_review` before a commit, that Moonlight declares an automatic continue choice, and that `quality_commit` exposes only valid resume targets.

```python
def test_quality_changes_share_one_review_and_commit_corridor(self):
    steps = self.flow["steps"]
    self.assertEqual("quality_review", steps["verify_post_ponytail_compile"]["next"])
    self.assertEqual("quality_review", steps["verify_codecheck_compile"]["next"])
    self.assertEqual("quality_review", steps["verify_ut_review_ready"]["next"])
    self.assertEqual("quality_commit", steps["quality_review"]["next"]["continue"])
    self.assertEqual("quality_rework", steps["quality_review"]["next"]["revise"])
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m unittest scripts.tests.test_spec2code_workflow scripts.tests.test_flow_liveness`

Expected: FAIL because the unified quality steps do not exist and current quality nodes bypass review.

- [ ] **Step 3: Add the minimal workflow nodes and prompts**

Define the common review corridor in `flow.json`. Prompts must show the complete current diff and evidence summary, ask once in normal mode, and state that Moonlight auto-continues. Do not put Git commit commands in Ponytail, CodeCheck or UT prompts.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m unittest scripts.tests.test_spec2code_workflow scripts.tests.test_flow_liveness`

Expected: PASS.

### Task 2: Persist semantic review origin and resume target

**Files:**
- Modify: `scripts/mae_flow_core/workflow/completion.py`
- Modify: `scripts/mae_flow_core/workflow/transitions.py`
- Modify: `scripts/mae_flow_core/cli_commands/done_status.py`
- Modify: `scripts/mae_flow_core/cli_commands/advancement.py`
- Modify: `scripts/mae_flow_core/cli_commands/current.py`
- Test: `scripts/tests/test_workflow_definition.py`
- Test: `scripts/tests/test_agent_evidence.py`
- Create: `scripts/tests/test_quality_review_cycle.py`

**Interfaces:**
- Produces state field `quality_review = {origin, resume, changed_files, entered_head}`.
- Consumes the field when resolving `quality_commit` and `quality_rework`; clears it only after successful commit transition.

- [ ] **Step 1: Write failing transition tests**

Cover initial build, Ponytail source edit, CodeCheck source edit, UT test edit and UT source edit. Assert semantic resume targets and that changing ordinary document text never invalidates the review.

```python
def test_ut_source_fix_resumes_codecheck_without_ponytail(self):
    state = enter_quality_review(origin="ut-source", changed_files=["src/a.cpp"])
    self.assertEqual("verify_codecheck", resume_after_quality_commit(state))
    self.assertNotEqual("verify_ponytail", resume_after_quality_commit(state))
```

- [ ] **Step 2: Run the new test and verify RED**

Run: `python -m unittest scripts.tests.test_quality_review_cycle`

Expected: FAIL because no semantic quality-review state or resolver exists.

- [ ] **Step 3: Implement the smallest semantic transition policy**

Add pure helpers for creating, validating and resolving the review context. Adapters may inspect Git to populate `changed_files`, but policy code must remain side-effect free. Replace `_done_source_change` and `_done_source_recheck` commit requirements with routing into validation/review; never require a quality Agent to commit.

- [ ] **Step 4: Render one recovery instruction**

`current` must explain the single valid next action from `quality_review`, `quality_rework` and `quality_commit`. Missing/corrupt resume state must stop once with `doctor`/migration guidance rather than guessing or looping.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `python -m unittest scripts.tests.test_quality_review_cycle scripts.tests.test_workflow_definition scripts.tests.test_agent_evidence`

Expected: PASS.

### Task 3: Restore Agent Skill capabilities and executable contracts

**Files:**
- Modify: `agents/compile-agent.md`
- Modify: `agents/codecheck-fix-agent.md`
- Modify: `agents/ut-generator-agent.md`
- Modify: `scripts/mae_flow_core/application/quality/task_card_documents.py`
- Test: `scripts/tests/test_story_contract.py`
- Test: `scripts/tests/test_quality_task_inputs.py`
- Test: `scripts/tests/test_hook_compile_contract.py`
- Test: `scripts/tests/test_hook_unit_test_contract.py`

**Interfaces:**
- Agent frontmatter must include `Skill` whenever its task card may require a Skill.
- Task cards select exactly one execution route: configured Skill identity or configured Bash command.

- [ ] **Step 1: Write failing frontmatter/contract tests**

```python
def test_agents_that_may_require_skills_declare_skill_tool(self):
    for name in ("compile-agent.md", "codecheck-fix-agent.md", "ut-generator-agent.md"):
        frontmatter = read("agents/" + name).split("---", 2)[1]
        self.assertIn("Skill", frontmatter)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest scripts.tests.test_story_contract scripts.tests.test_quality_task_inputs`

Expected: FAIL because the three Agent tool lists omit `Skill`.

- [ ] **Step 3: Restore Skill tools and align task-card wording**

Add `Skill` to the three frontmatter declarations. State explicitly that CodeCheck uses the configured compile Skill only when compilation is required, and that UT uses configured AutoUT/java-autout or the exact repository command. Do not restore token or fixed-report requirements.

- [ ] **Step 4: Run contract tests and verify GREEN**

Run: `python -m unittest scripts.tests.test_story_contract scripts.tests.test_quality_task_inputs scripts.tests.test_hook_compile_contract scripts.tests.test_hook_unit_test_contract`

Expected: PASS.

### Task 4: Bound Ponytail and CodeCheck without loops

**Files:**
- Modify: `flow/steps/verify_ponytail.md`
- Modify: `flow/steps/verify_codecheck.md`
- Modify: `flow/steps/tw_codecheck.md`
- Modify: `flow/steps/rf_codecheck.md`
- Modify: `scripts/mae_flow_core/cli_commands/codecheck_commands.py`
- Modify: `scripts/mae_flow_core/cli_commands/codecheck_facts.py`
- Modify: `scripts/mae_flow_core/application/quality/codecheck_state.py`
- Test: `scripts/tests/test_quality_codecheck_state.py`
- Test: `scripts/tests/test_codecheck_logging.py`
- Create: `scripts/tests/test_quality_attempt_limits.py`

**Interfaces:**
- Produces persisted counters `quality_attempts.ponytail` and `quality_attempts.codecheck`.
- CodeCheck counter increments only when a real scan round starts; retries of an identical failed command do not create a new round.

- [ ] **Step 1: Write failing attempt-limit tests**

Assert Ponytail is skipped after one recorded attempt and CodeCheck returns a bounded-risk result after the second round, while preserving diagnostics.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest scripts.tests.test_quality_attempt_limits`

Expected: FAIL because the counters and bounded outcome do not exist.

- [ ] **Step 3: Implement counters and terminal behavior**

Record attempts in state using real execution start events. After the second CodeCheck round, persist remaining findings as delivery risk and permit transition to UT. Do not call `accept-risk`, ask the user per warning, or reset the counter after a CodeCheck repair commit.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m unittest scripts.tests.test_quality_attempt_limits scripts.tests.test_quality_codecheck_state scripts.tests.test_codecheck_logging`

Expected: PASS.

### Task 5: Implement one logical adaptive UT session

**Files:**
- Modify: `scripts/mae_flow_core/cli_commands/agent_task.py`
- Modify: `scripts/mae_flow_core/quality/task_cards.py`
- Modify: `scripts/mae_flow_core/application/quality/task_card_documents.py`
- Modify: `flow/steps/verify_ut.md`
- Modify: `flow/steps/tw_ut.md`
- Modify: `flow/steps/rf_ut.md`
- Modify: `agents/ut-generator-agent.md`
- Create: `scripts/mae_flow_core/quality/ut_batches.py`
- Create: `scripts/tests/test_ut_batches.py`
- Modify: `scripts/tests/test_quality_task_inputs.py`
- Modify: `scripts/tests/test_hook_task_card_contracts.py`

**Interfaces:**
- Produces `ut_session = {targets, batches, completed, final_run, accumulated_test_files}`.
- `agent-task ut` accepts the next pending batch or `--scope 收口批`, and permits only accumulated test/build outputs from the same session.

- [ ] **Step 1: Write failing batch policy tests**

Test deterministic grouping of changed functions into 3-5 item batches, single-batch behavior for small scopes, stable resume after interruption and rejection of unrelated dirty files.

```python
def test_large_ut_scope_batches_without_per_batch_commit(self):
    plan = plan_ut_batches([f"method_{i}" for i in range(11)])
    self.assertEqual([4, 4, 3], [len(batch) for batch in plan.batches])
    self.assertFalse(plan.requires_batch_commit)
```

- [ ] **Step 2: Run the new tests and verify RED**

Run: `python -m unittest scripts.tests.test_ut_batches`

Expected: FAIL because the batch policy module does not exist.

- [ ] **Step 3: Implement deterministic adaptive batching**

Use one batch for at most five changed methods. For larger scopes, distribute targets into stable 3-5 item batches. Persist completed batch IDs and accumulated test paths. Generate a minimal task card containing only the current batch's relevant requirements and paths.

- [ ] **Step 4: Permit only same-session dirty tests**

Replace the blanket dirty-worktree rejection for UT with a check that accepts paths recorded in the current UT session and still rejects dirty business source, unrelated tests and unowned build files.

- [ ] **Step 5: Require one final full UT execution**

After all generation batches, issue a final task card that performs the configured full UT command without generating more tests. Only this successful run satisfies UT evidence.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run: `python -m unittest scripts.tests.test_ut_batches scripts.tests.test_quality_task_inputs scripts.tests.test_hook_task_card_contracts scripts.tests.test_hook_unit_test_contract`

Expected: PASS.

### Task 6: Make Delivery commit complete and Moonlight unattended

**Files:**
- Modify: `flow/steps/delivery_review.md`
- Modify: `flow/steps/push.md`
- Modify: `flow/flow.json`
- Modify: `scripts/mae_flow_core/cli_commands/delivery_manifest.py`
- Modify: `scripts/mae_flow_core/delivery/evidence.py`
- Modify: `scripts/mae_flow_core/delivery/moonlight.py`
- Modify: `scripts/mae_flow_core/application/delivery/moonlight.py`
- Modify: `scripts/mae_flow_core/application/delivery/moonlight_defer.py`
- Test: `scripts/tests/test_delivery_confirmation.py`
- Test: `scripts/tests/test_delivery_moonlight_use_cases.py`
- Create: `scripts/tests/test_delivery_commit_cycle.py`

**Interfaces:**
- Delivery review produces a confirmed exact manifest and requires a matching commit before `push`.
- Moonlight produces the same exact manifest and commit receipt automatically, with decisions appended to the morning report.

- [ ] **Step 1: Write failing delivery tests**

Cover dirty domain documentation, dirty quality test files and Moonlight auto-commit. Assert that `done` cannot enter push with staged/uncommitted delivery files.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest scripts.tests.test_delivery_commit_cycle scripts.tests.test_delivery_confirmation scripts.tests.test_delivery_moonlight_use_cases`

Expected: FAIL because delivery review currently stages without requiring a commit and Moonlight stops for routine review.

- [ ] **Step 3: Require the exact delivery commit**

Update the delivery prompt and evidence so normal mode confirms the manifest once, performs exact `git add -- <files>` and one ticket-formatted commit, then advances. Reject transition to push if any manifest path remains staged or dirty.

- [ ] **Step 4: Implement Moonlight automatic decisions**

Auto-confirm exact manifests, apply conservative domain archive output, commit verified changes and continue. Record diff, commit ID, skipped human gate and unresolved semantic notes in the morning report. Stop only for real external blockers or unsafe destructive choices.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `python -m unittest scripts.tests.test_delivery_commit_cycle scripts.tests.test_delivery_confirmation scripts.tests.test_delivery_moonlight_use_cases`

Expected: PASS.

### Task 7: Repair compatibility prompts and remove retired handoff code

**Files:**
- Modify: `flow/steps/design.md`
- Modify: `flow/steps/story_ask.md`
- Modify: `flow/steps/rf_verify.md`
- Delete: `scripts/mae_flow_core/quality/ut_handoff.py`
- Modify: `scripts/mae_flow_core/quality/__init__.py`
- Delete: `scripts/tests/test_ut_handoff.py`
- Modify: `scripts/tests/test_stable_recovery_contract.py`
- Modify: `scripts/tests/test_spec2code_prompt_resources.py`

**Interfaces:**
- Compatibility steps emit exactly one current recovery action.
- No production import exposes `append_ut_handoff` or `render_ut_context`.

- [ ] **Step 1: Write failing cleanup/recovery tests**

Assert compatibility prompts do not mention OpenSpec commits, UT blueprints, coding plans or deleted steps, and assert the retired UT handoff module/export is absent.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest scripts.tests.test_stable_recovery_contract scripts.tests.test_spec2code_prompt_resources`

Expected: FAIL because stale recovery instructions and UT handoff remain.

- [ ] **Step 3: Replace prompts and remove dead code**

Make each compatibility step a thin one-way bridge to the current graph. Delete the unused module, export and dedicated tests without touching active UT task-card behavior.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m unittest scripts.tests.test_stable_recovery_contract scripts.tests.test_spec2code_prompt_resources`

Expected: PASS.

### Task 8: Add semantic redline audit and run the full suite

**Files:**
- Create: `scripts/tests/test_quality_flow_redlines.py`
- Modify: `scripts/tests/selftest_suites.py`
- Modify: `scripts/tests/test_architecture.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- The redline audit traverses all workflow paths and checks prompt/tool/state invariants across adjacent steps.

- [ ] **Step 1: Write cross-step invariant tests**

Test that no source-writing Agent is followed by a task that rejects its legal dirty output, no prompt requires an unavailable Agent tool, no quality prompt commits before review, and every delivery path commits before push.

- [ ] **Step 2: Run the redline test and verify RED if any gap remains**

Run: `python -m unittest scripts.tests.test_quality_flow_redlines`

Expected: PASS only after Tasks 1-7; otherwise fix the reported invariant rather than weakening the assertion.

- [ ] **Step 3: Run formatting and complete verification**

Run:

```bash
git diff --check
python scripts/tests/test_architecture.py
python -W error::ResourceWarning -m unittest discover -s scripts/tests -p 'test_*.py'
python scripts/selftest.py
```

Expected: 0 failures, 0 errors and selftest `全部通过`.

- [ ] **Step 4: Inspect the final diff and commit exact files**

Verify that no `.mae-flow-work/`, generated cache or unrelated user file is staged. Commit implementation and tests with a focused message such as `fix: unify quality review and commit flow`.
