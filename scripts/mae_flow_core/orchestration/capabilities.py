"""Opaque expensive-capability facts and single-attempt decisions."""

from dataclasses import dataclass, replace
from enum import Enum
import hashlib

from .models import CapabilityAttempt
from .models import Phase


SUMMARY_LIMIT = 500
_OUTCOMES = {
    "returned",
    "failed-to-start",
    "timed-out",
    "not-observed",
}


class CapabilityKind(str, Enum):
    """Expensive capabilities governed by the one-attempt policy."""

    BUILD = "build"
    UT = "ut"
    UNIT_TEST = "ut"
    CODECHECK = "codecheck"
    FORMAL_CODECHECK = "codecheck"
    REVIEWER = "reviewer"
    GRILL = "grill"
    STORY = "story"


def _kind(value):
    try:
        return value if isinstance(value, CapabilityKind) else CapabilityKind(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("unknown capability kind") from exc


def _revision(value, field):
    if not isinstance(value, str) or not value:
        raise ValueError("%s must be a non-empty string" % field)
    return value


@dataclass(frozen=True)
class AttemptContext:
    """Capability-scoped revisions and authorization for one decision.

    ``source_revision`` identifies only source inputs relevant to the
    capability.  A documentation-only change, and a test-only change for a
    production Build, therefore retain the previous Build source revision.
    ``environment_revision`` includes relevant environment and configuration.
    """

    kind: CapabilityKind
    source_revision: str
    environment_revision: str
    user_authorized: bool = False

    def __post_init__(self):
        object.__setattr__(self, "kind", _kind(self.kind))
        _revision(self.source_revision, "source_revision")
        _revision(self.environment_revision, "environment_revision")
        if type(self.user_authorized) is not bool:
            raise ValueError("user_authorized must be a bool")


@dataclass(frozen=True)
class RetryOption:
    allowed: bool
    needs_user: bool
    reason: str


def _matching_attempt(attempts, context):
    return any(
        attempt.kind == context.kind.value
        and attempt.source_revision == context.source_revision
        and attempt.environment_revision == context.environment_revision
        for attempt in attempts
    )


def _same_capability_seen(attempts, context):
    return any(attempt.kind == context.kind.value for attempt in attempts)


def retry_options(attempts, context):
    """Return the one applicable option without interpreting tool output."""
    if not isinstance(context, AttemptContext):
        raise TypeError("context must be an AttemptContext")
    attempts = tuple(attempts)
    if _matching_attempt(attempts, context):
        if context.user_authorized:
            return RetryOption(
                True,
                False,
                "User authorized another attempt for this exact slot.",
            )
        return RetryOption(
            False,
            True,
            "An attempt already exists for unchanged inputs.",
        )
    if _same_capability_seen(attempts, context):
        if context.user_authorized:
            return RetryOption(
                True,
                False,
                "User authorized an attempt for this exact changed slot.",
            )
        return RetryOption(
            False,
            True,
            "This capability was already attempted in another slot.",
        )
    return RetryOption(
        True,
        False,
        "No attempt exists for this capability and input context.",
    )


def automatic_attempt_allowed(attempts, context):
    """Whether the current automatic or explicitly authorized attempt may run."""
    return retry_options(attempts, context).allowed


def record_attempt(attempts, context, outcome, summary=""):
    """Append an opaque fact; recording never infers a quality verdict."""
    if not isinstance(context, AttemptContext):
        raise TypeError("context must be an AttemptContext")
    if not isinstance(outcome, str) or outcome not in _OUTCOMES:
        raise ValueError("unsupported opaque capability outcome")
    if not isinstance(summary, str):
        raise ValueError("summary must be a string")
    attempt = CapabilityAttempt(
        context.kind.value,
        context.source_revision,
        context.environment_revision,
        outcome,
        summary[:SUMMARY_LIMIT],
    )
    return tuple(attempts) + (attempt,)


def _retry_digest(context):
    if not isinstance(context, AttemptContext):
        raise TypeError("context must be an AttemptContext")
    raw = "\0".join((
        context.kind.value,
        context.source_revision,
        context.environment_revision,
    )).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def retry_decision_key(context):
    """Return the user authorization key bound to one exact semantic slot."""
    return "capability.retry.%s.%s" % (
        context.kind.value, _retry_digest(context))


def _retry_used_key(context):
    return "capability.retry.used.%s.%s" % (
        context.kind.value, _retry_digest(context))


def record_flow_attempt(state, context, outcome, summary=""):
    """Record one opaque attempt and consume one state-backed retry choice."""
    from .models import FlowState

    if not isinstance(state, FlowState):
        raise TypeError("state must be a FlowState")
    if not isinstance(context, AttemptContext):
        raise TypeError("context must be an AttemptContext")
    retry_key = retry_decision_key(context)
    used_key = _retry_used_key(context)
    authorizations = tuple(
        value for key, value in state.decisions if key == retry_key)
    used = tuple(value for key, value in state.decisions if key == used_key)
    available = len(authorizations) > len(used)
    effective = AttemptContext(
        context.kind,
        context.source_revision,
        context.environment_revision,
        user_authorized=available,
    )
    option = retry_options(state.capabilities, effective)
    if not option.allowed:
        raise ValueError(
            "同一上下文已有能力尝试；需要先记录本轮自然语言重试决定 %s"
            % ("capability.retry.%s" % context.kind.value))
    attempts = record_attempt(
        state.capabilities, effective, outcome, summary=summary)
    decisions = state.decisions
    if available:
        decisions += ((used_key, authorizations[len(used)]),)
    return replace(state, capabilities=attempts, decisions=decisions)


def capability_slot(state, kind):
    """Derive the one semantic capability slot from recovery state."""
    capability = _kind(kind).value
    if capability == "reviewer" and state.phase == Phase.STORY:
        return "reviewer:design"
    checkpoint = state.current_cp or "CP1"
    if capability == "reviewer" and state.phase == Phase.CONSTRUCTION:
        return "reviewer:cp:%s" % checkpoint
    scoped_cp = (
        checkpoint
        if state.phase in {Phase.CONSTRUCTION, Phase.QUALITY}
        else "-"
    )
    return "%s:%s:%s" % (capability, state.phase.value, scoped_cp)


def flow_attempt_context(state, kind):
    return AttemptContext(
        kind,
        capability_slot(state, kind),
        "lean-workflow-v1",
    )
