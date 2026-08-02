# Behavior Baseline Lifecycle Design

## Context

Mae-Flow already stores each confirmed requirement under
`docs/mae-flow/requirements/<ticket>/spec.md` and reserves
`docs/mae-flow/behavior/` for durable behavior knowledge. The current workflow,
however, only defines where these files can live. It does not tell a new flow
which historical knowledge to read, how a delivered change updates current
truth, or how an interrupted flow recovers that intent.

Reading every historical Spec would be slow and would fill the model context
with superseded detail. Enforcing a machine-readable documentation schema would
create the same proof loops and Hook friction that the lean workflow is intended
to remove. The design therefore adds a small, recoverable lifecycle around
human-readable domain behavior documents.

## Goals

- Give future requirements a compact and current behavior baseline.
- Keep per-ticket Specs as stable historical change context.
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
- Adding a documentation maintenance command before real drift demonstrates a
  need for one.

## Truth Model

The repository has two complementary durable records:

- `docs/mae-flow/requirements/<ticket>/spec.md` records what one requirement
  changed and why. It remains at a stable path as historical context.
- `docs/mae-flow/behavior/<domain>.md` records the current observable truth for
  one business domain. New work consumes this layer instead of replaying old
  Specs.

Git history, blame, and the ticket's delivery commit connect current behavior to
past changes. No file is physically moved to an archive and no lifecycle status
is required in each Spec.

Behavior documents describe externally meaningful rules, boundaries, and
exceptions. They are not software detailed designs and do not replace Story.
Spec remains the WHAT authority for the current change; Story remains the HOW
authority for implementation.

## File Model

### Domain index

`docs/mae-flow/behavior/index.md` is a lightweight routing page. Each domain has
one Markdown entry containing a stable domain name, a link to its behavior
document, and a one-line scope description. Agents read it semantically; the
workflow does not parse it as a formal registry.

A new flow reads the index, chooses zero or more relevant domains, then reads
only those domain documents. A new domain adds one index entry during Delivery.

### Behavior template

The plugin provides `skills/mae-flow/assets/BEHAVIOR-TEMPLATE.md`, following the
same guidance model as the Story template:

```markdown
# <领域名称>

## 领域范围

说明该领域负责什么、不负责什么。

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

### Spec

Full Spec describes the delta from the selected current baseline: existing
behavior, intended change, retained behavior, and meaningful boundaries. The
Spec confirmation remains the single place where the user decides a behavior
change or resolves a relevant baseline contradiction.

Focused work still reads a relevant baseline when one exists. A bug fix that
restores documented behavior remains Focused and later records `unchanged`. If
investigation reveals a new product decision or observable behavior change, the
workflow proposes upgrading to Full instead of silently changing the contract.

### Story, Construction, and Quality

The approved Spec and reviewed Story continue to guide construction. Behavior
documents are context, not a second implementation plan. Checkpoint review and
Quality remain unchanged; they do not validate or regenerate behavior documents.

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
and are committed with the Spec and source in the same approved delivery commit.

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
- Spec confirms behavior deltas and relevant contradictions.
- Delivery shows final baseline actions and exact files.

Normal domain selection, template use, and faithful reconciliation do not create
new pauses. All decisions accept natural language; no fixed ACK phrase is added.

## Git and Ownership

- Per-ticket Spec and changed behavior baseline files are durable documents.
- Story remains local by default and follows the existing conditional commit
  policy.
- Only exact files named in the approved manifest may be staged.
- Existing user changes and unrelated dirty files remain outside the manifest.
- The delivery commit keeps the repository's required
  `[ticket][feat|fix]description` format.
- No directory-wide staging or standalone documentation commit is introduced.

## Testing Strategy

Tests cover workflow behavior, not the prose of a business document:

- document paths are portable on Windows and POSIX;
- the behavior template and index guidance are available;
- Full and Focused guidance select only relevant domains;
- missing or empty indexes remain a valid first-use state;
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
- A delivered behavior change leaves the selected domain baseline current.
- A restoring bug fix creates no documentation churn.
- New domains remain discoverable through a one-line index entry.
- An interrupted flow resumes with its domain intent intact.
- Documentation never creates a repeated capability call, polling loop, or Hook
  rejection cycle.
- The user sees meaningful behavior choices and exact delivery files at existing
  confirmation points only.
