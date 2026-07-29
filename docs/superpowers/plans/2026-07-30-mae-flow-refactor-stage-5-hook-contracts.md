# Mae-Flow Stage 5 Hook Agent Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Hook transcript interpretation, Agent report contracts, receipts, and event orchestration into independently tested core modules while preserving every observable behavior.

**Architecture:** Pure modules under `mae_flow_core.quality` interpret transcripts and decide COMPILE/CODECHECK/UT/GRILL contracts. `mae_flow_core.application.hooks` verifies task cards, manages receipts, and sequences Hook effects through explicit ports; `hooks/dispatch.py` remains the protocol and platform adapter.

**Tech Stack:** Python 3 standard library, immutable dataclasses, `unittest`, deterministic differential snapshots, AST architecture gates.

## Global Constraints

- Phase-14 golden keys and values are immutable; Phase-15 may only append scenarios.
- Hook exit codes remain 0 for allow/fail-open and 2 for a contract/gate rejection.
- Existing Chinese stdout/stderr text, state/sidecar schema, task-card hash, receipt binding, and effect order remain byte-compatible.
- Complete-flow and standalone safety boundaries remain distinct.
- `hooks/dispatch.py` must be at most 800 lines after this stage.
- New business modules must be at most 500 lines and each function's cyclomatic complexity at most 15.
- No application module may directly call `open`, `subprocess`, `chdir`, `print`, or `sys.exit`.
- Reproducible defects require a failing regression, findings entry, and separate `fix:` commit.
- Do not push remote; integration is local only.

---

### Task 1: Establish the Phase-15 Hook oracle

**Files:**
- Create: `scripts/tests/differential/stage5_hook_scenarios.py`
- Create: `scripts/tests/differential/goldens/phase15.json`
- Modify: `scripts/tests/differential/scenarios.py`
- Modify: `scripts/tests/differential/coverage.json`
- Modify: `scripts/tests/differential/runner.py`
- Modify: `scripts/tests/test_differential_harness.py`
- Modify: `scripts/tests/test_refactor_completion.py`

**Interfaces:**
- Consumes: `fixed_hook(implementation_root, env, event, payload)` and deterministic repository fixtures.
- Produces: `STAGE5_HOOK_SCENARIOS`, registered `SCENARIOS`, and Phase-15 snapshots consumed by every later task.

- [ ] **Step 1: Write failing registration and preservation tests**

Add `STAGE5_HOOK_SCENARIOS` with at least:

```python
STAGE5_HOOK_SCENARIOS = {
    "hook_compile_missing_execution",
    "hook_ut_zero_tests",
    "hook_grill_without_read",
    "hook_task_card_tampered",
    "hook_stop_moonlight_blocks",
}
```

Assert Phase-15 preserves every Phase-14 value and adds exactly this set.

- [ ] **Step 2: Run the differential harness and verify RED**

Run:

```bash
python3 scripts/tests/test_differential_harness.py
```

Expected: FAIL because Phase-15 and the new scenario module do not exist.

- [ ] **Step 3: Add deterministic Hook fixtures and capture Phase-15**

Create real flow/task-card/transcript fixtures. Invoke public `dispatch.py` events, record stdout,
stderr, exit code, state, sidecars, artifacts, and Git state. Copy Phase-14 unchanged, then append
only the new scenario snapshots.

- [ ] **Step 4: Run the harness and coverage checks**

Run:

```bash
python3 scripts/tests/test_differential_harness.py
python3 scripts/tests/test_refactor_completion.py
python3 scripts/tests/differential/runner.py --implementation-root .
```

Expected: PASS with zero differential.

- [ ] **Step 5: Commit the immutable oracle**

```bash
git add scripts/tests/differential scripts/tests/test_differential_harness.py scripts/tests/test_refactor_completion.py
git commit -m "test: characterize hook agent contracts"
```

### Task 2: Extract transcript and report parsing

**Files:**
- Create: `scripts/mae_flow_core/quality/tool_transcript.py`
- Create: `scripts/mae_flow_core/quality/agent_reports.py`
- Create: `scripts/tests/test_hook_tool_transcript.py`
- Create: `scripts/tests/test_hook_agent_reports.py`
- Modify: `scripts/tests/selftest_suites.py`
- Modify: `hooks/dispatch.py`

**Interfaces:**
- Produces: `ToolCall`, `Transcript`, `parse_transcript(lines)`,
  `select_contract_marker(text)`, `call_failed(call)`, `skill_call(calls, wanted)`,
  `bash_call(calls, expected)`, `bash_calls(calls, expected)`,
  `report_field(report, name)`, `report_number(report, name)`,
  `report_section(report, name)`, `empty_section(value)`, and
  `ac_coverage_has_mapping(value)`.
- Consumes: JSONL entries already decoded by the Hook file adapter.

- [ ] **Step 1: Write characterization tests**

Cover tool_use/tool_call, tool_result/tool_response, list/string results, missing IDs,
`is_error`/`isError`, result-seen semantics, Skill name normalization, Bash segments, duplicate
equal markers, contradictory markers, fields on one line, Markdown bullets/tables, and Chinese
empty/zero phrases.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
python3 scripts/tests/test_hook_tool_transcript.py
python3 scripts/tests/test_hook_agent_reports.py
```

Expected: import failure for the new modules.

- [ ] **Step 3: Implement immutable parsers and switch callers**

Use frozen dataclasses:

```python
@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    input: object
    result_seen: bool
    is_error: bool
    result: str

@dataclass(frozen=True)
class ContractMarker:
    kind: str
    status: str
    error: str = ""
```

Keep a temporary mapping wrapper in `dispatch.py` only where old trace persistence still requires
dict rows.

- [ ] **Step 4: Run focused, Phase-15, and architecture tests**

```bash
python3 scripts/tests/test_hook_tool_transcript.py
python3 scripts/tests/test_hook_agent_reports.py
python3 scripts/tests/test_differential_harness.py
python3 scripts/tests/test_architecture.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/mae_flow_core/quality scripts/tests hooks/dispatch.py
git commit -m "refactor: extract hook transcript parsing"
```

### Task 3: Extract task-card and source-scope contracts

**Files:**
- Create: `scripts/mae_flow_core/application/hooks/__init__.py`
- Create: `scripts/mae_flow_core/application/hooks/models.py`
- Create: `scripts/mae_flow_core/application/hooks/task_cards.py`
- Create: `scripts/tests/test_hook_task_card_contracts.py`
- Modify: `scripts/tests/selftest_suites.py`
- Modify: `hooks/dispatch.py`

**Interfaces:**
- Produces: `HookResponse(exit_code, stdout, stderr)`, `TaskCardFacts`,
  `TaskCardPorts`, `verify_dispatch_task(kind, state, ports)`,
  `verify_completion_task(kind, report, state, ports)`, and
  `verify_agent_scope(kind, task, source_facts)`.
- Consumes: state/task dictionaries and explicit callbacks for current HEAD, merge-base, task-card
  text, source snapshot, changed paths, and fingerprints.

- [ ] **Step 1: Add failing task-card tests**

Cover missing card, old step, missing/wrong report SHA, unreadable/tampered body, invalid HEAD,
amend/rebase, standalone HEAD change, precommit-review commit, initial dirty fingerprint exemption,
and out-of-scope source/test/build changes.

- [ ] **Step 2: Verify RED**

```bash
python3 scripts/tests/test_hook_task_card_contracts.py
```

Expected: import failure.

- [ ] **Step 3: Implement decisions without I/O**

Return `ContractDecision(accepted, reason, task, changed_paths)` rather than calling
`_contract_bail`. Inject all repository facts through frozen `TaskCardPorts`.

- [ ] **Step 4: Migrate dispatch tests from private helpers**

Move `_review_path_fingerprint`, `_source_snapshot`, `_source_like`,
`_enforce_agent_scope`, `_compile_net_lines`, and `_compile_agent_net` business assertions to
public core APIs. Retain only end-to-end Hook entry smoke tests.

- [ ] **Step 5: Run focused and differential tests**

```bash
python3 scripts/tests/test_hook_task_card_contracts.py
python3 scripts/tests/test_checkpoints.py
python3 scripts/tests/test_differential_harness.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/mae_flow_core/application/hooks scripts/tests hooks/dispatch.py
git commit -m "refactor: extract hook task card contracts"
```

### Task 4: Extract receipt creation and reuse

**Files:**
- Create: `scripts/mae_flow_core/application/hooks/receipts.py`
- Create: `scripts/tests/test_hook_receipts.py`
- Modify: `scripts/tests/selftest_suites.py`
- Modify: `hooks/dispatch.py`

**Interfaces:**
- Produces: `ReceiptBinding`, `ReceiptPlan`,
  `plan_codecheck_build_receipt(task, calls, config)`,
  `plan_codecheck_fullcheck_receipt(task, calls, scan)`,
  `plan_ut_receipts(task, report, calls, require_baseline)`, and
  `reusable_receipt(receipt, task, source_facts, expected_config=None)`.
- Consumes: immutable task/config/source/transcript values; persistence remains behind a port.

- [ ] **Step 1: Add failing receipt tests**

Cover task SHA, step, action ID, HEAD, source snapshot, command/config, reported counts, successful
tool results, missing output, stale source, changed config, report retry reuse, and standalone
binding.

- [ ] **Step 2: Verify RED**

```bash
python3 scripts/tests/test_hook_receipts.py
```

Expected: import failure.

- [ ] **Step 3: Implement pure receipt plans and adapt persistence**

Do not write state from the planner. Return ordered receipt mutations that
`application/hooks/agent_completion.py` will later persist through ports.

- [ ] **Step 4: Run focused and Phase-15 tests**

```bash
python3 scripts/tests/test_hook_receipts.py
python3 scripts/tests/test_differential_harness.py
python3 scripts/tests/test_codecheck_logging.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/mae_flow_core/application/hooks scripts/tests hooks/dispatch.py
git commit -m "refactor: extract hook quality receipts"
```

### Task 5: Extract COMPILE and GRILL contracts

**Files:**
- Create: `scripts/mae_flow_core/quality/compile_contract.py`
- Create: `scripts/mae_flow_core/quality/grill_contract.py`
- Create: `scripts/tests/test_hook_compile_contract.py`
- Create: `scripts/tests/test_hook_grill_contract.py`
- Modify: `scripts/tests/selftest_suites.py`
- Modify: `hooks/dispatch.py`

**Interfaces:**
- Produces: `evaluate_compile_contract(context) -> ContractDecision` and
  `evaluate_grill_contract(context) -> ContractDecision`.
- Consumes: `AgentContractContext(status, report, task, config, calls, source_facts, reusable_receipts)`.

- [ ] **Step 1: Add failing pure contract tests**

COMPILE covers OK/BLOCKED/FAIL, configured Skill/Bash proof, failed tools, missing or contradictory
BUILD_ERRORS, net source deletion, and SHRINK_EXEMPT. GRILL covers CLEAR/GAPS/FAIL, successful
Read/Grep/Glob, STAGE matching, GAPS_FOUND, and MISSING_BRANCHES.

- [ ] **Step 2: Verify RED**

```bash
python3 scripts/tests/test_hook_compile_contract.py
python3 scripts/tests/test_hook_grill_contract.py
```

- [ ] **Step 3: Implement pure evaluators and replace dispatch branches**

Preserve exact rejection strings as decision reasons; keep Git line-count facts in the Hook port
adapter, not the domain evaluator.

- [ ] **Step 4: Run focused, entry, and differential tests**

```bash
python3 scripts/tests/test_hook_compile_contract.py
python3 scripts/tests/test_hook_grill_contract.py
python3 scripts/tests/test_checkpoints.py
python3 scripts/tests/test_differential_harness.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/mae_flow_core/quality scripts/tests hooks/dispatch.py
git commit -m "refactor: extract compile and grill contracts"
```

### Task 6: Extract CodeCheck contract

**Files:**
- Create: `scripts/mae_flow_core/quality/codecheck_contract.py`
- Create: `scripts/tests/test_hook_codecheck_contract.py`
- Modify: `scripts/tests/selftest_suites.py`
- Modify: `hooks/dispatch.py`

**Interfaces:**
- Produces: `evaluate_codecheck_contract(context) -> ContractDecision` with ordered build/fullcheck
  receipt plans and a structured accepted trace summary.
- Consumes: task/config/report/transcript/source facts, Stage-4 scan facts, and reusable receipts.

- [ ] **Step 1: Add failing contract tests**

Cover status vocabulary, EXECUTED_BUILD/EXECUTED_COMMAND, configured Skill/Bash proof, failed calls,
FOUND/FIXED/REMAINING_COUNT arithmetic, stock-excluded counts, multi-command excerpts, scope changes,
old receipt invalidation, honest FAIL, soft retry, and missing transcript.

- [ ] **Step 2: Verify RED**

```bash
python3 scripts/tests/test_hook_codecheck_contract.py
```

- [ ] **Step 3: Implement evaluator and keep trace best-effort**

The evaluator returns no I/O side effects. `record_codecheck_agent_trace` remains best-effort and
must run before validation exactly as the current Hook does.

- [ ] **Step 4: Run focused logging and differential tests**

```bash
python3 scripts/tests/test_hook_codecheck_contract.py
python3 scripts/tests/test_codecheck_logging.py
python3 scripts/tests/test_quality_codecheck.py
python3 scripts/tests/test_differential_harness.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/mae_flow_core/quality scripts/tests hooks/dispatch.py
git commit -m "refactor: extract codecheck agent contract"
```

### Task 7: Extract UT contract

**Files:**
- Create: `scripts/mae_flow_core/quality/unit_test_contract.py`
- Create: `scripts/tests/test_hook_unit_test_contract.py`
- Modify: `scripts/tests/selftest_suites.py`
- Modify: `hooks/dispatch.py`

**Interfaces:**
- Produces: `evaluate_unit_test_contract(context) -> ContractDecision` with UT generator/run/baseline
  receipt plans.
- Consumes: configured generator and test command, report, normalized calls, source changes, and
  reusable receipts.

- [ ] **Step 1: Add failing contract tests**

Cover PASS/NEEDS_INPUT/FAIL, required Skill, exact reported Bash match, filters, shell failure
swallowing, mutation before baseline, non-running output, observed/reported counts, retry receipt
binding, pending/failure/bug sections, EARS mapping, number equality, and zero-test rejection.

- [ ] **Step 2: Verify RED**

```bash
python3 scripts/tests/test_hook_unit_test_contract.py
```

- [ ] **Step 3: Implement evaluator and replace dispatch policy**

Keep report parser and shell interpretation in the shared pure modules. Preserve exact risk and
accept-risk wording.

- [ ] **Step 4: Run focused and Phase-15 tests**

```bash
python3 scripts/tests/test_hook_unit_test_contract.py
python3 scripts/tests/test_hook_receipts.py
python3 scripts/tests/test_differential_harness.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/mae_flow_core/quality scripts/tests hooks/dispatch.py
git commit -m "refactor: extract unit test agent contract"
```

### Task 8: Extract SubagentStop completion orchestration

**Files:**
- Create: `scripts/mae_flow_core/application/hooks/agent_completion.py`
- Create: `scripts/tests/test_hook_agent_completion.py`
- Modify: `scripts/tests/selftest_suites.py`
- Modify: `hooks/dispatch.py`

**Interfaces:**
- Produces: `handle_agent_completion(request, ports) -> HookResponse`.
- Consumes: `AgentCompletionRequest(retry, transcript_path, standalone_kind)` and `HookPorts` for
  transcript reads, state facts, trace, receipt/token/rejection/autopsy persistence, and logging.

- [ ] **Step 1: Add failing orchestration tests**

Cover transcript path selection, unreadable transcript fail-open, unrelated subagent bypass,
standalone kind filtering, equal/contradictory markers, non-first-line marker, CodeCheck trace order,
valid token issuance, rejection persistence, soft retry no-loop behavior, and autopsy clue wording.

- [ ] **Step 2: Verify RED**

```bash
python3 scripts/tests/test_hook_agent_completion.py
```

- [ ] **Step 3: Implement orchestration with fakeable ports**

Use a dispatch table:

```python
CONTRACTS = {
    "COMPILE": evaluate_compile_contract,
    "CODECHECK": evaluate_codecheck_contract,
    "UT": evaluate_unit_test_contract,
    "GRILL": evaluate_grill_contract,
}
```

Apply receipt mutations before token issuance and never issue a token after a rejected decision.

- [ ] **Step 4: Delete migrated SubagentStop policy from dispatch**

Remove `_field`, `_flex_field`, `_number_field`, `_task_card_contract`, transcript parsers, receipt
planners, `_compile_contract`, `_codecheck_contract`, `_ut_contract`, and `_grill_contract`.

- [ ] **Step 5: Run focused, Phase-15, and full unittest**

```bash
python3 scripts/tests/test_hook_agent_completion.py
python3 scripts/tests/test_differential_harness.py
python3 -m unittest discover -s scripts/tests -p 'test_*.py'
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/mae_flow_core scripts/tests hooks/dispatch.py
git commit -m "refactor: extract agent completion orchestration"
```

### Task 9: Extract Hook event routing and slim the entry

**Files:**
- Create: `scripts/mae_flow_core/application/hooks/events.py`
- Create: `scripts/mae_flow_core/application/hooks/event_policies.py`
- Create: `scripts/mae_flow_core/application/hooks/runtime.py`
- Create: `scripts/tests/test_hook_events.py`
- Create: `scripts/tests/test_hook_protocol.py`
- Modify: `scripts/tests/selftest_suites.py`
- Modify: `scripts/tests/test_architecture.py`
- Modify: `scripts/tests/refactor_completion_contract.json`
- Modify: `hooks/dispatch.py`

**Interfaces:**
- Produces: `handle_hook_event(request, runtime, ports) -> HookResponse`,
  `stop_decision(state, active, guard)`, `template_decision(path, template, document)`, and
  `dispatch_task_decision(kind, state, task_facts)`.
- Consumes: decoded payload, resolved Runtime, and Hook ports for existing state/file/process/log
  operations.

- [ ] **Step 1: Add failing routing and protocol tests**

Cover ACTIVE/STANDALONE/DIRECT/INACTIVE/CORRUPT/terminal for all six events, runtime conflicts,
AskUserQuestion, Edit/Bash gate delegation, Agent write tracking, template placeholders,
direct-mode answer capture, Stop progress/retry/fail-open, BOM/GB18030, stdin timeout, watchdog
setup, and unexpected-exception fail-open.

- [ ] **Step 2: Verify RED**

```bash
python3 scripts/tests/test_hook_events.py
python3 scripts/tests/test_hook_protocol.py
```

- [ ] **Step 3: Implement named event use cases**

Keep all I/O behind `HookPorts`; use explicit response values rather than `print`/`sys.exit`.
Preserve the main routing order from `dispatch.py`.

- [ ] **Step 4: Reduce dispatch to the protocol adapter**

Delete migrated event functions and helpers. Keep decode/read/watchdog/root/port assembly/main only.
Add architecture assertions:

```python
self.assertLessEqual(line_count("hooks/dispatch.py"), 800)
self.assertFalse(migrated_private_names & top_level_functions("hooks/dispatch.py"))
```

- [ ] **Step 5: Run entry, architecture, differential, and full unittest**

```bash
python3 scripts/tests/test_hook_events.py
python3 scripts/tests/test_hook_protocol.py
python3 scripts/tests/test_architecture.py
python3 scripts/tests/test_differential_harness.py
python3 -m unittest discover -s scripts/tests -p 'test_*.py'
```

Expected: PASS and `hooks/dispatch.py` at most 800 lines.

- [ ] **Step 6: Commit**

```bash
git add hooks/dispatch.py scripts/mae_flow_core scripts/tests
git commit -m "refactor: reduce hook to protocol adapter"
```

### Task 10: Remove private-monolith test coupling

**Files:**
- Modify: `scripts/tests/test_checkpoints.py`
- Modify: `scripts/tests/test_codecheck_logging.py`
- Modify: `scripts/tests/test_architecture.py`
- Modify: `scripts/tests/refactor_completion_contract.json`

**Interfaces:**
- Consumes: public APIs created in Tasks 2–9.
- Produces: zero business tests that dynamically import private `hooks/dispatch.py` functions;
  architecture gates that prevent reintroduction.

- [ ] **Step 1: Add an AST failure for private Hook imports**

Detect `spec_from_file_location`, `run_path`, or importlib loading of `hooks/dispatch.py` in business
tests, with an allowlist containing only `test_hook_protocol.py`.

- [ ] **Step 2: Verify RED against remaining legacy tests**

```bash
python3 scripts/tests/test_architecture.py
```

Expected: FAIL listing each remaining private Hook consumer.

- [ ] **Step 3: Move assertions to public core APIs**

Replace private helper calls with `quality.*` or `application.hooks.*` APIs. Keep
`test_hook_protocol.py` limited to public process behavior.

- [ ] **Step 4: Run architecture and all Hook suites**

```bash
python3 scripts/tests/test_architecture.py
python3 scripts/tests/test_hook_tool_transcript.py
python3 scripts/tests/test_hook_agent_reports.py
python3 scripts/tests/test_hook_task_card_contracts.py
python3 scripts/tests/test_hook_receipts.py
python3 scripts/tests/test_hook_compile_contract.py
python3 scripts/tests/test_hook_codecheck_contract.py
python3 scripts/tests/test_hook_unit_test_contract.py
python3 scripts/tests/test_hook_grill_contract.py
python3 scripts/tests/test_hook_agent_completion.py
python3 scripts/tests/test_hook_events.py
python3 scripts/tests/test_hook_protocol.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/tests
git commit -m "test: remove private hook policy coupling"
```

### Task 11: Prove and document Stage 5 completion

**Files:**
- Modify: `docs/refactor-architecture.md`
- Modify: `docs/superpowers/mae-flow-refactor-findings.md` only if a defect was found.

**Interfaces:**
- Consumes: final Stage-5 implementation.
- Produces: fresh verification evidence and reviewer findings.

- [ ] **Step 1: Run strict Hook ResourceWarning tests**

```bash
python3 -W error::ResourceWarning -m unittest \
  scripts.tests.test_hook_tool_transcript \
  scripts.tests.test_hook_agent_reports \
  scripts.tests.test_hook_task_card_contracts \
  scripts.tests.test_hook_receipts \
  scripts.tests.test_hook_compile_contract \
  scripts.tests.test_hook_codecheck_contract \
  scripts.tests.test_hook_unit_test_contract \
  scripts.tests.test_hook_grill_contract \
  scripts.tests.test_hook_agent_completion \
  scripts.tests.test_hook_events \
  scripts.tests.test_hook_protocol
```

Expected: PASS with no warning.

- [ ] **Step 2: Run all release gates**

```bash
python3 -m unittest discover -s scripts/tests -p 'test_*.py'
python3 scripts/selftest.py
python3 scripts/tests/differential/runner.py --implementation-root .
python3 scripts/tests/test_fault_injection.py
python3 scripts/tests/test_architecture.py
python3 scripts/tests/test_refactor_completion.py
git diff --check
```

Expected: every command PASS, Phase-15 zero differential, clean warning output.

- [ ] **Step 3: Request an independent code review**

Review exact behavior parity for transcript parsing, task-card freshness, receipt invalidation,
four Agent contracts, runtime routing, Stop loop protection, Windows encoding, dependency direction,
module size, and private-monolith coupling. Fix every Critical/Important finding and rerun Step 2.

- [ ] **Step 4: Record evidence and commit**

Append exact counts, module sizes, `dispatch.py` line count, Phase-15 preservation, discovered
defects, and review disposition to the architecture/findings documents.

```bash
git add docs/refactor-architecture.md docs/superpowers/mae-flow-refactor-findings.md
git commit -m "docs: record hook contract refactor completion"
```
