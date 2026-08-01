"""Minimal phase guidance for recovering a lean workflow."""

import os

from .models import FlowState


_PHASE_ROOT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "flow", "phases"))


def _items(title, values):
    if not values:
        return "%s: none" % title
    return "%s:\n%s" % (
        title,
        "\n".join("- %s" % value for value in values),
    )


def render_guidance(state):
    """Render one phase document with only useful recovery context."""
    if not isinstance(state, FlowState):
        raise TypeError("state must be a FlowState")

    phase_path = os.path.join(_PHASE_ROOT, "%s.md" % state.phase.value)
    with open(phase_path, encoding="utf-8") as stream:
        phase_guidance = stream.read().strip()

    artifacts = tuple(
        "%s: %s" % (kind, path) for kind, path in state.artifacts)
    context = (
        "Ticket: %s\n"
        "Path: %s\n"
        "Phase: %s\n"
        "CP: %s\n"
        "%s\n"
        "%s"
    ) % (
        state.ticket,
        state.path.value,
        state.phase.value,
        state.current_cp or "none",
        _items("Artifacts", artifacts),
        _items("Unresolved risks", state.risks),
    )
    return "%s\n\n%s\n" % (context, phase_guidance)
