"""Pure policy for Full Spec's recoverable Interactive Grill subflow."""

from dataclasses import dataclass, replace
import json
import re

from .models import DeliveryPath, FlowState, Phase


_QUESTION_PREFIX = "grill.question."
_ANSWER_PREFIX = "grill.answer."
_CONVERGENCE = "grill.convergence"
_CRITIC = "review.grill"
_QUESTION_ID = re.compile(r"GQ-[A-Z0-9][A-Z0-9._-]*")
_DIGEST = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class GrillStatus:
    open_question: str
    question_ids: tuple
    answered_ids: tuple
    convergence: dict
    critic: dict


def _json_object(raw):
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def grill_status(state):
    if not isinstance(state, FlowState):
        raise TypeError("state must be a FlowState")
    questions = []
    answers = []
    convergence = {}
    critic = {}
    for key, value in state.decisions:
        if key.startswith(_QUESTION_PREFIX):
            question_id = key[len(_QUESTION_PREFIX):]
            if question_id not in questions:
                questions.append(question_id)
        elif key.startswith(_ANSWER_PREFIX):
            question_id = key[len(_ANSWER_PREFIX):]
            if question_id not in answers:
                answers.append(question_id)
        elif key == _CONVERGENCE:
            convergence = _json_object(value)
        elif key == _CRITIC:
            critic = _json_object(value)
    open_questions = tuple(
        question_id for question_id in questions if question_id not in answers)
    return GrillStatus(
        open_question=open_questions[0] if open_questions else "",
        question_ids=tuple(questions),
        answered_ids=tuple(answers),
        convergence=convergence,
        critic=critic,
    )


def _without_receipts(state):
    return replace(
        state,
        decisions=tuple(
            item for item in state.decisions
            if item[0] not in {_CONVERGENCE, _CRITIC}),
    )


def _full_spec_gap(state):
    if state.path != DeliveryPath.FULL or state.phase != Phase.SPEC:
        return "Interactive Grill events apply only to Full Spec."
    return ""


def _question_metadata(raw, status):
    value = _json_object(raw)
    for field in ("parent", "evidence", "impact", "recommendation"):
        if not isinstance(value.get(field), str):
            return {}, "Grill question metadata requires text field: %s." % field
    for field in ("evidence", "impact", "recommendation"):
        if not value[field].strip():
            return {}, "Grill question metadata field %s must not be empty." % field
    parent = value["parent"].strip()
    if parent and parent not in status.answered_ids:
        return {}, "Parent Grill question %s must already be answered." % parent
    return value, ""


def _receipt(raw, required):
    value = _json_object(raw)
    for field in required:
        if field not in value:
            return {}, "Grill receipt is missing %s." % field
    return value, ""


def _valid_digest(value):
    return isinstance(value, str) and bool(_DIGEST.fullmatch(value))


def apply_grill_event(state, request):
    """Apply one Grill event, or return ``None`` for unrelated events."""
    kind = request.kind.strip().lower()
    if kind not in {
            "grill-question", "grill-answer", "grill-converged",
            "grill-clear"}:
        return None
    gap = _full_spec_gap(state)
    if gap:
        return state, False, gap

    status = grill_status(state)
    question_id = request.decision_key.strip()

    if kind == "grill-question":
        if not _QUESTION_ID.fullmatch(question_id):
            return state, False, "Grill question key must be a stable GQ-* ID."
        if question_id in status.question_ids:
            return state, False, "Grill question %s already exists." % question_id
        if status.open_question:
            return state, True, (
                "Answer Grill question %s before opening another question."
                % status.open_question)
        unused, error = _question_metadata(request.decision_value, status)
        if error:
            return state, False, error
        reopened = _without_receipts(state)
        updated = reopened.with_decision(
            _QUESTION_PREFIX + question_id, request.decision_value)
        return updated, True, (
            "Interactive Grill question %s needs one user answer."
            % question_id)

    if kind == "grill-answer":
        if not status.open_question:
            return state, False, "Interactive Grill has no open question."
        if question_id != status.open_question:
            return state, True, (
                "Current Grill question is %s, not %s."
                % (status.open_question, question_id or "an empty key"))
        answer = request.decision_value.strip()
        if not answer:
            return state, True, "Interactive Grill answer must not be empty."
        updated = _without_receipts(state).with_decision(
            _ANSWER_PREFIX + question_id, answer)
        return updated, False, "Recorded the current Grill user answer."

    if kind == "grill-converged":
        if status.open_question:
            return state, True, (
                "Grill question %s is still open." % status.open_question)
        if not status.answered_ids:
            return state, True, (
                "Interactive Grill needs at least one answered question."
            )
        receipt, error = _receipt(
            request.decision_value, ("answer_count", "grill_sha256"))
        if error:
            return state, False, error
        if receipt["answer_count"] != len(status.answered_ids):
            return state, False, "Grill receipt answer count does not match state."
        if not _valid_digest(receipt["grill_sha256"]):
            return state, False, "Grill receipt digest is invalid."
        converged = _without_receipts(state).with_decision(
            _CONVERGENCE, request.decision_value)
        return converged, False, "Interactive Grill converged."

    if not status.convergence:
        return state, False, "Interactive Grill must converge before criticism."
    receipt, error = _receipt(
        request.decision_value,
        ("grill_sha256", "spec_sha256", "input_coverage"),
    )
    if error:
        return state, False, error
    if (not _valid_digest(receipt["grill_sha256"])
            or not _valid_digest(receipt["spec_sha256"])):
        return state, False, "Grill critic receipt digest is invalid."
    if receipt["grill_sha256"] != status.convergence.get("grill_sha256"):
        return state, False, "Grill critic digest does not match convergence."
    if receipt["input_coverage"] != "complete":
        return state, False, "Grill critic input coverage is not complete."
    reviewed = replace(
        state,
        decisions=tuple(
            item for item in state.decisions if item[0] != _CRITIC),
    ).with_decision(_CRITIC, request.decision_value)
    return reviewed, False, "Grill critic confirmed complete input coverage."


def grill_confirmation_gap(state):
    """Return why Full Spec cannot be confirmed, or an empty string."""
    if state.path != DeliveryPath.FULL or state.phase != Phase.SPEC:
        return ""
    status = grill_status(state)
    if status.open_question:
        return "Interactive Grill question %s is still open." % status.open_question
    if not status.answered_ids:
        return "Interactive Grill needs at least one answered question."
    if not status.convergence:
        return "Interactive Grill has not converged."
    if not status.critic:
        return "The Grill critic has not confirmed input coverage."
    if status.critic.get("input_coverage") != "complete":
        return "The Grill critic input coverage is incomplete."
    return ""

