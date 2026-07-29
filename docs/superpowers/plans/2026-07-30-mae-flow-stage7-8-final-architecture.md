# Mae-Flow Stage 7–8 Final Architecture Plan

## Goal

Finish the behavior-preserving refactor by making CLI dependencies explicit,
removing every oversized core-module exception, and retaining stable public
facades for compatibility.

## Stage 7: CLI dependency and architecture cleanup

1. Add a failing architecture assertion that command modules cannot use
   wildcard imports from the shared platform namespace.
2. Replace every wildcard with the exact imported names used by that module.
3. Keep cross-command calls behind the composition API, and keep compatibility
   overrides centralized in the composition root.
4. Tighten adapter complexity baselines to the achieved values and document
   which command functions are orchestration adapters rather than policy.
5. Run focused CLI tests, strict full unittest, Phase-15, architecture and
   `git diff --check`.

## Stage 8: Remaining oversized modules

### Capabilities

Split embedded asset rendering, host/runtime discovery, and CodeCheck lifecycle
into cohesive modules. Keep `mae_flow_core.capabilities` as a stable facade and
preserve its constants, exceptions, private compatibility helpers and public
functions.

### Lightcheck

Split source scanning, function matching/analysis, timeout isolation, and report
rendering into cohesive modules. Keep `mae_flow_core.lightcheck` as a stable
facade with unchanged result schemas and multiprocessing behavior.

### Specengine

Split filesystem/config/YAML, Markdown/spec parsing, change validation,
instructions/status, and archive application. Keep
`mae_flow_core.specengine` as the stable API, including the `_move_directory`
failure-injection seam.

## Completion gates

- Phase-15 must remain zero-diff after each facade split.
- `test_capabilities.py`, `test_lightcheck.py`, and `test_specengine.py` must
  pass under strict `ResourceWarning` handling.
- Every production module must be at most 500 lines; the oversized allowlist
  must be empty.
- Policy functions remain bounded by the existing complexity gates. Parser and
  protocol adapters may only exceed 15 when covered by focused tests and
  explicitly classified outside policy packages.
- Full selftest, full strict unittest, fault injection, completion contract,
  architecture tests and `git diff --check` must pass before final review.
- After review findings are fixed and verification is rerun from a clean
  checkout state, merge locally without pushing.
