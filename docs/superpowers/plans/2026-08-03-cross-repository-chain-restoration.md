# Cross-Repository Chain Restoration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore Chain as a recoverable cross-repository investigation, contract, validation, review, and handoff workflow with no delivery or Git effects.

**Architecture:** Replace only the `chain` one-shot route with a dedicated Chain domain and CLI lifecycle. Persist one pointer and one ticket-local immutable state, capture user answers against that state digest, allow exact Chain-document writes, and keep all referenced repositories read-only. Other toolbox actions remain stateless.

**Tech Stack:** Python 3 standard library, frozen dataclasses, schema-1 Chain JSON, atomic JSON writes, SHA-256 receipts, Hook adapters, `argparse`, `unittest`, Markdown.

## Global Constraints

- Chain requires at least two repositories.
- Each repository is inspected through keyword, interface-call-chain, and config-routing evidence angles.
- Questions are asked one at a time with evidence, impact, and recommendation.
- Every interface contract has non-empty shape, fields, and error semantics.
- Every repository passes an independent-start reverse check.
- Every cited path/file/symbol is verified before confirmation.
- Chain never edits business code, starts repository delivery, commits, or pushes.
- The confirmed document contains a self-contained launch card per repository.

---

### Task 1: Pure Chain Domain and Schema

**Files:**
- Create: `scripts/mae_flow_core/orchestration/chain_session.py`
- Create: `scripts/tests/test_lean_chain_session.py`
- Modify: `scripts/mae_flow_core/orchestration/__init__.py`

**Interfaces:**
- Produces: `ChainState`, `ChainRequest`, `ChainResult`, `decode_chain_state(raw)`, `encode_chain_state(state)`, `advance_chain(state, request)`, and `chain_completion_gaps(state)`.

- [ ] **Step 1: Add failing domain tests**

Test schema validation, duplicate repository/path rejection, three evidence angles, one open question, matching answer, complete contract fields, dependency facts, reverse checks, citation verification, rendered digest, confirmation invalidation, and terminal exit.

- [ ] **Step 2: Verify RED**

Run: `python -m unittest scripts.tests.test_lean_chain_session`

Expected: import failure because the Chain domain does not exist.

- [ ] **Step 3: Implement append-only typed records**

Use a small state rather than nested mutable dictionaries:

```python
@dataclass(frozen=True)
class ChainRecord:
    kind: str
    key: str
    value: str


@dataclass(frozen=True)
class ChainState:
    ticket: str
    request: str
    requirement_source: str
    anchor_root: str
    document_path: str
    status: str = "active"
    records: tuple = ()
    decisions: tuple = ()
```

`advance_chain` recognizes `repository`, `touchpoint`, `question`, `answer`, `contract`, `dependency`, `reverse-check`, `citations-verified`, `rendered`, `confirmed`, and `exit`. Any material record after rendering removes rendered/confirmation records before appending the new fact.

- [ ] **Step 4: Verify GREEN and commit**

Run: `python -m unittest scripts.tests.test_lean_chain_session`

```bash
git add scripts/mae_flow_core/orchestration/chain_session.py scripts/mae_flow_core/orchestration/__init__.py scripts/tests/test_lean_chain_session.py
git commit -m "feat: add recoverable Chain domain"
```

### Task 2: Chain Persistence and CLI Lifecycle

**Files:**
- Create: `scripts/mae_flow_core/cli_commands/chain_workflow.py`
- Modify: `scripts/mae_flow_core/cli_parser.py`
- Modify: `scripts/mae_flow_core/command_dispatch.py`
- Modify: `scripts/mae_flow_core/cli_runtime.py`
- Modify: `scripts/mae_flow_core/cli_commands/lean_workflow.py`
- Create: `scripts/tests/test_lean_chain_cli.py`
- Modify: `scripts/tests/test_lean_toolbox.py`

**Interfaces:**
- Consumes: Chain domain, `ProjectStateLock`, `atomic_write_json`, `safe_read_json`, and `DocumentPaths` ticket normalization.
- Produces: `cmd_lean_chain(root, args)`, `.mae-flow-work/chain-current.json`, and `.mae-flow-work/<safe-ticket>/chain-state.json`.

- [ ] **Step 1: Add failing CLI routing tests**

Cover `chain start`, `chain current`, record events, `chain answer`, `chain confirm`, `chain exit`, corrupt pointer/state, second active Chain, and active `.mae-flow.json` rejection. Assert `chain` is no longer accepted by `ToolboxRequest`.

- [ ] **Step 2: Verify RED**

Run: `python -m unittest scripts.tests.test_lean_chain_cli scripts.tests.test_lean_toolbox`

Expected: parser and route failures.

- [ ] **Step 3: Add nested Chain parser commands**

Define:

```text
chain start --ticket T --request TEXT --requirement PATH
chain current
chain record <repository|touchpoint|contract|dependency|reverse-check> --key K --value JSON
chain question --key CQ-001 --value JSON
chain answer --key CQ-001 TEXT
chain verify
chain rendered
chain confirm TEXT
chain exit --reason TEXT
```

Keep these commands internal to the Agent; user-facing guidance remains natural language.

- [ ] **Step 4: Implement atomic pointer/state ownership**

The pointer contains `{"schema_version":1,"state":"<repo-relative path>"}`. Resolve it without globbing or directory scans, reject absolute/traversal paths, lock the anchor root for every mutation, and write state before pointer on start. Exit atomically archives the state under `.mae-flow-work/chain-exited/` and removes only the pointer.

- [ ] **Step 5: Implement record and completion adapters**

`chain verify` resolves repository roots from repository records, checks every cited file with `os.path.isfile`, checks non-empty symbols exist in decoded file text, and records one digest of the verified citations. `chain rendered` reads exact `chain.md`, rejects empty content, and records its SHA-256. `chain confirm` calls domain completeness checks before applying the user decision.

- [ ] **Step 6: Verify GREEN and commit**

Run: `python -m unittest scripts.tests.test_lean_chain_session scripts.tests.test_lean_chain_cli scripts.tests.test_lean_toolbox`

```bash
git add scripts/mae_flow_core/cli_commands/chain_workflow.py scripts/mae_flow_core/cli_parser.py scripts/mae_flow_core/command_dispatch.py scripts/mae_flow_core/cli_runtime.py scripts/mae_flow_core/cli_commands/lean_workflow.py scripts/tests/test_lean_chain_cli.py scripts/tests/test_lean_toolbox.py
git commit -m "feat: add Chain CLI lifecycle"
```

### Task 3: Chain User Receipts and Hook Runtime

**Files:**
- Modify: `scripts/mae_flow_core/cli_commands/user_events.py`
- Modify: `scripts/mae_flow_core/adapters/lean_hook.py`
- Create: `scripts/mae_flow_core/guard/chain_safety.py`
- Modify: `scripts/tests/test_lean_hook_adapter.py`
- Modify: `scripts/tests/test_lean_chain_cli.py`
- Create: `scripts/tests/test_lean_chain_safety.py`

**Interfaces:**
- Produces: `matching_user_event(root, state, state_path=None)`, Chain Hook recovery, and `decide_chain_pretool(root, chain_state, tool, tool_input)`.

- [ ] **Step 1: Add failing receipt and safety tests**

Prove both user event sources bind to the Chain state digest, one answer cannot be reused, an event from an older Chain state is rejected, exact `chain.md` Write/Edit is allowed, business-code Write/Edit is blocked, recursive deletion is blocked, and Git commit/push is blocked.

- [ ] **Step 2: Verify RED**

Run: `python -m unittest scripts.tests.test_lean_chain_safety scripts.tests.test_lean_hook_adapter scripts.tests.test_lean_chain_cli`

Expected: Hook treats Chain as inactive and no answer is captured.

- [ ] **Step 3: Generalize user-event state binding**

Allow `_state_sha256` and `matching_user_event` to accept the exact owner-state path. Both `FlowState` and `ChainState` expose `decisions`; keep the same consumed receipt JSON and one-use rule.

- [ ] **Step 4: Detect active Chain in Lean Hook**

When `.mae-flow.json` is absent, resolve the exact Chain pointer and decode its state. Return runtime mode `chain`, record `UserPromptSubmit` and `AskUserQuestion` against the Chain state path, render a bounded recovery summary, and route pretool events to Chain safety. Corrupt Chain state fails open with a diagnostic on SessionStart and never guesses another state path.

- [ ] **Step 5: Implement Chain write and Git boundaries**

Allow direct Write/Edit/MultiEdit only for the exact normalized `document_path`. Reuse recursive-delete parsing and Git command classification so delete, commit, push, reset, and checkout effects are blocked. Allow read-only inspection commands and the exact internal Mae-Flow Chain CLI.

- [ ] **Step 6: Consume receipts in Chain answer/confirm and verify GREEN**

Run: `python -m unittest scripts.tests.test_lean_chain_safety scripts.tests.test_lean_hook_adapter scripts.tests.test_lean_chain_cli`

- [ ] **Step 7: Commit Hook integration**

```bash
git add scripts/mae_flow_core/cli_commands/user_events.py scripts/mae_flow_core/adapters/lean_hook.py scripts/mae_flow_core/guard/chain_safety.py scripts/tests/test_lean_hook_adapter.py scripts/tests/test_lean_chain_cli.py scripts/tests/test_lean_chain_safety.py
git commit -m "feat: bind Chain decisions to user input"
```

### Task 4: Chain Guidance, Template, and Launch Cards

**Files:**
- Modify: `skills/mae-flow/assets/CHAIN-TEMPLATE.md`
- Modify: `skills/mae-flow/SKILL.md`
- Modify: `commands/mae-flow.md`
- Modify: `scripts/mae_flow_core/orchestration/toolbox.py`
- Modify: `scripts/tests/test_lean_semantic_scenarios.py`
- Modify: `scripts/tests/test_architecture.py`
- Modify: `scripts/tests/test_lean_toolbox.py`

**Interfaces:**
- Consumes: Chain CLI lifecycle and artifact paths.
- Produces: complete main-Agent workflow, strengthened seven-section document, and exact per-repository launch-card contract.

- [ ] **Step 1: Add failing guidance and architecture tests**

Require repo/path inventory, `/add-dir` recommendation, the three inspection angles, one-at-a-time contract questions, exact shape/fields/error semantics, reverse check, citation verification, user review, and launch cards. Assert Chain is absent from `_KINDS`, `_TOOLBOX`, and the one-shot boundary.

- [ ] **Step 2: Verify RED**

Run: `python -m unittest scripts.tests.test_lean_semantic_scenarios scripts.tests.test_architecture scripts.tests.test_lean_toolbox`

- [ ] **Step 3: Rewrite Chain instructions and template**

Keep the seven top-level sections. In section 7 require for each repository: exact local path, starter text, recommended Full/Focused path, responsibility, contract IDs, upstream dependencies, downstream consumers, and repository-local verification boundary.

- [ ] **Step 4: Remove Chain from stateless toolbox**

Delete Chain from `_KINDS`, `_TOOLBOX`, `_chain_guidance`, and generic toolbox dispatch while retaining UT, CodeCheck, standalone Grill, and Story as one-shot actions.

- [ ] **Step 5: Verify GREEN and commit**

Run: `python -m unittest scripts.tests.test_lean_semantic_scenarios scripts.tests.test_architecture scripts.tests.test_lean_toolbox scripts.tests.test_lean_chain_cli`

```bash
git add skills/mae-flow/assets/CHAIN-TEMPLATE.md skills/mae-flow/SKILL.md commands/mae-flow.md scripts/mae_flow_core/orchestration/toolbox.py scripts/tests/test_lean_semantic_scenarios.py scripts/tests/test_architecture.py scripts/tests/test_lean_toolbox.py
git commit -m "docs: restore complete cross-repository Chain"
```

### Task 5: Full Chain Verification

**Files:**
- Modify only files required by a discovered regression.

**Interfaces:**
- Produces: complete release verification evidence for Chain.

- [ ] **Step 1: Run all Chain and Hook suites**

Run: `python -m unittest scripts.tests.test_lean_chain_session scripts.tests.test_lean_chain_cli scripts.tests.test_lean_chain_safety scripts.tests.test_lean_hook_adapter scripts.tests.test_lean_semantic_scenarios scripts.tests.test_architecture`

- [ ] **Step 2: Run all unit tests**

Run: `python -m unittest discover -s scripts/tests -p 'test_*.py'`

- [ ] **Step 3: Run release selftest**

Run: `python scripts/selftest.py`

Expected: `全部通过 30 项`.

- [ ] **Step 4: Check final diff and state**

Run: `git diff --check && git status --short --branch`

- [ ] **Step 5: Commit any exact verification corrections**

If tracked corrections were necessary, commit only those files with `test: complete Chain restoration coverage`. If none were necessary, create no extra commit.

