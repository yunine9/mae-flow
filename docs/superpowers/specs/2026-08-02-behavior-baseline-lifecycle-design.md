# Behavior Baseline Lifecycle Design

## Context

Mae-Flow already produces a confirmed Spec for Full work and reserves
`docs/mae-flow/behavior/` for durable behavior knowledge. The current workflow,
however, treats the per-ticket Spec as a durable repository document while only
defining where behavior files could live. It does not tell a new flow which
historical knowledge to read, how a delivered change updates current truth, or
how an interrupted flow recovers that intent.

Reading every historical Spec would be slow and would fill the model context
with superseded detail. Enforcing a machine-readable documentation schema would
create the same proof loops and Hook friction that the lean workflow is intended
to remove. The design therefore adds a small, recoverable lifecycle around
human-readable domain behavior documents.

## Goals

- Give future requirements a compact and current behavior baseline.
- Keep Spec as the confirmed change contract during a Full workflow without
  forcing every Spec into the repository.
- Read only the few behavior documents relevant to the current request.
- Reconcile delivered behavior without adding a new user confirmation stop.
- Survive interruption without repeating expensive capabilities.
- Keep documentation maintainable through a template, not a format gate.
- Preserve exact-file Git ownership and the existing delivery confirmation.

## Non-goals

- Reintroducing OpenSpec or a physical archive workflow.
- Building a document graph, JSON registry, or strict Markdown parser.
- Scanning every historical Spec or every behavior document for each request.
- Proving document quality with Hooks, receipts, fixed ACK text, or retry loops.
- Recording implementation history inside the current behavior baseline.
- Treating a behavior document as exhaustive before its legacy domain has been
  incrementally understood.
- Redesigning the Story template or turning Story into a step-by-step coding
  plan.
- Adding a documentation maintenance command before real drift demonstrates a
  need for one.

## Truth Model

The repository has one default durable documentation truth:

- `docs/mae-flow/behavior/<domain>.md` records the current observable truth for
  one business domain. New work consumes this layer instead of replaying old
  Specs.

A Full workflow keeps its confirmed change contract at
`.mae-flow-work/<ticket>/spec.md`. The Spec answers what this delivery intends to
change before implementation exists. It guides Grill, Story, and Construction,
but is local by default. The user may explicitly add it to the delivery manifest
when audit or historical rationale is worth preserving.

Git history, blame, the ticket identifier, and the delivery commit connect
current behavior to past changes. No file is physically moved to an archive and
no lifecycle status is required in a Spec.

Behavior documents describe externally meaningful rules, boundaries, and
exceptions. They are not software detailed designs and do not replace Story.
Spec remains the workflow's confirmed change contract. Story consolidates the
confirmed customer scenarios, business specifications, acceptance criteria,
software detailed design, and test design into a standalone handoff for
developers and testers. Domain documents remain the durable current-behavior
truth consumed by future workflows.

## File Model

### Domain index

`docs/mae-flow/behavior/index.md` is a lightweight routing page. Each domain has
one Markdown entry containing a stable domain name, a link to its behavior
document, and a one-line scope description. Agents read it semantically; the
workflow does not parse it as a formal registry.

A new flow reads the index, chooses zero or more relevant domains, then reads
only those domain documents. A new domain adds one index entry during Delivery.

### What counts as a domain

A domain is a stable business-capability module such as order query, payment
settlement, or account permissions. It is organized around shared business
language and observable rules, not source directories, services, classes,
database tables, programming languages, or ticket size. One domain may cross
several technical modules, and one delivery may affect several domains.

Start with a useful business boundary and split only when the work exposes a
real semantic boundary: different vocabulary or rules, independently changing
behavior, or a scope description that can no longer explain what belongs
together. These are judgment cues, not line-count or file-count thresholds. A
split is proposed in an existing confirmation card and is never performed only
to satisfy formatting.

### Behavior template

The plugin provides `skills/mae-flow/assets/BEHAVIOR-TEMPLATE.md`, following the
same guidance model as the Story template:

```markdown
# <领域名称>

## 领域范围

业务边界：说明该领域负责什么、不负责什么。

当前已确认覆盖：列出已经由代码、测试或用户确认的行为范围。

文档未提及的存量行为仍是未知，不表示该行为不存在。

## 当前行为

描述当前已经生效的用户可观察行为和业务规则。

## 边界与例外

描述异常、权限、兼容性和边界条件。

## 相关实现入口

列出稳定的模块、接口或关键文件；不记录易失效的行号。
```

New domain documents start from this template. Existing documents are updated
inside the relevant sections and describe only current truth. Obsolete claims
are removed instead of appending an unbounded change log. When an older document
is untidy, the Agent may normalize only the area touched by the current change;
it does not start a repository-wide documentation cleanup.

The headings are an editorial contract, not a delivery gate. No Hook, parser,
or fixed wording verifies them. A separate document doctor is deliberately left
out of the initial scope.

### Incremental bootstrap for legacy domains

The first requirement touching a complex legacy domain does not inventory the
whole domain. The Agent reads only the code, tests, existing documentation, and
user decisions relevant to the current request. At Delivery it creates the
first baseline from behavior that is actually evidenced, including the relevant
pre-existing behavior and the delivered change.

Statements present in a behavior document are authoritative current truth;
omissions are unknown until later work confirms them. The coverage note makes
this explicit, so a future Agent cannot interpret silence as unsupported
behavior. Later requirements extend or correct the same document in the area
they touch.

No first-use migration, whole-repository scan, or complete business explanation
is required. When only one coherent capability is understood, the Agent creates
a suitably scoped domain such as `order-query` instead of an omnibus
`order-system` document.

## Lifecycle

### Intake

Both Full and Focused paths perform lightweight domain discovery:

1. Read `behavior/index.md` when it exists.
2. Infer the relevant domains from the request, nearby code, and index scopes.
3. Read only the selected behavior documents.
4. Show the selected existing domains, or a proposed new domain, in the existing
   Intake or Spec confirmation card.
5. Ask a separate question only when domain ownership is genuinely ambiguous.

An empty or missing index is valid. Work proceeds and may propose a new domain
at Delivery if the delivered change establishes durable observable behavior.
For a complex legacy domain, the existing card identifies the first baseline's
confirmed coverage without asking the user to inventory the whole business.

### Spec

Full Spec is written under `.mae-flow-work/<ticket>/` and describes the delta
from the selected current baseline: existing behavior, intended change, retained
behavior, and meaningful boundaries. The Spec confirmation remains the single
place where the user decides a behavior change or resolves a relevant baseline
contradiction. The confirmed Spec remains available throughout the run but is
not selected for commit unless the user explicitly asks to preserve it.

Focused work does not require a Spec. It still reads a relevant baseline when
one exists. A bug fix that restores documented behavior remains Focused and
later records `unchanged`. If investigation reveals a new product decision or
observable behavior change, the workflow proposes upgrading to Full and then
creates a Spec instead of silently changing the contract.

### Story, Construction, and Quality

The approved Spec feeds the reviewed Story. Story follows the existing template:
its scenario, business-specification, and acceptance sections make the intended
function testable without requiring the tester to read Mae-Flow's internal Spec;
its detailed-design and test-design sections guide development and verification.
Story describes software design and coherent checkpoints, not line-by-line or
function-by-function coding instructions.

Behavior documents are context, not a second detailed design. Checkpoint review
and Quality remain unchanged; they do not validate or regenerate behavior
documents.

### Delivery reconciliation

After final code and user-visible behavior are known, the main Agent reconciles
each selected domain once:

- `updated`: merge the delivered current truth into an existing document.
- `new`: create a document from the behavior template and append one index entry.
- `unchanged`: the delivery restores or preserves the existing baseline, so no
  behavior file changes.

The existing Delivery card shows the action and exact files for every affected
domain. Faithful reconciliation adds no new confirmation stop. Behavior and
index files are added to the exact Git manifest only when they actually change,
and are committed with source and tests in the same approved delivery commit.
Spec is added only when the user explicitly chooses to preserve it.

## Lightweight Recovery State

The existing workflow state records two user-readable facts rather than a new
document schema:

- selected domain document paths established during Intake;
- the final `new`, `updated`, or `unchanged` action for each selected domain.

The implementation may store these facts using the existing decision/fact
mechanism. Their purpose is to make `current` and SessionStart recovery guidance
useful, not to prove Markdown correctness.

After interruption, recovery displays the selected domains, already-read
documents, and any recorded delivery actions. It does not rerun Grill, Story,
Build, UT, CodeCheck, or reviewers merely to reconstruct documentation state.

## Conflict and Failure Handling

### Baseline versus a new request

This is a normal behavior change. The Spec card presents the old behavior, new
intent, and impact in ordinary language. The user resolves it through the
existing Spec decision; no additional confirmation phase is created.

### Baseline versus code

Neither side wins automatically. If the contradiction affects the current
request, the Agent presents concrete evidence and asks the user to decide in the
current confirmation card. If it is unrelated, the Agent does not expand the
task into a cleanup project.

### Delivered code versus confirmed Spec

Delivery lists the deviation and lets the user choose, in natural language, to
fix the code, revise the Spec and baseline, or accept a documented delivery
risk. The workflow does not fabricate alignment.

### Baseline update cannot be completed

There is no automatic retry loop. Delivery reports the exact pending baseline
work and lets the user decide whether to correct it now or deliver with the
risk visible. Documentation failure never authorizes broad staging or bypasses
the exact-file manifest.

## User Intervention

This lifecycle reuses existing high-value stops:

- Intake or Spec shows selected domains and any ambiguity.
- Full Spec confirms behavior deltas and relevant contradictions.
- Delivery shows final baseline actions and exact files.

Normal domain selection, template use, and faithful reconciliation do not create
new pauses. All decisions accept natural language; no fixed ACK phrase is added.

## Git and Ownership

- Changed behavior baseline files are the default durable documentation.
- Per-ticket Spec and Story remain local by default. Each follows the existing
  conditional commit policy and enters the manifest only after the user
  explicitly selects it.
- Only exact files named in the approved manifest may be staged.
- Existing user changes and unrelated dirty files remain outside the manifest.
- The delivery commit keeps the repository's required
  `[ticket][feat|fix]description` format.
- No directory-wide staging or standalone documentation commit is introduced.

## Testing Strategy

Tests cover workflow behavior, not the prose of a business document:

- document paths are portable on Windows and POSIX;
- the behavior template and index guidance are available;
- domain guidance uses business capability boundaries and contains no mechanical
  size threshold;
- Full and Focused guidance select only relevant domains;
- missing or empty indexes remain a valid first-use state;
- a first legacy baseline records confirmed coverage and treats omissions as
  unknown rather than absent behavior;
- Full Spec stays local by default and can be explicitly selected for delivery;
- selected domains and actions survive serialization and recovery;
- `new`, `updated`, and `unchanged` drive the expected exact manifest behavior;
- a new domain includes both its document and index update;
- unrelated behavior documents are not scanned or staged;
- conflicts route to an existing user decision rather than a retry loop;
- recovery never implies re-running expensive capabilities;
- no Hook validates Markdown structure or content.

Tests do not require business repositories to use exact prose, table layouts, or
machine-readable sections.

## Success Criteria

- A new request can find relevant current behavior without reading old Specs.
- A confirmed Spec can guide Full implementation without becoming a default
  repository artifact.
- A delivered behavior change leaves the selected domain baseline current.
- A complex legacy domain can begin with an honest partial baseline instead of a
  blocking full-domain inventory.
- A restoring bug fix creates no documentation churn.
- New domains remain discoverable through a one-line index entry.
- An interrupted flow resumes with its domain intent intact.
- Documentation never creates a repeated capability call, polling loop, or Hook
  rejection cycle.
- The user sees meaningful behavior choices and exact delivery files at existing
  confirmation points only.
