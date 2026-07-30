# Compile Side-Effect Ownership Design

## Goal

Prevent every file created or modified as a side effect of a validated COMPILE
task from entering that delivery's commits unless an Agent subsequently makes
an explicit file edit to the path.

The rule is provenance-based. File names, extensions, and output directories
remain a fallback only; they are not the primary source of truth.

## Existing Defect

Mae-Flow currently records successful Agent `Write`, `Edit`, and `MultiEdit`
operations in `.mae-flow.json.agent-writes`. At commit time, a candidate without
that provenance is warning-only unless it is both newly added and matches a
high-confidence build-artifact pattern.

This leaves a reproducible gap: a compile framework may create or modify a
normal-looking configuration file. Because the file does not match an artifact
pattern, Mae-Flow warns but allows the commit even though the Agent never edited
the file.

## Considered Approaches

### Block every candidate without direct-write provenance

This is simple but cannot distinguish compile output from legitimate Git
deletions, moves, and repository-managed delivery artifacts. It would change
unrelated commit behavior and create avoidable false positives.

### Snapshot every Bash invocation

This gives command-level attribution but adds Git and fingerprint work to every
Bash call. It also depends on child-agent `PostToolUse` delivery, which is not
yet a hard contract on every company host.

### Record side effects at the COMPILE task boundary

This is the selected approach. COMPILE already has a signed task card, a
validated transcript, and a mandatory `SubagentStop` contract. Those boundaries
provide reliable before/after points without adding cost to unrelated Bash
commands.

## Design

### 1. Task baseline

When Mae-Flow creates a COMPILE task, it stores a review fingerprint snapshot of
all Git-visible changed paths, not only source paths. A clean tracked path is
implicitly represented by `HEAD`; dirty and untracked paths are represented
explicitly.

The snapshot is task metadata, not task-card prose. Existing task-card digest
and freshness rules remain unchanged.

### 2. Direct-edit evidence from the transcript

At COMPILE completion, Mae-Flow reads successful `Write`, `Edit`, and
`MultiEdit` calls directly from the validated subagent transcript. This avoids
depending solely on nested `PostToolUse` delivery.

Only repository-relative paths whose calls have a successful observed result
count as direct Agent edits.

### 3. Compile side-effect calculation

After the COMPILE contract validates the real build invocation, Mae-Flow takes a
second all-path worktree snapshot.

A path is a compile side effect when:

1. its current fingerprint differs from the task baseline; and
2. the validated transcript contains no successful direct file edit for it.

The comparison covers newly created files and modifications to tracked files.
Paths that disappear or become clean cannot enter a later commit and therefore
need no blocking record.

### 4. Provenance ledger

The existing `.mae-flow.json.agent-writes` sidecar gains a compatible
`compile_side_effects` mapping. Each entry stores the task identity, timestamp,
and observed fingerprint.

Old sidecars containing only `paths` remain valid. Flow initialization and the
existing sidecar reset points clear both direct-write and compile-side-effect
entries.

When a later successful Agent file edit targets a recorded side effect, the
direct edit supersedes that record. A later COMPILE task can record the path
again if compilation changes it again.

### 5. Commit Gate

Commit-candidate ownership receives a separate `compile_side_effects` fact.
Any staged candidate or same-command candidate in that fact is blocked
regardless of:

- extension or file name;
- directory;
- whether it is new or already tracked;
- whether it resembles a deliverable.

The error identifies the file as a COMPILE-generated side effect and gives
recovery for its actual state: remove staged paths from the index, or remove
not-yet-staged paths from the current `git add`, `git commit -a`, or commit
pathspec. These actions preserve the local build result. The block applies only
to that illegal commit attempt; it creates no persistent lock.

The current strong artifact classification remains as defense in depth for
artifacts created outside a validated COMPILE task or for migrated in-flight
flows without the new ledger.

### 6. Failure behavior

Availability and a smooth recovery path take precedence over exact capture.
Capture-side snapshot, comparison, ledger-read, or ledger-write failures are
logged and fail open. They must not silently label arbitrary files as compile
outputs, and they must not reject an otherwise accepted COMPILE completion.

When exact provenance cannot be captured or loaded, Commit Gate retains the
existing high-confidence artifact fallback. When a normal exact ledger is
available, it blocks only the affected commit attempt with actionable
unstage/remove-from-command guidance. It never deletes the file or creates a
persistent lock.

## Testing

The implementation must first add failing tests for:

1. a COMPILE task that creates a normal-looking configuration file;
2. a COMPILE task that modifies an already tracked configuration file;
3. a path explicitly edited by the compile Agent, which is not recorded as a
   side effect;
4. a recorded side effect that is later directly edited, which is allowed;
5. a same-command `git add && git commit` attempt containing a recorded side
   effect, which is blocked;
6. the existing `.o` fallback and ambiguous deliverable behavior outside a
   validated COMPILE task;
7. compatibility with old agent-write sidecars.

After focused tests pass, run the Hook, ownership, Gate probe, selftest,
architecture, and full strict suites.

## Success Criteria

- A compile-generated configuration file cannot be committed merely because its
  name looks legitimate.
- A tracked file modified only by compilation is blocked.
- Direct Agent edits remain distinguishable from command side effects.
- Exact-capture failures remain observable without interrupting COMPILE.
- A normal ledger block is recoverable without deleting local build outputs or
  clearing a persistent lock.
- Existing legitimate delete/move behavior is unchanged.
- Existing high-confidence artifact protection remains active.
