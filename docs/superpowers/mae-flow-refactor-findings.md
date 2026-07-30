# Mae-Flow Refactor Findings

## MF-RF-001: File handles remain open during tests

- Status: resolved by `5f8286b`
- Classification: resource lifecycle defect
- Baseline: `d5e7d7b2cb5d3def06d21df79fb3069efea94f16`
- Trigger: checkpoint tests reading `.tokens`, `.usermsg`, and step Markdown
- Reproduction: run Checkpoint cases with
  `-W always::ResourceWarning`; Python reports unclosed `.tokens`, `.usermsg`,
  step Markdown, and the test fixture's `flow.json`
- Root cause: production adapters used immediate `open(...).read()` /
  `json.load(open(...))` expressions whose streams depended on garbage
  collection for release
- Resolution: introduced `mae_flow_core.file_io` managed helpers, migrated all
  unmanaged opens in the four production entrypoints, and added an AST rule
  that prevents them from returning
- Regression: `test_file_io.py` checks helper lifecycle and launches real
  Checkpoint subprocesses with ResourceWarnings enabled;
  `test_architecture.py` requires zero unmanaged production opens
- Product behavior: output, state, encodings, append modes, and read limits are
  unchanged; streams now close deterministically, including on Windows

## MF-RF-002: Static next graph does not enumerate every entered step

- Status: resolved by `c75da6a`
- Classification: documentation and implementation mismatch
- Baseline: `d5e7d7b2cb5d3def06d21df79fb3069efea94f16`
- Trigger: enumerate `flow.json` ordinary `next` edges
- Evidence: `moonlight_review`, `rf_verify`, and `verify_recompile` require
  dynamic or compatibility code paths
- Root cause: static validation only knew `next`, while runtime policy also
  consumes source-change routes, Moonlight routing, and legacy in-flight entry
  points
- Resolution: transition metadata now includes `source_change_next`,
  `source_change_recheck`, and `dynamic_next`; `rf_verify` is declared as a
  compatibility entry; graph validation starts from both the normal start and
  declared compatibility entries
- Regression: `test_workflow_definition.py` covers deduplicated dynamic edges,
  unreachable steps, compatibility entries, and the complete repository graph
- Product behavior: runtime transition selection is unchanged; the new fields
  are static validation and documentation metadata only. All phase-8
  differential scenarios remain identical

## MF-RF-003: Combined short options escape Git add intent flags

- Status: resolved by `d78f15b`
- Classification: reproducible guard coverage gap
- Baseline: `d5e7d7b2cb5d3def06d21df79fb3069efea94f16`
- Trigger: `git add -fu` or another combined `git add` short-option token
- Evidence: Git accepts `git add -n -fu -- scripts/mae-flow.py` with exit code
  0, while `_git_add_intents("git add -fu")` reports `force=False`,
  `tracked_only=False`, and no default pathspec
- Root cause: add intent checks exact tokens for `-f` and `-u`; commit intent
  already expands combined short-option flags
- Impact: a same-command `git add -fu && git commit` can under-report pending
  candidates; an ignored path forced into the index can also miss the
  pre-commit artifact inspection
- Resolution: `git_add_intent()` now reuses the existing combined-short-option
  expansion and recognizes `f`, `u`, and uppercase `A` while retaining long
  option behavior
- Regression: the shared parser/CLI bridge matrix covers `-fu`, `-uf -- path`,
  and `-Af`; phase-9 adds a deterministic active-Gate scenario
- Behavior boundary: this is the only intentional baseline difference. Phase-9
  contains exactly one new scenario key, all phase-8 snapshots are unchanged,
  and the fixed old implementation demonstrably fails the new scenario

## MF-RF-004: Selftest searched for an extracted task-card variable

- Classification: refactor safety-net defect
- Baseline: introduced by phase 6 extraction, reproduced during phase 8 closeout
- Trigger: run `python scripts/selftest.py`
- Evidence: the CodeCheck routing check searched `scripts/mae-flow.py` for
  `expected_steps = {"COMPILE"` after that contract had moved to
  `mae_flow_core.quality.task_cards.EXPECTED_STEPS`
- Impact: selftest reported one false failure even though the three CodeCheck
  handlers and their task-card routes remained intact
- Refactor action: corrected the selftest to inspect the exported
  routing contract while retaining the CLI handler check
- Product behavior: unchanged

## MF-RF-005: Gate permit was replayed during commit branch assembly

- Status: resolved by `75bdf3c`
- Classification: refactor-introduced compatibility defect
- Trigger: sign a one-shot permit for an early pre-commit rule such as
  `bash-commit-format`, then retry the same commit command on a configured
  delivery branch
- Evidence: the first policy pass consumed the permit, but CLI assembly filled
  `current_branch` and reran the complete pre-commit policy; the same early rule
  immediately blocked again because the permit was already marked used
- Root cause: commit branch verification was coupled to the full ordered
  pre-commit evaluator instead of being a distinct later rule
- Resolution: split `decide_commit_branch()` from format and earlier rules;
  query Git at the historical point, then evaluate only the branch rule
- Regression: `test_guard_permit_integration.py` loads the real CLI assembly,
  signs a valid format permit, verifies exit 0, exactly one consumption and no
  strike sidecar; pure policy tests separately preserve branch failure
- Product behavior: restored to the pre-refactor one-shot permit semantics

## MF-RF-006: Quality task-scope fixture leaked its Flow file handle

- Status: resolved by `e856501`
- Classification: test resource lifecycle defect
- Trigger: run the Stage 4 Quality suites with
  `-W error::ResourceWarning`
- Evidence: `test_task_scope.py` loaded `flow/flow.json` through
  `json.load(open(...))`; the suite reported success but interpreter cleanup
  emitted an ignored unclosed-file `ResourceWarning`
- Root cause: the fixture predated the managed-file rule and lived outside the
  production entrypoint AST boundary
- Resolution: load the fixture with a context manager so the descriptor closes
  deterministically at module initialization
- Regression: all 56 Quality, CodeCheck, task-card, logging, and task-scope
  tests now run under strict `ResourceWarning` mode without warnings
- Product behavior: unchanged; only the test fixture lifecycle changed

## MF-RF-007: Selftest searched the Hook entrypoint for migrated Direct policy

- Status: resolved during Stage 5
- Classification: refactor safety-net defect
- Trigger: run `python scripts/selftest.py` after Hook event routing moves to
  `mae_flow_core.adapters.hook_events`
- Evidence: all Direct-mode process tests passed, but the static selftest still
  searched `hooks/dispatch.py` for `direct mode: bypass` and
  `不要运行 current/done`
- Root cause: the safety check was coupled to the old physical file instead of
  the extracted event adapter that owns the behavior
- Resolution: inspect the event adapter for the static publication check and
  add every new Hook application/adapter module to the syntax release gate
- Regression: the full selftest now completes with `全部通过`
- Product behavior: unchanged; the existing Direct-mode subprocess tests still
  verify bypass and answer capture through the public Hook process

## MF-RF-008: Standalone PostToolUse answer capture was routed to inactive

- Status: resolved by `7030e57`
- Classification: refactor-introduced behavior regression
- Trigger: complete `AskUserQuestion` while a Standalone Action is waiting for
  scope confirmation
- Evidence: the extracted runtime router sent Standalone `posttooluse` to the
  inactive adapter, so neither `user_messages` nor the `ASKUSER` token changed
- Impact: `action confirm-scope --ack "确认以上范围"` could not validate the
  user's real answer even though the question had completed successfully
- Root cause: the Standalone routing table preserved pretool, injection and
  SubagentStop ownership but omitted the shared PostToolUse answer-capture path
- Resolution: route Standalone PostToolUse through the same active posttool
  use case while leaving Standalone Stop inactive
- Regression: pure routing coverage and a real Hook subprocess test assert both
  the captured answer and the signed `ASKUSER/CONFIRMED` token
- Product behavior: restored to the pre-extraction behavior

## MF-RF-009: Non-PASS UT results persisted reusable receipts

- Status: resolved by `249c79b`
- Classification: refactor-introduced side-effect ordering regression
- Trigger: a UT Agent finishes with `NEEDS_INPUT` or `FAIL`
- Evidence: the extracted adapter called `_record_ut_receipts` before the pure
  contract evaluator validated the result status
- Impact: evidence from a non-passing run could be persisted and considered for
  a later retry, unlike the original early-return contract
- Root cause: receipt collection was moved ahead of status validation while
  separating platform effects from the pure evaluator
- Resolution: validate the three supported statuses immediately after task-card
  and scope checks; only `PASS` may collect or reuse UT receipts
- Regression: adapter-order tests assert that `NEEDS_INPUT`, `FAIL`, and an
  unknown status never touch receipt or configuration ports
- Product behavior: restored to the pre-extraction receipt semantics

## MF-RF-010: Commit-ownership fixture leaked its Flow file handle

- Status: resolved during Stage 5 verification
- Classification: test resource lifecycle defect
- Trigger: run the complete unittest suite with
  `-W error::ResourceWarning`
- Evidence: `test_commit_ownership.py` initialized the CLI fixture with
  `json.load(open(...))`; interpreter cleanup reported an unclosed
  `flow/flow.json` handle
- Resolution: initialize the shared Flow fixture through a context manager
- Regression: the complete suite is run under strict ResourceWarning handling
- Product behavior: unchanged; only the test fixture lifecycle changed

## MF-RF-011: Selftest searched dispatch for migrated active-event policy

- Status: resolved during Stage 5 verification
- Classification: refactor safety-net defect
- Trigger: run `python scripts/selftest.py` after active event handling moves
  from `hooks/dispatch.py` to application policy and platform adapters
- Evidence: six static publication checks failed while all corresponding unit,
  process and Phase-15 differential scenarios passed
- Root cause: template, Moonlight question and Stop checks remained coupled to
  the old physical entrypoint after the final assembly extraction
- Resolution: inspect `event_policies.py` for template routing and
  `hook_active_events.py` for active platform behavior; include the new adapter
  in the syntax release gate
- Product behavior: unchanged

## MF-RF-012: Completion contract rejected an already-achieved target

- Status: resolved during Stage 5 closeout
- Classification: refactor safety-net lifecycle defect
- Trigger: tighten the Hook architecture baseline from 2860 to its achieved
  326 lines while the approved final target remains 800
- Evidence: contract validation required every final target to remain strictly
  below the current architecture baseline, so surpassing the target made the
  completion test fail
- Root cause: the bootstrap assertion distinguished a future target from a
  permissive baseline but had no achieved-state semantics
- Resolution: the immutable approved target equality remains the anti-inflation
  guard; baseline validation now requires the target to be a positive integer
  and allows the current baseline to be stricter
- Product behavior: unchanged

## MF-RF-013: Extracted CLI dispatch resolved handlers from the wrong namespace

- Status: resolved during Stage 6
- Classification: refactor-introduced routing regression
- Trigger: invoke any table-routed action or flow command after splitting the
  historical CLI into command modules
- Evidence: Phase-15 reported `unknown Mae-Flow command handler` for action,
  checkpoint, done, agent-task and CodeCheck routes
- Root cause: the extracted dispatch module passed its own `globals()` to the
  public command router, while handlers now live in the composition registry
- Resolution: both table-routed dispatch paths resolve handlers from the
  registered public CLI API
- Regression: the complete Phase-15 subprocess differential suite is zero-diff
- Product behavior: restored to the pre-split routing semantics

## MF-RF-014: CLI test overrides stopped at the compatibility facade

- Status: resolved during Stage 6
- Classification: refactor safety-net compatibility defect
- Trigger: focused tests replace a process, Git, state or command dependency on
  the public `cli_runtime` facade
- Evidence: CodeCheck attempted a real installation and Gate executed the real
  write policy despite their dependencies being patched
- Root cause: Python star imports copy bindings into each command module; facade
  assignment updated the registry but not those copied module bindings
- Resolution: the composition registry tracks registered modules and propagates
  public compatibility overrides to every module that owns the binding
- Regression: strict CodeCheck logging and Gate permit integration tests cover
  imported platform dependencies and same-module command helpers
- Product behavior: unchanged

## MF-RF-015: Release probes still imported or scanned the historical CLI file

- Status: resolved during Stage 6
- Classification: refactor safety-net location coupling
- Trigger: run the complete selftest after the CLI entrypoint becomes a public
  adapter
- Evidence: the Gate evidence probe could not find `ev_spec_validate`, and the
  external-engine audit rejected the relocated `cmd_capability`
- Root cause: both checks encoded the former physical location instead of the
  public runtime/module ownership contract
- Resolution: the probe imports `mae_flow_core.cli_runtime`; static source and
  engine-call audits include the semantic command modules and permit only the
  named capability handler
- Product behavior: unchanged

## MF-RF-016: Public CLI facade omitted live compatibility state

- Status: resolved during final independent review
- Classification: refactor-introduced in-process API regression
- Trigger: import `mae_flow_core.cli_runtime` and inspect the legacy evidence
  rule objects, or read `FLOW` after the composition registry loads a new flow
- Evidence: the four `_AGENT/_DELIVERY/_QUALITY/_WORKFLOW_EVIDENCE` attributes
  raised `AttributeError`; `cli_runtime.FLOW` retained its import-time snapshot
  while command modules used the newly loaded registry value
- Impact: CLI subprocess behavior was unchanged, but Python callers and tests
  using the supported public runtime facade could observe missing or stale state
- Root cause: evidence registration filtered only names beginning
  `_EVIDENCE`, and the facade copied `FLOW` once instead of forwarding reads
- Resolution: register an explicit compatibility allowlist, enroll the evidence
  module in override propagation, and make facade `FLOW` reads resolve the live
  composition value
- Regression: `test_cli_runtime_facade.py` covers all four rule objects,
  evidence override propagation and bidirectional live Flow visibility;
  Phase-15 remains zero-diff
- Product behavior: restored to the historical in-process API

## MF-RF-017: Compile-owned normal and tracked files escaped the commit block

- Status: resolved by `b61116d`, `d8b2aca`, `fd2b674`, `0a0ab29`, and
  `573dc4b`; lifecycle/provenance closure completed in the final review fix wave
- Classification: reproducible guard coverage defect
- Baseline: `7910bfc` (491 tests passed)
- Trigger: a validated COMPILE task creates a normal-looking configuration
  file or modifies an already tracked configuration file, then that path is
  included in a commit
- Evidence: the prior pending-file policy blocked an unproven path only when it
  was both newly added and matched a high-confidence temporary-artifact
  pattern. `config/generated.properties` therefore produced only an advisory,
  while tracked `config/runtime.properties` could not enter the new-file
  branch at all
- Root cause: the Agent-write sidecar proved direct file-tool edits but did not
  record the complementary COMPILE-owned delta. The Gate inferred ownership
  from file naming, new-file status, and absence of a direct edit rather than
  from the validated COMPILE boundary. Final review additionally found that
  enforcement began only after `SubagentStop`, failed baselines were encoded as
  trustworthy `{}`, transcript-only direct edits could return before removing
  old records, capture and Gate disagreed on Windows identity, and missing
  paths were fingerprinted as outputs
- Resolution: COMPILE task cards now retain a detached all-path fingerprint
  baseline; accepted completion computes the post-COMPILE delta, excludes
  successful observed `Write`/`Edit`/`MultiEdit` calls, and stores exact paths
  in a backward-compatible sidecar ledger. Commit ownership hard-blocks an
  exact ledger match before the naming fallback, and a later successful direct
  edit supersedes the recorded COMPILE ownership. Final release verification
  also split candidate grouping/enforcement and recovery-message assembly into
  focused helpers, restoring the established adapter and guard complexity
  limits without changing policy. The final closure adds the universal
  no-commit/push instruction, rejects COMPILE completion after a HEAD advance,
  invalidates tokens on new issuance, binds tokens to the exact task digest,
  and transiently blocks commits until that matching token exists without
  strike/permit state. Baselines carry explicit validity; provenance Git
  failures surface; absent paths are excluded; and attribution,
  transcript/PostToolUse supersession, and Gate matching share one
  slash-normalized, Windows-case-folded identity. Old-key removal and new
  attribution occur in one locked atomic mutation even with a zero new delta.
  Exact ephemeral process state is excluded, but repository-owned
  `.mae-flow-defaults.json` remains delivery provenance and is hard-blocked if
  COMPILE changes it
- Regression: `test_compile_side_effects.py` covers normal/tracked deltas,
  failed and unobserved direct-write results, path normalization, and
  out-of-repository rejection; `test_hook_compile_contract.py` covers accepted
  persistence, direct-edit supersession, rejected-contract ordering, and
  fail-open diagnostics; `test_commit_ownership.py` covers normal new files,
  tracked files, legacy/corrupt sidecars, same-command candidates, ambiguous
  artifacts, and case-insensitive ledger identity; pure ownership tests and
  real Gate probes cover blocking precedence and recovery guidance
- Final-review regression: task-card/contract/evidence tests cover the
  no-commit instruction, HEAD advance, task digest, stale token invalidation,
  and invalid baseline behavior; real repository lifecycle tests cover new and
  tracked ordinary configuration files before and after exact completion with
  no strike/permit state; Hook/pure tests cover zero-delta transcript
  supersession, uppercase/backslash Windows spelling, strict Git failures, and
  tracked/pre-existing deletions remaining committable. The release-blocker
  wave additionally covers global Git options/`git.exe`, pipelines, quoted
  separators and line continuation; literal and variable-argv interpreter
  wrappers; repository/inline mutating aliases; opaque pathspec files;
  multiple commit/revert actions; staged-D recreation; force-added ignored
  files; hard-block ordering/aggregation; and exact defaults-file ownership
- Availability boundary: snapshot, comparison, or sidecar-update failures are
  logged and fail open; they do not reject an otherwise accepted COMPILE.
  With a normal exact ledger, only the illegal commit attempt is rejected.
  Recovery removes affected paths from the index or current command without
  deleting local files or creating a persistent lock. The corrupt-sidecar
  diagnostic pre-read can race only in log wording; the authoritative
  read-modify-write remains locked and atomically replaced
- Behavior boundary: high-confidence naming remains the fallback when exact
  provenance is absent. Legitimate move/delete behavior and unrelated golden
  scenarios are unchanged; exact provenance adds blocks only for recorded
  COMPILE paths. The only task-card body/digest change is the COMPILE
  no-commit instruction. Agent Git user-decision permits now leave exact
  actor-bound receipts: PostToolUse finalizes only a matching single
  commit/revert result, and push/done revalidates status, object, ancestry, and
  last touch. Extra paths and later same-path commits remain blocked; a legal
  user-external current delivery needs no Agent provenance. Permit-class rules
  display the exact one-shot exit on the first block, while review/COMPILE/
  strong-artifact integrity blocks precede and aggregate ownership findings
  without strike/permit state
- Parser boundary: direct Git actions recognize `git.exe`, global options,
  shell groups, quoted separators, and line continuation. Mutating aliases,
  opaque pathspec inputs, multiple HEAD mutations, and high-confidence
  interpreter wrappers are rejected. Arbitrary code/string obfuscation is not
  statically decidable; committed/pushed evidence remains the authoritative
  backstop
