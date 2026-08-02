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
FINAL_CONFORMANCE = "quality.final_conformance"
INTEGRATION_REQUIRED = "quality.integration.required"
INTEGRATION_REVIEW = "quality.integration.review"
_CROSS_CP_CAUSES = {
    "checkpoint.coupling": "coupling",
    "checkpoint.shared_state": "shared state",
    "checkpoint.interface_change": "interface change",
    "checkpoint.late_design_drift": "late design drift",
}


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


def decision_exists(state, key):
    return any(existing == key for existing, unused in state.decisions)


def replace_decision(state, key, value):
    decisions = tuple(item for item in state.decisions if item[0] != key)
    return replace(state, decisions=decisions + ((key, value),))


def cp_build_attempt(state, checkpoint):
    slot = "build:construction:%s" % (checkpoint or "CP1")
    return next((
        attempt for attempt in reversed(state.capabilities)
        if attempt.kind == "build" and attempt.source_revision == slot
    ), None)


def record_quality_fact(state, kind, key, value):
    """Record thin Quality facts and semantic cross-CP review triggers."""
    text = value.strip() if isinstance(value, str) else ""
    if kind == "final-conformance":
        if state.phase != Phase.QUALITY:
            return state, False, "Final conformance applies only in Quality."
        if not text:
            return state, False, (
                "Final conformance needs one natural-language conclusion.")
        return replace_decision(state, FINAL_CONFORMANCE, text), False, (
            "Recorded final behavior, design, and coverage conformance.")
    if kind == "integration-review-complete":
        if (state.phase != Phase.QUALITY
                or not decision_exists(state, INTEGRATION_REQUIRED)):
            return state, False, (
                "Integration review completion requires a semantic trigger.")
        slot = "reviewer:quality:%s" % (state.current_cp or "CP1")
        if not any(
                attempt.kind == "reviewer"
                and attempt.source_revision == slot
                for attempt in reversed(state.capabilities)):
            return state, False, (
                "Integration review completion requires one reviewer attempt.")
        if not text:
            return state, False, (
                "Integration review needs one natural-language conclusion.")
        return replace_decision(state, INTEGRATION_REVIEW, text), False, (
            "Recorded the one conditional integration review conclusion.")
    cause = _CROSS_CP_CAUSES.get(key.strip().lower())
    if kind != "cp-progress" or state.phase != Phase.CONSTRUCTION or not cause:
        return None
    detail = text or "semantic coupling detected"
    return replace_decision(
        state, INTEGRATION_REQUIRED, "%s: %s" % (cause, detail)), False, (
        "A cross-CP integration review is requested for %s." % cause)


def quality_completion_gap(state):
    if not decision_exists(state, FINAL_CONFORMANCE):
        return "Quality completion requires one final conformance conclusion."
    if (decision_exists(state, INTEGRATION_REQUIRED)
            and not decision_exists(state, INTEGRATION_REVIEW)):
        return "The semantic risk requires one integration review conclusion."
    return ""


def clear_downstream_authorization(state, include_construction=False):
    prefixes = ["quality.", "delivery."]
    exact = {"review.design"}
    retained = {INTEGRATION_REQUIRED}
    if include_construction:
        prefixes += ["focused.", "construction.", "review."]
        exact = set()
        retained = set()
    decisions = tuple(
        item for item in state.decisions
        if item[0] in retained
        or (
            item[0] not in exact
            and not item[0].startswith(tuple(prefixes))
        )
    )
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
