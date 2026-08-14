"""语义事件:Pi 事件进内核前的唯一形状(详设 §2)。

事件日志是追加式 JSONL,PostgreSQL 投影与恢复重放都以它为源;
`.mae-flow.json` 仍是阶段真相,事件日志不是第二个状态机。
幂等锚是任务内单调递增的 event_id:重放同一事件是 no-op,
乱序/回退的 event_id 被拒收——恢复逻辑宁可停下也不接受时间倒流。
"""

import json
import os
from dataclasses import dataclass, field

from mae_flow_core.state_store import ProjectStateLock


KINDS = frozenset((
    "session_started",
    "user_message",
    "assistant_message",
    "tool_requested",
    "tool_finished",
    "agent_spawned",
    "agent_finished",
    "turn_finished",
    "session_ended",
    "human_decision",
))

#: 同步事件:适配器必须应答裁决后 Pi 才能继续(五问第 1 问的落点)。
SYNC_KINDS = frozenset(("tool_requested",))

#: 每种事件 payload 的最小充分集——字段名对齐内核今天消费的真实名字
#: (详设 §1),校验缺字段而不是校验多字段:Pi 侧多给的进不了这里,
#: 已在 pi_event_map 消化。
REQUIRED_PAYLOAD = {
    "session_started": ("resume",),
    "user_message": ("text",),
    "assistant_message": ("text",),
    "tool_requested": ("call_id", "name", "input"),
    "tool_finished": ("call_id", "name", "input", "is_error", "result"),
    "agent_spawned": (
        "call_id", "agent_type", "description", "prompt", "child_session_id"),
    "agent_finished": (
        "call_id", "child_session_id", "lifecycle", "final_text"),
    "turn_finished": ("reason",),
    "session_ended": ("reason", "detail"),
    "human_decision": ("waiting_id", "state_version", "decision", "notes"),
}


@dataclass(frozen=True)
class SemanticEvent:
    event_id: int
    task_id: str
    session_id: str
    ts: str
    kind: str
    payload: dict = field(default_factory=dict)

    def to_row(self):
        return {
            "event_id": self.event_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "ts": self.ts,
            "kind": self.kind,
            "payload": self.payload,
        }

    @classmethod
    def from_row(cls, row):
        return cls(
            event_id=int(row.get("event_id", 0) or 0),
            task_id=str(row.get("task_id", "") or ""),
            session_id=str(row.get("session_id", "") or ""),
            ts=str(row.get("ts", "") or ""),
            kind=str(row.get("kind", "") or ""),
            payload=row.get("payload") or {},
        )


def validate_event(event):
    """返回错误描述;合法事件返回空串。

    校验放在入口而不是各消费方:一个畸形事件被 TranscriptStore 落了盘、
    却被 EventLog 拒收,两边就分叉了——所有消费方共享同一判据。
    """
    if not isinstance(event, SemanticEvent):
        return "事件必须是 SemanticEvent"
    if event.kind not in KINDS:
        return "未知事件种类: %s" % event.kind
    if not isinstance(event.event_id, int) or event.event_id <= 0:
        return "event_id 必须是正整数"
    if not event.task_id:
        return "缺少 task_id"
    if not isinstance(event.payload, dict):
        return "payload 必须是 dict"
    missing = [
        name for name in REQUIRED_PAYLOAD[event.kind]
        if name not in event.payload
    ]
    if missing:
        return "%s 缺少字段: %s" % (event.kind, "、".join(missing))
    return ""


class EventLogError(RuntimeError):
    pass


class EventLog:
    """追加式任务事件日志。

    append 语义:
    - event_id == last + 任意正增量:写入,返回 True;
    - event_id <= last:重放,no-op 返回 False(恢复时安全重灌);
    - 畸形事件:抛 EventLogError——静默丢事件会让投影缺页还查不出来。
    """

    def __init__(self, path, project_root=None):
        self.path = path
        self.project_root = project_root
        self._last = None

    def last_event_id(self):
        if self._last is None:
            self._last = self._scan_last()
        return self._last

    def _scan_last(self):
        if not os.path.isfile(self.path):
            return 0
        last = 0
        for row in self._rows():
            last = max(last, int(row.get("event_id", 0) or 0))
        return last

    def _rows(self):
        with open(self.path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError as error:
                    raise EventLogError(
                        "事件日志损坏(%s): %s" % (self.path, error))
                if isinstance(row, dict):
                    yield row

    def _locked(self):
        if self.project_root:
            return ProjectStateLock(self.project_root)
        return _NoLock()

    def append(self, event):
        error = validate_event(event)
        if error:
            raise EventLogError(error)
        with self._locked():
            last = self.last_event_id()
            if event.event_id <= last:
                return False
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(event.to_row(), ensure_ascii=False) + "\n")
                handle.flush()
            self._last = event.event_id
        return True

    def replay(self):
        if not os.path.isfile(self.path):
            return
        for row in self._rows():
            yield SemanticEvent.from_row(row)


class _NoLock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
