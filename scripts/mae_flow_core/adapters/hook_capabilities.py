"""Atomic capability reservation and opaque return completion for Hooks."""

from dataclasses import replace
import json

from ..application.hooks.models import HookResponse
from ..orchestration.capabilities import (
    SUMMARY_LIMIT,
    flow_attempt_context,
    record_flow_attempt,
)
from ..orchestration.capability_registry import (
    load_capability_registry,
    match_capability,
)


_PENDING = "capability.pending."


class _RetryRequired(Exception):
    pass


class LeanCapabilityGate:
    """Reserve a state-derived slot before invocation and complete it by ID."""

    def __init__(self, root, update_state):
        self.root = root
        self.update_state = update_state

    def reserve(self, state, payload):
        if state is None:
            return HookResponse()
        matched = match_capability(
            payload, load_capability_registry(self.root))
        if matched is None:
            return HookResponse()
        invocation = payload.get("tool_use_id")
        if not isinstance(invocation, str) or not invocation:
            return HookResponse(
                exit_code=2,
                stderr=(
                    "[mae-flow] Capability invocation identity is required "
                    "for one-attempt safety.\n"),
            )

        def reserve_attempt(current):
            context = flow_attempt_context(current, matched.kind)
            try:
                updated = record_flow_attempt(
                    current, context, "not-observed")
            except ValueError as exc:
                raise _RetryRequired(str(exc))
            pending = json.dumps({
                "tool_use_id": invocation,
                "tool_name": matched.tool_name,
                "identity": matched.identity,
                "kind": matched.kind,
                "slot": context.source_revision,
                "attempt_index": len(updated.capabilities) - 1,
            }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            return replace(
                updated,
                decisions=updated.decisions + ((
                    _PENDING + matched.kind, pending),),
            )

        try:
            self.update_state(reserve_attempt)
        except _RetryRequired as exc:
            return HookResponse(
                exit_code=2,
                stderr="[mae-flow] %s\n" % exc,
            )
        except (Exception, SystemExit):
            return HookResponse()
        return HookResponse()

    def complete(self, payload, observation):
        invocation = payload.get("tool_use_id")
        if not isinstance(invocation, str) or not invocation:
            return

        def complete_attempt(state):
            pending_index = None
            pending = None
            for index in range(len(state.decisions) - 1, -1, -1):
                key, raw = state.decisions[index]
                if key != _PENDING + observation.kind:
                    continue
                try:
                    candidate = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                if (
                        candidate.get("tool_use_id") == invocation
                        and candidate.get("tool_name") == observation.tool_name
                        and candidate.get("identity") == observation.identity
                        and candidate.get("kind") == observation.kind):
                    pending_index = index
                    pending = candidate
                    break
            if pending is None:
                return state
            attempt_index = pending.get("attempt_index")
            if (
                    not isinstance(attempt_index, int)
                    or attempt_index < 0
                    or attempt_index >= len(state.capabilities)):
                return state
            attempt = state.capabilities[attempt_index]
            if (
                    attempt.kind != observation.kind
                    or attempt.source_revision != pending.get("slot")
                    or attempt.environment_revision != "lean-workflow-v1"
                    or attempt.outcome != "not-observed"):
                return state
            attempts = list(state.capabilities)
            attempts[attempt_index] = replace(
                attempt,
                outcome=(
                    "returned" if observation.return_present
                    else "not-observed"),
                summary=observation.summary[:SUMMARY_LIMIT],
            )
            decisions = tuple(
                item for index, item in enumerate(state.decisions)
                if index != pending_index)
            return replace(
                state, capabilities=tuple(attempts), decisions=decisions)

        self.update_state(complete_attempt)
