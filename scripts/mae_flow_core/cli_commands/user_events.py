"""Bind semantic CLI decisions to current CodeAgent user-prompt events."""

from dataclasses import replace
import hashlib
import json
import os
import re

from mae_flow_core.state_store import safe_read_json
from mae_flow_core.orchestration.transitions import AdvanceRequest


_LEDGER = os.path.join(".mae-flow-work", "lean-hook-user-events.json")
_CONSUMED = "user.event.consumed"
USER_OWNED_EVENTS = {
    "startup-confirmed", "grill-answer", "spec-confirmed", "story-confirmed",
    "cp-confirmed", "cp-revise", "delivery-confirmed",
    "reviewer-tradeoff-resolved", "risk-resolved", "upgrade-to-full",
    "quality-defect-repair", "delivery-defect-repair",
}
_KEYED_SEMANTIC_EVENTS = {
    "risk-resolved", "grill-question", "grill-answer",
    "cp-ready", "cp-opened", "cp-progress",
    "cp-brief", "cp-result", "cp-review", "cp-ut-intent",
    "domain-selected", "domain-new", "domain-updated", "domain-unchanged",
    "capability-returned", "capability-failed-to-start",
    "capability-timed-out", "capability-not-observed",
}


def _state_sha256(root):
    try:
        with open(os.path.join(root, ".mae-flow.json"), "rb") as stream:
            return hashlib.sha256(stream.read()).hexdigest()
    except OSError as exc:
        raise ValueError("无法绑定当前流程状态与用户事件") from exc


def _consumed_ids(state):
    consumed = set()
    for key, raw in state.decisions:
        if key != _CONSUMED:
            continue
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict) and isinstance(value.get("event_id"), str):
            consumed.add(value["event_id"])
    return consumed


def matching_user_event(root, state):
    rows, error = safe_read_json(os.path.join(root, _LEDGER))
    if error or not isinstance(rows, list):
        raise ValueError(
            "未捕获到本轮 CodeAgent 用户输入"
            "（UserPromptSubmit 或 AskUserQuestion 回答）")
    state_sha = _state_sha256(root)
    consumed = _consumed_ids(state)
    for row in reversed(rows):
        if not isinstance(row, dict):
            continue
        event_id = row.get("event_id")
        payload = row.get("payload")
        prompt = payload.get("prompt") if isinstance(payload, dict) else None
        if (isinstance(event_id, str)
                and re.fullmatch(r"[0-9a-f]{64}", event_id)
                and event_id not in consumed
                and row.get("state_sha256") == state_sha
                and isinstance(prompt, str)
                and bool(prompt.strip())):
            return event_id
    raise ValueError(
        "当前流程状态没有尚未消费的 CodeAgent 用户输入"
        "（UserPromptSubmit 或 AskUserQuestion 回答）")


def bind_user_event(state, event_id, semantic_event):
    value = json.dumps(
        {"event_id": event_id, "semantic_event": semantic_event},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return replace(
        state, decisions=state.decisions + ((_CONSUMED, value),))


def requires_user_event(event):
    normalized = event.strip().lower()
    return (
        normalized in USER_OWNED_EVENTS
        or normalized.startswith("capability.retry."))


def semantic_request(event, key, decision):
    normalized = event.strip().lower()
    if key.strip() and normalized not in _KEYED_SEMANTIC_EVENTS:
        raise ValueError("语义事件 %s 不接受 --key" % normalized)
    return AdvanceRequest(event, key, decision)
