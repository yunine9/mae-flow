#!/usr/bin/env python3
"""Checkpoint navigation invariant tests."""

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.delivery.checkpoints import (  # noqa: E402
    checkpoint_goto_error,
    misplaced_checkpoint_step,
)


def state(current="build", status="craft_decision_pending"):
    return {
        "current": current,
        "choices": {"workflow": "full"},
        "development_review": {
            "version": 2,
            "status": "active",
            "current_index": 0,
            "checkpoints": [{
                "id": "CP1",
                "status": status,
            }],
        },
    }


class CheckpointNavigationTests(unittest.TestCase):
    def test_active_checkpoint_cannot_goto_downstream_quality(self):
        message = checkpoint_goto_error(state(), "verify_ut")
        self.assertIn("CP1", message)
        self.assertIn("不能跳到 verify_ut", message)
        self.assertIn("build", message)

    def test_active_checkpoint_can_return_to_its_code_step_or_rewind(self):
        self.assertEqual("", checkpoint_goto_error(state(), "build"))
        self.assertEqual("", checkpoint_goto_error(state(), "build_plan"))

    def test_old_forced_goto_is_detected_for_automatic_recovery(self):
        misplaced = state(current="verify_ut")
        self.assertEqual("build", misplaced_checkpoint_step(misplaced))
        self.assertEqual(
            "",
            misplaced_checkpoint_step(state(current="build")),
        )


if __name__ == "__main__":
    unittest.main()
