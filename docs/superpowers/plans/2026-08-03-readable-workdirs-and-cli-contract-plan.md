# Readable Workdirs and CLI Prompt Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make normal requirement work directories readable and guarantee that every capability prompt and CLI error exposes the exact executable state-transition command.

**Architecture:** Keep persisted schema-v3 events unchanged. Change only new path derivation, make persisted artifact paths authoritative for existing flows, and centralize capability command rendering so `current`, phase guidance, and recovery diagnostics share one grammar. Protect both surfaces with behavioral tests that execute the real parser and transition functions.

**Tech Stack:** Python 3 standard library, `unittest`, argparse, immutable dataclass workflow state.

## Global Constraints

- Work directly on `main` because the user explicitly authorized it.
- Do not rename or delete existing `.mae-flow-work` directories.
- Preserve schema-v3 phase values, capability outcomes, and stable event names.
- Never record a successful capability fact merely because an invalid alias was supplied.
- Every required CLI state change shown to an Agent must include the full launcher, event, and required arguments.
- Run all 677+ unit tests, `scripts/selftest.py`, and `git diff --check` before push.

---

### Task 1: Readable and portable requirement directory segments

**Files:**
- Modify: `scripts/tests/test_lean_documents.py`
- Modify: `scripts/mae_flow_core/orchestration/documents.py`

**Interfaces:**
- Consumes: raw requirement ticket text.
- Produces: `_safe_ticket_segment(ticket: str) -> str`, used by `local_full_artifacts` and `DocumentPaths.for_ticket`.

- [ ] **Step 1: Write failing path behavior tests**

Change the literal expectation for `REQ-42` to `REQ-42`. Add table-driven assertions that `NRPRACH支持SUL模式` and `REQ20260702112199` remain readable, while `REQ:42`, `CON`, overlong tickets, and `_mae-ticket-alias` enter the reserved `_mae-ticket-...-<sha256>` namespace. Assert exceptional paths remain within 255 UTF-16 code units and cannot collide with a literal reserved-prefix ticket.

- [ ] **Step 2: Verify RED**

Run:

```bash
python -m unittest scripts.tests.test_lean_documents.LeanDocumentPathTests
```

Expected: failures showing ordinary tickets still contain a 64-character suffix.

- [ ] **Step 3: Implement minimal deterministic naming**

Add a reserved prefix and split normal from exceptional names:

```python
_ENCODED_TICKET_PREFIX = "_mae-ticket-"

def _requires_ticket_encoding(original, normalized, safe):
    return (
        original.strip() != original
        or normalized != original
        or safe != normalized
        or safe.casefold().startswith(_ENCODED_TICKET_PREFIX.casefold())
        or safe.split(".", 1)[0].upper() in _RESERVED_WINDOWS_NAMES
        or len(safe.encode("utf-16-le")) // 2 > 255
    )
```

Return `safe` directly for normal tickets. For exceptional tickets, prepend `_mae-ticket-`, retain the full input digest, and trim only the readable middle to the Windows component limit.

- [ ] **Step 4: Verify GREEN**

Run the Task 1 command and expect all document path tests to pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/tests/test_lean_documents.py scripts/mae_flow_core/orchestration/documents.py
git commit -m "fix: keep normal workflow directories readable"
```

### Task 2: Preserve existing hashed artifact paths

**Files:**
- Modify: `scripts/tests/test_lean_grill_receipts.py`
- Modify: `scripts/mae_flow_core/cli_commands/grill_receipts.py`

**Interfaces:**
- Consumes: `FlowState.artifacts` and an artifact kind.
- Produces: `_artifact_path(root: str, state: FlowState, kind: str) -> str` and `_local_work_root(root: str, state: FlowState) -> str`.

- [ ] **Step 1: Write failing compatibility tests**

Construct a state whose ticket is `REQ-LEGACY` but whose persisted `grill`, `spec`, and `story` artifacts live under `.mae-flow-work/REQ-LEGACY-<old-full-digest>/`. Write real files there and assert Grill preparation, `grill-converged`, `grill-clear`, Spec confirmation, and Story receipt preparation read those persisted files rather than the newly derived readable directory.

- [ ] **Step 2: Verify RED**

```bash
python -m unittest scripts.tests.test_lean_grill_receipts
```

Expected: legacy-path tests fail with a missing file under `.mae-flow-work/REQ-LEGACY/`.

- [ ] **Step 3: Implement artifact-first resolution**

Resolve a matching persisted relative artifact safely beneath the repository root; otherwise use `DocumentPaths.for_ticket` as fallback. Derive `survey.md` and `grill-prep.md` from the persisted Grill artifact directory. Replace all direct `DocumentPaths.for_ticket` reads in receipt validation with these helpers.

- [ ] **Step 4: Verify GREEN**

Run the Task 2 command and expect all Grill receipt tests to pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/tests/test_lean_grill_receipts.py scripts/mae_flow_core/cli_commands/grill_receipts.py
git commit -m "fix: recover persisted workflow artifact paths"
```

### Task 3: Canonical capability command renderer and actionable errors

**Files:**
- Create: `scripts/tests/test_capability_cli_contract.py`
- Modify: `scripts/mae_flow_core/orchestration/capabilities.py`
- Modify: `scripts/mae_flow_core/cli_parser.py`
- Modify: `scripts/mae_flow_core/cli_commands/user_events.py`
- Modify: `scripts/mae_flow_core/cli_commands/lean_workflow.py`

**Interfaces:**
- Produces: `capability_record_command(kind: str, outcome: str = "returned", summary: str = "<简短不透明摘要>") -> str`.
- Produces: `capability_usage(kind: str = "") -> str` containing executable examples and the six stable kinds.
- Consumes: parse errors and invalid capability-like advance events.

- [ ] **Step 1: Write failing parser and recovery tests**

For every kind in `build`, `ut`, `codecheck`, `reviewer`, `grill`, `story` and every outcome in `returned`, `failed-to-start`, `timed-out`, `not-observed`, render a command, strip the launcher, parse it with the real `parse_args`, and assert event, key, and decision. Run the real CLI with `grill-critic-attempt`, `capability.grill-critic`, `capability-attempt --key grill`, and `capability.grill-critic --note done`; assert nonzero exit and an exact correction containing:

```text
advance capability-returned --key grill --decision "<简短不透明摘要>"
```

- [ ] **Step 2: Verify RED**

```bash
python -m unittest scripts.tests.test_capability_cli_contract
```

Expected: import failure for the missing renderer or diagnostics without the correction command.

- [ ] **Step 3: Implement the canonical renderer**

Validate kind and outcome through existing enums/constants and return the full project launcher command. Use the same renderer from argparse errors and semantic-event validation. Invalid aliases remain rejected; diagnostics become actionable. Ensure `--note` parser errors also detect capability-like argv.

- [ ] **Step 4: Verify GREEN**

Run the Task 3 command and expect every canonical command and invalid-alias recovery assertion to pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/tests/test_capability_cli_contract.py scripts/mae_flow_core/orchestration/capabilities.py scripts/mae_flow_core/cli_parser.py scripts/mae_flow_core/cli_commands/user_events.py scripts/mae_flow_core/cli_commands/lean_workflow.py
git commit -m "fix: make capability command errors actionable"
```

### Task 4: Exact commands in every capability-bearing phase

**Files:**
- Modify: `scripts/tests/test_lean_guidance.py`
- Modify: `scripts/tests/test_lean_cli.py`
- Modify: `scripts/mae_flow_core/orchestration/guidance.py`
- Modify: `flow/phases/spec.md`
- Modify: `flow/phases/story.md`
- Modify: `flow/phases/construction.md`
- Modify: `flow/phases/quality.md`
- Modify: `skills/mae-flow/SKILL.md`

**Interfaces:**
- Consumes: current `FlowState.phase` and capability slots.
- Produces: a Chinese “能力事实记录命令” card in `current`, with exact commands for the phase's capability kinds.

- [ ] **Step 1: Write failing end-to-end guidance tests**

Render each capability-bearing phase and assert its exact keys: Spec=`grill`; Story=`story`,`reviewer`; Construction=`reviewer`,`build`; Quality=`codecheck`,`ut`. Execute the Spec card's returned command against a real converged Grill state, then execute `advance grill-clear` and assert it succeeds. Assert rendered guidance contains neither `capability-<outcome>` nor `<kind>`.

- [ ] **Step 2: Verify RED**

```bash
python -m unittest scripts.tests.test_lean_guidance scripts.tests.test_lean_cli
```

Expected: failures because current phase guidance lacks exact command cards.

- [ ] **Step 3: Render exact phase commands and repair prose**

Add a phase-to-kind mapping and render all four outcome commands from the canonical renderer. Put the exact `grill/returned` command immediately before `grill-clear` in Spec guidance. Add exact story/reviewer/build/codecheck/ut mappings beside their invocation instructions. Replace generic `<kind>` and `<outcome>` capability prose in the Skill with the six stable kinds and four exact event forms.

- [ ] **Step 4: Verify GREEN**

Run the Task 4 command and expect guidance and real CLI progression tests to pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/tests/test_lean_guidance.py scripts/tests/test_lean_cli.py scripts/mae_flow_core/orchestration/guidance.py flow/phases/spec.md flow/phases/story.md flow/phases/construction.md flow/phases/quality.md skills/mae-flow/SKILL.md
git commit -m "fix: publish exact capability commands in every phase"
```

### Task 5: Global contract audit and release verification

**Files:**
- Modify only files required by concrete failures found in the audit.

**Interfaces:**
- Consumes: all public phase guidance, Skill commands, parser routes, transitions, migration, Hook, Grill, and Chain tests.
- Produces: a clean, pushed `main` with no known prompt-command drift.

- [ ] **Step 1: Run focused contracts**

```bash
python -m unittest scripts.tests.test_lean_documents scripts.tests.test_lean_grill_receipts scripts.tests.test_capability_cli_contract scripts.tests.test_lean_guidance scripts.tests.test_lean_cli scripts.tests.test_native_guidance scripts.tests.test_lean_semantic_scenarios
```

- [ ] **Step 2: Run full regression**

```bash
python -m unittest discover -s scripts/tests -p 'test_*.py'
python scripts/selftest.py
git diff --check
```

- [ ] **Step 3: Inspect release state**

```bash
git status --short --branch
git log --oneline --decorate -8
git fetch origin
git rev-list --left-right --count origin/main...HEAD
```

Resolve only concrete regressions, rerun the failing set and then rerun the full regression.

- [ ] **Step 4: Push verified commits**

```bash
git push origin main
```

- [ ] **Step 5: Verify remote parity**

```bash
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
```

Expected: clean worktree and identical local/remote hashes.
