"""Lightweight current-behavior selection and delivery reconciliation."""

from dataclasses import dataclass, replace

from .documents import _behavior_segment
from .models import FlowState


_SELECTED = "behavior.domain.selected"
_SCOPE = "behavior.domain.scope"
_ACTION = "behavior.domain.action"
_ACTIONS = {"new", "updated", "unchanged"}


@dataclass(frozen=True)
class DomainAction:
    path: str
    action: str
    summary: str = ""


def normalize_domain_path(path):
    if not isinstance(path, str):
        raise ValueError("domain path must be text")
    normalized = path.strip().replace("\\", "/")
    parts = normalized.split("/")
    if (len(parts) != 4
            or [part.casefold() for part in parts[:3]]
            != ["docs", "mae-flow", "behavior"]
            or not parts[3].casefold().endswith(".md")
            or parts[3].casefold() == "index.md"
            or parts[3] in {".md", "..md"}
            or ".." in parts[3]):
        raise ValueError(
            "domain path must be one exact docs/mae-flow/behavior/<domain>.md")
    domain = _behavior_segment(parts[3])
    return "docs/mae-flow/behavior/%s.md" % domain


def selected_domains(state):
    if not isinstance(state, FlowState):
        raise TypeError("state must be a FlowState")
    values = []
    for key, value in state.decisions:
        if key == _SELECTED and value not in values:
            values.append(value)
    return tuple(values)


def domain_actions(state):
    if not isinstance(state, FlowState):
        raise TypeError("state must be a FlowState")
    actions = []
    for key, value in state.decisions:
        if key != _ACTION:
            continue
        parts = value.split("\t", 2)
        if len(parts) >= 2 and parts[1] in _ACTIONS:
            actions.append(DomainAction(
                parts[0], parts[1], parts[2] if len(parts) == 3 else ""))
    return tuple(actions)


def select_domain(state, path, scope=""):
    normalized = normalize_domain_path(path)
    decisions = state.decisions
    if normalized not in selected_domains(state):
        decisions += ((_SELECTED, normalized),)
    if isinstance(scope, str) and scope.strip():
        scope_value = normalized + "\t" + scope.strip()
        decisions += ((_SCOPE, scope_value),)
    return replace(state, decisions=decisions)


def record_domain_action(state, path, action, summary=""):
    normalized = normalize_domain_path(path)
    normalized_action = action.strip().lower() if isinstance(action, str) else ""
    if normalized_action not in _ACTIONS:
        raise ValueError("domain action must be new, updated, or unchanged")
    if normalized not in selected_domains(state):
        raise ValueError("domain action requires a selected domain")
    if not isinstance(summary, str):
        raise ValueError("domain action summary must be text")
    retained = tuple(
        (key, value) for key, value in state.decisions
        if not (key == _ACTION and value.split("\t", 1)[0] == normalized)
    )
    value = "%s\t%s\t%s" % (
        normalized, normalized_action, summary.strip())
    return replace(state, decisions=retained + ((_ACTION, value),))
