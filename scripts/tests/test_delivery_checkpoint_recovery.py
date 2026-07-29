#!/usr/bin/env python3
"""Checkpoint status and recovery use-case tests."""

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.application.delivery.checkpoint_recovery import (  # noqa: E402
    CheckpointRecoveryPorts,
    refresh_checkpoint,
    refresh_final_review,
)
from mae_flow_core.delivery.models import thaw  # noqa: E402


class RecoveryPorts:
    def __init__(self):
        self.head = "candidate"
        self.snapshot = {"src/main.cpp": {"sha256": "one"}}
        self.upstream = ("origin/topic", "candidate", "candidate")
        self.source_fresh = (True, "")
        self.commit_paths = ("src/main.cpp",)
        self.commit_count = "1"
        self.dirty_paths = ()
        self.commit_tagged = (True, "")
        self.ack_cursor = ("message-1",)
        self.reopened = []

    def value(self):
        return CheckpointRecoveryPorts(
            head=lambda: self.head,
            current_snapshot=lambda _item: dict(self.snapshot),
            upstream=lambda: self.upstream,
            source_fresh=lambda _head: self.source_fresh,
            merge_base=lambda base, _head: base,
            commit_paths=lambda _base: self.commit_paths,
            commit_count=lambda _base: self.commit_count,
            dirty_paths=lambda: self.dirty_paths,
            commit_tagged=lambda: self.commit_tagged,
            commit_commands=lambda _item: (
                "git add -- src/main.cpp",
                "git commit -m '[REQ][fix]batch'",
            ),
            ack_cursor=lambda: self.ack_cursor,
            now=lambda: "2026-07-30 10:00:00",
            rework_target=lambda: "tw_change",
            reopen_spec_archive=lambda _state: (
                self.reopened.append(True) or (True, "")),
        )


def checkpoint_review(status):
    return {
        "mode": "staged",
        "review_before_commit": True,
        "current_index": 0,
        "checkpoints": [{
            "id": "CP1",
            "title": "batch",
            "status": status,
            "receipt": {
                "base": "base",
                "snapshot": {
                    "src/main.cpp": {"sha256": "one"},
                },
            },
        }],
    }


class CheckpointRecoveryUseCaseTests(unittest.TestCase):
    def changed_review(self, result):
        effect = next(
            item for item in result.effects
            if item.kind == "set_development_review"
        )
        return thaw(effect.payload)

    def test_commit_pending_verifies_exact_snapshot_then_waits_for_push(self):
        ports = RecoveryPorts()
        ports.upstream = ("", "", "candidate")
        result = refresh_checkpoint(
            checkpoint_review("commit_pending"),
            current="tw_change",
            ports=ports.value(),
        )
        item = self.changed_review(result)["checkpoints"][0]
        self.assertEqual("push_pending", item["status"])
        self.assertEqual("candidate", item["head"])
        self.assertIn("现在执行 git push", result.stdout[0])

    def test_bad_commit_enters_frozen_recovery(self):
        ports = RecoveryPorts()
        ports.commit_paths = ("src/main.cpp", "notes.txt")
        result = refresh_checkpoint(
            checkpoint_review("commit_pending"),
            current="tw_change",
            ports=ports.value(),
        )
        item = self.changed_review(result)["checkpoints"][0]
        self.assertEqual("commit_recovery", item["status"])
        self.assertIn("夹带 notes.txt", item["verification_error"])
        self.assertEqual(("message-1",), tuple(
            item["receipt"]["ack_cursor"]))
        self.assertIn("已禁止 push", result.stdout[0])

    def test_reset_pending_returns_to_coding_and_invalidates_quality(self):
        ports = RecoveryPorts()
        ports.head = "base"
        review = checkpoint_review("reset_pending")
        review["checkpoints"][0]["attempt"] = 2
        result = refresh_checkpoint(
            review, current="tw_change", ports=ports.value())
        item = self.changed_review(result)["checkpoints"][0]
        self.assertEqual("coding", item["status"])
        self.assertEqual(3, item["attempt"])
        self.assertNotIn("receipt", item)
        self.assertEqual(
            "invalidate_quality", result.effects[1].kind)

    def test_pushed_checkpoint_is_accepted_and_advances_plan(self):
        review = checkpoint_review("push_pending")
        review["checkpoints"][0]["head"] = "candidate"
        result = refresh_checkpoint(
            review,
            current="tw_change",
            ports=RecoveryPorts().value(),
        )
        review = self.changed_review(result)
        self.assertEqual(
            "accepted", review["checkpoints"][0]["status"])
        self.assertEqual(1, review["current_index"])
        self.assertEqual("append_history", result.effects[1].kind)

    def test_legacy_staged_candidate_creates_review_receipt(self):
        ports = RecoveryPorts()
        review = checkpoint_review("push_pending")
        review["review_before_commit"] = False
        review["checkpoints"][0].update({
            "compile_head": "candidate",
            "receipt": {},
        })
        result = refresh_checkpoint(
            review, current="tw_change", ports=ports.value())
        item = self.changed_review(result)["checkpoints"][0]
        self.assertEqual("review_pending", item["status"])
        self.assertEqual("origin/topic", item["receipt"]["remote_ref"])

    def test_final_commit_requests_full_quality_rework(self):
        ports = RecoveryPorts()
        review = checkpoint_review("accepted")
        review["current_index"] = 1
        review["final_review"] = {
            "status": "commit_pending",
            "title": "最终检视增量",
            "requires_quality_rerun": True,
            "receipt": {
                "base": "base",
                "scope": "final",
                "snapshot": {
                    "src/main.cpp": {"sha256": "one"},
                },
            },
        }
        result = refresh_final_review(
            {"current": "delivery_review",
             "choices": {"workflow": "tweak"},
             "history": [],
             "development_review": review},
            ports=ports.value())
        self.assertEqual(
            ["drop_quality_tokens", "set_state"],
            [item.kind for item in result.effects],
        )
        updated = thaw(result.effects[1].payload)
        self.assertEqual("tw_change", updated["current"])
        self.assertEqual(
            "candidate",
            updated["development_review"]["last_reviewed_head"])
        self.assertNotIn(
            "final_review", updated["development_review"])
        self.assertEqual(
            "base", updated["step_heads"]["tw_change"])
        self.assertEqual([True], ports.reopened)

    def test_legacy_final_push_migrates_to_local_review(self):
        ports = RecoveryPorts()
        review = checkpoint_review("accepted")
        review["current_index"] = 1
        review["final_review"] = {
            "status": "push_pending",
            "head": "candidate",
        }
        result = refresh_final_review(
            {"current": "delivery_review",
             "choices": {"workflow": "tweak"},
             "history": [],
             "development_review": review},
            ports=ports.value())
        final = self.changed_review(result)["final_review"]
        self.assertEqual("review_pending", final["status"])
        self.assertEqual("origin/topic", final["remote_ref"])
        self.assertEqual("show_final_review", result.effects[1].kind)


if __name__ == "__main__":
    unittest.main()
