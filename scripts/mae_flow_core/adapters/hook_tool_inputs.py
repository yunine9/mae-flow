"""Normalize exact host tool inputs for lean safety decisions."""

from collections.abc import Mapping
import re


def apply_patch_targets(tool, tool_input):
    """Add exact patch targets from the canonical Codex apply_patch payload."""
    if (
            str(tool or "").casefold() != "apply_patch"
            or not isinstance(tool_input, Mapping)):
        return tool_input
    command = tool_input.get("command")
    if not isinstance(command, str):
        return tool_input
    lines = command.splitlines()
    if (
            not lines
            or lines[0].strip() != "*** Begin Patch"
            or lines[-1].strip() != "*** End Patch"):
        return tool_input
    targets = []
    for line in lines[1:-1]:
        matched = re.fullmatch(
            r"\*\*\* (?:Add|Update|Delete) File: (.+)", line)
        if matched is None:
            matched = re.fullmatch(r"\*\*\* Move to: (.+)", line)
        if matched is None:
            continue
        path = matched.group(1).strip()
        if path and path not in targets:
            targets.append(path)
    enriched = dict(tool_input)
    enriched["targets"] = tuple(targets)
    return enriched
