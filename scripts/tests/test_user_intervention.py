#!/usr/bin/env python3
import os
import sys
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core import cli_parser, command_dispatch, cli_runtime  # noqa: E402,F401
from mae_flow_core.cli_commands.user_intervention import (  # noqa: E402
    cmd_user_intervention, intervention_target, render_user_intervention,
)
from mae_flow_core.cli_commands.wiring import api  # noqa: E402


class UserInterventionTests(unittest.TestCase):
    def state(self, step, workflow="full"):
        return {"current": step, "choices": {"workflow": workflow}}

    def test_parser_and_route_are_real(self):
        args = cli_parser.build_parser().parse_args([
            "intervention", "reconcile", "--file", "handoff.json"])
        self.assertEqual("intervention", args.cmd)
        self.assertEqual("reconcile", args.intervention_action)
        self.assertEqual("handoff.json", args.file)
        self.assertEqual(
            "cmd_user_intervention",
            command_dispatch.flow_route("intervention").handler)

    def test_user_source_change_rewinds_late_steps_without_hash_gate(self):
        self.assertEqual("quality_recompile", intervention_target(
            self.state("external_verify"), True, ["src/main/java/A.java"]))
        self.assertEqual("build", intervention_target(
            self.state("external_verify", "review"), True, ["src/a.cpp"]))
        self.assertEqual("build_rework", intervention_target(
            self.state("external_verify", "tweak"), True, ["src/a.cpp"]))
        self.assertEqual("quality_recompile", intervention_target(
            self.state("external_verify"), True, []),
            "路径摘要缺失也应保守回退，不能拒绝用户现场")

    def test_test_change_reenters_ut_and_review_cards_are_refreshed(self):
        self.assertEqual("verify_ut", intervention_target(
            self.state("external_verify"), True, ["tests/test_a.py"]))
        self.assertEqual("build_review", intervention_target(
            self.state("build_commit"), True, ["src/a.cpp"]))
        self.assertEqual("quality_review", intervention_target(
            self.state("quality_commit"), True, ["src/a.cpp"]))

    def test_current_explains_what_user_and_assistant_did(self):
        text = render_user_intervention({"user_intervention": {
            "request": "修复空指针并跑相关 UT",
            "assistant_summary": "修复 A.java，定向 UT 通过",
            "changed_paths": ["src/A.java"],
            "executions": [{"name": "bash", "state": "passed",
                            "result": "mvn -Dtest=A test: PASS"}],
        }})
        self.assertIn("最高优先级上下文", text)
        self.assertIn("修复空指针", text)
        self.assertIn("src/A.java", text)
        self.assertIn("mvn -Dtest=A test", text)
        self.assertIn("不要恢复旧审批", text)

    def test_reconcile_persists_user_context_and_invalidates_old_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            facts = os.path.join(root, "handoff.json")
            with open(facts, "w", encoding="utf-8") as stream:
                json.dump({
                    "schema": "mae-flow-user-intervention/1",
                    "actor": "alice",
                    "request": "修空指针",
                    "assistant_summary": "已修并跑 UT",
                    "changed": True,
                    "changed_paths": ["src/A.java"],
                    "executions": [{"name": "bash", "state": "passed",
                                    "result": "UT PASS"}],
                }, stream)
            state = self.state("external_verify")
            state.update({
                "history": [],
                "quality": {"external_verification": {"verdict": "PASS"}},
                "approval_subject": {"id": "old"},
            })
            saved = {}
            old_save, old_sh = api.save_state, api.sh
            api.save_state = lambda value: saved.update(json.loads(json.dumps(value)))
            api.sh = lambda _command: "a" * 40
            try:
                output = StringIO()
                with redirect_stdout(output):
                    cmd_user_intervention({}, state, SimpleNamespace(
                        intervention_action="reconcile", file=facts))
            finally:
                api.save_state, api.sh = old_save, old_sh
            self.assertEqual("quality_recompile", saved["current"])
            self.assertNotIn("quality", saved)
            self.assertNotIn("approval_subject", saved)
            self.assertEqual("alice", saved["user_intervention"]["actor"])
            self.assertIn("已修并跑 UT", render_user_intervention(saved))
            result = json.loads(output.getvalue().strip().splitlines()[-1])
            self.assertEqual("quality_recompile", result["target"])


if __name__ == "__main__":
    unittest.main()
