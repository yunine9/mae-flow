#!/usr/bin/env python3
"""Checkpoint status routing use-case tests."""

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.application.delivery.checkpoint_status import (  # noqa: E402
    inspect_checkpoint_status,
)


class CheckpointStatusUseCaseTests(unittest.TestCase):
    def test_legacy_state_has_no_refresh_effect(self):
        result = inspect_checkpoint_status(None)
        self.assertEqual((), result.effects)
        self.assertIn("旧版在途流程", result.stdout[0])

    def test_current_batch_routes_to_checkpoint_refresh(self):
        review = {
            "version": 1,
            "status": "active",
            "mode": "staged",
            "current_index": 0,
            "checkpoints": [{
                "id": "CP1",
                "status": "commit_pending",
                "title": "batch",
            }],
        }
        result = inspect_checkpoint_status(review)
        self.assertEqual("refresh_checkpoint", result.effects[0].kind)
        self.assertIn("  CP1 [commit_pending] batch", result.stdout)

    def test_final_locked_receipt_routes_to_final_refresh(self):
        review = {
            "version": 1,
            "status": "active",
            "mode": "continuous",
            "current_index": 1,
            "checkpoints": [{
                "id": "CP1",
                "status": "completed",
                "title": "batch",
            }],
            "final_review": {"status": "review_pending"},
        }
        result = inspect_checkpoint_status(review)
        self.assertEqual("refresh_final_review", result.effects[0].kind)


if __name__ == "__main__":
    unittest.main()
