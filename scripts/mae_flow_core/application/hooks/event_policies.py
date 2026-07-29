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


def _moonlight_safe_point(step, moonlight):
    unresolved = [
        issue for issue in (moonlight.get("issues") or [])
        if not issue.get("resolved_at")
    ]
    return (
        step in ("moonlight_review", "end")
        or bool(moonlight.get("hard_blocked"))
        or (
            step == "push"
            and any(issue.get("kind") == "push" for issue in unresolved)
        )
    )


def _stop_blocks(stop_hook_active, guard, revision):
    if not stop_hook_active:
        return 1
    if int(guard.get("revision", -1) or -1) != revision:
        return 1
    return int(guard.get("blocks", 0) or 0) + 1


def stop_decision(state, stop_hook_active, guard):
    """Decide whether Moonlight may stop without reading or writing state."""
    moonlight = state.get("moonlight") or {}
    revision = int(state.get("revision", 0) or 0)
    if not moonlight.get("enabled"):
        return StopDecision(True, revision=revision, reason="inactive")
    step = state.get("current", "")
    if _moonlight_safe_point(step, moonlight):
        return StopDecision(True, revision=revision, reason="safe-point")
    blocks = _stop_blocks(stop_hook_active, guard, revision)
    if stop_hook_active and blocks > 3:
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
