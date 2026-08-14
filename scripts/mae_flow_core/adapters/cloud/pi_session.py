"""控制通道与会话驱动(详设 §7 pi_session)。

PiRuntime 是五问的接口落点:同步应答工具(问 1)、发消息/建会话(问 2)、
事件流(问 4)、恢复(问 5)。真 Pi 客户端与测试桩都实现它;
SessionDriver 只认这个接口,不认 Pi 私有对象。

驱动循环 = 事实登记的唯一入口:每条语义事件先过校验进事件日志,
再落 transcript,顺序不许倒——投影里出现过的事件必须能在证据里找到。
"""

import abc
import time

from .pi_event_map import map_pi_event
from .semantic_events import SemanticEvent, validate_event
from .human_gate import render_decision


class PiRuntime(abc.ABC):
    """Pi 会话最小控制面。所有方法都是同步的。"""

    @abc.abstractmethod
    def create_session(self, *, task_id, workspace, resume=False):
        """返回 session_id(问 2/问 5)。"""

    @abc.abstractmethod
    def send_user_message(self, session_id, text):
        """向会话投递用户消息(问 2)。"""

    @abc.abstractmethod
    def events(self, session_id):
        """产出原始事件 dict 的迭代器;turn_end/session_end 处停(问 4)。

        tool_request 事件产出后,Pi 阻塞等待 answer_tool——这就是
        同步拦截的形状(问 1,一票否决)。
        """

    @abc.abstractmethod
    def answer_tool(self, session_id, call_id, *, allow,
                    reason="", result="", is_error=False):
        """应答一次工具外呼:放行(可携带宿主代答的结果)或打回。"""

    @abc.abstractmethod
    def terminate(self, session_id, reason=""):
        """终止会话;Pi 侧随后产出 session_end。"""


class SessionDriver:
    """主会话的驱动:泵事件、裁决工具、登记事实、桥接子 Agent。

    人工节点采用挂起路线(详设 §5):AskUserQuestion 拦下后本轮返回
    waiting_for_human,Pi 会话保持在未应答的工具调用上;
    决定到达后 resume_with_decision 回注并继续泵。

    登记归属规则(防双行):谁执行谁登记——Pi 真实执行的工具由 Pi 的
    tool_result 事件登记;宿主代演的工具(人工决定、子 Agent 结果)由
    driver 自己 emit,Pi 对这些 call_id 的回声一律丢弃。
    """

    def __init__(self, *, runtime, task_id, workspace, event_log,
                 transcript, gate, human_gate, agent_bridge,
                 current_step=None, log=None):
        self.runtime = runtime
        self.task_id = task_id
        self.workspace = workspace
        self.event_log = event_log
        self.transcript = transcript
        self.gate = gate
        self.human_gate = human_gate
        self.agent_bridge = agent_bridge
        self.current_step = current_step or (lambda: "")
        self.log = log or (lambda message: None)
        self.session_id = ""
        self.waiting = None
        self._host_answered = set()

    # ---- 事实登记(事件日志 → transcript,顺序固定) ----

    def emit(self, kind, session_id, payload):
        event = SemanticEvent(
            event_id=self.event_log.last_event_id() + 1,
            task_id=self.task_id,
            session_id=session_id,
            ts=time.strftime("%Y-%m-%d %H:%M:%S"),
            kind=kind,
            payload=payload,
        )
        error = validate_event(event)
        if error:
            raise ValueError(error)
        self.event_log.append(event)
        self.transcript.record(event)
        return event

    # ---- 生命周期 ----

    def start(self, user_message, *, resume=False):
        self.session_id = self.runtime.create_session(
            task_id=self.task_id, workspace=self.workspace, resume=resume)
        if self.transcript.main_session_id != self.session_id:
            self.transcript.main_session_id = self.session_id
        self.emit("user_message", self.session_id, {"text": user_message})
        self.runtime.send_user_message(self.session_id, user_message)
        return self._pump()

    def resume_with_decision(self, record):
        """把 Web 决定回注为 AskUserQuestion 的工具结果,继续本轮。"""
        if not self.waiting:
            raise RuntimeError("没有等待中的人工节点,无决定可回注")
        call_id = self.waiting["call_id"]
        question = self.waiting.get("question") or {}
        self.emit("human_decision", self.session_id, {
            "waiting_id": record["waiting_id"],
            "state_version": record["state_version"],
            "decision": record["decision"],
            "notes": record["notes"],
        })
        # 宿主代演的工具结果由 driver 登记(旧插件 posttooluse 捕获的
        # 同一形状),Pi 的回声在泵里按 _host_answered 丢弃。
        self.emit("tool_finished", self.session_id, {
            "call_id": call_id,
            "name": "AskUserQuestion",
            "input": question,
            "is_error": False,
            "result": render_decision(record),
        })
        self._host_answered.add(call_id)
        self.waiting = None
        self.runtime.answer_tool(
            self.session_id, call_id,
            allow=True, result=render_decision(record))
        return self._pump()

    # ---- 泵 ----

    def _pump(self):
        for raw in self.runtime.events(self.session_id):
            event = self._translate(raw)
            if event is None:
                continue
            if event.kind == "tool_requested":
                outcome = self._handle_tool(event)
                if outcome is not None:
                    return outcome
                continue
            if (event.kind == "tool_finished"
                    and event.payload["call_id"] in self._host_answered):
                # 宿主已代答并登记过,Pi 的回声丢弃,防同 id 双行。
                self._host_answered.discard(event.payload["call_id"])
                continue
            self.event_log.append(event)
            self.transcript.record(event)
            if event.kind == "turn_finished":
                return {"status": "turn_finished",
                        "reason": event.payload["reason"]}
            if event.kind == "session_ended":
                return {"status": "session_ended",
                        "reason": event.payload["reason"],
                        "detail": event.payload["detail"]}
        return {"status": "stream_ended"}

    def _translate(self, raw):
        event = map_pi_event(
            raw,
            task_id=self.task_id,
            event_id=self.event_log.last_event_id() + 1,
            ts=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        if event is None:
            # fail-open 精神:Pi 升级多出的新事件不打死任务,但必须留痕。
            self.log("未知 Pi 事件被跳过: %r" % (raw,))
        return event

    def _handle_tool(self, event):
        decision = self.gate.decide(event)
        if decision.action == "agent":
            # Task 不作为普通工具登记:桥会发 agent_spawned/agent_finished,
            # 重复登记会让主 transcript 出现两行同 id 的 tool_use。
            final = self.agent_bridge.run(self, event.payload)
            self._host_answered.add(event.payload["call_id"])
            self.runtime.answer_tool(
                self.session_id, event.payload["call_id"],
                allow=True,
                result=final["final_text"],
                is_error=final["lifecycle"] != "returned")
            return None
        self.event_log.append(event)
        self.transcript.record(event)
        if decision.action == "human":
            record = self.human_gate.create_waiting(
                task_id=self.task_id,
                step=str(self.current_step() or ""),
                call_id=event.payload["call_id"],
                question_input=event.payload["input"],
            )
            self.waiting = record
            return {"status": "waiting_for_human", "waiting": dict(record)}
        if decision.action == "deny":
            self.runtime.answer_tool(
                self.session_id, event.payload["call_id"],
                allow=False, reason=decision.reason)
            return None
        self.runtime.answer_tool(
            self.session_id, event.payload["call_id"], allow=True)
        return None
