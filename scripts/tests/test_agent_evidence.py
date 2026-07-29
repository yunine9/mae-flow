#!/usr/bin/env python3
"""Unit tests for Agent token and review Evidence rules."""

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.workflow.agent_evidence import (  # noqa: E402
    AgentEvidencePorts,
    AgentEvidenceRules,
)


def make_ports(**overrides):
    values = {
        "moonlight": lambda _state: False,
        "step_entered": lambda _state: "2026-07-29 10:00:00",
        "risk_acceptance": lambda _kind, _state: (False, ""),
        "script_path": lambda: "/repo/scripts/mae-flow.py",
        "risk_labels": {"COMPILE": "compile risk"},
        "tokens": lambda: {},
        "rejections": lambda: {},
        "source_snapshot_since": lambda _head, _state: {},
        "source_changed_since": lambda _head, _state: ([], ""),
        "changed_source_files": lambda _state: (["src/main.py"], ""),
        "shell_output": lambda _command: "a" * 40,
        "argv_output": lambda _arguments: "commit",
        "blocking_dirty_source_paths": lambda _state: [],
    }
    values.update(overrides)
    return AgentEvidencePorts(**values)


class AgentEvidenceRuleTests(unittest.TestCase):
    def test_missing_token_keeps_actionable_risk_message(self):
        rules = AgentEvidenceRules(make_ports())
        result = rules.agent_ran(
            {"agent": "COMPILE", "statuses": ["OK"]},
            {"current": "tw_compile"},
        )
        self.assertFalse(result.passed)
        self.assertIn(
            "本步内未检测到 COMPILE 子 agent 的合法收尾",
            result.reason,
        )
        self.assertIn(
            'accept-risk compile --reason "compile risk"',
            result.reason,
        )

    def test_token_is_bound_to_step_status_and_source_snapshot(self):
        token = {
            "COMPILE": {
                "at": "2026-07-29 10:00:01",
                "step": "tw_compile",
                "status": "OK",
                "head": "a" * 40,
                "source_snapshot": {"src/main.py": "hash"},
            }
        }
        state = {"current": "tw_compile"}
        rules = AgentEvidenceRules(make_ports(
            tokens=lambda: token,
            source_snapshot_since=lambda _head, _state: {
                "src/main.py": "hash"},
        ))
        self.assertTrue(rules.agent_ran(
            {"agent": "COMPILE", "statuses": ["OK"]}, state).passed)
        changed = AgentEvidenceRules(make_ports(
            tokens=lambda: token,
            source_snapshot_since=lambda _head, _state: {
                "src/main.py": "changed"},
        ))
        self.assertIn(
            "未提交代码快照已变化",
            changed.agent_ran(
                {"agent": "COMPILE", "statuses": ["OK"]},
                state,
            ).reason,
        )

    def test_no_source_short_circuits_agent_requirement(self):
        rules = AgentEvidenceRules(make_ports(
            changed_source_files=lambda _state: ([], "")))
        self.assertTrue(rules.agent_or_no_source(
            {"agent": "COMPILE"}, {"current": "tw_compile"}).passed)

    def test_review_snapshot_rejects_missing_entry_and_dirty_source(self):
        rules = AgentEvidenceRules(make_ports())
        state = {"current": "tw_review", "step_heads": {}}
        self.assertEqual(
            (
                False,
                "缺少 tw_review 的检视入口 HEAD，无法确定用户看到的是哪版代码",
            ),
            tuple(rules.review_snapshot(
                {"base_step": "tw_change"}, state)),
        )
        state["step_heads"] = {
            "tw_review": "a" * 40,
            "tw_change": "b" * 40,
        }
        dirty = AgentEvidenceRules(make_ports(
            argv_output=lambda arguments: (
                "b" * 40 if arguments[1] == "merge-base" else "commit"),
            blocking_dirty_source_paths=lambda _state: ["src/main.py"],
        ))
        self.assertIn(
            "用户检视期间源码/测试/构建文件又发生未提交变化",
            dirty.review_snapshot(
                {"base_step": "tw_change"}, state).reason,
        )


if __name__ == "__main__":
    unittest.main()
