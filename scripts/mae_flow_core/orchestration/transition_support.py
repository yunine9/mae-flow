"""Small shared state transforms for lean transition policy."""

from dataclasses import replace

from .models import Phase


_REVIEW_ATTEMPT = {
    Phase.SPEC: ("grill", "grill:spec:-"),
    Phase.STORY: ("reviewer", "reviewer:design"),
}


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
