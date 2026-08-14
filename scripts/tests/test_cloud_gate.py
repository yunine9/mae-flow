#!/usr/bin/env python3
"""云端门禁、人工节点与参考样机整链(详设 §4/§5/§6)。

样机(ReferencePi)是参考线格式的唯一可执行定义,与 cloud-probe 共用;
tool_request 产出后阻塞等 answer_tool——同步拦截(五问第 1 问)的
可执行形状;真 Pi 只换 PiRuntime 实现,本文件剧本即对拍基准。
"""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.adapters.cloud.agent_bridge import AgentBridge  # noqa: E402
from mae_flow_core.adapters.cloud.gate_service import (  # noqa: E402
    GateDecision,
    GateService,
)
from mae_flow_core.adapters.cloud.human_gate import (  # noqa: E402
    HumanGate,
    render_decision,
)
from mae_flow_core.adapters.cloud.pi_session import (  # noqa: E402
    SessionDriver,
)
from mae_flow_core.adapters.cloud.reference_runtime import (  # noqa: E402
    ReferencePi,
)
from mae_flow_core.adapters.cloud.semantic_events import (  # noqa: E402
    EventLog,
    SemanticEvent,
)
from mae_flow_core.adapters.cloud.transcript_store import (  # noqa: E402
    TranscriptStore,
)
from mae_flow_core.adapters.hook_transcript_paths import (  # noqa: E402
    explicit_agent_transcript_path,
)
from mae_flow_core.quality.tool_transcript import (  # noqa: E402
    bash_call,
    parse_transcript,
    select_contract_marker,
)
from mae_flow_core.state_store import StateConflictError  # noqa: E402


def _tool_event(name, tool_input, call_id="c1"):
    return SemanticEvent(
        event_id=1, task_id="T-1", session_id="S1",
        ts="2026-08-14 12:00:00", kind="tool_requested",
        payload={"call_id": call_id, "name": name, "input": tool_input})


class GateServiceTests(unittest.TestCase):
    def test_ask_user_question_routes_to_human(self):
        decision = GateService().decide(
            _tool_event("AskUserQuestion", {"questions": []}))
        self.assertEqual("human", decision.action)

    def test_task_routes_to_agent_bridge(self):
        decision = GateService().decide(
            _tool_event("Task", {"subagent_type": "compile-agent"}))
        self.assertEqual("agent", decision.action)

    def test_moonlight_blocks_question(self):
        decision = GateService(moonlight=True).decide(
            _tool_event("AskUserQuestion", {"questions": []}))
        self.assertEqual("deny", decision.action)
        self.assertTrue(decision.reason)

    def test_bash_without_contract_allows(self):
        decision = GateService().decide(
            _tool_event("Bash", {"command": "ls"}))
        self.assertEqual("allow", decision.action)

    def test_contract_deny_passes_through(self):
        service = GateService(
            contract=lambda tool, value, event: GateDecision("deny", "伪证"))
        decision = service.decide(_tool_event("Bash", {"command": "ls"}))
        self.assertEqual(("deny", "伪证"), (decision.action, decision.reason))

    def test_contract_crash_fails_open_with_trace(self):
        """门禁不许因为自己坏了卡死交付——放行,但必须留痕。"""
        logged = []

        def broken(tool, value, event):
            raise RuntimeError("契约内部错误")

        service = GateService(contract=broken, log=logged.append)
        decision = service.decide(_tool_event("Bash", {"command": "ls"}))
        self.assertEqual("allow", decision.action)
        self.assertTrue(any("fail-open" in line for line in logged))


class HumanGateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.gate = HumanGate(
            os.path.join(self.temporary.name, "waiting.json"),
            project_root=self.temporary.name)

    def test_create_is_idempotent_per_call_id(self):
        """恢复重放同一 tool_requested 不得生成第二张待办。"""
        first = self.gate.create_waiting(
            task_id="T-1", step="grill", call_id="c1",
            question_input={"q": "通过吗"})
        again = self.gate.create_waiting(
            task_id="T-1", step="grill", call_id="c1",
            question_input={"q": "换了内容也不新建"})
        self.assertEqual(first["waiting_id"], again["waiting_id"])
        self.assertEqual({"q": "通过吗"}, again["question"])
        self.assertEqual(1, len(self.gate.pending()))

    def test_first_decision_wins(self):
        record = self.gate.create_waiting(
            task_id="T-1", step="grill", call_id="c1",
            question_input={})
        resolved = self.gate.resolve(
            record["waiting_id"],
            state_version=record["state_version"],
            decision="通过", notes="看过 Diff")
        self.assertEqual("resolved", resolved["status"])
        with self.assertRaises(StateConflictError):
            self.gate.resolve(
                record["waiting_id"],
                state_version=record["state_version"],
                decision="打回")
        self.assertEqual([], self.gate.pending())

    def test_stale_version_is_rejected(self):
        record = self.gate.create_waiting(
            task_id="T-1", step="spec", call_id="c2", question_input={})
        with self.assertRaises(StateConflictError):
            self.gate.resolve(
                record["waiting_id"], state_version=99, decision="通过")

    def test_render_decision_keeps_decision_on_first_line(self):
        text = render_decision({"decision": "通过", "notes": "备注"})
        self.assertEqual("通过", text.splitlines()[0])


QUESTION = {"questions": [{"question": "Diff 通过吗?",
                           "options": ["通过", "打回"]}]}


def _driver(temporary, runtime, moonlight=False):
    main = os.path.join(temporary, "transcript.jsonl")
    return SessionDriver(
        runtime=runtime,
        task_id="T-1",
        workspace=temporary,
        event_log=EventLog(os.path.join(temporary, "events.jsonl")),
        transcript=TranscriptStore(main, ""),
        gate=GateService(moonlight=moonlight),
        human_gate=HumanGate(
            os.path.join(temporary, "waiting.json"),
            project_root=temporary),
        agent_bridge=AgentBridge(),
        current_step=lambda: "build_review",
    ), main


def _read_jsonl(path):
    with open(path, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


class ReferencePiChainTests(unittest.TestCase):
    """最小整链(样机剧本即真 Pi 对拍基准):编译工具放行 → 人工节点挂起 → 决定回注 → 收轮。"""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

    def test_full_turn_with_human_pause(self):
        runtime = ReferencePi([{
            "on_message": [
                {"type": "assistant_text", "text": "先编译"},
                {"type": "tool_request", "call_id": "c1", "name": "Bash",
                 "input": {"command": "mvn -B compile"}},
            ],
            "requests": {
                "c1": {"name": "Bash",
                       "input": {"command": "mvn -B compile"}},
                "c2": {"name": "AskUserQuestion", "input": QUESTION},
            },
            "auto_result": {
                "c1": {"is_error": False, "result": "BUILD SUCCESS"}},
            "after_answer": {
                "c1": [{"type": "tool_request", "call_id": "c2",
                        "name": "AskUserQuestion", "input": QUESTION}],
                "c2": [{"type": "assistant_text",
                        "text": "COMPILE_RESULT: PASS 已按决定继续"},
                       {"type": "turn_end"}],
            },
        }])
        driver, main = _driver(self.temporary.name, runtime)

        outcome = driver.start("交付 REQ-1")
        self.assertEqual("waiting_for_human", outcome["status"])
        waiting = outcome["waiting"]
        self.assertEqual("build_review", waiting["step"])
        self.assertEqual(QUESTION, waiting["question"])

        # 两个浏览器同时审批:后到的决定被拒,不覆盖先到。
        resolved = driver.human_gate.resolve(
            waiting["waiting_id"],
            state_version=waiting["state_version"],
            decision="通过", notes="Diff 已看")
        with self.assertRaises(StateConflictError):
            driver.human_gate.resolve(
                waiting["waiting_id"],
                state_version=waiting["state_version"],
                decision="打回")

        outcome = driver.resume_with_decision(resolved)
        self.assertEqual("turn_finished", outcome["status"])

        transcript = parse_transcript(_read_jsonl(main))
        compile_call = bash_call(transcript.tool_calls, "mvn -B compile")
        self.assertEqual("BUILD SUCCESS", compile_call.result)
        ask = [call for call in transcript.tool_calls
               if call.name == "AskUserQuestion"]
        self.assertEqual(1, len(ask))  # 回声被丢弃,同 id 不出双行
        self.assertTrue(ask[0].result.startswith("通过"))
        marker = select_contract_marker(transcript.assistant_texts[-1])
        self.assertEqual(("COMPILE", "PASS"), (marker.kind, marker.status))

        kinds = [event.kind for event in driver.event_log.replay()]
        self.assertIn("human_decision", kinds)
        ids = [event.event_id for event in driver.event_log.replay()]
        self.assertEqual(sorted(set(ids)), ids)

    def test_denied_tool_returns_reason_as_error_result(self):
        runtime = ReferencePi([{
            "on_message": [
                {"type": "tool_request", "call_id": "c1", "name": "Bash",
                 "input": {"command": "rm -rf /"}},
            ],
            "requests": {"c1": {"name": "Bash",
                                "input": {"command": "rm -rf /"}}},
            "after_answer": {"c1": [{"type": "turn_end"}]},
        }])
        driver, main = _driver(self.temporary.name, runtime)
        driver.gate = GateService(
            contract=lambda tool, value, event: GateDecision(
                "deny", "危险命令,打回"))
        outcome = driver.start("清理")
        self.assertEqual("turn_finished", outcome["status"])
        transcript = parse_transcript(_read_jsonl(main))
        self.assertTrue(transcript.tool_calls[0].is_error)
        self.assertIn("打回", transcript.tool_calls[0].result)


class AgentBridgeTests(unittest.TestCase):
    """D5:平行会话模拟 Task;主/子 transcript 与生命周期对账素材齐全。"""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

    def test_subagent_round_trip(self):
        main_plan = {
            "on_message": [
                {"type": "tool_request", "call_id": "toolu-9",
                 "name": "Task",
                 "input": {"subagent_type": "compile-agent",
                           "description": "专项编译",
                           "prompt": "跑编译并按契约报告"}},
            ],
            "requests": {"toolu-9": {"name": "Task", "input": {}}},
            "after_answer": {"toolu-9": [
                {"type": "assistant_text", "text": "编译完成"},
                {"type": "turn_end"},
            ]},
        }
        child_plan = {
            "on_message": [
                {"type": "tool_request", "call_id": "cc1", "name": "Bash",
                 "input": {"command": "mvn -B compile"}},
            ],
            "requests": {"cc1": {"name": "Bash",
                                 "input": {"command": "mvn -B compile"}}},
            "auto_result": {
                "cc1": {"is_error": False, "result": "BUILD SUCCESS"}},
            "after_answer": {"cc1": [
                {"type": "assistant_text",
                 "text": "COMPILE_RESULT: PASS 编译通过"},
                {"type": "turn_end"},
            ]},
        }
        runtime = ReferencePi([main_plan, child_plan])
        driver, main = _driver(self.temporary.name, runtime)

        outcome = driver.start("开始编码后编译")
        self.assertEqual("turn_finished", outcome["status"])

        # 主 transcript:一次 Task 调用,结果=子会话最终文本,只此一行。
        transcript = parse_transcript(_read_jsonl(main))
        task_calls = [call for call in transcript.tool_calls
                      if call.name == "Task"]
        self.assertEqual(1, len(task_calls))
        self.assertEqual("COMPILE_RESULT: PASS 编译通过",
                         task_calls[0].result)
        self.assertFalse(task_calls[0].is_error)

        # 子 transcript:确定性绑定命中,编译证据在子文件里。
        child = explicit_agent_transcript_path(
            {"transcript_path": main, "tool_use_id": "toolu-9"})
        self.assertTrue(child and os.path.isfile(child))
        child_transcript = parse_transcript(_read_jsonl(child))
        self.assertIsNotNone(
            bash_call(child_transcript.tool_calls, "mvn -B compile"))

        # 事件日志:spawned/finished 配对,lifecycle 对齐旧对账语义。
        events = {event.kind: event for event in driver.event_log.replay()}
        self.assertEqual("toolu-9",
                         events["agent_spawned"].payload["call_id"])
        self.assertEqual("returned",
                         events["agent_finished"].payload["lifecycle"])

    def test_child_question_is_refused(self):
        """子 Agent 不设人工节点——提问被打回而不是挂起整个任务。"""
        main_plan = {
            "on_message": [
                {"type": "tool_request", "call_id": "toolu-1",
                 "name": "Task",
                 "input": {"subagent_type": "compile-agent",
                           "description": "编译", "prompt": "去编译"}},
            ],
            "requests": {"toolu-1": {"name": "Task", "input": {}}},
            "after_answer": {"toolu-1": [{"type": "turn_end"}]},
        }
        child_plan = {
            "on_message": [
                {"type": "tool_request", "call_id": "cq",
                 "name": "AskUserQuestion", "input": QUESTION},
            ],
            "requests": {"cq": {"name": "AskUserQuestion",
                                "input": QUESTION}},
            "after_answer": {"cq": [
                {"type": "assistant_text", "text": "收到,按任务卡继续"},
                {"type": "turn_end"},
            ]},
        }
        runtime = ReferencePi([main_plan, child_plan])
        driver, _ = _driver(self.temporary.name, runtime)
        outcome = driver.start("编译")
        self.assertEqual("turn_finished", outcome["status"])
        refusal = [answer for answer in runtime.answers
                   if answer["call_id"] == "cq"][0]
        self.assertFalse(refusal["allow"])
        self.assertIn("人工节点", refusal["reason"])


if __name__ == "__main__":
    unittest.main()
