# Hook Block Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record privacy-safe, rule-level diagnostics for Mae-Flow `PreToolUse` blocks without changing gate behavior or user-facing recovery text.

**Architecture:** Bash gate denials carry an internal rule marker from the CLI subprocess to `hooks/dispatch.py`. The dispatcher removes that marker before forwarding stderr, then writes one structured decision line containing the event, tool, source, stable rule, and SHA-256 of the Bash command. Direct Hook denials use a stable fallback rule.

**Tech Stack:** Python 3 standard library, `unittest`, subprocess-based Hook integration tests.

## Global Constraints

- Do not add, remove, or relax any gate.
- Do not log the full Bash command, tool input, prompt, or stderr.
- Emit exactly one decision record per blocked `PreToolUse` call.
- Preserve the existing user-facing recovery message.
- Preserve fail-open behavior for Hook and CLI failures.

---

### Task 1: Structured PreToolUse block diagnostics

**Files:**
- Create: `scripts/tests/test_hook_block_diagnostics.py`
- Modify: `scripts/mae_flow_core/guard/bash.py`
- Modify: `scripts/mae_flow_core/cli_commands/gate.py`
- Modify: `scripts/mae_flow_core/cli_commands/gate_permit_state.py`
- Create: `scripts/mae_flow_core/adapters/hook_diagnostics.py`
- Modify: `hooks/dispatch.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `GateDecision.kind`, `GateDecision.rule`, `HookResponse.exit_code`, and the Hook payload fields `tool_name` and `tool_input.command`.
- Produces: one log line in the form `decision event=pretooluse tool=<tool> result=blocked source=mae-flow rule=<rule> command_sha256=<sha256>`.

- [ ] **Step 1: Write failing integration tests**

Create subprocess tests that:

```python
def test_blocked_bash_logs_rule_and_hash_without_command():
    command = "git add . # secret-token-123"
    result, log_text = run_pretooluse(command, active_flow=True)
    self.assertEqual(2, result.returncode)
    self.assertIn(
        "decision event=pretooluse tool=Bash result=blocked "
        "source=mae-flow rule=bash-wide-add "
        "command_sha256=7d3319b51c438fda9df539ef0b62c134"
        "b3ab1e470147919d2481670df1814379",
        log_text,
    )
    self.assertNotIn(command, log_text)

def test_allowed_bash_does_not_log_decision():
    result, log_text = run_pretooluse("git status --short", active_flow=True)
    self.assertEqual(0, result.returncode)
    self.assertNotIn(" decision event=pretooluse ", log_text)

def test_direct_hook_block_uses_stable_fallback_rule():
    result, log_text = run_standalone_pretooluse("echo harmless")
    self.assertEqual(2, result.returncode)
    self.assertIn("source=mae-flow rule=hook-policy", log_text)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python scripts/tests/test_hook_block_diagnostics.py
```

Expected: the blocked calls return 2, but assertions fail because no structured `decision` line exists.

- [ ] **Step 3: Add stable Bash rule names and internal rule markers**

Give every absolute Bash `GateDecision` a stable `rule`. Before a Bash gate exits 2, prefix its internal subprocess stderr with:

```text
[mae-flow-rule=<stable-rule>]
```

Apply the same marker to `_gate_die` decisions. The marker is transport metadata only and must not remain in forwarded user-facing stderr.

- [ ] **Step 4: Log one privacy-safe decision in the dispatcher**

Add dispatcher helpers with these contracts:

```python
def _extract_gate_rule(stderr):
    """Return (sanitized_stderr, stable_rule_or_empty)."""

def _decision_subject(payload):
    """Return Bash command text for hashing, otherwise an empty string."""

def _log_pretool_decision(payload, response, rule=""):
    """Write one structured line only for exit_code == 2."""
```

`maeflow()` stores the parsed rule for the current invocation. `main()` calls
`_log_pretool_decision` once after handling the event. Missing rules use
`hook-policy`; Bash commands are represented only by lowercase hexadecimal
SHA-256.

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run:

```bash
python scripts/tests/test_hook_block_diagnostics.py
```

Expected: all focused tests pass with no command text in the log.

- [ ] **Step 6: Run Hook and full regression suites**

Run:

```bash
python scripts/tests/test_state_core.py
python scripts/selftest.py
```

Expected: both commands exit 0 with no failed checks.

- [ ] **Step 7: Review the diff and commit**

Run:

```bash
git diff --check
git diff --stat HEAD
git status --short
```

Then commit only the plan, tests, and implementation:

```bash
git add docs/superpowers/plans/2026-07-31-hook-block-diagnostics.md \
  README.md \
  scripts/tests/test_hook_block_diagnostics.py \
  scripts/mae_flow_core/guard/bash.py \
  scripts/mae_flow_core/cli_commands/gate.py \
  scripts/mae_flow_core/cli_commands/gate_permit_state.py \
  scripts/mae_flow_core/adapters/hook_diagnostics.py \
  hooks/dispatch.py
git commit -m "feat: diagnose hook policy blocks"
```
