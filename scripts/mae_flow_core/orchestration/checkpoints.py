"""Small recoverable checkpoint briefs, results, reviews, and UT intents."""

from dataclasses import dataclass, replace
import json
import re

from .models import CommitPace, DeliveryPath, FlowState, Phase
from .transition_facts import (
    GIT_COMMIT_OBSERVATION,
    authorize_checkpoint,
    checkpoint_confirmation_key,
    checkpoint_name,
    checkpoint_ready_key,
    checkpoint_receipt_key,
    decision_values,
    load_delivery_receipt,
    valid_delivery_receipt,
)
from .transition_support import cp_build_attempt


_PREFIX = "construction.cp."
_FACTS = {"brief", "result", "review", "ut-intent"}


@dataclass(frozen=True)
class CheckpointFacts:
    name: str
    brief: str = ""
    result: str = ""
    review: str = ""
    ut_intent: str = ""


def _key(checkpoint, fact):
    if fact not in _FACTS:
        raise ValueError("unsupported checkpoint fact")
    return "%s%s.%s" % (_PREFIX, checkpoint_name(checkpoint), fact)


def record_checkpoint_fact(state, checkpoint, fact, text):
    if not isinstance(state, FlowState):
        raise TypeError("state must be a FlowState")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("checkpoint fact must be non-empty natural language")
    key = _key(checkpoint, fact)
    value = text.strip()
    decisions = list(state.decisions)
    for index, item in enumerate(decisions):
        if item[0] == key:
            decisions[index] = (key, value)
            break
    else:
        decisions.append((key, value))
    return replace(state, decisions=tuple(decisions))


def checkpoint_facts(state):
    if not isinstance(state, FlowState):
        raise TypeError("state must be a FlowState")
    order = []
    values = {}
    for key, value in state.decisions:
        if not key.startswith(_PREFIX):
            continue
        remainder = key[len(_PREFIX):]
        if "." not in remainder:
            continue
        checkpoint, fact = remainder.rsplit(".", 1)
        if fact not in _FACTS:
            continue
        if checkpoint not in values:
            values[checkpoint] = {}
            order.append(checkpoint)
        values[checkpoint][fact] = value
    return tuple(
        CheckpointFacts(
            name,
            brief=values[name].get("brief", ""),
            result=values[name].get("result", ""),
            review=values[name].get("review", ""),
            ut_intent=values[name].get("ut-intent", ""),
        )
        for name in order
    )


def checkpoint_context(state, checkpoint):
    name = checkpoint_name(checkpoint)
    for item in checkpoint_facts(state):
        if item.name == name:
            return item
    return CheckpointFacts(name)


def next_checkpoint_context(state, checkpoint):
    name = checkpoint_name(checkpoint)
    items = checkpoint_facts(state)
    for index, item in enumerate(items):
        if item.name == name and index + 1 < len(items):
            return items[index + 1]
    return None


def cumulative_ut_handoff(state):
    return "\n".join(
        "%s: %s" % (item.name, item.ut_intent)
        for item in checkpoint_facts(state) if item.ut_intent)


def checkpoint_commit_observed(state, checkpoint):
    """Whether Hook recorded the one commit bound to this Full Staged CP."""
    values = decision_values(state, checkpoint_receipt_key(checkpoint))
    if len(values) != 1 or not valid_delivery_receipt(
            state, values[0], checkpoint):
        return False
    try:
        digest = load_delivery_receipt(values[0]).digest
    except ValueError:
        return False
    for raw in decision_values(state, GIT_COMMIT_OBSERVATION):
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if (isinstance(value, dict)
                and value.get("receipt_digest") == digest
                and isinstance(value.get("sha"), str)
                and re.fullmatch(r"[0-9a-f]{40}", value["sha"])):
            return True
    return False


def checkpoint_commit_pending(state):
    """Return the confirmed CP whose exact local commit is still pending."""
    if (state.phase != Phase.CONSTRUCTION
            or state.path != DeliveryPath.FULL
            or state.commit_pace != CommitPace.STAGED
            or not state.current_cp):
        return ""
    checkpoint = checkpoint_name(state.current_cp)
    values = decision_values(state, checkpoint_receipt_key(checkpoint))
    if (len(values) == 1
            and valid_delivery_receipt(state, values[0], checkpoint)
            and not checkpoint_commit_observed(state, checkpoint)):
        return checkpoint
    return ""


def _open_checkpoint(state, request):
    current = state.current_cp or "CP1"
    requested = request.decision_key.strip()
    if not requested:
        return state, False, "Opening a checkpoint requires its exact name."
    requested = checkpoint_name(requested)
    if requested == current:
        return state, False, "The requested checkpoint is already current."
    if cp_build_attempt(state, current) is None:
        return state, False, (
            "The completed CP needs one configured Build attempt before "
            "the next CP opens.")
    if state.path == DeliveryPath.FULL:
        current_key = checkpoint_confirmation_key(current)
        if not any(key == current_key for key, unused in state.decisions):
            return state, True, (
                "The current checkpoint must be confirmed before the next "
                "checkpoint is opened.")
        if (state.commit_pace == CommitPace.STAGED
                and not checkpoint_commit_observed(state, current)):
            return state, False, (
                "The confirmed checkpoint must be committed before the next "
                "checkpoint is opened.")
    return replace(state, current_cp=requested), False, (
        "Opened the next checkpoint without a premature user stop.")


def _ready_checkpoint(state, request):
    current = state.current_cp or "CP1"
    requested = request.decision_key.strip()
    if requested and checkpoint_name(requested) != current:
        return state, False, (
            "cp-ready applies only to the current checkpoint; open the next "
            "checkpoint separately.")
    if cp_build_attempt(state, current) is None:
        return state, False, (
            "The current CP needs one configured Build attempt before user "
            "review.")
    if state.commit_pace == CommitPace.STAGED:
        prefix = "delivery.cp.%s." % current
        files = decision_values(state, prefix + "file")
        messages = decision_values(state, prefix + "message")
        source_shas = decision_values(state, prefix + "source_sha")
        if not files or len(messages) != 1 or len(source_shas) != 1:
            return state, False, (
                "The current Staged CP needs its exact manifest, commit "
                "message, and source snapshot before user review.")
    ready_key = checkpoint_ready_key(current)
    decisions = tuple(
        item for item in state.decisions if item[0] != ready_key)
    ready = replace(
        state,
        decisions=decisions + ((ready_key, "true"),),
        current_cp=current,
    )
    if state.path == DeliveryPath.FOCUSED:
        return ready, False, (
            "Focused checkpoint completion updated the internal cursor.")
    return ready, True, (
        "This checkpoint needs user confirmation before continuing.")


def _confirm_checkpoint(state, request):
    checkpoint = state.current_cp or "CP1"
    if state.path == DeliveryPath.FULL:
        checkpoint = checkpoint_name(checkpoint)
        if not any(
                key == checkpoint_ready_key(checkpoint)
                for key, unused in state.decisions):
            return state, True, (
                "The checkpoint can be confirmed only after its Build "
                "completed and cp-ready exposed the review card.")
    if state.commit_pace == CommitPace.STAGED:
        try:
            confirmed = authorize_checkpoint(state, request, checkpoint)
        except ValueError as exc:
            return state, False, str(exc)
    else:
        key = checkpoint_confirmation_key(checkpoint)
        decisions = tuple(item for item in state.decisions if item[0] != key)
        confirmed = replace(
            state,
            current_cp=checkpoint,
            decisions=decisions + ((key, request.decision_value.strip()),),
        )
    return confirmed, False, "The checkpoint and commit pace were confirmed."


def _revise_checkpoint(state, request):
    checkpoint = checkpoint_name(state.current_cp or "CP1")
    if checkpoint_commit_observed(state, checkpoint):
        return state, False, (
            "The checkpoint is already committed; open a new repair CP "
            "instead of rewriting reviewed history.")
    removable = {
        checkpoint_ready_key(checkpoint),
        checkpoint_confirmation_key(checkpoint),
        "construction.cp.%s.revision" % checkpoint,
    }
    plan_prefix = "delivery.cp.%s." % checkpoint
    decisions = tuple(
        item for item in state.decisions
        if item[0] not in removable and not item[0].startswith(plan_prefix))
    decisions += ((
        "construction.cp.%s.revision" % checkpoint,
        request.decision_value.strip(),
    ),)
    return replace(state, decisions=decisions, delivery_files=()), False, (
        "The uncommitted checkpoint review was reopened for revision.")


def advance_checkpoint_event(state, kind, request):
    """Return a transition tuple for one CP lifecycle event, else None."""
    if state.phase != Phase.CONSTRUCTION:
        return None
    handlers = {
        "cp-opened": _open_checkpoint,
        "cp-ready": _ready_checkpoint,
        "cp-confirmed": _confirm_checkpoint,
        "cp-revise": _revise_checkpoint,
    }
    handler = handlers.get(kind)
    return handler(state, request) if handler is not None else None
