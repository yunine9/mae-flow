# Single-Action Compile Wait Design

## Goal

Make long Windows C++ builds complete through one observable tool action instead of
repeated `sleep` and log-poll actions, without weakening compile, UT, or CodeCheck
quality contracts.

## Problem

The current agent instructions launch `mcde build -i` in the background and tell
agents to issue repeated `sleep 120-180` plus log-tail calls. That policy was added
to reduce short polling, but it has three undesirable effects:

- a build that finishes quickly still waits for the full sleep interval;
- every wait and log check consumes another agent turn and runs the Hook pipeline;
- log-tail inspection is not a reliable process-completion signal.

The sleep policy is an orchestration workaround. It is not part of the internal
Maven/g++ build contract.

## Chosen design

Each compile round is one synchronous build invocation:

```bash
cd "$BUILD_DIR" && mcde build -i
```

The Bash tool should use its longest supported timeout, targeting ten minutes for
the known five-to-ten-minute module build. The command's return is the completion
signal. The agent must not append `&`, create a polling loop, inspect a PID, tail a
log to guess completion, or issue a separate `sleep` action.

For the `build-fix` route, the compile agent invokes the Skill once and consumes
the Skill's final result. It does not run another confirmation build or parse the
private Maven/g++ output. For an explicit build-command route, the compile agent
runs that command once with the same synchronous policy.

The fix loop may start another compile only after source/build input was actually
changed to address a concrete compile error. If the source snapshot is unchanged,
the previous completed result is reused. If the host reports a timeout or transport
failure, the agent reports that failure once with evidence instead of switching to
background polling or repeatedly rerunning the same build.

## Windows portability

The workflow must not depend on Unix background-process behavior, `/tmp`, PID
probing, `kill -0`, or GNU-only wait helpers. A direct command invocation works with
the plugin's Windows shell route and leaves Maven/g++ process ownership with the
host tool.

## Quality boundaries

- Compile success still comes only from the configured build provider.
- The existing task-card, source-freshness, and compile-receipt checks remain.
- UT and CodeCheck pass/fail contracts do not change.
- UT and CodeCheck agents also stop prescribing sleep when they invoke the configured
  compile route after a repair; they inherit the same single-invocation behavior.
- A timeout is not a successful compile and never produces an OK receipt.

## Verification

Add regression coverage that inspects both checked-in agent instructions and the
packaged `build-fix.skill` contents. The test must reject fixed sleeps, background
compile syntax, and log-tail completion guessing in compile-wait instructions, and
must require synchronous invocation plus explicit no-unchanged-rerun guidance.

Run the focused test, the compile contract/receipt suites, the full unit suite, and
the repository self-test. Retain a Windows field-test item for the real internal
`mcde` wrapper because it is unavailable in this repository.
