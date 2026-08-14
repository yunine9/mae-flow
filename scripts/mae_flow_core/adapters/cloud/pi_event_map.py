"""Pi 原始事件 → 语义事件。唯一知道 Pi 长相的文件(详设 §2/D1)。

当前对齐的是**参考线格式**(fake Pi 与阶段 0 原型共用);真 Pi 的
线格式在阶段 0 拿到后只改本文件,语义事件与所有消费方零改动。

参考线格式(每条是一个 dict):
    {"type": "session_start", "session_id", "resume"?}
    {"type": "assistant_text", "session_id", "text"}
    {"type": "tool_request",  "session_id", "call_id", "name", "input"}
    {"type": "tool_result",   "session_id", "call_id", "name", "input",
                              "is_error"?, "result"?}
    {"type": "turn_end",      "session_id", "reason"?}
    {"type": "session_end",   "session_id", "reason"?, "detail"?}

未知 type 返回 None——调用方记日志继续,不因 Pi 升级加了新事件
就把任务打死(fail-open 精神);但已知 type 缺字段按畸形处理,
交给 EventLog 的校验拒收。
"""

from .semantic_events import SemanticEvent


def map_pi_event(raw, *, task_id, event_id, ts):
    """把一条 Pi 原始事件翻译成 SemanticEvent;不认识的返回 None。"""
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("type", "") or "")
    session_id = str(raw.get("session_id", "") or "")

    def build(semantic_kind, payload):
        return SemanticEvent(
            event_id=event_id,
            task_id=task_id,
            session_id=session_id,
            ts=ts,
            kind=semantic_kind,
            payload=payload,
        )

    if kind == "session_start":
        return build("session_started", {"resume": bool(raw.get("resume"))})
    if kind == "user_text":
        return build("user_message", {"text": str(raw.get("text", "") or "")})
    if kind == "assistant_text":
        return build(
            "assistant_message", {"text": str(raw.get("text", "") or "")})
    if kind == "tool_request":
        return build("tool_requested", {
            "call_id": str(raw.get("call_id", "") or ""),
            "name": str(raw.get("name", "") or ""),
            "input": raw.get("input") if isinstance(raw.get("input"), dict)
            else {},
        })
    if kind == "tool_result":
        return build("tool_finished", {
            "call_id": str(raw.get("call_id", "") or ""),
            "name": str(raw.get("name", "") or ""),
            "input": raw.get("input") if isinstance(raw.get("input"), dict)
            else {},
            "is_error": bool(raw.get("is_error")),
            "result": str(raw.get("result", "") or ""),
        })
    if kind == "turn_end":
        return build("turn_finished", {
            "reason": str(raw.get("reason", "") or "end_turn")})
    if kind == "session_end":
        return build("session_ended", {
            "reason": str(raw.get("reason", "") or "completed"),
            "detail": str(raw.get("detail", "") or ""),
        })
    return None
