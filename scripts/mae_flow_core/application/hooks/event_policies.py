"""Pure policies shared by Hook event use cases."""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class StopDecision:
    allow: bool
    blocks: int = 0
    revision: int = 0
    reason: str = ""


@dataclass(frozen=True)
class TemplateDecision:
    accepted: bool
    missing: tuple = ()


def stop_decision(state, stop_hook_active, guard):
    """Decide whether Moonlight may stop without reading or writing state."""
    moonlight = state.get("moonlight") or {}
    revision = int(state.get("revision", 0) or 0)
    if not moonlight.get("enabled"):
        return StopDecision(True, revision=revision, reason="inactive")
    step = state.get("current", "")
    unresolved = [
        issue for issue in (moonlight.get("issues") or [])
        if not issue.get("resolved_at")
    ]
    safe = (
        step in ("moonlight_review", "end")
        or bool(moonlight.get("hard_blocked"))
        or (
            step == "push"
            and any(issue.get("kind") == "push" for issue in unresolved)
        )
    )
    if safe:
        return StopDecision(True, revision=revision, reason="safe-point")
    blocks = 1
    if stop_hook_active:
        if int(guard.get("revision", -1) or -1) == revision:
            blocks = int(guard.get("blocks", 0) or 0) + 1
        if blocks > 3:
            return StopDecision(
                True,
                blocks=blocks,
                revision=revision,
                reason="retry-limit",
            )
    return StopDecision(False, blocks=blocks, revision=revision)


def _headings(text):
    return [
        re.sub(r"\s+", " ", heading.strip())
        for heading in re.findall(r"^#{1,3}\s+(.+)$", text, re.M)
    ]


def _heading_matches(template, actual):
    if "{" not in template:
        return template in actual
    pattern = (
        "^"
        + re.sub(r"\\\{[^}]*\\\}", ".+", re.escape(template))
        + "$"
    )
    return any(re.match(pattern, heading) for heading in actual)


def template_decision(template, document):
    """Validate required headings while allowing instantiated placeholders."""
    actual = _headings(document)
    missing = tuple(
        heading
        for heading in _headings(template)
        if not _heading_matches(heading, actual)
    )
    return TemplateDecision(not missing, missing)
