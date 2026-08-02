## Objective
Implement the approved outcome in coherent checkpoints and create testability seams early for the later formal UT chain.

## Inspect
Read the current CP brief, approved Story or Focused scope, selected behavior
baseline, changed interfaces, planned testability seams, cumulative UT handoff,
and repository state.
After implementing each checkpoint, run `craft-reviewer-agent` once with the
CODE Reviewer role over that checkpoint diff and direct integration boundary.
Give every supplied review item one clear disposition: fixed, unsupported with
evidence, design tradeoff, or out of scope. Then synchronously invoke the exact
confirmed Build route once for that CP. A C++ route may use
`build-fix`; a Java route uses the confirmed Maven command; other languages use
their confirmed repository Skill or command. Do not use delay loops, repeated
status probes, detached execution, or
automatically retry while waiting for Build.

## Stop for the user
Stop for a real ambiguity, a meaningful design deviation, an irreversible risk,
or an agreed Full-flow checkpoint confirmation.

## Outputs
Record the current CP brief, actual result, one-pass Reviewer conclusion,
incremental UT intent, changed files, unresolved risks, and the next CP brief.
The same user card compares the completed CP with the next design. These are
natural-language recovery facts, not a separate detailed coding-plan document.
CP Construction does not write or run formal UT. Its one configured Build is
the CP compile fact and is recorded as one opaque capability outcome; Mae-Flow
does not parse its output.

## Next
Proceed to Quality when construction and its cumulative UT handoff are complete.
The next meaningful action is the current checkpoint.
