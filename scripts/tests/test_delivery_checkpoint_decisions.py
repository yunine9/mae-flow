#!/usr/bin/env python3
"""Checkpoint decision application use-case tests."""

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.application.delivery.checkpoint_decisions import (  # noqa: E402
    CheckpointDecisionPorts,
    decide_checkpoint,
)
from mae_flow_core.delivery.models import thaw  # noqa: E402


class CheckpointDecisionUseCaseTests(unittest.TestCase):
    def review(self, precommit=True):
        return {
            "version": 1,
            "status": "active",
            "mode": "staged",
            "review_before_commit": precommit,
            "delivery_base": "base",
            "last_reviewed_head": "base",
            "current_index": 0,
            "checkpoints": [{
                "id": "CP1",
                "title": "first batch",
                "status": "review_pending",
                "fixed_base": "base",
                "compile_head": "base",
                "receipt": {
                    "base": "base",
                    "head": "candidate",
                    "remote_ref": "origin/topic",
                    "ack_cursor": ["old"],
                    "snapshot": {"src/main.py": {"sha256": "one"}},
                },
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
            "review": self.review() if review is None else review,
            "current": "tw_change",
            "moonlight": False,
            "choice": "continue",
            "ack": "我已认真检视并完成自验证，继续",
            "ports": CheckpointDecisionPorts(
                verify_ack=supplied("verify_ack", (True, "")),
                head=supplied("head", overrides.pop("head", "base")),
                upstream=supplied(
                    "upstream",
                    overrides.pop("upstream", (
                        "origin/topic", "candidate", "candidate"))),
                worktree_fresh=supplied(
                    "worktree_fresh",
                    overrides.pop("worktree_fresh", (True, ""))),
                final_snapshot=supplied(
                    "final_snapshot",
                    overrides.pop("final_snapshot", {})),
                source_fresh=supplied(
                    "source_fresh",
                    overrides.pop("source_fresh", (True, ""))),
                upstream_contains=supplied(
                    "upstream_contains",
                    overrides.pop("upstream_contains", "")),
                now=supplied("now", "2026-07-30 12:00:00"),
            ),
        }
        values.update(overrides)
        return decide_checkpoint(**values), calls

    def test_rejects_without_review_before_using_ports(self):
        result, calls = self.call(review={})
        self.assertEqual(2, result.exit_code)
        self.assertIn("没有等待用户裁决", result.stderr[0])
        self.assertEqual([], calls)

    def test_precommit_continue_freezes_commit_pending(self):
        result, calls = self.call()
        self.assertEqual(0, result.exit_code)
        updated = thaw(result.effects[0].payload)
        item = updated["checkpoints"][0]
        self.assertEqual("commit_pending", item["status"])
        self.assertFalse(item["after_commit_continuous"])
        self.assertEqual(["now", "verify_ack", "worktree_fresh"], calls)
        self.assertIn("  git add -- src/main.py", result.stdout)

    def test_revise_returns_to_coding_and_invalidates_quality(self):
        result, calls = self.call(
            choice="revise",
            ack="需要调整代码",
        )
        updated = thaw(result.effects[0].payload)
        item = updated["checkpoints"][0]
        self.assertEqual("coding", item["status"])
        self.assertNotIn("receipt", item)
        self.assertEqual("invalidate_quality", result.effects[1].kind)
        self.assertNotIn("worktree_fresh", calls)

    def test_final_revise_requests_rework_effect(self):
        review = self.review()
        review["final_review"] = {
            "status": "review_pending",
            "base": "base",
            "head": "candidate",
            "ack_cursor": [],
        }
        result, calls = self.call(
            review=review,
            current="delivery_review",
            choice="revise",
            ack="需要调整代码",
        )
        self.assertEqual(0, result.exit_code)
        self.assertEqual("activate_final_rework", result.effects[0].kind)
        self.assertEqual(["now", "verify_ack"], calls)

    def test_commit_recovery_only_allows_unpushed_revise(self):
        review = self.review()
        review["checkpoints"][0]["status"] = "commit_recovery"
        result, _calls = self.call(
            review=review,
            choice="continue",
        )
        self.assertIn("错误提交不能用", result.stderr[0])
        result, calls = self.call(
            review=review,
            choice="revise",
            ack="需要调整代码",
        )
        updated = thaw(result.effects[0].payload)
        self.assertEqual(
            "reset_pending", updated["checkpoints"][0]["status"])
        self.assertIn("upstream_contains", calls)


if __name__ == "__main__":
    unittest.main()
