#!/usr/bin/env python3
"""Final checkpoint review application use-case tests."""

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.application.delivery.checkpoint_final import (  # noqa: E402
    FinalReviewPorts,
    prepare_final_review,
)
from mae_flow_core.delivery.models import thaw  # noqa: E402


class FinalReviewUseCaseTests(unittest.TestCase):
    def review(self):
        return {
            "version": 1,
            "status": "active",
            "mode": "continuous",
            "delivery_base": "base",
            "last_reviewed_head": "reviewed",
            "current_index": 1,
            "checkpoints": [{
                "id": "CP1",
                "status": "completed",
                "title": "batch",
            }],
        }

    def call(self, review=None, **overrides):
        calls = []

        def supplied(name, value):
            def get(*_args):
                calls.append(name)
                return value
            return get

        values = {
            "current": "delivery_review",
            "review": self.review() if review is None else review,
            "moonlight": False,
            "ports": FinalReviewPorts(
                final_delta=supplied(
                    "final_delta",
                    overrides.pop("final_delta", (["src/main.py"], ""))),
                head=supplied("head", "candidate"),
                final_snapshot=supplied(
                    "final_snapshot",
                    overrides.pop("final_snapshot", {})),
                snapshot_sha256=supplied("snapshot_sha256", "snapshot"),
                upstream=supplied(
                    "upstream",
                    overrides.pop("upstream", ("", "", "candidate"))),
                ack_cursor=supplied("ack_cursor", ("message-1",)),
                now=supplied("now", "2026-07-30 13:00:00"),
            ),
        }
        values.update(overrides)
        return prepare_final_review(**values), calls

    def test_rejects_wrong_step_before_querying_ports(self):
        result, calls = self.call(current="tw_change")
        self.assertEqual(2, result.exit_code)
        self.assertEqual([], calls)

    def test_no_delta_needs_no_receipt(self):
        result, calls = self.call(final_delta=([], ""))
        self.assertEqual(0, result.exit_code)
        self.assertEqual((), result.effects)
        self.assertEqual(["final_delta"], calls)
        self.assertIn("无需重复确认", result.stdout[0])

    def test_builds_final_worktree_receipt_and_show_effect(self):
        snapshot = {"src/main.py": {"sha256": "one"}}
        result, calls = self.call(final_snapshot=snapshot)
        updated = thaw(result.effects[0].payload)
        final = updated["final_review"]
        self.assertTrue(final["requires_commit"])
        self.assertTrue(final["requires_quality_rerun"])
        self.assertEqual("snapshot", final["receipt"]["snapshot_sha256"])
        self.assertEqual("show_final_review", result.effects[1].kind)
        self.assertEqual(
            [
                "final_delta", "head", "final_snapshot",
                "snapshot_sha256", "upstream", "ack_cursor", "now",
            ],
            calls,
        )


if __name__ == "__main__":
    unittest.main()
