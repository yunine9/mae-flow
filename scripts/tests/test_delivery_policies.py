#!/usr/bin/env python3
"""Tests for pure delivery substate policies."""

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.delivery.checkpoints import (  # noqa: E402
    current_item,
    expected_code_step,
    locked_item,
    review_locked,
    review_pending,
)
from mae_flow_core.delivery.moonlight import (  # noqa: E402
    finalize_target,
    issue_id,
)
from mae_flow_core.cli_commands.checkpoint_facts import (  # noqa: E402
    _development_review,
)


class CheckpointPolicyTests(unittest.TestCase):
    def test_current_and_expected_code_step(self):
        state = {
            "choices": {"workflow": "tweak"},
            "development_review": {
                "version": 1,
                "current_index": 1,
                "checkpoints": [
                    {"id": "CP1"},
                    {"id": "CP2"},
                ],
            },
        }
        self.assertEqual("CP2", current_item(state)["id"])
        self.assertEqual("tw_change", expected_code_step(state))

    def test_v2_plan_and_craft_states_are_visible_and_locked(self):
        state = {
            "current": "build",
            "choices": {"workflow": "full"},
            "development_review": {
                "version": 2,
                "current_index": 0,
                "checkpoints": [
                    {"id": "CP1", "status": "craft_pending"},
                ],
            },
        }
        self.assertEqual("CP1", current_item(state)["id"])
        self.assertEqual("CP1", locked_item(state)["id"])
        self.assertTrue(review_locked(state, moonlight=False))
        self.assertFalse(review_pending(state, moonlight=False))
        self.assertIs(
            state["development_review"],
            _development_review(state),
        )

    def test_locked_item_prefers_current_then_final_review(self):
        state = {
            "current": "build",
            "development_review": {
                "version": 1,
                "current_index": 0,
                "checkpoints": [
                    {"id": "CP1", "status": "review_pending"},
                ],
            },
        }
        self.assertEqual("CP1", locked_item(state)["id"])
        self.assertTrue(review_pending(state, moonlight=False))
        self.assertTrue(review_locked(state, moonlight=False))
        self.assertFalse(review_locked(state, moonlight=True))

        state["development_review"]["checkpoints"][0][
            "status"] = "accepted"
        state["current"] = "delivery_review"
        state["development_review"]["final_review"] = {
            "id": "FINAL",
            "status": "push_pending",
        }
        self.assertEqual("FINAL", locked_item(state)["id"])


class MoonlightPolicyTests(unittest.TestCase):
    def test_issue_id_and_finalize_target(self):
        self.assertEqual("ML-003", issue_id(2))
        self.assertEqual(
            "end",
            finalize_target({
                "choices": {"workflow": "review"},
                "config": {"CHANGE_NAME": "change"},
            }),
        )
        self.assertEqual(
            "end",
            finalize_target({
                "choices": {"workflow": "full"},
                "config": {},
            }),
        )
        self.assertEqual(
            "archive_confirm",
            finalize_target({
                "choices": {"workflow": "full"},
                "config": {"CHANGE_NAME": "change"},
            }),
        )


if __name__ == "__main__":
    unittest.main()
