# Complete Lean Workflow Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the operational configuration lost in the lean cutover and implement the approved Spec, Story, checkpoint, behavior-baseline, Git, and recovery lifecycle without reintroducing evidence-heavy quality gates.

**Architecture:** Extend the immutable lean recovery state with one typed startup configuration and lightweight domain/CP facts. Keep documents human-readable and template-guided; state records only paths, actions, and user decisions. Git remains the only strict Hook boundary: exact files, exact confirmed branch, and the confirmed `[ticket][type]description` prefix. Build, UT, CodeCheck, Story, Grill, and reviewers remain opaque one-attempt capabilities with no output parsing or retry loop.

**Tech Stack:** Python 3 standard library, immutable dataclasses, `unittest`, CodeAgent JSON Hooks, Markdown runtime guidance; all paths and subprocess boundaries must remain Windows-compatible.

## Global Constraints

- Do not parse Build, UT, CodeCheck, Story, Grill, or reviewer output.
- Do not add polling, sleep, background waiting, automatic retries, task cards, receipts, fixed ACK text, or Markdown format gates.
- Do not infer complexity from line count or file count.
- Preserve exact-file Git ownership, dirty-file protection, destructive-command protection, and natural-language user decisions.
- Story and per-ticket Spec stay local unless the user explicitly selects their exact files for commit.
- Behavior baselines represent current observable business truth and are organized by business capability, not technical layout.
- Preserve Python 3.8 compatibility and Windows path, encoding, locking, and command-line behavior.
- Never stage `.mae-flow.json`, `.mae-flow.json.failures`, or unrelated user files.

---

### Task 1: Typed startup configuration and repository defaults

**Files:**
- Modify: `scripts/mae_flow_core/orchestration/models.py`
- Modify: `scripts/mae_flow_core/orchestration/state_schema.py`
- Create: `scripts/mae_flow_core/orchestration/startup_config.py`
- Modify: `scripts/mae_flow_core/cli_parser.py`
- Modify: `scripts/mae_flow_core/cli_commands/lean_workflow.py`
- Modify: `scripts/mae_flow_core/orchestration/guidance.py`
- Test: `scripts/tests/test_lean_state.py`
- Test: `scripts/tests/test_lean_cli.py`
- Test: `scripts/tests/test_windows_lean_runtime.py`

**Interfaces:**
- Produces: `StartupConfig`, `load_startup_defaults(root)`, `resolve_startup_config(root, args, current_branch, user_name)`, and `FlowState.startup_config`.
- Consumes: existing `FlowState`, strict schema-v3 state storage, Git startup facts, and `.mae-flow-defaults.json`.

- [ ] Add failing state round-trip tests for worker, ticket type, requirement source, base/working branch, Build route, UT route, and UT run entry.
- [ ] Run the focused tests and confirm failure because `FlowState` has no startup configuration.
- [ ] Implement the immutable configuration model and strict backward-compatible schema defaults.
- [ ] Add failing CLI tests for explicit arguments, Chinese legacy defaults, English defaults, CLI override precedence, derived branch naming, and one-card rendering.
- [ ] Run the CLI tests and confirm the new arguments/defaults are absent.
- [ ] Implement safe defaults loading and CLI integration without executing Build or UT commands.
- [ ] Run state, CLI, and Windows tests to green.

### Task 2: Behavior-baseline document lifecycle

**Files:**
- Modify: `scripts/mae_flow_core/orchestration/models.py`
- Modify: `scripts/mae_flow_core/orchestration/state_schema.py`
- Modify: `scripts/mae_flow_core/orchestration/documents.py`
- Create: `scripts/mae_flow_core/orchestration/behavior_baseline.py`
- Modify: `scripts/mae_flow_core/orchestration/transitions.py`
- Modify: `scripts/mae_flow_core/orchestration/guidance.py`
- Create: `skills/mae-flow/assets/BEHAVIOR-TEMPLATE.md`
- Test: `scripts/tests/test_lean_documents.py`
- Test: `scripts/tests/test_lean_transitions.py`
- Test: `scripts/tests/test_lean_semantic_scenarios.py`

**Interfaces:**
- Produces: portable behavior index/domain paths, `DomainSelection`, `DomainAction`, and semantic events for selecting and reconciling domains.
- Consumes: the existing exact delivery manifest and natural-language decision/event mechanism.

- [ ] Add failing behavior tests for index routing, business-capability domain names, missing index, incremental legacy coverage, state recovery, and `new/updated/unchanged` reconciliation.
- [ ] Run the tests and confirm failure because behavior state/actions and the template do not exist.
- [ ] Implement portable paths, small typed state facts, and non-blocking semantic events; do not parse Markdown.
- [ ] Make changed behavior/index files eligible for exact delivery while unrelated domain files remain unselected.
- [ ] Run document, transition, semantic, and Windows tests to green.

### Task 3: Correct Spec and Story ownership

**Files:**
- Modify: `scripts/mae_flow_core/orchestration/documents.py`
- Modify: `skills/mae-flow/SKILL.md`
- Modify: `agents/story-generator-agent.md`
- Modify: `skills/mae-flow/assets/STORY-TEMPLATE.md`
- Modify: `flow/phases/spec.md`
- Modify: `flow/phases/story.md`
- Modify: `runtime/guidance/story-design.md`
- Modify: `runtime/guidance/grill.md`
- Test: `scripts/tests/test_lean_documents.py`
- Test: `scripts/tests/test_native_guidance.py`
- Test: `scripts/tests/test_lean_semantic_scenarios.py`

**Interfaces:**
- Produces: local `spec.md` and `story.md` paths under one ticket work directory, conditional commit policy for both, and a standalone Story handoff contract.
- Consumes: the existing Story template sections and Full Spec confirmation.

- [ ] Add failing behavioral contract tests proving Spec and Story are local by default and only exact explicit selection makes them committable.
- [ ] Add failing guidance tests for customer scenarios, business specifications, functional acceptance criteria, software detailed design, test handoff, and the prohibition on line-by-line coding plans.
- [ ] Run focused tests and confirm current durable Spec/pure-HOW wording fails.
- [ ] Implement document ownership and update every production guidance surface consistently.
- [ ] Run document, guidance, and semantic tests to green.

### Task 4: Coherent checkpoints and cumulative UT handoff

**Files:**
- Modify: `scripts/mae_flow_core/orchestration/models.py`
- Modify: `scripts/mae_flow_core/orchestration/state_schema.py`
- Modify: `scripts/mae_flow_core/orchestration/transitions.py`
- Modify: `scripts/mae_flow_core/orchestration/guidance.py`
- Modify: `scripts/mae_flow_core/quality/ut_handoff.py`
- Modify: `skills/mae-flow/SKILL.md`
- Modify: `agents/story-generator-agent.md`
- Modify: `agents/ut-generator-agent.md`
- Modify: `runtime/guidance/construction.md`
- Modify: `runtime/guidance/quality.md`
- Test: `scripts/tests/test_lean_state.py`
- Test: `scripts/tests/test_lean_transitions.py`
- Test: `scripts/tests/test_ut_handoff.py`
- Test: `scripts/tests/test_native_guidance.py`

**Interfaces:**
- Produces: lightweight checkpoint briefs/results and ordered cumulative UT intents that survive recovery.
- Consumes: `cp-ready`, `cp-confirmed`, final Spec/Story paths, and final diff context.

- [ ] Add failing tests for CP brief/result/UT-intent recording, order preservation, recovery, next-CP display, and final UT context precedence.
- [ ] Run focused tests and confirm the state cannot represent the agreed handoff.
- [ ] Implement semantic CP events and rendering without creating a separate coding-plan artifact or mandatory report schema.
- [ ] Update Story, Construction, reviewer, and UT prompts so coding creates test seams and final UT receives cumulative intent once.
- [ ] Run state, transition, handoff, and guidance tests to green.

### Task 5: Confirmed branch and commit-format Git guard

**Files:**
- Modify: `scripts/mae_flow_core/foundation/commit_message.py`
- Modify: `scripts/mae_flow_core/guard/safety_kernel.py`
- Modify: `scripts/mae_flow_core/guard/bash.py`
- Modify: `scripts/mae_flow_core/adapters/lean_hook.py`
- Modify: `scripts/mae_flow_core/cli_commands/lean_manifest.py`
- Modify: `scripts/mae_flow_core/orchestration/delivery.py`
- Test: `scripts/tests/test_lean_safety_kernel.py`
- Test: `scripts/tests/test_lean_hook_adapter.py`
- Test: `scripts/tests/test_lean_delivery.py`
- Test: `scripts/tests/test_windows_lean_runtime.py`

**Interfaces:**
- Produces: `valid_business_commit_message(ticket, ticket_type, message)` and Hook enforcement of the confirmed working branch and exact commit prefix.
- Consumes: `FlowState.startup_config`, existing parsed Git intent, exact delivery receipt, and path manifest.

- [ ] Add failing tests proving `[ticket][wrong-type]` and commits on the wrong branch are blocked while the confirmed type/branch pass on POSIX and Windows.
- [ ] Run focused tests and confirm current validation accepts either type and has no lean working branch.
- [ ] Thread confirmed type/branch through delivery and the Hook safety context using structured state, not shell-output parsing.
- [ ] Keep failures local to the Git command; do not mutate phases or invalidate quality facts.
- [ ] Run safety, Hook, delivery, and Windows tests to green.

### Task 6: End-to-end phase guidance and recovery consistency

**Files:**
- Modify: `flow/phases/startup.md`
- Modify: `flow/phases/spec.md`
- Modify: `flow/phases/story.md`
- Modify: `flow/phases/construction.md`
- Modify: `flow/phases/quality.md`
- Modify: `flow/phases/delivery.md`
- Modify: `runtime/guidance/grill.md`
- Modify: `runtime/guidance/story-design.md`
- Modify: `runtime/guidance/construction.md`
- Modify: `runtime/guidance/review.md`
- Modify: `runtime/guidance/quality.md`
- Modify: `skills/mae-flow/SKILL.md`
- Modify: `commands/mae-flow.md`
- Test: `scripts/tests/test_native_guidance.py`
- Test: `scripts/tests/test_lean_guidance.py`
- Test: `scripts/tests/test_lean_semantic_scenarios.py`

**Interfaces:**
- Produces: one consistent production narrative from Intake through Delivery.
- Consumes: startup configuration, selected domains, final Spec/Story, CP facts, quality capability facts, and exact delivery plan.

- [ ] Add failing semantic scenarios for one Full delivery and one Focused restoration using the new state and document rules.
- [ ] Run the scenarios and confirm guidance/state gaps.
- [ ] Update all public and runtime guidance together so no dormant legacy path contradicts the production CLI.
- [ ] Confirm capability calls remain agent-recorded opaque facts; do not add proof Hooks.
- [ ] Run all lean guidance and scenario tests to green.

### Task 7: Release verification and exact commit

**Files:**
- Modify only if verification exposes a defect in an in-scope file.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: one verified exact commit and push to the requested main branch.

- [ ] Run `python3 -m unittest discover -s scripts/tests -p 'test_*.py'` and require zero failures.
- [ ] Run `python3 scripts/selftest.py` and require exit code 0.
- [ ] Run the Windows-focused suite explicitly.
- [ ] Run source scans proving no production sleep/poll loop, no new private-output parser, no directory-wide Git staging guidance, and no strict Markdown gate was introduced.
- [ ] Inspect `git diff --check`, `git status --short`, and the exact staged file list.
- [ ] Keep `.mae-flow.json` and `.mae-flow.json.failures` untracked and unstaged.
- [ ] Commit using the repository's required `[MAE-FLOW][feat|fix]description` format, re-run release verification against the committed tree, then push `main` without force.
