#!/usr/bin/env python3
"""Agent evidence depends on lifecycle, never return wording or fingerprints."""

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
        "finished_observation": lambda _kind, _step, _since: None,
        "quality_execution": lambda _kind, _step, _state: None,
        "askuser_tokens": lambda: {},
        "changed_source_files": lambda _state: (["src/main.py"], ""),
        "shell_output": lambda _command: "a" * 40,
        "argv_output": lambda _arguments: "commit",
        "blocking_dirty_source_paths": lambda _state: [],
        "open_observation": lambda _kind, _step, _since: None,
    }
    values.update(overrides)
    return AgentEvidencePorts(**values)


class AgentEvidenceRuleTests(unittest.TestCase):
    def test_missing_return_has_actionable_message_without_receipt_language(self):
        result = AgentEvidenceRules(make_ports()).agent_ran(
            {"agent": "COMPILE", "statuses": ["OK"]},
            {"current": "build"},
        )
        self.assertFalse(result.passed)
        self.assertIn("本步内未检测到 COMPILE 子 Agent 已返回", result.reason)
        self.assertNotIn("令牌", result.reason)
        self.assertNotIn("XXX_RESULT", result.reason)

    def test_open_start_with_missing_return_forbids_automatic_redispatch(self):
        ports = make_ports()
        object.__setattr__(ports, "open_observation", lambda *_args: {
                "kind": "GRILL_FINAL",
                "step": "grill",
                "lifecycle": "started",
                "invocation_id": "toolu-final",
                "at": "2026-07-29 10:01:00",
            })

        result = AgentEvidenceRules(ports).agent_ran(
            {"agent": "GRILL_FINAL"}, {"current": "grill"})

        self.assertFalse(result.passed)
        self.assertIn("禁止自动重派", result.reason)
        self.assertNotIn("请启动对应专项 Agent", result.reason)
        self.assertNotIn("继续重跑", result.reason)

    def test_quality_step_prompts_share_the_missing_return_anti_loop_rule(self):
        for name in ("build.md", "verify_codecheck.md", "verify_ut.md"):
            with self.subTest(name=name):
                with open(
                        os.path.join(ROOT, "flow", "steps", name),
                        encoding="utf-8") as stream:
                    content = stream.read()
                self.assertIn("禁止自动重派", content)
                self.assertNotIn("状态不确定就重启 agent", content)

    def test_returned_lifecycle_passes_regardless_of_declared_statuses(self):
        observation = {
            "kind": "COMPILE", "step": "build",
            "lifecycle": "returned", "at": "2026-07-29 10:01:00",
            "detail": "任意自然语言；甚至说 FAIL 也不由这里裁决",
        }
        rules = AgentEvidenceRules(make_ports(
            finished_observation=lambda _kind, _step, _since: observation,
            quality_execution=lambda _kind, _step, _state: {"succeeded": True}))
        self.assertTrue(rules.agent_ran(
            {"agent": "COMPILE", "statuses": ["OK"]},
            {"current": "build"},
        ).passed)

    def test_quality_return_without_real_execution_is_not_enough(self):
        observation = {
            "kind": "UT", "step": "verify_ut", "lifecycle": "returned",
            "at": "2026-07-29 10:01:00",
        }
        result = AgentEvidenceRules(make_ports(
            finished_observation=lambda *_args: observation,
        )).agent_ran({"agent": "UT"}, {"current": "verify_ut"})
        self.assertFalse(result.passed)
        self.assertIn("返回文字不能替代机器执行", result.reason)

    def test_interrupted_or_timeout_does_not_count_as_returned(self):
        for lifecycle in ("interrupted", "timeout"):
            with self.subTest(lifecycle=lifecycle):
                rules = AgentEvidenceRules(make_ports(
                    finished_observation=lambda *_args: None))
                self.assertFalse(rules.agent_ran(
                    {"agent": "REVIEWER"}, {"current": "story"}).passed)

    def test_askuser_keeps_real_interaction_evidence(self):
        rules = AgentEvidenceRules(make_ports(
            askuser_tokens=lambda: {
                "ASKUSER": {"at": "2026-07-29 10:01:00"}}))
        self.assertTrue(rules.agent_ran(
            {"agent": "ASKUSER"}, {"current": "grill"}).passed)

    def test_no_source_short_circuits_agent_requirement(self):
        rules = AgentEvidenceRules(make_ports(
            changed_source_files=lambda _state: ([], "")))
        self.assertTrue(rules.agent_or_no_source(
            {"agent": "COMPILE"}, {"current": "build"}).passed)

    def test_review_snapshot_safety_is_unchanged(self):
        rules = AgentEvidenceRules(make_ports())
        state = {"current": "tw_review", "step_heads": {}}
        self.assertIn("缺少 tw_review 的检视入口 HEAD", rules.review_snapshot(
            {"base_step": "tw_change"}, state).reason)
        state["step_heads"] = {
            "tw_review": "a" * 40, "tw_change": "b" * 40}
        dirty = AgentEvidenceRules(make_ports(
            argv_output=lambda arguments: (
                "b" * 40 if arguments[1] == "merge-base" else "commit"),
            blocking_dirty_source_paths=lambda _state: ["src/main.py"],
        ))
        self.assertIn("用户检视期间源码/测试/构建文件又发生未提交变化",
                      dirty.review_snapshot(
                          {"base_step": "tw_change"}, state).reason)


if __name__ == "__main__":
    unittest.main()
