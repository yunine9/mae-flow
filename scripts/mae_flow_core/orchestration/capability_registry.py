"""Exact host-tool identities for opaque quality capabilities."""

from collections.abc import Mapping
from dataclasses import dataclass
import json
import os

from .capabilities import CapabilityKind


@dataclass(frozen=True)
class CapabilitySelector:
    """Map exact values in named tool-input fields to capability kinds."""

    tool_name: str
    identity_fields: tuple
    values: tuple

    def __post_init__(self):
        if not isinstance(self.tool_name, str) or not self.tool_name:
            raise ValueError("tool_name must be a non-empty string")
        if not isinstance(self.identity_fields, (tuple, list)):
            raise ValueError("identity_fields must be a tuple or list")
        fields = tuple(self.identity_fields)
        if (
                not fields
                or any(not isinstance(field, str) or not field
                       for field in fields)
                or len(set(fields)) != len(fields)):
            raise ValueError("identity_fields must be unique non-empty strings")
        raw_values = (
            self.values.items()
            if isinstance(self.values, Mapping)
            else self.values
        )
        normalized = []
        seen = {}
        for item in raw_values:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise ValueError("selector values must map identity to kind")
            identity, kind = item
            if not isinstance(identity, str) or not identity:
                raise ValueError("selector identity must be a non-empty string")
            try:
                capability = CapabilityKind(kind).value
            except (TypeError, ValueError) as exc:
                raise ValueError("selector contains an unknown kind") from exc
            if identity in seen and seen[identity] != capability:
                raise ValueError("selector identity maps to conflicting kinds")
            if identity not in seen:
                normalized.append((identity, capability))
                seen[identity] = capability
        if not normalized:
            raise ValueError("selector values must not be empty")
        object.__setattr__(self, "identity_fields", fields)
        object.__setattr__(self, "values", tuple(normalized))


@dataclass(frozen=True)
class CapabilityMatch:
    kind: str
    tool_name: str
    identity_field: str
    identity: str


_AGENT_CAPABILITIES = {
    "ut-generator-agent": "ut",
    "codecheck-advisor-agent": "codecheck",
    "grill-critic-agent": "grill",
    "story-generator-agent": "story",
    "craft-reviewer-agent": "reviewer",
}
_PLUGIN_AGENT_CAPABILITIES = dict(_AGENT_CAPABILITIES)
_PLUGIN_AGENT_CAPABILITIES.update({
    "mae-flow:" + identity: kind
    for identity, kind in _AGENT_CAPABILITIES.items()
})
_CODEX_AGENT_CAPABILITIES = {
    identity.replace("-", "_"): kind
    for identity, kind in _AGENT_CAPABILITIES.items()
}


DEFAULT_CAPABILITY_REGISTRY = (
    CapabilitySelector(
        "Task",
        ("subagent_type",),
        _PLUGIN_AGENT_CAPABILITIES,
    ),
    CapabilitySelector(
        "Agent",
        ("subagent_type", "agent_type"),
        _PLUGIN_AGENT_CAPABILITIES,
    ),
    CapabilitySelector(
        "spawn_agent",
        ("task_name",),
        _CODEX_AGENT_CAPABILITIES,
    ),
    CapabilitySelector(
        "Skill",
        ("skill", "name"),
        {"build-fix": "build", "mae-flow:build-fix": "build"},
    ),
)


def _selector_matches(selector, tool_input):
    values = dict(selector.values)
    supplied = tuple(
        (field, tool_input[field])
        for field in selector.identity_fields
        if field in tool_input
    )
    if not supplied:
        return None
    identity = supplied[0][1]
    if (
            not isinstance(identity, str)
            or identity not in values
            or any(value != identity for _field, value in supplied[1:])):
        return None
    return CapabilityMatch(
        values[identity], selector.tool_name, supplied[0][0], identity)


def match_capability(payload, registry):
    """Return one exact configured match, or ``None`` when uncertain."""
    if not isinstance(payload, Mapping):
        return None
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_name, str) or not isinstance(tool_input, Mapping):
        return None
    matches = []
    try:
        selectors = tuple(registry)
    except (TypeError, ValueError):
        return None
    for selector in selectors:
        if (
                isinstance(selector, CapabilitySelector)
                and selector.tool_name == tool_name):
            matched = _selector_matches(selector, tool_input)
            if matched is not None:
                matches.append(matched)
    distinct = {
        (match.kind, match.identity)
        for match in matches
    }
    return matches[0] if len(distinct) == 1 else None


def _configured_selectors(raw):
    if not isinstance(raw, Mapping):
        return ()
    rows = raw.get("capability_selectors", ())
    if not isinstance(rows, list):
        return ()
    selectors = []
    expected = {"tool_name", "identity_fields", "values"}
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != expected:
            continue
        try:
            selectors.append(CapabilitySelector(
                row["tool_name"], row["identity_fields"], row["values"]))
        except (TypeError, ValueError):
            continue
    return tuple(selectors)


def load_capability_registry(root):
    """Load optional project selectors while retaining conservative defaults."""
    path = os.path.join(os.path.abspath(root), ".mae-flow-defaults.json")
    try:
        with open(path, encoding="utf-8-sig") as stream:
            configured = _configured_selectors(json.load(stream))
    except (OSError, UnicodeError, ValueError, TypeError):
        configured = ()
    return DEFAULT_CAPABILITY_REGISTRY + configured
