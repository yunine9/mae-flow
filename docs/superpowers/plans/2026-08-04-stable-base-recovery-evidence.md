# Stable-Base Recovery Verification Evidence

Date: 2026-08-04

## Scope

- Recovery branch: `recovery/stable-subtractive-refactor`
- Stable implementation base: `d32ccfb`
- Strategy: retain the old runtime and remove approved weight; do not port the rewritten Lean runtime.
- Preserved: Chinese configuration card, Interactive Grill, Chain, scoped Lightcheck, CodeCheck/UT/Compile repair paths,
  source/Git authorization, project-local launcher and exact delivery manifest.
- Approved subtraction: Story replaces the independent Blueprint/Roadmap/Build Plan chain; Agent return prose and digest gates are removed.

## Automated evidence

1. Focused Story/Grill/CP/Hook/checkpoint regression: 142 real tests passed. Two explicitly named nonexistent test modules in the
   first ad-hoc invocation were corrected; they were invocation mistakes, not product failures.
2. First full regression exposed four release blockers: one lifecycle fixture missing a task card, two function complexity overruns,
   and three modules above the 500-line architecture limit. All were fixed without weakening the constraints.
3. Final full regression:

   ```text
   Ran 1114 tests in 106.488s
   OK
   ```

4. Release self-test:

   ```text
   python scripts/selftest.py
   全部通过 ✅
   ```

5. Static repository checks: `git diff --check` passed; command/prompt agreement, reachable-state liveness, architecture dependency,
   function complexity, module size, JSON/flow graph, Hook protocol, fault injection and differential suites all passed.

## Red-line contracts now covered

- Every command emitted by reachable workflow guidance parses through the production CLI.
- Every reachable nonterminal workflow state has a real successor; Story review cannot schedule itself.
- Agent return prose is opaque; lifecycle and real execution facts are recorded independently.
- Source ownership remains enforced from repository changes and successful write tool calls, without reading return prose.
- Story Generator/Reviewer, Grill prep/final Critic, CP Implementer and Code Reviewer all have real task-card commands.
- Staged stops at each CP; Continuous reviews only after the final CP; the pace comes only from the user-selected configuration.
- Reviewer fixes and document changes do not trigger digest rebind, automatic rerun or duplicate confirmation.
- Lightcheck remains auto-scoped/advisory; compile remains one synchronous call without fixed sleep or polling.

## Remaining release boundary

Automated coverage is complete for repository behavior. `FIELD-TEST.md` stage 0 still defines the company Windows/CodeAgent host
canary for real Hook payloads, Git Bash, long `mcde` compilation and UI behavior; those environment checks cannot be proven on macOS.
