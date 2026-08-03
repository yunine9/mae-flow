# Cross-Repository Chain Restoration Design

## Problem

The Lean cutover changed Chain from a cross-repository decomposition workflow
into a stateless one-shot prompt. The current command does not retain repository
inventory, evidence, questions, interface contracts, validation, the Chain
document, or per-repository launch cards.

## Goals

- Restore Chain as a complete, recoverable cross-repository design workflow.
- Inspect repository facts before asking the user for decisions.
- Define exact repository responsibilities, interface shapes, fields, error
  semantics, dependency direction, delivery order, and integration timing.
- Validate that every repository can start independently from its responsibility
  and contract.
- Produce one reviewed Chain document and a self-contained launch card for each
  repository.

## Non-goals

- Chain does not start Full or Focused delivery in any repository.
- Chain does not edit business code, commit, push, or perform irreversible Git
  effects in any repository.
- Chain is not folded into the six-phase single-repository workflow.

## Workflow

1. Start Chain from an anchor repository and identify the ticket and requirement
   source.
2. Ask for the complete repository list and local paths. Recommend adding the
   paths to the host workspace when they are not already readable.
3. Inspect each repository through three evidence angles: requirement keywords,
   interface call chains, and configuration or routing. Every touchpoint records
   repository, file, symbol, relevance, and confidence.
4. Ask only cross-repository product or contract decisions. Questions are
   numbered, asked one at a time, and include evidence, impact, and a recommended
   answer. Derived branches must be closed before convergence.
5. Define each repository responsibility and every changed interface contract,
   including shape, fields, and error semantics.
6. Define dependency direction, what can run in parallel, merge order, and the
   integration point.
7. Reverse-check each repository: with only its responsibility and interface
   contract, can a new delivery session implement and test its part without
   rediscovering cross-repository decisions? Reopen questioning when the answer
   is no.
8. Verify that every cited repository path, file, and symbol still exists.
9. Render the Chain document, ask the user to confirm touchpoint completeness and
   error semantics, then render one launch card per repository.

## State and Recovery

Chain uses a dedicated local state instead of `.mae-flow.json`:

```text
.mae-flow-work/chain-current.json
.mae-flow-work/<safe-ticket>/chain-state.json
```

The first file is a narrow recovery pointer to the exact active state file; it
prevents directory scanning and contains no business decisions. The state
records the anchor root, ticket, requirement source, repository
inventory, evidence touchpoints, question tree, contracts, dependencies,
reverse-check results, document digest, confirmation receipt, and launch-card
digest. Internal commands support start, current, fact recording, question,
answer, convergence, confirmation, and exit.

Only one Chain action may be active in an anchor repository. It cannot start
while an active Full or Focused flow owns that repository. Exiting archives the
state without touching any referenced repository.

While Chain is active, Hooks record both `UserPromptSubmit` and
`AskUserQuestion` answers against the Chain state digest. Direct file writes are
limited to its exact local `chain.md`; repository inspection stays read-only,
and Git commit or push remains forbidden.

Changing repositories, touchpoints, questions, contracts, dependencies, or the
rendered document after confirmation invalidates the confirmation and launch
cards. A user must review the updated document again.

## Artifacts

The local result is:

```text
.mae-flow-work/<safe-ticket>/chain.md
```

It retains the existing seven sections and strengthens their contracts:

1. Version and change history.
2. Requirement overview and exact sources.
3. Repository inventory and responsibilities.
4. Evidence-backed touchpoints.
5. Interface contracts with non-empty shape, fields, and error semantics.
6. Dependency graph, parallel work, delivery order, and integration timing.
7. Per-repository launch cards with path, exact starter text, recommended
   Mae-Flow path, responsibility, contract IDs, dependencies, and verification
   boundary.

The user may explicitly select the exact durable copy at
`docs/specs/requirements/<safe-ticket>/chain.md`; otherwise all Chain files stay
local and uncommitted.

## CLI and Guidance

The public slash command remains `/mae-flow:mae-flow` with natural language.
The main Agent uses the `chain` CLI lifecycle internally. Other toolbox commands
remain one-shot. The existing `chain --request/--file` invocation starts or
resumes the Chain action rather than printing disposable guidance.

The Skill must state that the main Agent owns Chain because it requires direct
user interaction and cross-repository reasoning. Subagents may inspect bounded
repository facts, but they may not ask Chain decisions or independently change
the contract.

## Verification

- Domain tests cover valid state progression, one open question, invalidation,
  reverse-check gating, confirmation, and no Git effects.
- CLI tests cover start/current/resume/exit, cross-platform paths, corrupt state,
  and coexistence rejection with active delivery.
- Semantic scenarios cover three-way repository inspection, complete contract
  fields, citation verification, review, and launch-card rendering.
- Architecture tests ensure Chain is no longer routed through the stateless
  toolbox and cannot gain code-write, commit, or push effects.
