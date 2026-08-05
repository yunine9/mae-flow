#!/usr/bin/env python3
"""Semantic quality review and resume policy regressions."""

import os
import json
import sys
import unittest


SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.workflow import transitions  # noqa: E402


class QualityReviewCycleTests(unittest.TestCase):
    def test_every_compile_to_review_bridge_declares_recovery_context(self):
        root = os.path.abspath(os.path.join(SCRIPTS, ".."))
        with open(os.path.join(root, "flow", "flow.json"),
                  encoding="utf-8") as stream:
            flow = json.load(stream)
        for step_id, step in flow["steps"].items():
            if step.get("next") != "quality_review":
                continue
            with self.subTest(step=step_id):
                self.assertTrue(step.get("quality_review_origin"))
                self.assertTrue(step.get("quality_review_resume"))
                self.assertTrue(step.get("quality_review_rework"))

    def test_quality_context_records_semantic_resume_without_document_digest(self):
        factory = getattr(transitions, "quality_review_context", None)
        self.assertTrue(callable(factory))
        context = factory(
            "ut-source", ["src/a.cpp", "tests/a_test.cpp"], "a" * 40)
        self.assertEqual("verify_codecheck", context["resume"])
        self.assertEqual("quality_recompile", context["rework"])
        self.assertEqual(
            ["src/a.cpp", "tests/a_test.cpp"], context["changed_files"])
        self.assertNotIn("digest", context)

    def test_test_only_context_returns_to_ut_for_rework_and_verify_for_commit(self):
        factory = getattr(transitions, "quality_review_context", None)
        self.assertTrue(callable(factory))
        context = factory("ut-test", ["tests/a_test.cpp"], "b" * 40)
        self.assertEqual("verify_comet", context["resume"])
        self.assertEqual("verify_ut", context["rework"])

    def test_focused_paths_may_supply_their_real_resume_nodes(self):
        context = transitions.quality_review_context(
            "codecheck-source", ["src/a.cpp"], "b" * 40,
            resume="tw_codecheck",
        )
        self.assertEqual("tw_codecheck", context["resume"])
        self.assertEqual("quality_recompile", context["rework"])

    def test_dynamic_next_reads_only_declared_quality_context_field(self):
        state = {
            "quality_review": {
                "resume": "verify_codecheck",
                "rework": "quality_recompile",
            }
        }
        self.assertEqual(
            "verify_codecheck",
            transitions.next_step(
                {"next_from_state": "quality_review.resume"}, state),
        )
        self.assertEqual(
            "quality_recompile",
            transitions.next_step(
                {"next_from_state": "quality_review.rework"}, state),
        )

    def test_unknown_origin_is_rejected_instead_of_guessing(self):
        factory = getattr(transitions, "quality_review_context", None)
        self.assertTrue(callable(factory))
        with self.assertRaisesRegex(ValueError, "unknown quality review origin"):
            factory("mystery", ["src/a.cpp"], "c" * 40)


if __name__ == "__main__":
    unittest.main()
