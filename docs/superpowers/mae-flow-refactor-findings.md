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
