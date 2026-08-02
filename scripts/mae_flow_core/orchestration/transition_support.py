"""Small shared state transforms for lean transition policy."""

from dataclasses import replace

from .capabilities import flow_attempt_context, record_flow_attempt
from .behavior_baseline import record_domain_action, select_domain
from .models import Phase


_REVIEW_ATTEMPT = {
    Phase.SPEC: ("grill", "grill:spec:-"),
    Phase.STORY: ("reviewer", "reviewer:design"),
}
_DOMAIN_ACTION_EVENTS = {
    "domain-new": "new", "domain-updated": "updated",
    "domain-unchanged": "unchanged",
}
_CP_FACT_EVENTS = {
    "cp-brief": "brief", "cp-result": "result", "cp-review": "review",
    "cp-ut-intent": "ut-intent",
}
_RISK_RESOLUTION = "risk.resolution"


def record_context_fact(state, kind, key, value):
    """Return one lightweight domain/CP update, or None for other events."""
    try:
        if kind == "domain-selected":
            return select_domain(state, key, value), (
                "Recorded one relevant business-domain baseline.")
        domain_action = _DOMAIN_ACTION_EVENTS.get(kind)
        if domain_action is not None:
            return record_domain_action(state, key, domain_action, value), (
                "Recorded one final business-domain reconciliation action.")
        cp_fact = _CP_FACT_EVENTS.get(kind)
        if cp_fact is None:
            return None
        if state.phase != Phase.CONSTRUCTION:
            return state, "Checkpoint facts apply only during Construction."
        from .checkpoints import record_checkpoint_fact
        return record_checkpoint_fact(state, key, cp_fact, value), (
            "Recorded one lightweight checkpoint fact.")
    except ValueError as exc:
        return state, str(exc)


def resolve_risk(state, identity, resolution):
    matches = tuple(
        index for index, risk in enumerate(state.risks)
        if isinstance(identity, str) and identity and risk == identity)
    if len(matches) != 1:
        return state, True, (
            "Risk resolution requires one exact, currently stored risk "
            "identity.")
    if not isinstance(resolution, str) or not resolution.strip():
        return state, True, (
            "Risk resolution requires a non-empty natural-language decision.")
    index = matches[0]
    remaining = state.risks[:index] + state.risks[index + 1:]
    audit = "%s Resolved risk: %s" % (resolution.strip(), identity)
    updated = replace(
        state, risks=remaining,
        decisions=state.decisions + ((_RISK_RESOLUTION, audit),))
    if remaining:
        return updated, True, (
            "The identified risk was resolved; other risks remain.")
    return updated, False, (
        "The identified risk was resolved by a natural-language decision.")


def add_material_risk(state, kind, detail, default_detail):
    text = detail.strip() if isinstance(detail, str) else ""
    risk = "%s: %s" % (kind, text or default_detail)
    if risk in state.risks:
        return state
    return replace(state, risks=state.risks + (risk,))


def clear_downstream_authorization(state, include_construction=False):
    prefixes = ["quality.", "delivery."]
    exact = {"review.design"}
    if include_construction:
        prefixes += ["focused.", "construction.", "review."]
        exact = set()
    decisions = tuple(
        item for item in state.decisions
        if item[0] not in exact
        and not item[0].startswith(tuple(prefixes)))
    return replace(
        state,
        decisions=decisions,
        delivery_files=(),
        current_cp="" if include_construction else state.current_cp,
    )


def latest_review_attempt(state):
    requirement = _REVIEW_ATTEMPT.get(state.phase)
    if requirement is None:
        return None
    kind, slot = requirement
    matches = tuple(
        attempt for attempt in state.capabilities
        if attempt.kind == kind and attempt.source_revision == slot)
    return matches[-1] if matches else None


def record_capability_observation(state, kind, outcome, summary):
    """Store one Agent-owned CodeAgent call fact without parsing its return."""
    context = flow_attempt_context(state, kind)
    updated = record_flow_attempt(state, context, outcome, summary=summary)
    prefix = "Capability %s did not return in slot " % context.kind.value
    risks = tuple(risk for risk in updated.risks if not risk.startswith(prefix))
    if outcome != "returned" and context.kind.value not in {"grill", "reviewer"}:
        risks += ("%s%s: %s." % (
            prefix, context.source_revision, outcome),)
    return replace(updated, risks=risks)
