"""Deterministic host transcript path resolution for Agent completions."""

import json
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


def _meta_bound_transcript(directory, invocation_id):
    """在 subagents 目录里按 meta.json 的 toolUseId 精确绑定 transcript。

    实战事故:宿主 SubagentStop payload 给的 agent transcript 路径指向
    永不存在的文件(payload 里的 agent id 与真实落盘的不一致),编译真实
    执行了却被 fail-closed 判为无证据,模型被误导去追固定字段的假线索。
    meta.json 的 toolUseId 与观察台账的 invocation_id 精确对应——
    这是确定性绑定,不是"挑最新文件"那种危险猜测;匹配不到照旧返回空,
    fail-closed 语义不变。
    """
    wanted = str(invocation_id or "").strip()
    if not wanted or not os.path.isdir(directory):
        return ""
    hits = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".meta.json"):
            continue
        try:
            with open(os.path.join(directory, name),
                      encoding="utf-8") as stream:
                meta = json.load(stream)
        except (OSError, ValueError):
            continue
        if str(meta.get("toolUseId", "") or "").strip() == wanted:
            hits.append(name[:-len(".meta.json")] + ".jsonl")
    if len(hits) != 1:
        return ""
    candidate = os.path.join(directory, hits[0])
    return candidate if os.path.isfile(candidate) else ""


def resolve_agent_transcript(payload, invocation_id=""):
    """显式路径优先;路径存在直接用,不存在(宿主 id 错位)按 meta 绑定兜底。"""
    explicit = explicit_agent_transcript_path(payload, invocation_id)
    if explicit and os.path.isfile(explicit):
        return explicit
    directories = []
    if explicit:
        directories.append(os.path.dirname(explicit))
    main = payload.get("transcript_path", "")
    if isinstance(main, str) and main:
        directories.append(
            os.path.join(os.path.splitext(main)[0], "subagents"))
    for directory in dict.fromkeys(directories):
        bound = _meta_bound_transcript(directory, invocation_id)
        if bound:
            return bound
    return explicit
