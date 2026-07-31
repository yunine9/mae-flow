#!/usr/bin/env python3
"""Tests for SubagentStop completion orchestration."""

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.application.hooks.agent_completion import (  # noqa: E402
    AgentCompletionPorts,
    handle_agent_completion,
)
from mae_flow_core.application.hooks.models import HookResponse  # noqa: E402


def assistant(content):
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": content},
    }


class AgentCompletionTests(unittest.TestCase):
    def ports(
            self, lines, state=None, contract_response=None,
            transcript_head="compile-agent\nCOMPILE_RESULT:"):
        events = []
        values = {
            "latest_subagent_transcript": lambda main: main + ".agent",
            "load_transcript": lambda _path: lines,
            "read_transcript_head": lambda _path, _limit: transcript_head,
            "contract_state": lambda: state or {},
            "record_codecheck_trace": lambda *args: events.append(
                ("trace", args[0], args[1])),
            "run_contract": lambda *args: (
                events.append(("contract", args[0], args[1]))
                or contract_response
                or HookResponse()
            ),
            "record_token": lambda *args: events.append(
                ("token", args[0], args[1])),
            "record_rejection": lambda *args: events.append(
                ("rejection", args[0], args[1])),
            "autopsy": lambda _path, _texts: (
                events.append(("autopsy",)) or "约 1 轮"),
            "log": lambda message: events.append(("log", message)),
        }
        return AgentCompletionPorts(**values), events

    def test_valid_contract_runs_validation_before_issuing_token(self):
        lines = [assistant(
            "COMPILE_RESULT: OK\nTASK_CARD_SHA256: " + "a" * 64)]
        ports, events = self.ports(lines)

        response = handle_agent_completion(
            {"agent_transcript_path": "/tmp/agent.jsonl"},
            ports,
        )

        self.assertEqual(0, response.exit_code)
        self.assertEqual(
            ["contract", "token"],
            [event[0] for event in events
             if event[0] in ("contract", "token")],
        )

    def test_rejected_contract_never_issues_token(self):
        lines = [assistant("COMPILE_RESULT: OK")]
        ports, events = self.ports(
            lines,
            contract_response=HookResponse(
                exit_code=2, stderr="compile rejected\n"),
        )
        response = handle_agent_completion(
            {"agent_transcript_path": "/tmp/agent.jsonl"},
            ports,
        )
        self.assertEqual(2, response.exit_code)
        self.assertEqual("compile rejected\n", response.stderr)
        self.assertNotIn("token", [event[0] for event in events])

    def test_codecheck_trace_is_best_effort_and_precedes_contract(self):
        lines = [assistant("CODECHECK_RESULT: CLEAN")]
        ports, events = self.ports(lines)

        handle_agent_completion(
            {"agent_transcript_path": "/tmp/agent.jsonl"},
            ports,
        )

        self.assertEqual(
            ["trace", "contract", "token"],
            [event[0] for event in events
             if event[0] in ("trace", "contract", "token")],
        )

    def test_conflicting_markers_record_rejection_and_return_autopsy(self):
        lines = [assistant(
            "UT_RESULT: PASS\nUT_RESULT: FAIL")]
        ports, events = self.ports(lines)
        response = handle_agent_completion(
            {"agent_transcript_path": "/tmp/agent.jsonl"},
            ports,
        )
        self.assertEqual(2, response.exit_code)
        self.assertIn("互相矛盾的结果标记", response.stderr)
        self.assertIn("尸检线索(约 1 轮)", response.stderr)
        self.assertEqual("SUBAGENT", [
            event for event in events if event[0] == "rejection"
        ][0][1])

    def test_retry_without_marker_records_rejection_but_does_not_loop(self):
        lines = [assistant("unable to complete")]
        ports, events = self.ports(lines)
        response = handle_agent_completion(
            {
                "agent_transcript_path": "/tmp/agent.jsonl",
                "stop_hook_active": True,
            },
            ports,
        )
        self.assertEqual(HookResponse(), response)
        self.assertEqual("", response.stderr)
        self.assertIn("autopsy", [event[0] for event in events])
        self.assertIn("rejection", [event[0] for event in events])

    def test_unrelated_subagent_and_standalone_kind_mismatch_bypass(self):
        unrelated_ports, unrelated_events = self.ports(
            [assistant("ordinary helper result")],
            transcript_head="ordinary helper",
        )
        response = handle_agent_completion(
            {"agent_transcript_path": "/tmp/agent.jsonl"},
            unrelated_ports,
        )
        self.assertEqual(HookResponse(), response)
        self.assertNotIn(
            "token", [event[0] for event in unrelated_events])

        standalone = {
            "_standalone": True,
            "current": "standalone_ut",
        }
        mismatch_ports, mismatch_events = self.ports(
            [assistant("GRILL_RESULT: CLEAR")],
            state=standalone,
        )
        response = handle_agent_completion(
            {"agent_transcript_path": "/tmp/agent.jsonl"},
            mismatch_ports,
        )
        self.assertEqual(HookResponse(), response)
        self.assertNotIn(
            "contract", [event[0] for event in mismatch_events])

    def test_missing_explicit_agent_path_uses_latest_subagent_transcript(self):
        lines = [assistant("COMPILE_RESULT: OK")]
        ports, events = self.ports(lines)
        handle_agent_completion(
            {"transcript_path": "/tmp/main.jsonl"},
            ports,
        )
        logs = [event[1] for event in events if event[0] == "log"]
        self.assertIn("main.jsonl.agent", logs[0])

    def test_unreadable_transcript_fails_open(self):
        ports, events = self.ports([])

        def broken(_path):
            raise OSError("unreadable")

        ports = AgentCompletionPorts(
            **{**ports.__dict__, "load_transcript": broken})
        response = handle_agent_completion(
            {"agent_transcript_path": "/tmp/agent.jsonl"},
            ports,
        )
        self.assertEqual(HookResponse(), response)
        self.assertNotIn("contract", [event[0] for event in events])

    def test_role_result_marker_bypasses_hard_contract_router(self):
        for marker in (
                "CRAFT_REVIEW_RESULT: FINDINGS",
                "TASK_ANALYSIS_RESULT: OK",
                "TEST_DESIGN_RESULT: OK",
                "CP_IMPLEMENT_RESULT: OK"):
            with self.subTest(marker=marker):
                ports, events = self.ports(
                    [assistant(marker + "\nTASK_CARD_SHA256: " + "a" * 64)],
                    transcript_head=marker,
                )
                response = handle_agent_completion(
                    {"agent_transcript_path": "/tmp/agent.jsonl"},
                    ports,
                )
                self.assertEqual(HookResponse(), response)
                self.assertNotIn(
                    "contract", [event[0] for event in events])
                self.assertNotIn(
                    "token", [event[0] for event in events])


if __name__ == "__main__":
    unittest.main()
