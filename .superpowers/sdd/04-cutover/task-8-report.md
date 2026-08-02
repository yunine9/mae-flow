# Task 8 Report — Retire obsolete runtime wiring

## Result

DONE. The single fresh full selftest and all targeted architecture,
capability, migration, CLI, Hook, safety, guidance, Lightcheck, and
infrastructure suites are green. Post-review hardening was verified with the
focused suites only, preserving the requested one-shot full-selftest run.

## Old-test classification before removal

The machine-readable inventory was added first to
`runtime/guidance/capability-preservation.json` under
`retirement_test_classification`. Every suite/assertion removed from the
release runner is assigned to one of the required classes and points to lean
semantic test IDs.

- **preserved behavior** — lean state/transitions/guidance/CLI, exact delivery
  manifest, lean Hook router/adapter, safety kernel, Lightcheck, architecture,
  managed I/O, completion contract, and atomic-failure regressions remain in
  the release runner.
- **thin replacement** — legacy workflow/gate/delivery/checkpoint/CLI facade,
  differential, old Hook routing, and old ResourceWarning assertions now map
  to lean transition, manifest, safety, Hook, native-guidance, and lean-I/O
  semantic tests.
- **intentionally removed friction** — fixed ACK/message IDs, evidence tokens,
  evidence hashes, task cards, agent report parsers/fixed result envelopes,
  accept-risk paths, and receipt-led quality/Hook suites are not release
  behavior. Their replacements assert natural-language decisions, opaque
  one-attempt capability facts, and protocol-free prompts.
- **migration-only** — schema-v2 mapping/CLI recovery, vendored source hashes,
  licenses, retained upstream prompt sources, old spec-engine/reference prompt
  material remain available for diagnostics or explicit migration tests, not
  production routing.

No legacy assertion was removed from the release runner before this inventory
and its replacement semantic IDs were committed to the preservation map.

## RED / GREEN

### RED

Command: `python3 scripts/tests/test_architecture.py`

- 39 tests ran: 1 failure and 1 expected budget-key error.
- Production graph contained 154 reachable Python files and 45 retired
  protocol violations.
- First root-cause chain:
  `scripts/mae-flow.py -> mae_flow_core.cli_runtime -> cli_commands.shared ->`
  old Evidence/task-card/report registries.
- Second root-cause chain: Python loads `mae_flow_core/__init__.py` before CLI
  or Hook submodules, and that initializer imported `capabilities ->`
  `capability_shared/CAPABILITY_PACKS -> capability_packs`.
- The absent final reachability baseline key was intentional RED: the final
  budget was recorded only after production disconnection stabilized.

### GREEN

- `cli_runtime.py` now directly composes lean handlers; dynamic legacy module
  registration and Evidence compatibility exports are gone.
- `cli_parser.py` exposes only lean commands, Lightcheck, and the explicit
  schema-v2 `migrate-flow` reader.
- `command_dispatch.py` contains only lean routes; obsolete registries and
  accept-risk route are removed.
- `mae_flow_core/__init__.py` is dependency-light, so importing any production
  submodule no longer eagerly imports prompt packs or old contracts.
- `lean_migration.py` owns its state filename locally instead of importing the
  retired shared registry. `orchestration/migration.py` retains exact
  `task_card`/`task_cards` scrub keys as an audited migration-only exception.
- Lean Lightcheck keeps exact-file, changed-line, fail-open behavior without
  importing the old shared CLI graph.
- Architecture budget records the exact final 66-file production graph and the
  completion contract caps production reachability at 66. The roots include
  the CLI, Hook dispatcher, statusline, and Comet compatibility entrypoints.
  No line or
  complexity limit was raised; obsolete route complexity entries were removed.

Final reachability: **154 -> 66 files** (-88, about 57%).

Final architecture scanners:

- production retired-protocol violations: **45 -> 0**
- native phase-guidance violations: **0**

## Retained sources

The following are deliberately still present and were not physically deleted:

- all `runtime/vendor/{openspec,comet,superpowers,ponytail,lizard}` trees;
- `runtime/vendor/manifest.json`, all component licenses,
  `runtime/THIRD_PARTY_NOTICES.md`, and integrity hashing diagnostics;
- `scripts/mae_flow_core/capability_shared.py` and `capability_packs.py` as
  reference-only upstream prompt-pack readers;
- `scripts/mae_flow_core/workflow/evidence.py`,
  `workflow/agent_evidence.py`, and `quality/agent_contracts.py` as retained
  schema-v2/reference implementations, unreachable from production roots;
- `scripts/mae_flow_core/orchestration/migration.py` and its explicit migration
  tests, including exact legacy-field scrubbing;
- retained agent/flow prompt sources and their source-integrity tests.

## Verification

Targeted commands and latest counts:

- `python3 scripts/tests/test_architecture.py` — 40/40 PASS
- `python3 scripts/tests/test_capabilities.py` — 4/4 PASS
- `python3 scripts/tests/test_native_guidance.py` — 27/27 PASS
- `python3 scripts/tests/test_refactor_completion.py` — 8/8 PASS
- `python3 scripts/tests/test_lean_cli.py` — 26/26 PASS
- `python3 scripts/tests/test_lean_migration_cli.py` — 11/11 PASS
- `python3 scripts/tests/test_lightcheck.py` — 43/43 PASS
- lean state/migration/transitions — 15/15, 14/14, 36/36 PASS
- lean guidance/composition/delivery/documents/moonlight/toolbox — 12/12,
  2/2, 23/23, 15/15, 23/23, 10/10 PASS
- delivery manifest/safety/Hook events/Hook adapter — 21/21, 28/28,
  9/9, 32/32 PASS
- lean capabilities/reference prompts/file I/O/fault injection — 14/14,
  7/7, 2/2, 3/3 PASS
- `git diff --check` — PASS
- `python3 scripts/selftest.py` — PASS, 27/27 release checks; executed exactly
  once. It compiled 294 Python sources, loaded 5 runtime JSON documents,
  verified retained reference/license/migration sources, and ran all 24
  registered semantic subprocess suites.

Reviewer hardening after that one-shot full run:

- statusline now imports `RuntimeMode` and `resolve_runtime` directly from the
  owning runtime module; its standalone subprocess smoke test passes;
- production static reachability now starts from all four Python runtime
  entrypoints, with the final exact 66-file graph and zero retired-protocol
  violations;
- Lightcheck resolves repository/file aliases before containment checks, so an
  absolute in-repository path receives real changed-line analysis while an
  outside-repository path is rejected fail-open. The regression proves both
  the changed magic-number finding and exclusion of untouched parameter debt.
- Post-review focused verification: architecture 40/40, Lightcheck 43/43,
  capability classification 4/4, completion contract 8/8.

No real Build, UT capability, CodeCheck capability, push, or delivery command
was run.

## Concerns and deviations

- The brief's named source files were not sufficient to cut transitive
  production reachability. Additional composition-root/parser/route,
  migration-import, Lightcheck-adapter, architecture-helper, release-runner,
  and completion-contract files were necessarily changed. The causal chains
  are documented above.
- Two stale targeted tests surfaced during GREEN. The migration composition
  test now records the required derived opaque Grill attempt before a clear
  review event; the ResourceWarning test now exercises lean migration, Hook,
  and manifest paths. Neither change restores receipts, hashes, task cards,
  report parsing, or retries.
- Task 7's parked Bash `>&file` false-positive remains unchanged. No Hook parser
  changes were made for that concern.
- The full selftest was not rerun after reviewer hardening, by explicit
  instruction; the four affected focused suites above are the final evidence
  for those changes.
- Windows/Python 3.8-compatible language and subprocess APIs were retained;
  local verification used `python3` as required.
