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
all delivery-relevant Git-visible changed paths, not only source paths. Only
exact ephemeral process state is excluded: `.mae-flow.json` and its sidecars,
`.mae-flow-history.jsonl`, `.mae-flow-need-reload`, `.mae-flow/`,
`.mae-flow-work/`, and `.codecheckcli/`. These paths cannot enter a delivery,
and task-card state contains per-run absolute locations that are intentionally
nondeterministic. The repository-owned `.mae-flow-defaults.json` is deliberately
not excluded: if COMPILE changes it, provenance records it and Commit Gate
blocks it like any other compile side effect. A clean tracked path is implicitly
represented by `HEAD`; dirty and untracked paths are represented explicitly.

The task record also stores `worktree_snapshot_valid`. Dedicated provenance Git
helpers surface command failures instead of translating them to empty output.
If capture fails, issuance records an empty, explicitly invalid baseline and
continues; completion logs the invalid baseline and skips attribution instead
of treating every pre-existing dirty path as COMPILE-owned.

Deleted paths are not snapshot members. An absent worktree path cannot be a
compile output and remains governed by the existing Git move/delete ownership
rules.

### 2. Task-bound pre-completion window

Every full-flow COMPILE card explicitly forbids `git commit` and `git push` and
requires direct fixes to remain uncommitted for the main flow. This instruction
is the only intentional task-card body/digest change.

The card is also enforced mechanically. COMPILE completion rejects any HEAD
advance since issuance. Issuing a new task drops the old token, and a completion
token carries the exact task-card digest. While the current step has a COMPILE
task without a matching token, Commit Gate rejects all commit attempts under
the dedicated `bash-compile-task-pending` rule. The rule creates no
strike/permit state and disappears after accepted `SubagentStop` writes the
provenance ledger and task-bound token; candidate-specific ownership rules then
apply normally.

### 3. Direct-edit evidence from the transcript

At COMPILE completion, Mae-Flow reads successful `Write`, `Edit`, and
`MultiEdit` calls directly from the validated subagent transcript. This avoids
depending solely on nested `PostToolUse` delivery.

Only repository-relative paths whose calls have a successful observed result
count as direct Agent edits.

### 4. Compile side-effect calculation

After the COMPILE contract validates the real build invocation, Mae-Flow takes a
second all-path worktree snapshot.

A path is a compile side effect when:

1. its current fingerprint differs from the task baseline; and
2. the validated transcript contains no successful direct file edit for it.

The comparison covers newly created files and modifications to tracked files.
Paths absent from the current worktree, including tracked deletions, are
excluded before fingerprinting. Paths that become clean likewise need no
blocking record.

### 5. Provenance ledger

The existing `.mae-flow.json.agent-writes` sidecar gains a compatible
`compile_side_effects` mapping. Each entry stores the task identity, timestamp,
and observed fingerprint.

Old sidecars containing only `paths` remain valid. Flow initialization and the
existing sidecar reset points clear both direct-write and compile-side-effect
entries.

Attribution, transcript supersession, nested `PostToolUse` supersession, and
Gate matching share one repository path-identity rule: slash-normalized
repository-relative spelling, with Windows case folding. In one locked atomic
sidecar mutation, every old side-effect key matching a successful transcript
direct edit is removed before new effects are added—even when the new-effect
set is empty or nested `PostToolUse` was not delivered. A later COMPILE task can
record the path again if compilation changes it again.

### 6. Commit Gate

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

Commit ownership evaluates review-snapshot integrity, exact COMPILE
side-effects, and high-confidence/force-added ignored files as non-permittable
hard blocks before inherited or foreign ownership choices. Independent
findings are aggregated into one response. Hard blocks write no strike or
permit state. A pure deletion is absent from delivery membership; if a staged
deletion is recreated and explicitly added later in the same command, the
later present A/M candidate wins and receives normal ownership checks.

### 7. Git action, authorization, and actor boundary

Agent-origin Bash is normalized into ordered `GitAction` facts. The parser
recognizes `git.exe`, Git global options such as `-C` and `-c`, pipelines,
quoted shell separators, and backslash-newline continuation. It rejects:

- more than one `commit`/`revert` HEAD mutation in one Bash call;
- repository or inline Git aliases whose expansion mutates the repository;
- write actions using opaque `--pathspec-from-file` input; and
- high-confidence Python, shell, PowerShell, or cmd wrappers around
  `git add`/`commit`/`push`, including literal and variable-assembled
  `subprocess`/`os.exec*` forms.

Read-only aliases remain available. Static command inspection cannot prove the
absence of arbitrary-code or string-obfuscated wrappers; the rule intentionally
claims only high-confidence detection. Exact candidate checks, the
task-bound HEAD invariant, and final committed/pushed evidence remain the
backstop.

The Hook actor boundary is explicit. A command entered by the user in an
external terminal does not traverse Agent `PreToolUse`; a legal current-change
delivery therefore does not need fabricated Agent-write provenance. For an
Agent action that hits a user-decision rule, the first block displays the exact
one-shot `allow` command. The verified acknowledgment must cover the exact
operation plus every path, or the exact revert commit, and remains bound to the
step and pre-action HEAD.

Consuming an exact Git permit records an `agent-hook` authorization receipt.
For `commit` and `revert`, `PostToolUse` finalizes that receipt only when exactly
one resulting commit matches the expected A/M/D paths, object IDs, and HEAD
transition. Pushed evidence accepts that finalized result only while the
recorded commit remains the last touch for each path. A later same-path commit,
an extra path, a stale HEAD, or an object mismatch is not authorized. Revert
authorization first resolves the target and derives its inverse path/status/blob
set, so the same durable proof applies at delivery.

### 8. Failure behavior

Availability and a smooth recovery path take precedence over exact capture.
Capture-side snapshot, comparison, ledger-read, or ledger-write failures are
logged and fail open. They must not silently label arbitrary files as compile
outputs, and they must not reject an otherwise accepted COMPILE completion.

When exact provenance cannot be captured or loaded, Commit Gate retains the
existing high-confidence artifact fallback. When a normal exact ledger is
available, it blocks only the affected commit attempt with actionable
unstage/remove-from-command guidance. It never deletes the file or creates a
persistent lock.

The diagnostic corrupt-sidecar pre-read is intentionally best-effort and may
race with another writer only in the wording of the recovery log. The
authoritative read-modify-write still occurs under the shared lock with atomic
replacement, so this accepted minor race cannot lose or misapply provenance.

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
7. compatibility with old agent-write sidecars;
8. pre-completion commit attempts for new and tracked ordinary configuration
   files, stale versus exact task tokens, and no strike/permit state;
9. invalid baseline capture with pre-existing dirt;
10. transcript-only supersession with no new delta and Windows path spelling;
11. tracked and pre-existing deletions remaining outside the ledger;
12. global Git options, `git.exe`, pipelines, quoted separators, and shell line
    continuation;
13. high-confidence interpreter wrappers, mutating aliases, opaque pathspec
    files, and multiple HEAD mutations;
14. pure D candidates versus a staged D recreated by a later add;
15. first-block recovery guidance, hard-block precedence/aggregation, and no
    strike/permit state for hard rules;
16. exact commit/revert receipts surviving into pushed evidence, while extra
    paths and later same-path commits remain blocked;
17. user-external current delivery without Agent provenance; and
18. `.mae-flow-defaults.json` remaining repository-owned and protected.

After focused tests pass, run the Hook, ownership, Gate probe, selftest,
architecture, and full strict suites.

## Success Criteria

- A compile-generated configuration file cannot be committed merely because its
  name looks legitimate.
- A tracked file modified only by compilation is blocked.
- Direct Agent edits remain distinguishable from command side effects.
- No COMPILE child can commit before its exact current task completes.
- Exact-capture failures remain observable without interrupting COMPILE.
- A normal ledger block is recoverable without deleting local build outputs or
  clearing a persistent lock.
- Existing legitimate delete/move behavior is unchanged.
- Existing high-confidence artifact protection remains active.
- Exact user-authorized Agent Git actions are not re-denied at push/done, but
  their authorization cannot expand to another path or later commit.
- Legal user-external current-delivery commits need no Agent provenance.
- Static wrapper detection has an explicit residual boundary and final evidence
  remains authoritative.
