"""子 Agent 桥(详设 §6/D5)。

Pi 没有原生子会话时,用平行 Pi 会话模拟 Task 工具:对主会话仍表现为
一次 Task 调用 + 最终文本结果;对内核,agent_spawned/agent_finished
携带 subagent_type/description/prompt 与结束信号,agent_kind 推断、
生命周期对账、到子 transcript 查证据的路径全部照旧。

子会话内的工具照过同一 GateService;AskUserQuestion 在子会话里
直接打回——子 Agent 不设人工节点,与旧插件"子 Agent 非交互"的
契约一致,人工停顿只属于主流程的固定节点。
"""


class AgentBridge:
    def run(self, driver, request_payload):
        """driver: SessionDriver(提供 runtime/emit/gate/task_id)。

        返回 {"final_text", "lifecycle"};lifecycle 语义对齐
        hook_agent_lifecycle:returned / interrupted。
        """
        runtime = driver.runtime
        tool_input = request_payload.get("input") or {}
        prompt = str(tool_input.get("prompt", "") or "")
        child = runtime.create_session(
            task_id=driver.task_id, workspace=driver.workspace)
        driver.emit("agent_spawned", driver.session_id, {
            "call_id": request_payload["call_id"],
            "agent_type": str(tool_input.get("subagent_type", "") or ""),
            "description": str(tool_input.get("description", "") or ""),
            "prompt": prompt,
            "child_session_id": child,
        })
        runtime.send_user_message(child, prompt)
        final_text = ""
        lifecycle = "returned"
        for raw in runtime.events(child):
            event = driver._translate(raw)
            if event is None:
                continue
            if event.kind == "tool_requested":
                self._handle_child_tool(driver, child, event)
                continue
            driver.event_log.append(event)
            driver.transcript.record(event)
            if event.kind == "assistant_message":
                final_text = event.payload["text"]
            elif event.kind == "turn_finished":
                break
            elif event.kind == "session_ended":
                if event.payload["reason"] != "completed":
                    lifecycle = "interrupted"
                break
        driver.emit("agent_finished", driver.session_id, {
            "call_id": request_payload["call_id"],
            "child_session_id": child,
            "lifecycle": lifecycle,
            "final_text": final_text,
        })
        return {"final_text": final_text, "lifecycle": lifecycle}

    def _handle_child_tool(self, driver, child, event):
        decision = driver.gate.decide(event)
        if decision.action in ("human", "agent"):
            # 子 Agent 不提问、不再派子 Agent(嵌套一层封顶,旧契约同款)。
            driver.event_log.append(event)
            driver.transcript.record(event)
            driver.runtime.answer_tool(
                child, event.payload["call_id"], allow=False,
                reason="子 Agent 不设人工节点、不得再派子 Agent;"
                       "按任务卡既有信息完成或如实报告失败。")
            return
        driver.event_log.append(event)
        driver.transcript.record(event)
        if decision.action == "deny":
            driver.runtime.answer_tool(
                child, event.payload["call_id"], allow=False,
                reason=decision.reason)
            return
        driver.runtime.answer_tool(
            child, event.payload["call_id"], allow=True)
