#!/usr/bin/env python3
"""Spec2Code 编码前流程节点回归。"""

import json
import os
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class Spec2CodeWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(
            os.path.join(ROOT, "flow", "flow.json"),
            encoding="utf-8",
        ) as stream:
            cls.flow = json.load(stream)

    def test_full_chain_contains_blueprint_and_plan_loops(self):
        steps = self.flow["steps"]
        self.assertEqual("test_blueprint", steps["design"]["next"])
        self.assertEqual("build_plan", steps["story"]["next"])
        self.assertEqual("build_plan", steps["story_ask"]["next"]["no"])
        self.assertEqual(
            {
                "continue": "story_ask",
                "revise": "test_blueprint",
            },
            steps["test_blueprint"]["next"],
        )
        self.assertEqual(
            {
                "continue": "build_pace",
                "revise": "build_plan",
            },
            steps["build_plan"]["next"],
        )

    def test_new_loops_bind_local_artifact_evidence(self):
        steps = self.flow["steps"]
        blueprint = steps["test_blueprint"]["evidence"]
        self.assertIn(
            {"type": "spec2code_artifact", "kind": "blueprint"},
            blueprint,
        )
        plan_evidence = steps["build_plan"]["evidence"]
        self.assertIn(
            {"type": "spec2code_artifact", "kind": "roadmap"},
            plan_evidence,
        )
        self.assertIn(
            {"type": "spec2code_artifact", "kind": "plan"},
            plan_evidence,
        )
        self.assertIn(
            {"type": "spec2code_plan_review", "checkpoint": "CP1"},
            plan_evidence,
        )

    def test_other_workflow_entries_remain_unchanged(self):
        steps = self.flow["steps"]
        self.assertEqual("hf_open", steps["branch_create"]["next"]["hotfix"])
        self.assertEqual("tw_open", steps["branch_create"]["next"]["tweak"])
        self.assertEqual("rf_triage", steps["branch_create"]["next"]["review"])
        self.assertEqual("build_pace", steps["hf_open"]["next"])
        self.assertEqual("tw_pace", steps["tw_open"]["next"])


if __name__ == "__main__":
    unittest.main()
