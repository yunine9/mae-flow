# Stable CodeAgent Launcher and Grill CLI Design

## Problem

Mae-Flow currently tells the main Agent to run:

```text
python "${CODEAGENT3_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/mae-flow.py"
```

`CODEAGENT3_PLUGIN_ROOT` is available to plugin Hook subprocesses but is empty
in the main CodeAgent Bash environment. The empty expansion becomes
`/scripts/mae-flow.py`; Git Bash maps that path under its installation root,
producing `C:\Program Files\Git\scripts\mae-flow.py`. The earlier fix therefore
replaced directory guessing with a different environment-scope assumption.

Interactive Grill has a second contract mismatch. Production prompts describe
`--decision` as human-readable evidence, impact, recommendation, and parent
text, while the domain requires a JSON object with four exact fields. The CLI
does not expose those fields, returns success when the domain rejects the
question, and cannot consume an answer captured before question registration.

## Goals

- Main-session CLI calls do not depend on Hook-only environment variables.
- CodeAgent is the primary host contract; `CODEAGENT3_*` names take precedence.
- No Agent scans `installed_plugins.json`, marketplace directories, or
  versioned cache paths.
- Grill question creation is discoverable from `--help` and needs no JSON
  construction by the Agent.
- Root questions accept the user-facing parent value `ROOT`.
- Normal Grill ordering is recoverable: register the question, then ask the
  user, then bind the answer.
- An already captured answer can atomically register and answer the missing
  question without asking the user again.
- Rejected Grill commands return exit code 2 and actionable guidance.

## Non-goals

- Parse free-form prose into Grill metadata.
- Weaken state-digest binding or allow fabricated user answers.
- Discover the newest plugin cache by filesystem traversal or installation
  metadata parsing.
- Change Grill convergence, critic receipts, or Grill-to-Spec traceability.
- Change Hook safety policy or delivery semantics.

## Stable CodeAgent Entrypoint

Add an executable `bin/mae-flow` at the plugin root. CodeAgent exposes enabled
plugin `bin/` executables to Bash, so production prompts use:

```text
mae-flow current
```

The launcher resolves its own directory from `$0` and executes the adjacent
`scripts/mae-flow.py` with Windows-available `python`, preserving every original
argument and exit code. It never reads a plugin-root environment variable.
`.gitattributes` keeps the launcher LF-only so Git for Windows cannot corrupt
its shebang.

Hook registration remains rooted through `CODEAGENT3_PLUGIN_ROOT`, with the
existing `CLAUDE_PLUGIN_ROOT` fallback retained only for compatible hosts. Main
Agent guidance does not depend on either Hook variable. If the bare launcher is
absent, the Agent reports a plugin packaging/PATH error and stops; it must not
search caches or hard-code a version.

SessionStart writes the active CodeAgent plugin root to `CODEAGENT3_ENV_FILE`
when the host provides that variable. A missing environment file is logged and
remains non-blocking. No Claude-named environment file is required. This
compatibility path is not required by the primary `bin/mae-flow` entrypoint.

## Explicit Grill Question Interface

The `advance` parser gains four conditional Grill fields:

```text
mae-flow advance grill-question --key GQ-01 \
  --parent ROOT \
  --evidence "当前代码事实" \
  --impact "待决语义的影响" \
  --recommendation "推荐答案"
```

For `grill-question`, all metadata is assembled into canonical compact JSON
inside the CLI. `ROOT` is normalized to the domain's empty-parent value. A
non-root parent must still name an already answered `GQ-*`. Metadata flags on
unrelated events are rejected rather than ignored. The legacy JSON
`--decision` form remains readable for existing automation during this release,
but production prompts no longer generate it.

The normal sequence is:

1. `advance grill-question ...` persists one open question.
2. The Agent presents exactly that evidence, impact, and recommendation through
   natural conversation or AskUserQuestion.
3. `decision grill-answer "<faithful semantic answer>" --key GQ-01` consumes a
   current UserPromptSubmit or AskUserQuestion event bound to the open-question
   state.

## Answer-first Recovery

When the user has already answered before the question was persisted, the
Agent uses the same metadata flags on `decision grill-answer`:

```text
mae-flow decision grill-answer "用户选择 TYPE_1" --key GQ-01 \
  --parent ROOT --evidence "..." --impact "..." \
  --recommendation "TYPE_1"
```

This command first matches the still-current captured user event. Within one
locked state mutation it creates the question and immediately answers it, then
binds the single-use event receipt. It is accepted only when there is no open
question and the key is new. If an open question exists, ordinary
`grill-answer` remains the only valid form. Thus the recovery path cannot attach
an old answer to a different question or bypass current-state ownership.

## Error Semantics

CLI-level Grill validation rejects missing or partial metadata, unsupported
metadata on other events, invalid `GQ-*` keys, invalid parents, duplicate/open
question conflicts, and answer/key mismatches with exit code 2. The diagnostic
shows either the exact explicit question form or the ordinary answer form.

The pure domain remains immutable and keeps returning structured transition
results. The CLI adapter treats an unchanged rejected Grill mutation as a
command error instead of rendering it as successful workflow progress.

## Prompt Synchronization

Update both production prompt sources together:

- `skills/mae-flow/SKILL.md` uses the bare launcher, explicit Grill flags, and
  register-before-ask ordering plus the answer-first recovery form.
- `commands/mae-flow.md` uses the same launcher and removes the stale atomic
  `start --decision` instructions, restoring the persisted card → user input →
  `decision startup-confirmed` handshake.
- `flow/phases/spec.md` uses the exact explicit Grill interface.

## Testing

- Architecture tests require executable, LF-only `bin/mae-flow`, require both
  production prompts to use the bare launcher, and forbid cache scanning,
  version paths, and main-session plugin-root expansion.
- A launcher smoke test runs with both plugin-root variables absent and proves
  the real CLI is reached with arguments and exit status preserved.
- CLI tests first fail because the metadata flags are unknown, then prove root
  normalization, canonical persisted metadata, and actionable exit-2 errors.
- A user-event integration test captures AskUserQuestion before registration
  and proves the atomic answer-first command creates and closes exactly one
  question with one consumed receipt.
- A stale event, conflicting open question, or unrelated metadata remains
  rejected without state mutation.
- Full unittest discovery and `scripts/selftest.py` must pass before push.

## Acceptance Criteria

On an updated CodeAgent plugin installation, `/mae-flow:mae-flow` reaches the
CLI on its first attempt with `mae-flow current`, even when both root variables
are empty. During Full Spec, the Agent can copy the explicit Grill syntax from
the prompt or `--help`; a valid question is persisted before asking. If the
answer was already collected, it is consumed once without repeating the user
question. No path scanning or version-specific cache command appears.
