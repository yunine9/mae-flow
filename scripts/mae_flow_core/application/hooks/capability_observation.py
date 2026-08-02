"""Opaque PostToolUse return observation without quality interpretation."""

from collections.abc import Mapping
from dataclasses import dataclass
import json

from mae_flow_core.application.hooks.models import HookResponse
from mae_flow_core.orchestration.capabilities import SUMMARY_LIMIT
from mae_flow_core.orchestration.capability_registry import match_capability


@dataclass(frozen=True)
class ReturnObservation:
    return_present: bool
    summary: str


@dataclass(frozen=True)
class CapabilityObservation:
    kind: str
    tool_name: str
    identity_field: str
    identity: str
    return_present: bool
    summary: str


@dataclass(frozen=True)
class CapabilityObservationResult:
    observation: object = None


def _human_summary(value):
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(
                value, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"))
        except (TypeError, ValueError, OverflowError):
            text = str(value)
    return text[:SUMMARY_LIMIT]


def observe_return(payload):
    """Observe only response-key presence and a bounded human summary."""
    if not isinstance(payload, Mapping) or "tool_response" not in payload:
        return ReturnObservation(False, "")
    return ReturnObservation(
        True, _human_summary(payload.get("tool_response")))


def _matched_result(payload, registry):
    matched = match_capability(payload, registry)
    if matched is None:
        return None
    returned = observe_return(payload)
    observation = CapabilityObservation(
        matched.kind,
        matched.tool_name,
        matched.identity_field,
        matched.identity,
        returned.return_present,
        returned.summary,
    )
    return CapabilityObservationResult(observation)


def observe_capability(payload, registry):
    """Build an exact observation from a registered real host identity."""
    matched = _matched_result(payload, registry)
    return matched if matched is not None else CapabilityObservationResult()


def _observation_payload(observation):
    return {
        "kind": observation.kind,
        "tool_name": observation.tool_name,
        "identity_field": observation.identity_field,
        "identity": observation.identity,
        "return_present": observation.return_present,
        "summary": observation.summary,
    }


def handle_capability_posttool(payload, registry, audit, update_state):
    """Sequence audit and persistence through fail-open adapter ports."""
    result = observe_capability(payload, registry)
    if result.observation is not None:
        audit("CapabilityObservation", _observation_payload(
            result.observation))
        update_state(payload, result.observation)
    return HookResponse()
