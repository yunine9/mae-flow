"""Small immutable facts used by lean workflow transitions."""

from dataclasses import replace
import re

from .models import Phase


DELIVERY_CONFIRMATION = "delivery.confirmation"
DELIVERY_CONFIRMED_FILE = "delivery.confirmed_file"
DELIVERY_RESULT = "delivery.result"
STAGED_FINAL_FILE = "delivery.staged_final_file"
_REVIEW_ATTEMPT = {
    Phase.SPEC: ("grill", "grill:spec:-"),
    Phase.STORY: ("reviewer", "reviewer:design"),
}


def path_identity(path):
    return path.replace("\\", "/").casefold()


def decision_values(state, key):
    return tuple(value for existing, value in state.decisions
                 if existing == key)


def same_exact_files(left, right):
    return (
        len(left) == len(right)
        and {path_identity(path) for path in left}
        == {path_identity(path) for path in right}
    )


def checkpoint_files(state):
    files = []
    identities = set()
    for key, value in state.decisions:
        if key.startswith("delivery.cp.") and key.endswith(".file"):
            identity = path_identity(value)
            if identity not in identities:
                files.append(value)
                identities.add(identity)
    return tuple(files)


def checkpoint_confirmation_key(checkpoint):
    return "construction.cp.%s.confirmation" % checkpoint


def checkpoint_name(value):
    name = (value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError(
            "checkpoint must contain only letters, digits, '_' or '-'")
    return name


def authorize_exact_delivery(state, request):
    decisions = tuple(
        item for item in state.decisions
        if item[0] not in {
            DELIVERY_CONFIRMATION,
            DELIVERY_CONFIRMED_FILE,
            DELIVERY_RESULT,
        })
    decisions += ((
        DELIVERY_CONFIRMATION,
        request.decision_value or "Deliver the reviewed file manifest.",
    ),)
    decisions += tuple(
        (DELIVERY_CONFIRMED_FILE, path) for path in state.delivery_files)
    return replace(state, decisions=decisions)


def latest_review_attempt(state):
    requirement = _REVIEW_ATTEMPT.get(state.phase)
    if requirement is None:
        return None
    kind, slot = requirement
    matches = tuple(
        attempt for attempt in state.capabilities
        if attempt.kind == kind and attempt.source_revision == slot)
    return matches[-1] if matches else None


def review_attempt_risk(state, attempt):
    risk = "Review capability %s did not return in slot %s: %s." % (
        attempt.kind,
        attempt.source_revision,
        attempt.outcome,
    )
    if risk in state.risks:
        return state
    return replace(state, risks=state.risks + (risk,))
