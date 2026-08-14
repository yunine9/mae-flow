#!/usr/bin/env python3
"""云端语义事件与 transcript 同形性(详设 §2/§3,D2 的核心验收)。

TranscriptStore 的产物必须不经任何转换直接过 parse_transcript 与
契约判定函数——证据链换输入源,格式一个字节都不许漂。
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

from mae_flow_core.adapters.cloud.semantic_events import (  # noqa: E402
    EventLog,
    EventLogError,
    SemanticEvent,
    validate_event,
)
from mae_flow_core.adapters.cloud.transcript_store import (  # noqa: E402
    TranscriptStore,
)
from mae_flow_core.adapters.hook_transcript_paths import (  # noqa: E402
    explicit_agent_transcript_path,
)
from mae_flow_core.application.hooks.event_policies import (  # noqa: E402
    agent_kind,
)
from mae_flow_core.quality.tool_transcript import (  # noqa: E402
    bash_call,
    call_failed,
    parse_transcript,
    select_contract_marker,
)


def _event(event_id, kind, payload, session_id="S1"):
    return SemanticEvent(
        event_id=event_id, task_id="T-1", session_id=session_id,
        ts="2026-08-14 12:00:00", kind=kind, payload=payload)


def _read_jsonl(path):
    with open(path, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


class EventLogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = os.path.join(self.temporary.name, "events.jsonl")

    def test_append_then_replay_round_trips(self):
        log = EventLog(self.path)
        first = _event(1, "user_message", {"text": "开工"})
        second = _event(2, "turn_finished", {"reason": "end_turn"})
        self.assertTrue(log.append(first))
        self.assertTrue(log.append(second))
        replayed = list(EventLog(self.path).replay())
        self.assertEqual([first, second], replayed)

    def test_replayed_event_is_noop(self):
        """恢复重灌同一事件不产生第二行——幂等锚是 event_id。"""
        log = EventLog(self.path)
        event = _event(1, "user_message", {"text": "开工"})
        self.assertTrue(log.append(event))
        self.assertFalse(log.append(event))
        self.assertFalse(log.append(_event(1, "turn_finished",
                                           {"reason": "end_turn"})))
        self.assertEqual(1, len(_read_jsonl(self.path)))

    def test_malformed_event_is_rejected_loudly(self):
        """静默丢事件会让投影缺页还查不出来——必须抛错。"""
        log = EventLog(self.path)
        with self.assertRaises(EventLogError):
            log.append(_event(1, "tool_requested", {"call_id": "c1"}))
        with self.assertRaises(EventLogError):
            log.append(_event(1, "没有这种事件", {}))
        self.assertFalse(os.path.exists(self.path))

    def test_validate_reports_missing_fields_by_name(self):
        error = validate_event(_event(1, "agent_finished", {"call_id": "x"}))
        self.assertIn("child_session_id", error)
        self.assertIn("lifecycle", error)


class TranscriptShapeTests(unittest.TestCase):
    """云端 transcript 直接喂现有契约函数,判定与 CLI 版一致。"""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.main = os.path.join(self.temporary.name, "transcript.jsonl")
        self.store = TranscriptStore(self.main, "S1")

    def _record_all(self, events):
        for event in events:
            self.store.record(event)

    def test_tool_calls_join_and_contract_functions_agree(self):
        self._record_all([
            _event(1, "user_message", {"text": "编译一下"}),
            _event(2, "assistant_message", {"text": "先跑编译"}),
            _event(3, "tool_requested", {
                "call_id": "c1", "name": "Bash",
                "input": {"command": "mvn -B compile"}}),
            _event(4, "tool_finished", {
                "call_id": "c1", "name": "Bash",
                "input": {"command": "mvn -B compile"},
                "is_error": False, "result": "BUILD SUCCESS"}),
            _event(5, "tool_requested", {
                "call_id": "c2", "name": "Bash",
                "input": {"command": "mvn -B test"}}),
            _event(6, "tool_finished", {
                "call_id": "c2", "name": "Bash",
                "input": {"command": "mvn -B test"},
                "is_error": False,
                "result": "Tests failed\nexit code: 1"}),
            _event(7, "assistant_message",
                   {"text": "COMPILE_RESULT: PASS 编译通过,UT 待修"}),
        ])
        transcript = parse_transcript(_read_jsonl(self.main))
        self.assertEqual(("编译一下",), transcript.user_texts[:1])
        compile_call = bash_call(transcript.tool_calls, "mvn -B compile")
        self.assertIsNotNone(compile_call)
        self.assertTrue(compile_call.result_seen)
        self.assertFalse(call_failed(compile_call))
        test_call = bash_call(transcript.tool_calls, "mvn -B test")
        self.assertTrue(call_failed(test_call))  # 退出码嗅探照常工作
        marker = select_contract_marker(transcript.assistant_texts[-1])
        self.assertEqual(("COMPILE", "PASS"), (marker.kind, marker.status))

    def test_error_result_flag_survives(self):
        self._record_all([
            _event(1, "tool_requested", {
                "call_id": "c1", "name": "Bash",
                "input": {"command": "make"}}),
            _event(2, "tool_finished", {
                "call_id": "c1", "name": "Bash",
                "input": {"command": "make"},
                "is_error": True, "result": "沙箱超时"}),
        ])
        transcript = parse_transcript(_read_jsonl(self.main))
        self.assertTrue(transcript.tool_calls[0].is_error)
        self.assertTrue(call_failed(transcript.tool_calls[0]))


class ChildTranscriptTests(unittest.TestCase):
    """子 Agent transcript 的布局必须让现有确定性绑定原样命中。"""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.main = os.path.join(self.temporary.name, "transcript.jsonl")
        self.store = TranscriptStore(self.main, "S1")

    def test_spawn_binds_child_and_host_resolution_finds_it(self):
        spawn = _event(1, "agent_spawned", {
            "call_id": "toolu-77", "agent_type": "compile-agent",
            "description": "专项编译", "prompt": "跑编译并报告",
            "child_session_id": "S2"})
        self.store.record(spawn)
        self.store.record(_event(2, "assistant_message",
                                 {"text": "COMPILE_RESULT: PASS"},
                                 session_id="S2"))
        self.store.record(_event(3, "agent_finished", {
            "call_id": "toolu-77", "child_session_id": "S2",
            "lifecycle": "returned",
            "final_text": "COMPILE_RESULT: PASS"}))
        child = self.store.child_path("S2")
        self.assertTrue(os.path.isfile(child))
        # 旧插件的确定性绑定(tool_use_id → subagents/agent-<id>.jsonl)
        # 必须原样命中云端布局——契约到子 transcript 查证据的路径不变。
        resolved = explicit_agent_transcript_path(
            {"transcript_path": self.main, "tool_use_id": "toolu-77"})
        self.assertEqual(child, resolved)
        # 主 transcript 视角是一次 Task 调用,agent_kind 推断照旧。
        rows = _read_jsonl(self.main)
        tool_use = rows[0]["message"]["content"][0]
        self.assertEqual("Task", tool_use["name"])
        self.assertEqual("COMPILE", agent_kind(tool_use["input"]))
        joined = parse_transcript(rows)
        self.assertEqual("COMPILE_RESULT: PASS",
                         joined.tool_calls[0].result)

    def test_unbound_child_session_raises(self):
        """证据落错文件比缺证据更毒——未绑定子会话直接拒收。"""
        with self.assertRaises(ValueError):
            self.store.record(_event(
                1, "assistant_message", {"text": "hi"}, session_id="S9"))


if __name__ == "__main__":
    unittest.main()
