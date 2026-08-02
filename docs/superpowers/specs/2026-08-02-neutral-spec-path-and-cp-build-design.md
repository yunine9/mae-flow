<!-- generated-by: mae-flow -->

# Neutral Spec Paths and CP Build Design

## Outcome

Mae-Flow keeps private process artifacts under `.mae-flow-work/<ticket>/`, but
new versioned business documents no longer use a `mae-flow` directory. Current
domain specifications live directly at `docs/specs/<domain>.md`, with
`docs/specs/index.md` as the lightweight router. A requirement document enters
`docs/specs/requirements/<ticket>/` only when the user explicitly selects that
exact durable copy.

Every newly generated Spec, Story, and domain Markdown document starts with
`<!-- generated-by: mae-flow -->`. The marker is provenance only: no Hook,
parser, transition, or delivery rule may require it.

## Build ownership

Intake confirms the repository's one build route. C++ projects may select the
configured `build-fix` Skill. Java/Maven projects use the confirmed Maven
command, such as `mvn compile -q`. Other repositories use the exact confirmed
Skill or command. No phase guesses a route from language after Intake.

Each Construction checkpoint invokes that configured route synchronously once
after local checks and accepted Reviewer fixes, before presenting the CP card.
Different CP slots each receive their own first automatic attempt. The same CP
never retries automatically, polls, sleeps, or starts a background wait. If a
user-requested CP revision changes the compiled snapshot, the Agent explains
the impact and obtains a current retry decision before invoking it again.
Quality does not repeat Build when the last CP build still covers the final
production and build inputs.

## Thin guarantees restored

- A confirmed start creates or switches to the exact confirmed working branch
  before the workflow advances beyond Intake.
- Intake shows one natural-language quality plan covering per-CP Build, formal
  CodeCheck, UT, CP review, and conditional integration review.
- Review-fix work accounts for every supplied review item as fixed, unsupported,
  design work, or out of scope; this is ordinary prose, not a report schema.
- Semantic cross-CP coupling records that one integration review is required.
  Quality cannot finish until the one review attempt and its conclusion are
  recorded. Ordinary local work does not invoke it.
- Before Quality completes, the main Agent records one concise final
  conformance conclusion comparing final code and coverage with the confirmed
  Spec/Story, or with the confirmed Focused scope when those documents do not
  exist. Delivery shows the conclusion.

## Removed material

Engineering-experience notes are not generated, committed, or consumed. The
workflow retains business truth in domain specifications and task-local design
in Spec/Story, without creating an unowned knowledge artifact.

## Compatibility and safety

Existing `.mae-flow-work/` paths stay valid. Existing
`docs/mae-flow/behavior/...` and `docs/mae-flow/requirements/...` values remain
readable for migration and in-flight recovery, but new path generation emits
only the neutral durable layout. Exact-file delivery, initial-dirty ownership,
commit format, one final push, Windows path identity, opaque capability returns,
and no automatic retry remain unchanged.
