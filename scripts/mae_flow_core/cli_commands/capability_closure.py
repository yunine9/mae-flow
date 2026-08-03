"""Atomically bind capability attempts to their phase-local conclusions."""

from mae_flow_core.orchestration import AdvanceRequest, Phase, advance_flow

from . import grill_receipts


def close_capability_result(root, state, advanced, request):
    """Close the phase receipt that belongs to one recorded capability fact."""
    normalized = request.kind.strip().lower()
    if not normalized.startswith("capability-"):
        return advanced
    outcome = normalized[len("capability-"):]
    capability = request.decision_key.strip().lower()
    closure = None
    if state.phase == Phase.SPEC and capability == "grill":
        if outcome == "returned":
            closure = grill_receipts.prepare_grill_request(
                root, advanced, AdvanceRequest("grill-clear"))
        else:
            closure = AdvanceRequest(
                "grill-failed", decision_value=request.decision_value)
    elif state.phase == Phase.STORY and capability == "reviewer":
        event = "reviewer-clear" if outcome == "returned" else "reviewer-failed"
        closure = grill_receipts.prepare_phase_request(
            root, advanced,
            AdvanceRequest(event, decision_value=request.decision_value),
        )
    elif state.phase == Phase.CONSTRUCTION and capability == "reviewer":
        closure = AdvanceRequest(
            "cp-review", decision_key=state.current_cp or "CP1",
            decision_value=request.decision_value)
    elif (state.phase == Phase.QUALITY and capability == "reviewer"
          and _decision_exists(advanced, "quality.integration.required")):
        closure = AdvanceRequest(
            "integration-review-complete",
            decision_value=request.decision_value)
    if closure is None:
        return advanced
    closed = advance_flow(advanced, closure)
    if closed.state == advanced:
        raise ValueError(closed.reason)
    return closed.state


def closure_already_recorded(state, event):
    """Recognize stale second commands rendered before atomic closure shipped."""
    normalized = event.strip().lower()
    keys = {key for key, unused in state.decisions}
    if normalized in {"grill-clear", "reviewer-clear"}:
        key = "review.grill" if state.phase == Phase.SPEC else "review.design"
        return key in keys
    if normalized in {
            "grill-failed", "reviewer-failed", "design-review-failed"}:
        key = (
            "review.grill.attempted"
            if state.phase == Phase.SPEC else "review.design.attempted")
        return key in keys
    if normalized in {"design-review-approved", "design-review-clear"}:
        return "review.design" in keys
    if normalized == "cp-review":
        return "construction.cp.%s.review" % (state.current_cp or "CP1") in keys
    if normalized == "integration-review-complete":
        return "quality.integration.review" in keys
    return False


def _decision_exists(state, key):
    return any(existing == key for existing, unused in state.decisions)
