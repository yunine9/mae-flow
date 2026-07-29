#!/usr/bin/env python3
"""Tests for the pure COMPILE Agent contract."""

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.quality.agent_contracts import (  # noqa: E402
    AgentContractContext,
)
from mae_flow_core.quality.compile_contract import (  # noqa: E402
    evaluate_compile_contract,
)
from mae_flow_core.quality.tool_transcript import ToolCall  # noqa: E402


def call(name, value, result="", seen=True, error=False):
    return ToolCall(
        call_id="fixture",
        name=name,
        input=value,
        result_seen=seen,
        is_error=error,
        result=result,
    )


class CompileContractTests(unittest.TestCase):
    def context(self, report, calls=(), status="OK", net=0, build=None):
        return AgentContractContext(
            kind="COMPILE",
            status=status,
            report=report,
            task={"step": "tw_compile"},
            config={"编译方式": build or "python build.py"},
            calls=tuple(calls),
            changed_paths=(),
            compile_net=net,
        )

    def test_ok_requires_the_configured_successful_build_call(self):
        report = "EXECUTED_BUILD: python build.py\nBUILD_ERRORS: 0"
        accepted = evaluate_compile_contract(self.context(
            report,
            [call(
                "Bash",
                {"command": "python build.py"},
                "build complete\nexit code: 0",
            )],
        ))
        self.assertTrue(accepted.accepted)

        missing = evaluate_compile_contract(self.context(report))
        self.assertFalse(missing.accepted)
        self.assertIn("没有真实执行配置的编译命令", missing.reason)

    def test_ok_rejects_failed_tool_and_nonzero_error_count(self):
        report = "EXECUTED_BUILD: python build.py\nBUILD_ERRORS: 0"
        failed = evaluate_compile_contract(self.context(
            report,
            [call(
                "Bash",
                {"command": "python build.py"},
                "process exited with code 2",
            )],
        ))
        self.assertIn("工具结果明确失败", failed.reason)

        contradictory = evaluate_compile_contract(self.context(
            "EXECUTED_BUILD: python build.py\nBUILD_ERRORS: 3",
            [call("Bash", {"command": "python build.py"}, "done")],
        ))
        self.assertEqual(
            "标记 OK 但 BUILD_ERRORS=3,自相矛盾。",
            contradictory.reason,
        )

    def test_blocked_accepts_a_real_failed_attempt_with_errors(self):
        decision = evaluate_compile_contract(self.context(
            "EXECUTED_BUILD: python build.py\nBUILD_ERRORS: 2",
            [call(
                "Bash",
                {"command": "python build.py"},
                "process exited with code 2",
            )],
            status="BLOCKED",
        ))
        self.assertTrue(decision.accepted)

    def test_skill_build_uses_the_last_matching_tool_result(self):
        decision = evaluate_compile_contract(self.context(
            "EXECUTED_BUILD: build-fix / mcde build -i\nBUILD_ERRORS: 0",
            [
                call(
                    "Skill",
                    {"skill": "build-fix"},
                    "first failed",
                    error=True,
                ),
                call(
                    "Skill",
                    {"skill": "build-fix"},
                    "fixed",
                ),
            ],
            build="build-fix",
        ))
        self.assertTrue(decision.accepted)

    def test_net_deletion_requires_a_nonempty_shrink_exemption(self):
        base = (
            "EXECUTED_BUILD: python build.py\n"
            "BUILD_ERRORS: 0\n"
        )
        calls = [call("Bash", {"command": "python build.py"}, "done")]
        rejected = evaluate_compile_contract(
            self.context(base, calls, net=-4))
        self.assertIn("代码净删 4 行", rejected.reason)

        accepted = evaluate_compile_contract(self.context(
            base + "SHRINK_EXEMPT:\nremoved duplicate wrapper\n",
            calls,
            net=-4,
        ))
        self.assertTrue(accepted.accepted)

    def test_honest_fail_does_not_require_execution_fields(self):
        decision = evaluate_compile_contract(self.context(
            "compiler unavailable",
            status="FAIL",
        ))
        self.assertTrue(decision.accepted)


if __name__ == "__main__":
    unittest.main()
