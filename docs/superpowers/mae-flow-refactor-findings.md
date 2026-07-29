# Mae-Flow Refactor Findings

## MF-RF-001: File handles remain open during tests

- Classification: evidence insufficient
- Baseline: `d5e7d7b2cb5d3def06d21df79fb3069efea94f16`
- Trigger: checkpoint tests reading `.tokens`, `.usermsg`, and step Markdown
- Evidence: Python emits `ResourceWarning: unclosed file`
- Refactor action: none
- Required next step: isolate a deterministic resource-warning test before
  deciding whether this is a user-visible defect

## MF-RF-002: Static next graph does not enumerate every entered step

- Classification: documentation and implementation mismatch
- Baseline: `d5e7d7b2cb5d3def06d21df79fb3069efea94f16`
- Trigger: enumerate `flow.json` ordinary `next` edges
- Evidence: `moonlight_review`, `rf_verify`, and `verify_recompile` require
  dynamic or compatibility code paths
- Refactor action: none in phase one
- Required next step: register dynamic transition policies in phase two
  without changing their behavior

## MF-RF-003: Combined short options escape Git add intent flags

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
- Refactor action: none; the shared parser preserves baseline behavior
- Required next step: add a failing black-box Gate regression, then fix in a
  dedicated `fix:` commit after explicit classification

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
