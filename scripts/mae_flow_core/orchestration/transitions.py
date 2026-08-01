"""Pure transition policy for Full and Focused lean workflows."""

from dataclasses import dataclass, replace

from .models import DeliveryPath, FlowState, Phase


@dataclass(frozen=True)
class AdvanceRequest:
    kind: str
    decision_key: str = ""
    decision_value: str = ""


@dataclass(frozen=True)
class AdvanceResult:
    state: FlowState
    needs_user: bool
    reason: str


_FULL_TRANSITIONS = {
    (Phase.STARTUP, "startup-confirmed"): Phase.SPEC,
    (Phase.SPEC, "spec-confirmed"): Phase.STORY,
    (Phase.STORY, "story-confirmed"): Phase.CONSTRUCTION,
    (Phase.CONSTRUCTION, "construction-complete"): Phase.QUALITY,
    (Phase.QUALITY, "quality-complete"): Phase.DELIVERY,
}

_FOCUSED_TRANSITIONS = {
    (Phase.STARTUP, "startup-confirmed"): Phase.CONSTRUCTION,
    (Phase.CONSTRUCTION, "construction-complete"): Phase.QUALITY,
    (Phase.QUALITY, "quality-complete"): Phase.DELIVERY,
}

_FULL_USER_STOPS = {
    (Phase.STARTUP, "startup-ready"),
    (Phase.SPEC, "spec-ready"),
    (Phase.STORY, "story-ready"),
    (Phase.CONSTRUCTION, "cp-ready"),
    (Phase.DELIVERY, "delivery-ready"),
}

_FOCUSED_USER_STOPS = {
    (Phase.STARTUP, "startup-ready"),
    (Phase.DELIVERY, "delivery-ready"),
}

_CONDITIONAL_USER_STOPS = {
    "ambiguity": "A real ambiguity needs a user decision.",
    "design-deviation": "A meaningful design deviation needs a user decision.",
    "meaningful-design-deviation": (
        "A meaningful design deviation needs a user decision."),
    "reviewer-tradeoff": "A reviewer tradeoff needs a user decision.",
    "expensive-capability-retry": (
        "An expensive capability retry needs a user decision."),
    "irreversible-action": "An irreversible action needs a user decision.",
    "irreversible-risk": "An irreversible risk needs a user decision.",
    "delivery-manifest-changed": (
        "The changed delivery manifest needs a user decision."),
}

_CONFIRMATION_DECISIONS = {
    "startup-confirmed": (
        "startup.confirmation",
        "Proceed with the selected delivery path and commit pace.",
    ),
    "spec-confirmed": (
        "spec.confirmation",
        "Proceed with the reviewed observable behavior and scope.",
    ),
    "story-confirmed": (
        "story.confirmation",
        "Proceed with the reviewed construction story.",
    ),
    "cp-confirmed": (
        "construction.checkpoint_confirmation",
        "Continue at the agreed checkpoint and commit pace.",
    ),
    "delivery-confirmed": (
        "delivery.confirmation",
        "Deliver the reviewed file manifest.",
    ),
}

_REVIEW_DECISIONS = {
    "grill-clear": (
        Phase.SPEC,
        "review.grill",
        "The Grill critic found no unresolved product ambiguity.",
    ),
    "design-review-approved": (
        Phase.STORY,
        "review.design",
        "The Design Reviewer approved the design without a tradeoff.",
    ),
    "design-review-clear": (
        Phase.STORY,
        "review.design",
        "The Design Reviewer found no blocking design concern.",
    ),
}

_NON_BLOCKING_EVENTS = {
    "capability-success": "The capability completed successfully.",
    "cp-progress": "Ordinary checkpoint progress continues.",
    "reviewer-clear": "The reviewer found no user-level tradeoff.",
}


def _with_decision(state, request, default_key, default_value):
    key = request.decision_key or default_key
    value = request.decision_value or default_value
    return state.with_decision(key, value)


def _with_review_decision(state, request, key, default_value):
    if any(existing_key == key for existing_key, unused in state.decisions):
        return state
    return state.with_decision(key, request.decision_value or default_value)


def _semantic_text(request):
    text = "%s %s" % (request.decision_key, request.decision_value)
    return " ".join(text.lower().replace("_", " ").replace("-", " ").split())


def _needs_cross_cp_review(request):
    key = " ".join(request.decision_key.lower().replace(
        "_", " ").replace("-", " ").split())
    if "coupling" in key or "shared state" in key:
        return True
    if "interface change" in key or "interface changed" in key:
        return True
    return "design drift" in key and "late" in _semantic_text(request)


def _transition_table(path):
    if path == DeliveryPath.FULL:
        return _FULL_TRANSITIONS
    return _FOCUSED_TRANSITIONS


def _user_stops(path):
    if path == DeliveryPath.FULL:
        return _FULL_USER_STOPS
    return _FOCUSED_USER_STOPS


def advance_flow(state, request):
    """Apply one semantic event without performing orchestration side effects."""
    if not isinstance(state, FlowState):
        raise TypeError("state must be a FlowState")
    if not isinstance(request, AdvanceRequest):
        raise TypeError("request must be an AdvanceRequest")
    if not isinstance(request.kind, str) or not request.kind.strip():
        raise ValueError("request kind must be a non-empty string")

    kind = request.kind.strip().lower()

    if state.status != "active":
        return AdvanceResult(
            state, False,
            "The flow is inactive; new or resume behavior is handled elsewhere.",
        )

    if kind == "exit":
        return AdvanceResult(
            replace(state, status="exited"), False,
            "The active flow exited at its current phase.",
        )
    if kind == "complete":
        return AdvanceResult(
            replace(state, status="complete"), False,
            "The active flow is complete.",
        )

    stop_reason = _CONDITIONAL_USER_STOPS.get(kind)
    if stop_reason is not None:
        return AdvanceResult(state, True, stop_reason)

    if kind == "upgrade-to-full" and state.path == DeliveryPath.FOCUSED:
        upgraded = replace(state, path=DeliveryPath.FULL, phase=Phase.SPEC)
        upgraded = _with_decision(
            upgraded,
            request,
            "workflow.path",
            "Use Full because the work needs explicit specification and design.",
        )
        return AdvanceResult(
            upgraded, False,
            "The Focused flow upgraded to Full specification.",
        )

    review = _REVIEW_DECISIONS.get(kind)
    if review is not None and state.path == DeliveryPath.FULL:
        phase, key, value = review
        if state.phase == phase:
            reviewed = _with_review_decision(state, request, key, value)
            return AdvanceResult(
                reviewed, False,
                "The reviewer result is clear and does not need a user stop.",
            )

    if kind == "cp-progress" and _needs_cross_cp_review(request):
        return AdvanceResult(
            state, False,
            "A cross-CP integration review is requested for semantic coupling.",
        )

    if kind in _NON_BLOCKING_EVENTS:
        return AdvanceResult(state, False, _NON_BLOCKING_EVENTS[kind])

    if (state.phase, kind) in _user_stops(state.path):
        return AdvanceResult(
            state, True,
            "This high-value point needs user confirmation before continuing.",
        )

    if kind == "cp-confirmed" and state.phase == Phase.CONSTRUCTION:
        confirmed = _with_decision(
            state, request, *_CONFIRMATION_DECISIONS[kind])
        return AdvanceResult(
            confirmed, False,
            "The checkpoint and commit pace were confirmed.",
        )

    if kind == "delivery-confirmed" and state.phase == Phase.DELIVERY:
        completed = _with_decision(
            state, request, *_CONFIRMATION_DECISIONS[kind])
        return AdvanceResult(
            replace(completed, status="complete"), False,
            "The reviewed delivery was confirmed and the flow is complete.",
        )

    target = _transition_table(state.path).get((state.phase, kind))
    if target is not None:
        advanced = replace(state, phase=target)
        default = _CONFIRMATION_DECISIONS.get(kind)
        if default is not None:
            advanced = _with_decision(advanced, request, *default)
        return AdvanceResult(
            advanced, False,
            "The flow advanced to %s." % target.value,
        )

    return AdvanceResult(
        state, False,
        "The event does not change this path and phase.",
    )
