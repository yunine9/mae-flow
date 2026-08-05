#!/usr/bin/env python3
"""Redline liveness contracts for the stable subtractive workflow."""

import json
import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.workflow.transitions import transition_targets  # noqa: E402


with open(os.path.join(ROOT, "flow", "flow.json"), encoding="utf-8") as stream:
    FLOW = json.load(stream)


def reachable():
    seen, pending = set(), [FLOW["start"]]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        pending.extend(
            target for target in transition_targets(FLOW["steps"][current])
            if target not in seen)
    return seen


class FlowLivenessTests(unittest.TestCase):
    def test_every_reachable_nonterminal_step_has_a_real_successor(self):
        reached = reachable()
        self.assertIn("end", reached)
        for step_id in reached:
            step = FLOW["steps"][step_id]
            if not step.get("terminal"):
                self.assertTrue(
                    transition_targets(step),
                    "%s 没有下一步，会卡死" % step_id)

    def test_heavy_compatibility_steps_are_not_reachable(self):
        reached = reachable()
        for retired in FLOW.get("compatibility_entries", ()):
            self.assertNotIn(retired, reached)

    def test_story_review_is_single_pass_and_cannot_schedule_itself(self):
        story = FLOW["steps"]["story"]
        self.assertEqual("build", story["next"])
        self.assertEqual(1, sum(
            item.get("agent") == "REVIEWER"
            for item in story.get("evidence", ())))
        for step_id in reachable():
            step = FLOW["steps"][step_id]
            if step_id != "open":
                self.assertNotIn("story", transition_targets(step))

    def test_build_has_one_compile_then_optional_precheck_and_human_review(self):
        build = FLOW["steps"]["build"]
        self.assertIn("COMPILE", [
            item.get("agent") for item in build.get("evidence", ())])
        self.assertEqual("build_review", build["next"]["disabled"])
        self.assertEqual("build_agent_review", build["next"]["enabled"])
        self.assertEqual(
            "build_review", FLOW["steps"]["build_agent_review"]["next"])
        self.assertEqual(
            "build_commit", FLOW["steps"]["build_review"]["next"]["continue"])
        self.assertEqual(
            "build_rework", FLOW["steps"]["build_review"]["next"]["revise"])

    def test_quality_review_corridor_has_no_commit_bypass(self):
        steps = FLOW["steps"]
        self.assertEqual(
            "quality_review", steps["verify_post_ponytail_compile"]["next"])
        self.assertEqual("quality_review", steps["quality_recompile"]["next"])
        self.assertEqual(
            "quality_commit", steps["quality_review"]["next"]["continue"])
        self.assertEqual(
            "quality_rework", steps["quality_review"]["next"]["revise"])
        self.assertIn("quality_review_committed", {
            item["type"] for item in steps["quality_commit"]["evidence"]
        })

    def test_no_step_uses_agent_return_text_as_a_transition_choice(self):
        for step_id, step in FLOW["steps"].items():
            serialized = json.dumps(step, ensure_ascii=False)
            for forbidden in (
                    "_RESULT:", "TASK_CARD_SHA256", "reviewer_digest",
                    "capability.retry"):
                self.assertNotIn(forbidden, serialized, step_id)

    def test_every_delivery_path_archives_domain_truth_exactly_once(self):
        self.assertEqual("domain_archive", FLOW["steps"]["verify_comet"]["next"])
        self.assertEqual("domain_archive", FLOW["steps"]["tw_verify"]["next"])
        self.assertEqual("domain_archive", FLOW["steps"]["rf_ut"]["next"])
        self.assertEqual("delivery_review", FLOW["steps"]["domain_archive"]["next"])
        self.assertEqual("push", FLOW["steps"]["delivery_review"]["next"])
        for step_id in reachable():
            if step_id != "domain_archive":
                self.assertNotEqual(
                    "domain_archive",
                    FLOW["steps"][step_id].get("next")
                    if step_id not in {"verify_comet", "tw_verify", "rf_ut"}
                    else "allowed",
                    step_id)

    def test_legacy_archive_steps_are_one_way_recovery_bridges(self):
        for step_id in ("archive_confirm", "archive"):
            self.assertNotIn(step_id, reachable())
            self.assertEqual("domain_archive", FLOW["steps"][step_id]["next"])


if __name__ == "__main__":
    unittest.main()
