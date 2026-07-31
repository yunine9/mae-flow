# Confirmation Receipts Design

## Problem

Mae-Flow currently has three confirmation mechanisms with different maturity:

1. Most workflow `done` confirmations already consume a fresh
   `AskUserQuestion` answer and do not require the user to type a second phrase.
2. Standalone scope confirmation and checkpoint decisions still ask the Agent
   to copy a fixed answer into `--ack`.
3. High-risk escape hatches require the Agent to copy the user's full message
   into a shell argument.

The second mechanism is contradictory: Mae-Flow prints a fixed `--ack` command
while also requiring that the fixed phrase occur literally in the captured user
answer. A valid answer such as “范围没问题，优先覆盖缺失较多的文件” is rejected,
and an Agent-generated “确认以上范围” is correctly rejected as forged. The host
then renders the CLI exit code as a failed Bash call, which makes the failure
look like a Bash or Hook defect.

The third mechanism preserves provenance but unnecessarily transports user text
through the shell. It is vulnerable to quoting and encoding failures and makes
Agents likely to paraphrase the authorization.

## Design Principles

- Do not weaken confirmation into generic keyword guessing.
- Routine confirmation proves that a fresh answer was captured after the exact
  artifact or scope was presented.
- Structured choices are consumed directly; the Agent passes only the selected
  machine value.
- High-risk authorization keeps strict user-message provenance but transports a
  stable message ID, never the full user text.
- A receipt is single-step and version-bound. It cannot authorize another step,
  another scope, or a changed review artifact.
- Existing `moonlight on` bootstrap keeps its short `月光宝盒` / `moonlight`
  token because it works before normal flow state and already avoids transporting
  the full request.

## Confirmation Classes

### 1. Standalone scope confirmation

`action start ut|codecheck` stores a deterministic scope fingerprint over:

- action kind;
- frozen file list;
- base HEAD;
- proposal epoch.

Every captured user answer while the action is waiting stores that fingerprint.
`action confirm-scope` takes no `--ack`. It accepts only a fresh positive scope
answer bound to the current fingerprint. Negative, uncertain, question, and
adjustment answers are rejected. The confirmed state records the message ID,
answer hash, and scope fingerprint rather than an Agent-supplied phrase.

### 2. Checkpoint review choices

`checkpoint plan-decide` and `checkpoint decide` keep their machine choices
(`continue`, `revise`, `continuous`) but remove `--ack`. Their existing review
receipts already contain artifact hashes and an answer cursor. The adapter finds
a fresh answer after that cursor and verifies it against the exact display label
for the selected machine choice.

No old answer can confirm a newly rendered plan, code diff, or final review.

### 3. CodeCheck choices and high-risk authorizations

Commands whose user answer may contain detailed candidate IDs or risk wording
accept `--message-id`:

- `codecheck-scope`;
- `codecheck-record`;
- `approve-exemption`;
- `goto --force`;
- `unlock source`;
- `accept-risk`;
- `allow`.

The ID must resolve to a message captured in the current step after entry. The
CLI reads trusted answer fields from that message internally. Existing
action-specific checks still run, including exact Git path/commit coverage for
`allow`. Audit records store message ID and SHA-256; they do not duplicate the
full user answer.

## Error Handling

- Missing or stale IDs explain whether the message belongs to another step.
- A structured response with no trusted answer field is rejected.
- A standalone answer bound to a different scope fingerprint is rejected and
  instructs the Agent to show the current scope again.
- CLI guidance must say `messages` + `--message-id`, never ask the user to repeat
  a magic phrase.
- Mae-Flow policy rejection remains exit code 2; Hook block diagnostics continue
  to distinguish Hook policy blocks from CLI business rejection.

## Compatibility

This is an intentional CLI contract change for the affected commands. Old
`--ack` examples are removed from prompts, the skill, and the README so Agents
cannot keep selecting the broken path. Stored legacy state remains readable;
only new confirmation commands use the receipt protocol.

## Testing

Tests must demonstrate:

- a natural positive scope answer succeeds without `--ack`;
- a synthesized command with no captured answer fails;
- negative/question/adjustment scope answers fail;
- changing the frozen scope invalidates the answer;
- checkpoint choices consume only answers after the receipt cursor;
- message IDs cannot cross steps;
- structured answers exclude question/option metadata;
- exact Git authorization still requires all paths/commits in the captured
  answer;
- no affected public guidance recommends copying user text into `--ack`;
- architecture limits and the complete self-test suite remain green.
