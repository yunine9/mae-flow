#!/usr/bin/env python3
"""Agent lifecycle observations are opaque, atomic workflow evidence."""

import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.workflow.agent_observations import (  # noqa: E402
    has_finished_observation,
    latest_started_invocation,
    observation_path,
    record_agent_finished,
    record_agent_started,
)
from mae_flow_core.adapters.hook_active_events import (  # noqa: E402
    ActiveHookEventAdapter,
)
from mae_flow_core.workflow.quality_executions import (  # noqa: E402
    quality_input_snapshot,
    successful_quality_execution,
)


class AgentObservationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state = os.path.join(self.temporary.name, ".mae-flow.json")

    def records(self):
        with open(observation_path(self.state), encoding="utf-8") as stream:
            return json.load(stream)["observations"]

    def test_started_and_arbitrary_return_are_recorded_atomically(self):
        record_agent_started(
            self.state, "REVIEWER", "story", "run-1",
            "2026-08-04 10:00:00")
        record_agent_finished(
            self.state, "run-1", "returned", "2026-08-04 10:01:00",
            "CLEAR；无新增问题\n**任意 Markdown 都可以**")

        self.assertTrue(has_finished_observation(
            self.state, "REVIEWER", "story"))
        self.assertEqual("CLEAR；无新增问题\n**任意 Markdown 都可以**",
                         self.records()[-1]["detail"])

    def test_append_is_idempotent_by_invocation_and_lifecycle(self):
        record_agent_started(
            self.state, "STORY", "story", "run-1", "2026-08-04 10:00:00")
        record_agent_started(
            self.state, "STORY", "story", "run-1", "2026-08-04 10:00:01")
        record_agent_finished(
            self.state, "run-1", "returned", "2026-08-04 10:01:00")
        record_agent_finished(
            self.state, "run-1", "returned", "2026-08-04 10:01:01")

        self.assertEqual(2, len(self.records()))

    def test_interrupted_and_timeout_are_not_successful_returns(self):
        for invocation, lifecycle in (("run-1", "interrupted"),
                                      ("run-2", "timeout")):
            record_agent_started(
                self.state, "COMPILE", "tw_compile", invocation,
                "2026-08-04 10:00:00")
            record_agent_finished(
                self.state, invocation, lifecycle,
                "2026-08-04 10:01:00")

        self.assertFalse(has_finished_observation(
            self.state, "COMPILE", "tw_compile"))
        self.assertEqual("", latest_started_invocation(
            self.state, "COMPILE", "tw_compile"))

    def test_latest_open_started_invocation_is_recoverable(self):
        record_agent_started(
            self.state, "STORY", "story", "older", "2026-08-04 10:00:00")
        record_agent_started(
            self.state, "REVIEWER", "story", "newer", "2026-08-04 10:01:00")
        self.assertEqual(
            "newer", latest_started_invocation(self.state, step="story"))

    def test_agent_guidance_has_no_fixed_return_receipt(self):
        agents = os.path.join(ROOT, "agents")
        for name in os.listdir(agents):
            if not name.endswith("-agent.md"):
                continue
            with self.subTest(agent=name):
                with open(os.path.join(agents, name), encoding="utf-8") as stream:
                    text = stream.read()
                self.assertNotIn("_RESULT:", text)
                self.assertNotIn("TASK_CARD_SHA256", text)

    def test_pretool_agent_and_subagentstop_form_one_lifecycle(self):
        runtime = SimpleNamespace(
            _contract_state=lambda: {
                "current": "story", "agent_tasks": {}},
        )
        adapter = ActiveHookEventAdapter(
            state=self.state,
            maeflow_path="/repo/scripts/mae-flow.py",
            repository_root=self.temporary.name,
            maeflow=lambda *_args: 0,
            runtime_adapter=runtime,
            task_card_ports=lambda: None,
            log=lambda _message: None,
        )
        payload = {
            "tool_name": "Agent", "tool_use_id": "story-run",
            "tool_input": {"subagent_type": "story-generator-agent"},
        }
        self.assertEqual(0, adapter.pretool(payload).exit_code)
        self.assertEqual("story-run", latest_started_invocation(
            self.state, "STORY", "story"))
        self.assertEqual(0, adapter.subagentstop({
            "tool_use_id": "story-run", "assistant_text": "已完成",
        }).exit_code)
        self.assertTrue(has_finished_observation(
            self.state, "STORY", "story"))

    def test_quality_completion_records_real_successful_command(self):
        state = {
            "current": "tw_compile",
            "config": {"编译方式": "make module"},
            "agent_tasks": {"COMPILE": {
                "step": "tw_compile", "head": "abc",
                "task_files": ["src/a.cpp"], "execution_roots": ["src"],
            }},
        }
        runtime = SimpleNamespace(_contract_state=lambda: state)
        adapter = ActiveHookEventAdapter(
            state=self.state, maeflow_path="/repo/scripts/mae-flow.py",
            repository_root=self.temporary.name, maeflow=lambda *_args: 0,
            runtime_adapter=runtime,
            task_card_ports=lambda: SimpleNamespace(script_path=lambda: "mae-flow"),
            log=lambda _message: None,
        )
        transcript = os.path.join(self.temporary.name, "agent.jsonl")
        rows = (
            {"message": {"role": "assistant", "content": [{
                "type": "tool_use", "id": "build", "name": "Bash",
                "input": {"command": "make module"},
            }]}},
            {"message": {"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": "build",
                "content": "exit_code: 0\nbuild succeeded",
            }]}},
        )
        with open(transcript, "w", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        payload = {
            "tool_name": "Task", "tool_use_id": "compile-run",
            "tool_input": {"subagent_type": "compile-agent"},
        }
        self.assertEqual(0, adapter.pretool(payload).exit_code)
        adapter.subagentstop({
            "tool_use_id": "compile-run",
            "agent_transcript_path": transcript,
        })
        self.assertIsNotNone(successful_quality_execution(
            self.state, "COMPILE", "tw_compile",
            quality_input_snapshot(state, "COMPILE", "tw_compile")))


if __name__ == "__main__":
    unittest.main()
