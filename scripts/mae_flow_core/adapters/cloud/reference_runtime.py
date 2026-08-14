"""参考线格式的可执行样机(详设 §7/§8)。

pi_event_map 声明的参考线格式,唯一的可执行定义在这里:契约测试与
cloud-probe 命令共用它,不留两份"参考格式"各自漂移。真 Pi 客户端
就位后(阶段 0),它的角色变成对拍基准——同一剧本喂真 Pi 与样机,
驱动/门禁/证据三条链的行为必须一致。

剧本(plan)按会话创建顺序领取:
    on_message:   收到用户消息后入队的事件;
    requests:     call_id → {name, input},用于合成回声 tool_result;
    auto_result:  call_id → {is_error, result},allow 后由样机"代跑"工具;
    after_answer: call_id → 应答后续入队的事件。

tool_request 产出后阻塞等 answer_tool——同步拦截(五问第 1 问)的
可执行形状;真 Pi 必须给出等价能力,否则整个方案不成立。
"""

from .pi_session import PiRuntime


class ReferencePi(PiRuntime):
    def __init__(self, plans):
        self.pending_plans = list(plans)
        self.plans = {}
        self.queues = {}
        self.answers = []
        self._count = 0

    def create_session(self, *, task_id, workspace, resume=False):
        self._count += 1
        session_id = "S%d" % self._count
        self.plans[session_id] = (
            self.pending_plans.pop(0) if self.pending_plans else {})
        self.queues[session_id] = [{
            "type": "session_start", "session_id": session_id,
            "resume": resume}]
        return session_id

    def send_user_message(self, session_id, text):
        self._enqueue(session_id,
                      self.plans[session_id].get("on_message", []))

    def events(self, session_id):
        queue = self.queues[session_id]
        while queue:
            yield queue.pop(0)

    def answer_tool(self, session_id, call_id, *, allow,
                    reason="", result="", is_error=False):
        self.answers.append({
            "session_id": session_id, "call_id": call_id,
            "allow": allow, "reason": reason, "result": result})
        plan = self.plans[session_id]
        request = (plan.get("requests") or {}).get(call_id, {})
        echo = {
            "type": "tool_result", "call_id": call_id,
            "name": request.get("name", ""),
            "input": request.get("input", {}),
        }
        if not allow:
            echo.update({"is_error": True, "result": reason})
        else:
            auto = (plan.get("auto_result") or {}).get(call_id)
            if auto is not None:
                echo.update(auto)
            else:
                echo.update({"is_error": is_error, "result": result})
        self._enqueue(session_id, [echo])
        self._enqueue(session_id,
                      (plan.get("after_answer") or {}).get(call_id, []))

    def terminate(self, session_id, reason=""):
        self._enqueue(session_id, [{
            "type": "session_end", "reason": reason or "cancelled",
            "detail": ""}])

    def _enqueue(self, session_id, events):
        self.queues[session_id].extend(
            dict(event, session_id=session_id) for event in events)
