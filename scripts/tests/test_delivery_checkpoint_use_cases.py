#!/usr/bin/env python3
"""Checkpoint application use-case tests."""

import hashlib
import json
import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.application.delivery.checkpoints import (  # noqa: E402
    CheckpointPlanPorts,
    CheckpointReadyPorts,
    plan_checkpoint,
    ready_checkpoint,
)
from mae_flow_core.delivery.models import thaw  # noqa: E402


class CheckpointPlanUseCaseTests(unittest.TestCase):
    def call(self, **overrides):
        calls = []

        def supplied(name, value):
            def get():
                calls.append(name)
                return value
            return get

        values = {
            "current": "tw_pace",
            "workflow": "tweak",
            "moonlight": False,
            "raw_items": (" core behavior ", "regression   coverage"),
            "ports": CheckpointPlanPorts(
                dirty_paths=supplied(
                    "dirty_paths", overrides.pop("dirty_paths", ())),
                task_structure=supplied(
                    "task_structure", (
                        overrides.pop("task_sha256", "task-sha"),
                        tuple(range(overrides.pop("task_count", 2))),
                    )),
                head=supplied(
                    "head", overrides.pop("head", "abcdef1234567890")),
                ack_cursor=supplied(
                    "ack_cursor",
                    overrides.pop("ack_cursor", ("message-1",))),
                now=supplied(
                    "now",
                    overrides.pop("now", "2026-07-30 10:00:00")),
            ),
        }
        values.update(overrides)
        return plan_checkpoint(**values), calls

    def test_rejects_wrong_step_moonlight_and_invalid_items_in_order(self):
        wrong, calls = self.call(
            current="build", moonlight=True, raw_items=())
        self.assertEqual(2, wrong.exit_code)
        self.assertIn("只允许在开发节奏确认步骤", wrong.stderr[0])
        self.assertEqual([], calls)
        moonlight, calls = self.call(moonlight=True)
        self.assertIn("月光宝盒不需要", moonlight.stderr[0])
        self.assertEqual([], calls)
        invalid, calls = self.call(raw_items=("x",))
        self.assertIn("1-6 个非空", invalid.stderr[0])
        self.assertEqual([], calls)
        duplicate, calls = self.call(
            raw_items=("same item", "same   item"))
        self.assertIn("不能重复", duplicate.stderr[0])
        self.assertEqual([], calls)

    def test_rejects_dirty_source_before_building_plan(self):
        result, calls = self.call(dirty_paths=("src/main.py",))
        self.assertEqual(2, result.exit_code)
        self.assertIn("src/main.py", result.stderr[0])
        self.assertEqual((), result.effects)
        self.assertEqual(["dirty_paths"], calls)

    def test_builds_frozen_plan_effect_and_historical_output(self):
        result, calls = self.call()
        self.assertEqual(0, result.exit_code)
        self.assertEqual(
            ["dirty_paths", "task_structure", "head", "ack_cursor", "now"],
            calls,
        )
        self.assertEqual("set_development_review", result.effects[0].kind)
        review = thaw(result.effects[0].payload)
        self.assertEqual(
            ["core behavior", "regression coverage"],
            [item["title"] for item in review["checkpoints"]],
        )
        body = json.dumps({
            "head": "abcdef1234567890",
            "task_sha256": "task-sha",
            "items": [
                {"id": "CP1", "title": "core behavior"},
                {"id": "CP2", "title": "regression coverage"},
            ],
        }, ensure_ascii=False, sort_keys=True)
        self.assertEqual(
            hashlib.sha256(body.encode("utf-8")).hexdigest(),
            review["plan_sha256"],
        )
        self.assertEqual(
            "[mae-flow] 开发检查点方案（确认前尚未开始写码）",
            result.stdout[0],
        )
        self.assertIn("  CP2 — regression coverage", result.stdout)


class CheckpointReadyUseCaseTests(unittest.TestCase):
    def review(self, mode="staged", precommit=True, count=1):
        return {
            "version": 1,
            "status": "active",
            "mode": mode,
            "review_before_commit": precommit,
            "delivery_base": "base",
            "current_index": 0,
            "checkpoints": [
                {
                    "id": "CP%d" % (index + 1),
                    "title": "batch %d" % (index + 1),
                    "status": "coding",
                    "fixed_base": "base" if index == 0 else "",
                }
                for index in range(count)
            ],
        }

    def call(self, review=None, **overrides):
        calls = []

        def supplied(name, value):
            def get(*_args):
                calls.append(name)
                return value
            return get

        snapshot = overrides.pop(
            "snapshot", {"assets/banner.txt": {"sha256": "asset"}})
        values = {
            "review": self.review() if review is None else review,
            "current": "tw_change",
            "workflow": "tweak",
            "moonlight": False,
            "checkpoint_id": "CP1",
            "agent_tasks": {},
            "ports": CheckpointReadyPorts(
                head=supplied("head", overrides.pop("head", "base")),
                object_type=supplied("object_type", "commit"),
                merge_base=supplied("merge_base", "base"),
                worktree_snapshot=supplied("snapshot", snapshot),
                is_source_path=supplied(
                    "is_source_path",
                    overrides.pop("is_source", False)),
                agent_evidence=supplied("agent_evidence", (True, "")),
                snapshot_sha256=supplied("snapshot_sha256", "snapshot-sha"),
                ack_cursor=supplied("ack_cursor", ("message-1",)),
                now=supplied("now", "2026-07-30 11:00:00"),
                task_structure_drift=supplied("task_drift", False),
                dirty_paths=supplied(
                    "dirty_paths", overrides.pop("dirty_paths", ())),
                has_commit=supplied("has_commit", True),
                commit_tagged=supplied("commit_tagged", (True, "")),
                source_files=supplied(
                    "source_files",
                    overrides.pop("source_files", ("src/main.py",))),
            ),
        }
        values.update(overrides)
        return ready_checkpoint(**values), calls

    def test_rejects_invalid_request_before_git_queries(self):
        result, calls = self.call(review={})
        self.assertIn("当前没有已确认", result.stderr[0])
        self.assertEqual([], calls)
        result, calls = self.call(current="build")
        self.assertIn("tw_change", result.stderr[0])
        self.assertEqual([], calls)
        result, calls = self.call(checkpoint_id="CP2")
        self.assertIn("当前应处理 CP1", result.stderr[0])
        self.assertEqual([], calls)

    def test_precommit_non_source_builds_review_receipt_without_compile(self):
        result, calls = self.call()
        self.assertEqual(0, result.exit_code)
        review = thaw(result.effects[0].payload)
        item = review["checkpoints"][0]
        self.assertEqual("review_pending", item["status"])
        self.assertTrue(item["compile_skipped_no_source"])
        self.assertEqual("snapshot-sha", item["receipt"]["snapshot_sha256"])
        self.assertEqual("render_worktree_review", result.effects[1].kind)
        self.assertNotIn("agent_evidence", calls)
        self.assertEqual(2, calls.count("snapshot"))

    def test_continuous_committed_checkpoint_advances_next_batch(self):
        review = self.review(mode="continuous", precommit=False, count=2)
        result, calls = self.call(
            review=review,
            head="next",
            agent_tasks={"COMPILE": {
                "checkpoint": "CP1",
                "sha256": "compile-sha",
            }},
        )
        self.assertEqual(0, result.exit_code)
        updated = thaw(result.effects[0].payload)
        self.assertEqual(1, updated["current_index"])
        self.assertEqual(
            "completed", updated["checkpoints"][0]["status"])
        self.assertEqual("next", updated["checkpoints"][1]["fixed_base"])
        self.assertIn("commit_tagged", calls)
        self.assertIn("agent_evidence", calls)
        self.assertIn("连续模式不 push", result.stdout[0])


if __name__ == "__main__":
    unittest.main()
