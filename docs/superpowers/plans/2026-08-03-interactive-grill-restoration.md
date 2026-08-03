# Interactive Grill Restoration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore a mandatory, recoverable Interactive Grill inside Full Spec and make its converged decisions a digest-bound input to Spec generation and criticism.

**Architecture:** Keep schema-v3 and the six public phases. Store Grill questions, answers, convergence, and critic receipts as append-only `FlowState.decisions`, with pure policy in a focused orchestration module and file digest preparation in a CLI adapter. Full Spec gains a local `grill.md`; Focused gains it only after `upgrade-to-full`.

**Tech Stack:** Python 3 standard library, immutable dataclasses, JSON decision payloads, SHA-256 receipts, `unittest`, Markdown guidance.

## Global Constraints

- Full must answer at least one real Interactive Grill question before Spec can converge.
- Only one question may be unanswered at a time.
- Every question carries evidence, impact, recommendation, and optional parent ID.
- `grill-answer` consumes one current `UserPromptSubmit` or `AskUserQuestion` receipt.
- Spec confirmation requires unchanged `grill.md` and `spec.md` digests plus critic coverage.
- Focused upgrades to Full before entering Grill.
- Do not add a seventh public phase or a rigid Markdown Hook parser.

---

### Task 1: Pure Interactive Grill State Policy

**Files:**
- Create: `scripts/mae_flow_core/orchestration/grill_session.py`
- Create: `scripts/tests/test_lean_grill_session.py`
- Modify: `scripts/mae_flow_core/orchestration/__init__.py`

**Interfaces:**
- Consumes: `FlowState`, `Phase`, and `AdvanceRequest`.
- Produces: `apply_grill_event(state, request) -> tuple[FlowState, bool, str] | None`, `grill_confirmation_gap(state) -> str`, and `grill_status(state) -> GrillStatus`.

- [ ] **Step 1: Write failing pure-policy tests**

Cover wrong phase/path rejection, one open question, duplicate IDs, answer-key matching, non-empty answers, at least one answer, no-open-question convergence, and critic-before-convergence rejection. Use structured metadata:

```python
question = json.dumps({
    "parent": "",
    "evidence": "接口当前只定义主载波行为。",
    "impact": "SUL 选择语义不明确。",
    "recommendation": "仅在配置 SUL 时选择 SUL 资源。",
}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
```

- [ ] **Step 2: Run the new tests and verify RED**

Run: `python -m unittest scripts.tests.test_lean_grill_session`

Expected: import failure because `grill_session` does not exist.

- [ ] **Step 3: Implement the immutable policy**

Use decision keys `grill.question.<ID>`, `grill.answer.<ID>`, `grill.convergence`, and `review.grill`. Parse JSON defensively and return an explanatory unchanged state for invalid events. `grill_status` must derive the latest effective state without mutating the tuple.

```python
@dataclass(frozen=True)
class GrillStatus:
    open_question: str
    question_ids: tuple
    answered_ids: tuple
    convergence: dict
    critic: dict


def apply_grill_event(state, request):
    kind = request.kind.strip().lower()
    if kind not in {"grill-question", "grill-answer", "grill-converged",
                    "grill-clear"}:
        return None
    # Validate Full/Spec, apply exactly one semantic event, and return
    # (updated_state, needs_user, reason).
```

- [ ] **Step 4: Run the pure-policy tests and verify GREEN**

Run: `python -m unittest scripts.tests.test_lean_grill_session`

Expected: all tests pass.

- [ ] **Step 5: Export the focused interfaces and commit**

Run:

```bash
git add scripts/mae_flow_core/orchestration/grill_session.py scripts/mae_flow_core/orchestration/__init__.py scripts/tests/test_lean_grill_session.py
git commit -m "feat: add interactive Grill state policy"
```

### Task 2: Transition and User-Event Integration

**Files:**
- Modify: `scripts/mae_flow_core/orchestration/transitions.py`
- Modify: `scripts/mae_flow_core/cli_commands/user_events.py`
- Modify: `scripts/tests/test_lean_transitions.py`
- Modify: `scripts/tests/test_lean_cli.py`

**Interfaces:**
- Consumes: `apply_grill_event`, `grill_confirmation_gap`.
- Produces: keyed `grill-question`/`grill-answer`, user-owned `grill-answer`, and a hard `spec-confirmed` Grill gate.

- [ ] **Step 1: Add failing transition tests**

Assert that `grill-clear` without interactive convergence does not create `review.grill`, `spec-confirmed` without the new receipt remains in Spec, and the complete event sequence advances:

```python
for request in (
    AdvanceRequest("grill-question", "GQ-001", question),
    AdvanceRequest("grill-answer", "GQ-001", "用户选择推荐边界。"),
    AdvanceRequest("grill-converged", decision_value=convergence_receipt),
    AdvanceRequest("grill-clear", decision_value=critic_receipt),
    AdvanceRequest("spec-confirmed", decision_value="用户确认 Spec。"),
):
    state = advance_flow(state, request).state
```

- [ ] **Step 2: Verify transition tests fail for the missing gate**

Run: `python -m unittest scripts.tests.test_lean_transitions.LeanTransitionTests scripts.tests.test_lean_cli.LeanCliTests.test_full_flow_surfaces_only_five_high_value_user_stops`

Expected: Grill events do not yet produce the required state.

- [ ] **Step 3: Delegate Grill events before generic review handling**

Call `apply_grill_event` in `advance_flow` after capability facts and before `_REVIEW_DECISIONS`. Remove `(Phase.SPEC, "grill-clear")` from the generic review map. Before the transition table handles `spec-confirmed`, return the `grill_confirmation_gap` reason when non-empty.

- [ ] **Step 4: Bind `grill-answer` to real user input**

Add `grill-answer` to `USER_OWNED_EVENTS`, add both Grill keyed events to `_KEYED_SEMANTIC_EVENTS`, and add `grill-answer` to transition `_USER_DECISION_EVENTS`. Keep `advance grill-answer` rejected by `cmd_lean_advance`; only `decision grill-answer --key <ID> <text>` may consume the answer.

- [ ] **Step 5: Update the Full CLI scenario and verify GREEN**

Run: `python -m unittest scripts.tests.test_lean_grill_session scripts.tests.test_lean_transitions scripts.tests.test_lean_cli`

Expected: all selected suites pass.

- [ ] **Step 6: Commit transition integration**

```bash
git add scripts/mae_flow_core/orchestration/transitions.py scripts/mae_flow_core/cli_commands/user_events.py scripts/tests/test_lean_transitions.py scripts/tests/test_lean_cli.py
git commit -m "feat: require interactive Grill before Spec"
```

### Task 3: Grill Artifact and Digest Receipts

**Files:**
- Modify: `scripts/mae_flow_core/orchestration/documents.py`
- Create: `scripts/mae_flow_core/cli_commands/grill_receipts.py`
- Modify: `scripts/mae_flow_core/cli_commands/lean_workflow.py`
- Modify: `scripts/tests/test_lean_documents.py`
- Create: `scripts/tests/test_lean_grill_receipts.py`
- Modify: `scripts/tests/test_lean_cli.py`

**Interfaces:**
- Consumes: `DocumentPaths.for_ticket(root, ticket)`, `AdvanceRequest`, and Grill state.
- Produces: `prepare_grill_request(root, state, request) -> AdvanceRequest` and `validate_spec_confirmation(root, state) -> str`.

- [ ] **Step 1: Add failing document and digest tests**

Require `DocumentPaths.local_grill`, a `("grill", path)` Full artifact, SHA-256 convergence payloads, critic receipts containing current Grill and Spec digests, and mutation detection for either file.

- [ ] **Step 2: Run digest tests and verify RED**

Run: `python -m unittest scripts.tests.test_lean_documents scripts.tests.test_lean_grill_receipts`

Expected: missing path and receipt helper failures.

- [ ] **Step 3: Add the local artifact path**

Add `.mae-flow-work/<safe-ticket>/grill.md` to `local_full_artifacts` and `DocumentPaths.local_grill`. Do not add a durable `grill.md`; the confirmed Spec carries durable behavior and the Grill remains local evidence.

- [ ] **Step 4: Implement exact file receipts**

Use binary SHA-256 and reject absent/empty files:

```python
def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()
```

`grill-converged` replaces its decision value with JSON containing `grill_sha256` and `answer_count`. `grill-clear` records `grill_sha256`, `spec_sha256`, and `input_coverage: "complete"`. `validate_spec_confirmation` recomputes both hashes and returns a Chinese diagnostic on mismatch.

- [ ] **Step 5: Integrate receipt preparation into both CLI paths**

In `cmd_lean_advance`, prepare Grill requests before `_advance_state`. In `cmd_lean_decision`, validate current file receipts immediately before `spec-confirmed`. Keep pure transitions free of filesystem I/O.

- [ ] **Step 6: Verify artifact and CLI tests GREEN**

Run: `python -m unittest scripts.tests.test_lean_documents scripts.tests.test_lean_grill_receipts scripts.tests.test_lean_cli`

Expected: all tests pass, including mutations after criticism.

- [ ] **Step 7: Commit digest-bound artifacts**

```bash
git add scripts/mae_flow_core/orchestration/documents.py scripts/mae_flow_core/cli_commands/grill_receipts.py scripts/mae_flow_core/cli_commands/lean_workflow.py scripts/tests/test_lean_documents.py scripts/tests/test_lean_grill_receipts.py scripts/tests/test_lean_cli.py
git commit -m "feat: bind Spec to Grill results"
```

### Task 4: Production Guidance and Semantic Coverage

**Files:**
- Modify: `flow/phases/spec.md`
- Modify: `runtime/guidance/grill.md`
- Modify: `agents/grill-critic-agent.md`
- Modify: `skills/mae-flow/SKILL.md`
- Modify: `commands/mae-flow.md`
- Modify: `scripts/tests/test_lean_semantic_scenarios.py`
- Modify: `scripts/tests/test_native_guidance.py`
- Modify: `scripts/tests/test_architecture.py`

**Interfaces:**
- Consumes: the Grill event protocol and `grill.md`/`spec.md` paths.
- Produces: main-Agent instructions, critic input contract, and refactor-regression assertions.

- [ ] **Step 1: Add failing semantic assertions**

Assert that production guidance says Interactive Grill precedes Spec generation, one question is asked at a time, Grill answers are key Spec input, traceability maps `GQ-*` to Spec acceptance, and the critic reads both files. Assert the old phrase “main Agent drafts the candidate Spec, then critic” is absent.

- [ ] **Step 2: Verify semantic assertions RED**

Run: `python -m unittest scripts.tests.test_lean_semantic_scenarios scripts.tests.test_native_guidance scripts.tests.test_architecture`

Expected: guidance-order and traceability assertions fail.

- [ ] **Step 3: Rewrite the Spec and Grill guidance**

Document the evidence scan, numbered one-at-a-time questions, derived branches, `grill.md`, convergence, Spec generation, and later read-only coverage critic. State that a corrected Spec digest is a new critic context but automatic retry is forbidden.

- [ ] **Step 4: Strengthen the critic contract**

Require the critic to read request, baseline, `grill.md`, `spec.md`, and relevant code facts. Its clear result must explicitly state complete Grill-input coverage; unresolved branches return to the main Agent.

- [ ] **Step 5: Verify guidance suites GREEN and commit**

Run: `python -m unittest scripts.tests.test_lean_semantic_scenarios scripts.tests.test_native_guidance scripts.tests.test_architecture`

```bash
git add flow/phases/spec.md runtime/guidance/grill.md agents/grill-critic-agent.md skills/mae-flow/SKILL.md commands/mae-flow.md scripts/tests/test_lean_semantic_scenarios.py scripts/tests/test_native_guidance.py scripts/tests/test_architecture.py
git commit -m "docs: restore Interactive Grill workflow"
```

### Task 5: Full Grill Verification

**Files:**
- Modify only files required by a discovered regression.

**Interfaces:**
- Consumes: all Grill tasks.
- Produces: release verification evidence.

- [ ] **Step 1: Run targeted suites**

Run: `python -m unittest scripts.tests.test_lean_grill_session scripts.tests.test_lean_grill_receipts scripts.tests.test_lean_transitions scripts.tests.test_lean_cli scripts.tests.test_lean_semantic_scenarios scripts.tests.test_architecture`

- [ ] **Step 2: Run all unit tests**

Run: `python -m unittest discover -s scripts/tests -p 'test_*.py'`

- [ ] **Step 3: Run release selftest**

Run: `python scripts/selftest.py`

Expected: `全部通过 30 项`.

- [ ] **Step 4: Check whitespace and repository state**

Run: `git diff --check && git status --short --branch`

- [ ] **Step 5: Commit any test-only corrections**

If verification required tracked corrections, add only those exact files and commit with `test: complete Interactive Grill coverage`. If no corrections were required, leave the tree unchanged.

