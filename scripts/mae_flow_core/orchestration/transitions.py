"""Pure transition policy for Full and Focused lean workflows."""

from dataclasses import dataclass, replace
from .models import CommitPace, DeliveryPath, FlowState, Phase
from .checkpoints import (
    advance_checkpoint_event as _advance_checkpoint_event,
)
from .transition_facts import (
    DELIVERY_CONFIRMATION as _DELIVERY_CONFIRMATION,
    add_material_risk as _add_material_risk,
    authorize_exact_delivery as _authorize_exact_delivery,
    clear_downstream_authorization as _clear_downstream_authorization,
    current_delivery_receipt as _current_delivery_receipt,
    delivery_effects_observed as _delivery_effects_observed,
    latest_review_attempt as _latest_review_attempt,
    staged_checkpoint_receipts_valid as _staged_checkpoint_receipts_valid,
)
from .transition_support import (
    cp_build_attempt as _cp_build_attempt,
    quality_completion_gap as _quality_completion_gap,
    record_context_fact as _record_context_fact,
    record_capability_observation as _record_capability_observation,
    record_quality_fact as _record_quality_fact,
    resolve_risk as _resolve_risk,
    return_to_repair_checkpoint as _return_to_repair_checkpoint,
)
from .grill_session import apply_grill_event, grill_confirmation_gap
from .capabilities import capability_command_hint, capability_usage

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
_CONFIRMATION_KEYS = {
    "startup-confirmed": "startup.confirmation",
    "spec-confirmed": "spec.confirmation",
    "story-confirmed": "story.confirmation",
}
_REVIEW_DECISIONS = {
    (Phase.SPEC, "reviewer-clear"): ("review.grill", "Grill found no ambiguity."),
    (Phase.SPEC, "reviewer-tradeoff-resolved"): (
        "review.grill", "The user resolved the Grill tradeoff."),
    (Phase.SPEC, "grill-failed"): ("review.grill", "Grill did not return."),
    (Phase.SPEC, "reviewer-failed"): ("review.grill", "Grill did not return."),
    (Phase.STORY, "design-review-approved"): (
        "review.design", "The Design Reviewer approved the design."),
    (Phase.STORY, "design-review-clear"): (
        "review.design", "The Design Reviewer found no blocking concern."),
    (Phase.STORY, "reviewer-clear"): (
        "review.design", "The Design Reviewer found no blocking concern."),
    (Phase.STORY, "reviewer-tradeoff-resolved"): (
        "review.design", "The user resolved the design tradeoff."),
    (Phase.STORY, "design-review-failed"): (
        "review.design", "The Design Reviewer did not return."),
    (Phase.STORY, "reviewer-failed"): (
        "review.design", "The Design Reviewer did not return."),
}
_FULL_REQUIRED_REVIEWS = {
    (Phase.SPEC, "spec-confirmed"): "review.grill",
    (Phase.STORY, "story-confirmed"): "review.design",
}
_NON_BLOCKING_EVENTS = {
    "capability-success": "The capability completed successfully.",
    "cp-progress": "Ordinary checkpoint progress continues.",
    "reviewer-clear": "The reviewer found no user-level tradeoff.",
}
_CAPABILITY_OUTCOMES = {
    "capability-returned": "returned",
    "capability-failed-to-start": "failed-to-start",
    "capability-timed-out": "timed-out",
    "capability-not-observed": "not-observed",
}
_USER_DECISION_EVENTS = frozenset(
    set(_CONFIRMATION_KEYS)
    | {"grill-answer", "cp-confirmed", "cp-revise", "delivery-confirmed",
       "reviewer-tradeoff-resolved", "upgrade-to-full",
       "quality-defect-repair", "delivery-defect-repair"})

def _with_decision(state, request, default_key, default_value):
    value = request.decision_value or default_value
    return state.with_decision(default_key, value)


def _with_review_decision(state, request, key, default_value):
    if any(existing_key == key for existing_key, unused in state.decisions):
        return state
    return state.with_decision(key, request.decision_value or default_value)


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

    capability_hint = capability_command_hint(kind, request.decision_key)
    known_capability_events = (
        set(_CAPABILITY_OUTCOMES)
        | set(_NON_BLOCKING_EVENTS)
        | set(_CONDITIONAL_USER_STOPS)
    )
    if capability_hint and kind not in known_capability_events:
        return AdvanceResult(
            state, False, capability_usage(capability_hint))

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

    if (kind in _USER_DECISION_EVENTS
            and (not isinstance(request.decision_value, str)
                 or not request.decision_value.strip())):
        return AdvanceResult(
            state,
            True,
            "This user-owned transition requires a non-empty natural-language "
            "decision.",
        )

    if kind == "risk-resolved":
        return AdvanceResult(*_resolve_risk(
            state, request.decision_key, request.decision_value))

    context_fact = _record_context_fact(
        state, kind, request.decision_key, request.decision_value)
    if context_fact is not None:
        return AdvanceResult(context_fact[0], False, context_fact[1])

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
        receipt = _current_delivery_receipt(state)
        if receipt is None:
            return AdvanceResult(
                state, False,
                "Delivery completion requires a current exact receipt.",
            )
        if not _delivery_effects_observed(state, receipt):
            return AdvanceResult(
                state,
                False,
                "Delivery completion requires Hook-observed Git effects from "
                "the current receipt.",
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

    capability_outcome = _CAPABILITY_OUTCOMES.get(kind)
    if capability_outcome is not None:
        observed = _record_capability_observation(
            state,
            request.decision_key.strip(),
            capability_outcome,
            request.decision_value,
        )
        return AdvanceResult(
            observed,
            False,
            "Recorded one opaque CodeAgent capability call fact.",
        )

    quality_fact = _record_quality_fact(
        state, kind, request.decision_key, request.decision_value)
    if quality_fact is not None:
        return AdvanceResult(*quality_fact)

    stop_reason = _CONDITIONAL_USER_STOPS.get(kind)
    if stop_reason is not None:
        stopped = _add_material_risk(
            state, kind, request.decision_value, stop_reason)
        return AdvanceResult(stopped, True, stop_reason)

    if kind == "upgrade-to-full" and state.path == DeliveryPath.FOCUSED:
        upgraded = _clear_downstream_authorization(
            replace(state, path=DeliveryPath.FULL, phase=Phase.SPEC),
            include_construction=True,
        )
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

    if kind in {"quality-defect-repair", "delivery-defect-repair"}:
        expected = (
            Phase.QUALITY if kind == "quality-defect-repair"
            else Phase.DELIVERY)
        if state.phase != expected:
            return AdvanceResult(
                state, False,
                "%s applies only in the %s phase."
                % (kind, expected.value.title()),
            )
        repaired = _return_to_repair_checkpoint(
            state, request.decision_value)
        return AdvanceResult(
            repaired,
            False,
            "The explicit defect repair opened a fresh Construction CP.",
        )

    if kind == "grill-clear":
        attempt = _latest_review_attempt(state)
        if attempt is None:
            return AdvanceResult(
                state,
                False,
                "The matching Grill critic attempt has not been recorded.",
            )
        if attempt.outcome != "returned":
            attempted = _with_review_decision(
                state,
                request,
                "review.grill.attempted",
                "The required reviewer was attempted once and did not return.",
            )
            return AdvanceResult(
                attempted,
                False,
                "The Grill critic did not return; complete coverage remains "
                "required before Spec confirmation.",
            )

    grill_result = apply_grill_event(state, request)
    if grill_result is not None:
        return AdvanceResult(*grill_result)

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
            review_key, unused = review
            attempted = _with_review_decision(
                state,
                request,
                review_key + ".attempted",
                "The required reviewer was attempted once and did not return.",
            )
            return AdvanceResult(
                attempted,
                False,
                "The review capability did not return normally; the attempt "
                "was recorded without retrying or blocking user confirmation.",
            )
        key, value = review
        reviewed = _with_review_decision(state, request, key, value)
        if kind == "reviewer-tradeoff-resolved":
            reviewed = replace(
                reviewed,
                risks=tuple(
                    risk for risk in reviewed.risks
                    if not risk.startswith("reviewer-tradeoff:")),
            )
        return AdvanceResult(
            reviewed, False,
            "The reviewer completed without creating another user stop.",
        )

    if kind in _NON_BLOCKING_EVENTS:
        return AdvanceResult(state, False, _NON_BLOCKING_EVENTS[kind])

    checkpoint_result = _advance_checkpoint_event(state, kind, request)
    if checkpoint_result is not None:
        return AdvanceResult(*checkpoint_result)

    if (state.phase, kind) in _user_stops(state.path):
        return AdvanceResult(
            state, True,
            "This high-value point needs user confirmation before continuing.",
        )

    if kind == "delivery-confirmed" and state.phase == Phase.DELIVERY:
        if not state.delivery_files:
            return AdvanceResult(
                state,
                False,
                "Delivery confirmation requires a non-empty exact manifest.",
            )
        try:
            authorized = _authorize_exact_delivery(state, request)
        except ValueError as exc:
            return AdvanceResult(state, False, str(exc))
        return AdvanceResult(
            authorized, False,
            "The reviewed delivery was authorized; side effects remain pending.",
        )

    if kind == "spec-confirmed":
        grill_gap = grill_confirmation_gap(state)
        if grill_gap:
            return AdvanceResult(state, False, grill_gap)

    required_review = None
    if state.path == DeliveryPath.FULL:
        required_review = _FULL_REQUIRED_REVIEWS.get((state.phase, kind))
    if (required_review is not None
            and not any(key in {
                            required_review, required_review + ".attempted"}
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

    if state.phase == Phase.QUALITY and kind == "quality-complete":
        gap = _quality_completion_gap(state)
        if gap:
            return AdvanceResult(state, False, gap)

    if state.risks and kind in {
            "spec-confirmed", "story-confirmed", "construction-complete"}:
        return AdvanceResult(
            state,
            True,
            "The phase cannot advance while workflow risks remain unresolved.",
        )

    if (state.phase == Phase.CONSTRUCTION
            and kind == "construction-complete"
            and _cp_build_attempt(
                state, state.current_cp or "CP1") is None):
        return AdvanceResult(
            state, False,
            "Construction completion requires one configured Build attempt "
            "for the current CP.",
        )

    if (state.path == DeliveryPath.FULL
            and state.phase == Phase.CONSTRUCTION
            and state.commit_pace == CommitPace.STAGED
            and kind == "construction-complete"
            and not _staged_checkpoint_receipts_valid(state)):
        return AdvanceResult(
            state,
            False,
            "Full Staged Construction requires a valid receipt for the "
            "current CP and every planned CP.",
        )

    target = _transition_table(state.path).get((state.phase, kind))
    if target is not None:
        advanced = replace(state, phase=target)
        if target == Phase.CONSTRUCTION and not advanced.current_cp:
            advanced = replace(advanced, current_cp="CP1")
        confirmation_key = _CONFIRMATION_KEYS.get(kind)
        if confirmation_key is not None:
            advanced = advanced.with_decision(
                confirmation_key, request.decision_value.strip())
        if (state.path == DeliveryPath.FOCUSED
                and state.phase == Phase.STARTUP
                and kind == "startup-confirmed"):
            advanced = advanced.with_decision(
                "focused.scope_approved", request.decision_value.strip())
        return AdvanceResult(
            advanced, False,
            "The flow advanced to %s." % target.value,
        )

    return AdvanceResult(
        state, False,
        "The event does not change this path and phase.",
    )
