"""tool_requested 的同步裁决点(详设 §4/D3)。

复用,不重写:路由用现有纯函数 active_pretool_decision;
gate-edit/gate-bash 的深层契约经 contract 端口注入(接线时指向
今天 dispatch pretooluse 背后的同一批函数)。

fail-open 语义保留:GateService 自身故障 = 放行 + 留痕。
门禁不许因为自己坏了卡死交付——这与旧插件看门狗同一精神。
拦截(deny)的 reason 即打回文案,经 Pi 以工具错误结果回给 Agent,
等价于旧插件的 exit 2 + stderr。
"""

from dataclasses import dataclass

from mae_flow_core.application.hooks.event_policies import (
    active_pretool_decision,
)


#: action 取值:allow(放行)/ deny(打回,带 reason)/
#: human(AskUserQuestion → Web 待办,详设 §5)/ agent(Task → 子会话桥,§6)
@dataclass(frozen=True)
class GateDecision:
    action: str
    reason: str = ""


ALLOW = GateDecision("allow")


class GateService:
    def __init__(self, *, moonlight=False, contract=None, log=None):
        """contract(tool, value, event) -> GateDecision|None,None=放行。

        深层契约需要完整任务状态,由编排器接线时注入;
        未注入时 gate-edit/gate-bash 放行——路由骨架先立起来,
        比塞一个假契约诚实。
        """
        self.moonlight = moonlight
        self.contract = contract
        self.log = log or (lambda message: None)

    def decide(self, event):
        try:
            return self._decide(event)
        except Exception as error:  # fail-open:门禁故障不许卡死交付
            self.log("gate fail-open: %r" % (error,))
            return ALLOW

    def _decide(self, event):
        payload = event.payload
        tool = str(payload.get("name", "") or "")
        tool_input = payload.get("input") or {}
        if tool == "AskUserQuestion" and not self.moonlight:
            # D4:永不真实执行,转 Web 待办;决定以工具结果按 call_id 回注。
            return GateDecision("human")
        routed = active_pretool_decision(tool, tool_input, self.moonlight)
        if routed.action == "agent":
            return GateDecision("agent")
        if routed.action == "block-question":
            return GateDecision(
                "deny",
                "月光宝盒模式下不提问;按既定决定继续,待办已记录。")
        if routed.action in ("gate-edit", "gate-bash"):
            if self.contract is None:
                return ALLOW
            decision = self.contract(tool, routed.value, event)
            if isinstance(decision, GateDecision):
                return decision
            return ALLOW
        return ALLOW
