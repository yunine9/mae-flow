"""AskUserQuestion → WAITING_FOR_HUMAN(详设 §5/D4)。

Agent 按步骤文档提问(34 处文档原样生效),问题在裁决通道被拦下、
变成结构化 Web 待办;决定回来后以 AskUserQuestion 工具结果按
call_id 回注,Agent 视角与旧插件完全一致。

并发规则:第一个匹配状态版本的决定生效,后到的抛 StateConflictError
——两个浏览器同时审批,不覆盖先到决定(主 spec §5.1)。
无身份认证的首版里,记录只承诺时间、页面输入与状态版本可靠。
"""

import time

from mae_flow_core.state_store import StateConflictError, update_json


class HumanGate:
    def __init__(self, path, project_root=None):
        self.path = path
        self.project_root = project_root

    def _update(self, mutator):
        return update_json(
            self.path, mutator,
            default={"records": {}},
            project_root=self.project_root,
        )

    def create_waiting(self, *, task_id, step, call_id, question_input):
        """据拦下的 tool_requested 建待办;同一 call_id 幂等返回已有记录。

        幂等锚是 call_id:恢复重放同一 tool_requested 时不得生成第二张
        待办(小鲁班待办去重的前提)。
        """
        waiting_id = "%s:%s" % (task_id, call_id)
        state = {}

        def mutate(current):
            records = current.setdefault("records", {})
            if waiting_id in records:
                state["record"] = records[waiting_id]
                return current
            record = {
                "waiting_id": waiting_id,
                "task_id": task_id,
                "step": step,
                "call_id": call_id,
                "question": question_input,
                "state_version": 1,
                "status": "waiting",
                "decision": "",
                "notes": "",
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "resolved_at": "",
                "reminders": 0,
            }
            records[waiting_id] = record
            state["record"] = record
            return current

        self._update(mutate)
        return dict(state["record"])

    def pending(self):
        def read(current):
            state["records"] = [
                dict(record)
                for record in (current.get("records") or {}).values()
                if record.get("status") == "waiting"
            ]
            return current

        state = {}
        self._update(read)
        return sorted(state["records"], key=lambda r: r.get("created_at", ""))

    def resolve(self, waiting_id, *, state_version, decision, notes=""):
        """消费决定;版本不匹配或已被抢先,抛 StateConflictError。"""
        state = {}

        def mutate(current):
            records = current.setdefault("records", {})
            record = records.get(waiting_id)
            if record is None:
                raise StateConflictError("待办 %s 不存在" % waiting_id)
            if record.get("status") != "waiting":
                raise StateConflictError(
                    "任务状态已变化:待办 %s 已由先到决定完成" % waiting_id)
            if int(record.get("state_version", 0)) != int(state_version):
                raise StateConflictError(
                    "任务状态已变化:待办 %s 版本不匹配" % waiting_id)
            record["status"] = "resolved"
            record["decision"] = str(decision)
            record["notes"] = str(notes or "")
            record["state_version"] = int(record["state_version"]) + 1
            record["resolved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            state["record"] = record
            return current

        self._update(mutate)
        return dict(state["record"])


def render_decision(record):
    """决定 → 回注文本(AskUserQuestion 工具结果的内容)。

    形状对齐旧插件捕获路径吃的东西:纯文本、决定顶行——
    _text_of(tool_response) 拿到的就是这个;备注跟在决定后面,
    不挤掉首行(XXX_RESULT 同款纪律)。
    """
    decision = str(record.get("decision", "") or "")
    notes = str(record.get("notes", "") or "")
    return decision + ("\n" + notes if notes else "")
