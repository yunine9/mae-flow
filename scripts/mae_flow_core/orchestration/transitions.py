"""Pure transition policy for Full and Focused lean workflows."""

from dataclasses import dataclass, replace

from .models import CommitPace, DeliveryPath, FlowState, Phase
from .transition_facts import (
    DELIVERY_CONFIRMATION as _DELIVERY_CONFIRMATION,
    DELIVERY_CONFIRMED_FILE as _DELIVERY_CONFIRMED_FILE,
    STAGED_FINAL_FILE as _STAGED_FINAL_FILE,
    authorize_exact_delivery as _authorize_exact_delivery,
    checkpoint_confirmation_key as _checkpoint_confirmation_key,
    checkpoint_files as _checkpoint_files,
    checkpoint_name as _checkpoint_name,
    decision_values as _decision_values,
    latest_review_attempt as _latest_review_attempt,
    review_attempt_risk as _review_attempt_risk,
    same_exact_files as _same_exact_files,
)


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
    (Phase.SPEC, "spec-confirmed"): Phase.CONSTRUCTION,
    (Phase.STORY, "story-confirmed"): Phase.CONSTRUCTION,
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
    (Phase.SPEC, "grill-clear"): (
        "review.grill",
        "The Grill critic found no unresolved product ambiguity.",
    ),
    (Phase.SPEC, "reviewer-clear"): (
        "review.grill",
        "The Grill critic found no unresolved product ambiguity.",
    ),
    (Phase.SPEC, "reviewer-tradeoff-resolved"): (
        "review.grill",
        "The user resolved the Grill critic's documented tradeoff.",
    ),
    (Phase.SPEC, "grill-failed"): (
        "review.grill",
        "The Grill critic failure was recorded without automatic retry.",
    ),
    (Phase.SPEC, "reviewer-failed"): (
        "review.grill",
        "The Grill critic failure was recorded without automatic retry.",
    ),
    (Phase.STORY, "design-review-approved"): (
        "review.design",
        "The Design Reviewer approved the design without a tradeoff.",
    ),
    (Phase.STORY, "design-review-clear"): (
        "review.design",
        "The Design Reviewer found no blocking design concern.",
    ),
    (Phase.STORY, "reviewer-clear"): (
        "review.design",
        "The Design Reviewer found no blocking design concern.",
    ),
    (Phase.STORY, "reviewer-tradeoff-resolved"): (
        "review.design",
        "The user resolved the Design Reviewer's documented tradeoff.",
    ),
    (Phase.STORY, "design-review-failed"): (
        "review.design",
        "The Design Reviewer failure was recorded without automatic retry.",
    ),
    (Phase.STORY, "reviewer-failed"): (
        "review.design",
        "The Design Reviewer failure was recorded without automatic retry.",
    ),
}

_FULL_REQUIRED_REVIEWS = {
    (Phase.SPEC, "spec-confirmed"): "review.grill",
    (Phase.STORY, "story-confirmed"): "review.design",
}

_CROSS_CP_CAUSES = {
    "checkpoint.coupling": "coupling",
    "checkpoint.shared_state": "shared state",
    "checkpoint.interface_change": "interface change",
    "checkpoint.late_design_drift": "late design drift",
}

_NON_BLOCKING_EVENTS = {
    "capability-success": "The capability completed successfully.",
    "cp-progress": "Ordinary checkpoint progress continues.",
    "reviewer-clear": "The reviewer found no user-level tradeoff.",
}

_RISK_RESOLUTION = "risk.resolution"


def _with_decision(state, request, default_key, default_value):
    value = request.decision_value or default_value
    return state.with_decision(default_key, value)


def _with_review_decision(state, request, key, default_value):
    if any(existing_key == key for existing_key, unused in state.decisions):
        return state
    return state.with_decision(key, request.decision_value or default_value)


def _cross_cp_cause(request):
    return _CROSS_CP_CAUSES.get(request.decision_key.strip().lower())


def _transition_table(path):
    if path == DeliveryPath.FULL:
        return _FULL_TRANSITIONS
    return _FOCUSED_TRANSITIONS


def _user_stops(path):
    if path == DeliveryPath.FULL:
        return _FULL_USER_STOPS
    return _FOCUSED_USER_STOPS


def _resolve_risk(state, request):
    identity = request.decision_key
    resolution = request.decision_value
    matches = tuple(
        index for index, risk in enumerate(state.risks)
        if isinstance(identity, str) and identity and risk == identity)
    if len(matches) != 1:
        return AdvanceResult(
            state,
            True,
            "Risk resolution requires one exact, currently stored risk "
            "identity.",
        )
    if not isinstance(resolution, str) or not resolution.strip():
        return AdvanceResult(
            state,
            True,
            "Risk resolution requires a non-empty natural-language decision.",
        )

    index = matches[0]
    remaining = state.risks[:index] + state.risks[index + 1:]
    audit = "%s Resolved risk: %s" % (resolution.strip(), identity)
    updated = replace(
        state,
        risks=remaining,
        decisions=state.decisions + ((_RISK_RESOLUTION, audit),),
    )
    if remaining:
        return AdvanceResult(
            updated,
            True,
            "The identified risk was resolved; other risks remain.",
        )
    return AdvanceResult(
        updated,
        False,
        "The identified risk was resolved by a natural-language decision.",
    )


def advance_flow(state, request):
    """Apply one semantic event without performing orchestration side effects."""
    if not isinstance(state, FlowState):
        raise TypeError("state must be a FlowState")
    if not isinstance(request, AdvanceRequest):
        raise TypeError("request must be an AdvanceRequest")
    if not isinstance(request.kind, str) or not request.kind.strip():
        raise ValueError("request kind must be a non-empty string")

    kind = request.kind.strip().lower()

    if kind == "exit":
        return AdvanceResult(
            replace(state, status="exited"), False,
            "The flow exited unconditionally at its current phase.",
        )

    if state.status != "active":
        return AdvanceResult(
            state, False,
            "The flow is inactive; new or resume behavior is handled elsewhere.",
        )

    if kind == "risk-resolved":
        return _resolve_risk(state, request)

    if kind in {"delivery-completed", "complete"}:
        if state.phase != Phase.DELIVERY:
            return AdvanceResult(
                state, False,
                "Delivery completion applies only in the Delivery phase.",
            )
        if state.risks:
            return AdvanceResult(
                state,
                True,
                "Delivery cannot complete while workflow risks remain "
                "unresolved.",
            )
        if not any(key == _DELIVERY_CONFIRMATION
                   for key, unused in state.decisions):
            return AdvanceResult(
                state, False,
                "Delivery completion requires prior delivery authorization.",
            )
        confirmed_files = _decision_values(state, _DELIVERY_CONFIRMED_FILE)
        if (not state.delivery_files
                or not _same_exact_files(
                    confirmed_files, state.delivery_files)):
            return AdvanceResult(
                state, False,
                "Delivery completion requires confirmation of the current "
                "exact manifest.",
            )
        if state.commit_pace == CommitPace.STAGED:
            final_files = _decision_values(state, _STAGED_FINAL_FILE)
            checkpoint_files = _checkpoint_files(state)
            if (not final_files
                    or not _same_exact_files(final_files, state.delivery_files)
                    or not _same_exact_files(
                        checkpoint_files, state.delivery_files)):
                return AdvanceResult(
                    state, False,
                    "Staged delivery completion requires the recorded final "
                    "checkpoint union.",
                )
        completed = _with_review_decision(
            state,
            request,
            "delivery.result",
            "The delivery adapter reported completed side effects.",
        )
        return AdvanceResult(
            replace(completed, status="complete"), False,
            "The authorized delivery side effects completed.",
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

    review = _REVIEW_DECISIONS.get((state.phase, kind))
    if review is not None and state.path == DeliveryPath.FULL:
        attempt = _latest_review_attempt(state)
        if attempt is None:
            return AdvanceResult(
                state,
                False,
                "The matching review capability attempt has not been "
                "recorded for this phase.",
            )
        if attempt.outcome != "returned" or kind.endswith("-failed"):
            failed = _review_attempt_risk(state, attempt)
            return AdvanceResult(
                failed,
                True,
                "The review capability did not return normally; no required "
                "review fact was recorded.",
            )
        key, value = review
        reviewed = _with_review_decision(state, request, key, value)
        return AdvanceResult(
            reviewed, False,
            "The reviewer completed without creating another user stop.",
        )

    cross_cp_cause = _cross_cp_cause(request)
    if (kind == "cp-progress"
            and state.phase == Phase.CONSTRUCTION
            and cross_cp_cause is not None):
        return AdvanceResult(
            state, False,
            "A cross-CP integration review is requested for %s." %
            cross_cp_cause,
        )

    if kind in _NON_BLOCKING_EVENTS:
        return AdvanceResult(state, False, _NON_BLOCKING_EVENTS[kind])

    if (kind == "cp-ready"
            and state.phase == Phase.CONSTRUCTION
            and state.path == DeliveryPath.FULL):
        current = state.current_cp or "CP1"
        requested = request.decision_key.strip()
        if requested:
            requested = _checkpoint_name(requested)
            current_key = _checkpoint_confirmation_key(current)
            if (requested != current and not any(
                    key == current_key for key, unused in state.decisions)):
                return AdvanceResult(
                    state,
                    True,
                    "The current checkpoint must be confirmed before the "
                    "next checkpoint is opened.",
                )
            current = requested
        ready = replace(state, current_cp=current)
        return AdvanceResult(
            ready,
            True,
            "This checkpoint needs user confirmation before continuing.",
        )

    if (state.phase, kind) in _user_stops(state.path):
        return AdvanceResult(
            state, True,
            "This high-value point needs user confirmation before continuing.",
        )

    if kind == "cp-confirmed" and state.phase == Phase.CONSTRUCTION:
        checkpoint = state.current_cp or "CP1"
        if state.path == DeliveryPath.FULL:
            checkpoint = _checkpoint_name(checkpoint)
        key = _checkpoint_confirmation_key(checkpoint)
        confirmed = _with_review_decision(
            replace(state, current_cp=checkpoint),
            request,
            key,
            _CONFIRMATION_DECISIONS[kind][1],
        )
        return AdvanceResult(
            confirmed, False,
            "The checkpoint and commit pace were confirmed.",
        )

    if kind == "delivery-confirmed" and state.phase == Phase.DELIVERY:
        if not state.delivery_files:
            return AdvanceResult(
                state,
                False,
                "Delivery confirmation requires a non-empty exact manifest.",
            )
        authorized = _authorize_exact_delivery(state, request)
        return AdvanceResult(
            authorized, False,
            "The reviewed delivery was authorized; side effects remain pending.",
        )

    required_review = None
    if state.path == DeliveryPath.FULL:
        required_review = _FULL_REQUIRED_REVIEWS.get((state.phase, kind))
    if (required_review is not None
            and not any(key == required_review
                        for key, unused in state.decisions)):
        return AdvanceResult(
            state, False,
            "The required reviewer has not completed this phase.",
        )

    if (state.phase == Phase.QUALITY
            and kind == "quality-complete"
            and state.risks):
        return AdvanceResult(
            state,
            True,
            "Quality cannot advance to Delivery while workflow risks remain "
            "unresolved.",
        )

    target = _transition_table(state.path).get((state.phase, kind))
    if target is not None:
        advanced = replace(state, phase=target)
        if target == Phase.CONSTRUCTION and not advanced.current_cp:
            advanced = replace(advanced, current_cp="CP1")
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
