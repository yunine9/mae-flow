"""Deterministic host transcript path resolution for Agent completions."""

import os


def explicit_agent_transcript_path(payload, invocation_id=""):
    """Resolve only a transcript explicitly bound to this host invocation.

    Claude Code and compatible CodeAgent hosts may either provide the
    subagent transcript directly or provide the main transcript plus an agent
    id. Picking the newest sibling is unsafe when agents overlap, so an
    unbound payload deliberately yields no path.
    """
    for key, value in payload.items():
        if (isinstance(value, str) and "transcript" in key.lower()
                and "agent" in key.lower()):
            return value
    main = payload.get("transcript_path", "")
    if not isinstance(main, str) or not main:
        return ""
    identifiers = {
        str(value or "").strip()
        for value in (
            invocation_id,
            payload.get("invocation_id"),
            payload.get("agent_id"),
            payload.get("agentId"),
            payload.get("tool_use_id"),
            payload.get("task_id"),
        )
        if str(value or "").strip()
    }
    expected = set()
    for identifier in identifiers:
        safe = os.path.basename(identifier)
        if safe != identifier:
            continue
        expected.add(safe + ".jsonl")
        expected.add("agent-" + safe + ".jsonl")
    directory = os.path.join(os.path.splitext(main)[0], "subagents")
    matches = [
        os.path.join(directory, name)
        for name in sorted(expected)
        if os.path.isfile(os.path.join(directory, name))
    ]
    return matches[0] if len(matches) == 1 else ""
