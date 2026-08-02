"""Pure Moonlight authorization policy over Full and Focused workflows."""

from dataclasses import dataclass, replace

from .models import CommitPace, FlowState, MoonlightAuthorization
from .transitions import AdvanceRequest, advance_flow


_ENABLED = "moonlight.enabled"
_BUSINESS_FILE = "moonlight.business_file"
_ALLOW_COMMIT = "moonlight.allow_commit"
_ALLOW_PUSH = "moonlight.allow_push"
_ADOPTED_DIRTY = "delivery.adopted_dirty"
_AUTHORIZATION_KEYS = {
    _ENABLED,
    _BUSINESS_FILE,
    _ALLOW_COMMIT,
    _ALLOW_PUSH,
}
_ROUTINE_STOPS = {
    "startup-ready",
    "spec-ready",
    "story-ready",
    "cp-ready",
}
_SAFE_STOP_EVENTS = {
    "ambiguity": "A real ambiguity remains unresolved.",
    "unavailable-material": "Required material is unavailable.",
    "irreversible-action": "An irreversible action needs user authorization.",
    "irreversible-risk": "An irreversible risk needs user authorization.",
    "blocked-external-dependency": "An external dependency is blocked.",
    "delivery-manifest-changed": "The exact delivery manifest changed.",
    "expensive-capability-retry": (
        "An expensive capability retry needs current user authorization."),
    "capability-failed": "An expensive capability did not complete normally.",
    "push-failed": "The final push failed.",
}
_FAILED_ATTEMPT_OUTCOMES = {
    "failed-to-start",
    "timed-out",
    "not-observed",
}


@dataclass(frozen=True)
class MoonlightPolicyResult:
    """Effective permission and any ordinary lean transition result."""

    state: FlowState
    authorization: MoonlightAuthorization
    needs_user: bool
    safe_stop: bool
    reason: str


@dataclass(frozen=True)
class MoonlightAuthorizationView:
    """Requested and effective permissions plus any withholding reason."""

    requested: MoonlightAuthorization
    effective: MoonlightAuthorization
    block_reason: str


def _identity(path):
    return path.replace("\\", "/").casefold()


def _bool_text(value):
    return "true" if value else "false"


def _normalized_authorization(authorization):
    from mae_flow_core.guard.manifest import DeliveryManifest

    files = DeliveryManifest.from_paths(
        authorization.business_files).files
    return MoonlightAuthorization(
        authorization.enabled,
        files,
        authorization.allow_commit,
        authorization.allow_push,
    )


def _disabled_authorization():
    return MoonlightAuthorization(False, (), False, False)


def _reauthorization_reason(detail):
    return "Moonlight reauthorization is required: %s" % detail


def _stored_authorization(state):
    values = {
        _ENABLED: [],
        _ALLOW_COMMIT: [],
        _ALLOW_PUSH: [],
    }
    files = []
    found = False
    for key, value in state.decisions:
        if key == _BUSINESS_FILE:
            found = True
            files.append(value)
        elif key in {_ENABLED, _ALLOW_COMMIT, _ALLOW_PUSH}:
            found = True
            values[key].append(value)
    if not found:
        return _disabled_authorization(), ""

    for key in (_ENABLED, _ALLOW_COMMIT, _ALLOW_PUSH):
        if len(values[key]) != 1:
            return _disabled_authorization(), _reauthorization_reason(
                "reserved decision %s is missing, duplicated, or conflicting."
                % key)
        if values[key][0] not in {"true", "false"}:
            return _disabled_authorization(), _reauthorization_reason(
                "reserved decision %s has an invalid value." % key)

    enabled = values[_ENABLED][0] == "true"
    allow_commit = values[_ALLOW_COMMIT][0] == "true"
    allow_push = values[_ALLOW_PUSH][0] == "true"
    if not enabled:
        if allow_commit or allow_push:
            return _disabled_authorization(), _reauthorization_reason(
                "disabled policy contains delivery permission.")
        return _disabled_authorization(), ""
    try:
        authorization = MoonlightAuthorization(
            True, tuple(files), allow_commit, allow_push)
        return _normalized_authorization(authorization), ""
    except (TypeError, ValueError) as exc:
        return _disabled_authorization(), _reauthorization_reason(str(exc))


def _store_authorization(state, authorization):
    decisions = tuple(
        item for item in state.decisions
        if item[0] not in _AUTHORIZATION_KEYS
    )
    decisions += (
        (_ENABLED, _bool_text(authorization.enabled)),
        (_ALLOW_COMMIT, _bool_text(authorization.allow_commit)),
        (_ALLOW_PUSH, _bool_text(authorization.allow_push)),
    )
    decisions += tuple(
        (_BUSINESS_FILE, path) for path in authorization.business_files)
    return replace(state, decisions=decisions)


def _manifest_files(state):
    from mae_flow_core.guard.manifest import DeliveryManifest
    return DeliveryManifest.from_paths(state.delivery_files).files


def _unowned_dirty(state, manifest):
    from mae_flow_core.guard.manifest import DeliveryManifest

    initial = DeliveryManifest.from_paths(state.initial_dirty).files
    adopted = tuple(
        value for key, value in state.decisions if key == _ADOPTED_DIRTY)
    adopted = DeliveryManifest.from_paths(adopted).files
    manifest_ids = {_identity(path) for path in manifest}
    adopted_ids = {
        _identity(path) for path in adopted
        if _identity(path) in manifest_ids
    }
    return tuple(
        path for path in initial if _identity(path) not in adopted_ids)


def _effective_authorization(state, requested):
    disabled = MoonlightAuthorization(
        requested.enabled,
        requested.business_files,
        False,
        False,
    )
    if not requested.enabled:
        return disabled, "Moonlight is disabled."

    try:
        manifest = _manifest_files(state)
        unowned_dirty = _unowned_dirty(state, manifest)
    except (TypeError, ValueError) as exc:
        return disabled, "The exact delivery manifest is unavailable: %s" % exc

    if state.risks:
        return disabled, "Unresolved workflow risk requires a safe stop."
    if unowned_dirty:
        return disabled, (
            "Unowned dirty files prevent automatic commit and push: %s" %
            ", ".join(unowned_dirty))
    if not manifest:
        return disabled, "No exact delivery manifest is available yet."

    authorized = {_identity(path) for path in requested.business_files}
    outside = tuple(
        path for path in manifest if _identity(path) not in authorized)
    if outside:
        return disabled, (
            "The manifest includes files outside exact Moonlight "
            "preauthorization, including any conditional document not "
            "explicitly named: %s" % ", ".join(outside))

    return requested, "The current exact manifest is preauthorized."


def moonlight_authorization_view(state):
    """Describe persisted Moonlight intent without hiding policy revocation."""
    if not isinstance(state, FlowState):
        raise TypeError("state must be a FlowState")
    requested, stored_reason = _stored_authorization(state)
    if stored_reason:
        return MoonlightAuthorizationView(
            requested, _disabled_authorization(), stored_reason)
    effective, effective_reason = _effective_authorization(state, requested)
    withheld = (
        (requested.allow_commit and not effective.allow_commit)
        or (requested.allow_push and not effective.allow_push)
    )
    return MoonlightAuthorizationView(
        requested,
        effective,
        effective_reason if withheld else "",
    )


def _append_risk(state, risk):
    if risk in state.risks:
        return state
    return replace(state, risks=state.risks + (risk,))


def _latest_attempt_failed(state):
    latest = {}
    for attempt in state.capabilities:
        latest[attempt.kind] = attempt
    return tuple(
        attempt for attempt in latest.values()
        if attempt.outcome in _FAILED_ATTEMPT_OUTCOMES)


def _policy_result(state, requested, needs_user, safe_stop, reason):
    effective, authorization_reason = _effective_authorization(
        state, requested)
    return MoonlightPolicyResult(
        state=state,
        authorization=effective,
        needs_user=needs_user,
        safe_stop=safe_stop,
        reason=reason or authorization_reason,
    )


def _safe_stop(state, requested, risk):
    stopped = _append_risk(state, risk)
    return _policy_result(stopped, requested, True, True, risk)


def apply_moonlight_policy(state, decision):
    """Apply authorization or one semantic event without adding a workflow.

    Passing :class:`MoonlightAuthorization` records the user's exact
    preauthorization as ordinary recoverable decision facts.  Passing an
    :class:`AdvanceRequest` delegates phase changes to ``advance_flow`` while
    suppressing only routine confirmation stops.  Real uncertainty and unsafe
    effects remain safe stops and are recorded as unresolved risks.
    """
    if not isinstance(state, FlowState):
        raise TypeError("state must be a FlowState")

    if isinstance(decision, MoonlightAuthorization):
        try:
            requested = _normalized_authorization(decision)
        except (TypeError, ValueError) as exc:
            reason = _reauthorization_reason(str(exc))
            return MoonlightPolicyResult(
                state=state,
                authorization=_disabled_authorization(),
                needs_user=True,
                safe_stop=True,
                reason=reason,
            )
        updated = _store_authorization(state, requested)
        effective, reason = _effective_authorization(updated, requested)
        unsafe = bool(updated.risks) or (
            bool(updated.delivery_files)
            and (
                "outside exact Moonlight preauthorization" in reason
                or "manifest is unavailable" in reason
            ))
        return MoonlightPolicyResult(
            state=updated,
            authorization=effective,
            needs_user=unsafe,
            safe_stop=unsafe,
            reason=reason,
        )

    if not isinstance(decision, AdvanceRequest):
        raise TypeError(
            "decision must be MoonlightAuthorization or AdvanceRequest")

    kind = decision.kind.strip().lower()
    requested, authorization_issue = _stored_authorization(state)
    if kind == "exit":
        normal = advance_flow(state, decision)
        return MoonlightPolicyResult(
            state=normal.state,
            authorization=requested,
            needs_user=False,
            safe_stop=False,
            reason=normal.reason,
        )

    if kind == "risk-resolved":
        normal = advance_flow(state, decision)
        return _policy_result(
            normal.state,
            requested,
            normal.needs_user,
            normal.needs_user,
            normal.reason,
        )

    if authorization_issue:
        if kind in {"commit-ready", "final-push", "delivery-completed"}:
            return MoonlightPolicyResult(
                state=state,
                authorization=requested,
                needs_user=True,
                safe_stop=True,
                reason=authorization_issue,
            )
        normal = advance_flow(state, decision)
        return MoonlightPolicyResult(
            state=normal.state,
            authorization=requested,
            needs_user=normal.needs_user,
            safe_stop=False,
            reason="%s %s" % (authorization_issue, normal.reason),
        )

    if not requested.enabled:
        normal = advance_flow(state, decision)
        return MoonlightPolicyResult(
            normal.state,
            requested,
            normal.needs_user,
            False,
            normal.reason,
        )

    if state.risks:
        return _safe_stop(state, requested, state.risks[0])

    stop_reason = _SAFE_STOP_EVENTS.get(kind)
    if stop_reason is not None:
        if kind == "push-failed":
            requested = MoonlightAuthorization(
                requested.enabled,
                requested.business_files,
                requested.allow_commit,
                False,
            )
            state = _store_authorization(state, requested)
        return _safe_stop(
            state,
            requested,
            decision.decision_value or stop_reason,
        )

    if kind in {"quality-complete", "delivery-ready", "delivery-confirmed"}:
        failed = _latest_attempt_failed(state)
        if failed:
            names = ", ".join(attempt.kind for attempt in failed)
            return _safe_stop(
                state,
                requested,
                "A capability failure remains unresolved: %s." % names,
            )

    if kind == "delivery-completed":
        observation = decision.decision_value
        if not isinstance(observation, str) or not observation.strip():
            return _safe_stop(
                state,
                requested,
                "A non-empty real adapter observation is required before "
                "delivery can be completed.",
            )
        observed = AdvanceRequest(
            kind,
            decision.decision_key,
            observation.strip(),
        )
        normal = advance_flow(state, observed)
        return _policy_result(
            normal.state,
            requested,
            normal.needs_user,
            False,
            normal.reason,
        )

    effective, authorization_reason = _effective_authorization(
        state, requested)
    if (kind == "cp-ready"
            and state.commit_pace == CommitPace.STAGED
            and not effective.allow_commit):
        return _safe_stop(
            state,
            requested,
            "Moonlight does not preauthorize this staged commit.",
        )
    if kind == "commit-ready" and not effective.allow_commit:
        return _safe_stop(
            state,
            requested,
            "Moonlight does not preauthorize this commit.",
        )
    if (kind in {"delivery-ready", "delivery-confirmed"}
            and (not effective.allow_commit or not effective.allow_push)):
        return _safe_stop(state, requested, authorization_reason)
    if kind == "final-push" and not effective.allow_push:
        if (not requested.allow_push
                and authorization_reason
                == "The current exact manifest is preauthorized."):
            authorization_reason = (
                "Fresh push authorization is required before retrying the "
                "final push.")
        return _safe_stop(state, requested, authorization_reason)

    normal = advance_flow(state, decision)
    if kind in _ROUTINE_STOPS or kind == "delivery-ready":
        return _policy_result(
            normal.state,
            requested,
            False,
            False,
            "Moonlight preauthorization suppresses this routine stop.",
        )
    return _policy_result(
        normal.state,
        requested,
        normal.needs_user,
        False,
        normal.reason,
    )
