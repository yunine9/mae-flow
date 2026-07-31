#!/usr/bin/env python3
"""Checkpoint 计划与 Craft Review 子状态回归。"""

import hashlib
import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from mae_flow_core.application.delivery.checkpoint_quality import (  # noqa: E402
    CRAFT_DECISION_ACK,
    CheckpointQualityPorts,
    decide_craft_review,
    decide_checkpoint_plan,
    prepare_checkpoint_plan,
    record_craft_review,
)
from mae_flow_core.delivery.models import thaw  # noqa: E402
from test_spec2code_artifacts import (  # noqa: E402
    PLAN,
    TASK_CARD_SHA,
    review,
)
from mae_flow_core.cli_parser import parse_args  # noqa: E402


class CheckpointQualityTests(unittest.TestCase):
    SOURCE_SHA = "d" * 64

    def test_parser_exposes_plan_and_craft_commands(self):
        global_plan = parse_args([
            "checkpoint",
            "plan",
            "--roadmap",
            ".mae-flow-work/roadmap-REQ-1.md",
            "--plan",
            ".mae-flow-work/plan-REQ-1.md",
        ])
        self.assertEqual([], global_plan.item)
        prepared = parse_args([
            "checkpoint",
            "prepare",
            "CP2",
            "--plan",
            ".mae-flow-work/plan-REQ-1.md",
            "--review",
            ".mae-flow-work/reviews/REQ-1/CP2-plan.md",
        ])
        self.assertEqual("prepare", prepared.checkpoint_action)
        self.assertEqual("CP2", prepared.checkpoint_id)
        decided = parse_args([
            "checkpoint",
            "plan-decide",
            "continue",
        ])
        self.assertEqual("continue", decided.choice)
        self.assertFalse(hasattr(decided, "ack"))
        crafted = parse_args([
            "checkpoint",
            "craft-reviewed",
            "CP2",
            "--review",
            ".mae-flow-work/reviews/REQ-1/CP2-code.md",
        ])
        self.assertEqual("craft-reviewed", crafted.checkpoint_action)
        craft_decision = parse_args([
            "checkpoint",
            "craft-decide",
            "CP2",
            "--review",
            ".mae-flow-work/reviews/REQ-1/CP2-code.md",
        ])
        self.assertEqual("craft-decide", craft_decision.checkpoint_action)

    def state(self, mode="staged", count=1):
        return {
            "version": 2,
            "status": "active",
            "mode": mode,
            "current_index": 0,
            "checkpoints": [
                {
                    "id": "CP%d" % (index + 1),
                    "title": "batch",
                    "status": "planned",
                    "fixed_base": "base" if index == 0 else "",
                }
                for index in range(count)
            ],
        }

    def ports(self, files, verify=True):
        return CheckpointQualityPorts(
            is_file=lambda path: path in files,
            read_text=lambda path: files[path],
            normalize_path=lambda path: path,
            digest=lambda text: hashlib.sha256(
                text.encode("utf-8")).hexdigest(),
            ack_cursor=lambda: ("message-1",),
            verify_ack=lambda _receipt, _expected: (
                verify,
                "" if verify else "missing ack",
            ),
            role_task_sha=lambda _role, _checkpoint: TASK_CARD_SHA,
            registered_artifact_sha=lambda kind: (
                hashlib.sha256(PLAN.encode("utf-8")).hexdigest()
                if kind == "plan" else ""
            ),
            now=lambda: "2026-07-30 13:00:00",
        )

    def test_prepare_and_user_decide_plan_loop(self):
        paths = {
            ".mae-flow-work/plan-REQ-1.md": PLAN,
            ".mae-flow-work/reviews/REQ-1/CP1-plan.md": review(
                mode="PLAN",
                target_sha=hashlib.sha256(
                    PLAN.encode("utf-8")).hexdigest(),
            ),
        }
        prepared = prepare_checkpoint_plan(
            self.state(),
            "CP1",
            ".mae-flow-work/plan-REQ-1.md",
            ".mae-flow-work/reviews/REQ-1/CP1-plan.md",
            "REQ-1",
            self.ports(paths),
        )
        item = thaw(prepared.effects[0].payload)["checkpoints"][0]
        self.assertEqual("plan_review_pending", item["status"])
        self.assertEqual(1, item["plan_attempt"])

        continued = decide_checkpoint_plan(
            thaw(prepared.effects[0].payload),
            "continue",
            self.ports(paths),
        )
        self.assertEqual(
            "coding",
            thaw(continued.effects[0].payload)["checkpoints"][0]["status"],
        )

        revised = decide_checkpoint_plan(
            thaw(prepared.effects[0].payload),
            "revise",
            self.ports(paths),
        )
        revised_item = thaw(revised.effects[0].payload)["checkpoints"][0]
        self.assertEqual("planned", revised_item["status"])
        self.assertNotIn("plan_receipt", revised_item)

    def test_user_plan_confirmation_rejects_changed_displayed_files(self):
        plan_path = ".mae-flow-work/plan-REQ-1.md"
        review_path = ".mae-flow-work/reviews/REQ-1/CP1-plan.md"
        paths = {
            plan_path: PLAN,
            review_path: review(
                mode="PLAN",
                target_sha=hashlib.sha256(
                    PLAN.encode("utf-8")).hexdigest(),
            ),
        }
        prepared = prepare_checkpoint_plan(
            self.state(),
            "CP1",
            plan_path,
            review_path,
            "REQ-1",
            self.ports(paths),
        )
        paths[plan_path] = PLAN + "\n<!-- changed after display -->\n"
        result = decide_checkpoint_plan(
            thaw(prepared.effects[0].payload),
            "continue",
            self.ports(paths),
        )
        item = thaw(result.effects[0].payload)["checkpoints"][0]
        self.assertEqual("planned", item["status"])
        self.assertNotIn("plan_receipt", item)
        self.assertIn("发生变化", result.stdout[0])

    def test_prepare_rejects_plan_changed_after_registration(self):
        plan_path = ".mae-flow-work/plan-REQ-1.md"
        review_path = ".mae-flow-work/reviews/REQ-1/CP1-plan.md"
        changed = PLAN + "\n<!-- unregistered change -->\n"
        changed_sha = hashlib.sha256(
            changed.encode("utf-8")).hexdigest()
        result = prepare_checkpoint_plan(
            self.state(),
            "CP1",
            plan_path,
            review_path,
            "REQ-1",
            self.ports({
                plan_path: changed,
                review_path: review(
                    mode="PLAN",
                    target_sha=changed_sha,
                ),
            }),
        )
        self.assertEqual(2, result.exit_code)
        self.assertIn("已登记 plan 摘要不一致", result.stderr[0])

    def test_moonlight_plan_rejects_human_decision_finding(self):
        plan_path = ".mae-flow-work/plan-REQ-1.md"
        review_path = ".mae-flow-work/reviews/REQ-1/CP1-plan.md"
        result = prepare_checkpoint_plan(
            self.state(),
            "CP1",
            plan_path,
            review_path,
            "REQ-1",
            self.ports({
                plan_path: PLAN,
                review_path: review(
                    mode="PLAN",
                    disposition="人工裁决",
                    status="已解决",
                    target_sha=hashlib.sha256(
                        PLAN.encode("utf-8")).hexdigest(),
                ),
            }),
            moonlight=True,
        )

        self.assertEqual(2, result.exit_code)
        self.assertIn("月光宝盒不得代替用户拍板", result.stderr[0])

    def test_craft_findings_wait_for_user_then_rework(self):
        code_path = ".mae-flow-work/reviews/REQ-1/CP1-code.md"
        pending_files = {
            code_path: review(
                status="待裁决",
                disposition="待用户裁决",
                target_sha=self.SOURCE_SHA,
            ),
        }
        current = self.state()
        current["checkpoints"][0].update({
            "status": "craft_pending",
            "compile_source_sha256": self.SOURCE_SHA,
        })
        pending = record_craft_review(
            current,
            "CP1",
            code_path,
            "REQ-1",
            self.SOURCE_SHA,
            self.ports(pending_files),
        )
        self.assertEqual(
            "craft_decision_pending",
            thaw(pending.effects[0].payload)["checkpoints"][0]["status"],
        )
        self.assertNotIn(
            "invalidate_quality",
            [effect.kind for effect in pending.effects],
        )

        pending_files[code_path] = pending_files[code_path].replace(
            "待用户裁决", "修改").replace("待裁决", "待处理")
        decided = decide_craft_review(
            thaw(pending.effects[0].payload),
            "CP1",
            code_path,
            "REQ-1",
            self.SOURCE_SHA,
            self.ports(pending_files),
        )
        self.assertEqual(
            "coding",
            thaw(decided.effects[0].payload)["checkpoints"][0]["status"],
        )
        self.assertEqual("invalidate_quality", decided.effects[1].kind)
        self.assertTrue(any(
            "checkpoint ready CP1" in line for line in decided.stdout
        ))

    def test_craft_decision_recovers_when_source_was_fixed_early(self):
        code_path = ".mae-flow-work/reviews/REQ-1/CP1-code.md"
        files = {
            code_path: review(
                status="待裁决",
                disposition="待用户裁决",
                target_sha=self.SOURCE_SHA,
            ),
        }
        current = self.state()
        current["checkpoints"][0].update({
            "status": "craft_pending",
            "compile_source_sha256": self.SOURCE_SHA,
        })
        pending = record_craft_review(
            current,
            "CP1",
            code_path,
            "REQ-1",
            self.SOURCE_SHA,
            self.ports(files),
        )
        files[code_path] = files[code_path].replace(
            "待用户裁决", "验证后修改").replace(
                "待裁决", "已解决")

        decided = decide_craft_review(
            thaw(pending.effects[0].payload),
            "CP1",
            code_path,
            "REQ-1",
            "e" * 64,
            self.ports(files),
        )

        self.assertEqual(0, decided.exit_code)
        item = thaw(decided.effects[0].payload)["checkpoints"][0]
        self.assertEqual("coding", item["status"])
        self.assertTrue(item["craft_review_performed"])
        self.assertEqual("invalidate_quality", decided.effects[1].kind)
        self.assertTrue(any(
            "重新编译" in line for line in decided.stdout
        ))

    def test_clean_craft_review_advances_without_decision(self):
        code_path = ".mae-flow-work/reviews/REQ-1/CP1-code.md"
        current = self.state()
        current["checkpoints"][0].update({
            "status": "craft_pending",
            "compile_source_sha256": self.SOURCE_SHA,
        })
        clean_files = {
            code_path: review(
                findings=0,
                result="CLEAN",
                target_sha=self.SOURCE_SHA,
            ),
        }
        accepted = record_craft_review(
            current,
            "CP1",
            code_path,
            "REQ-1",
            self.SOURCE_SHA,
            self.ports(clean_files),
        )
        self.assertEqual(
            "review_pending",
            thaw(accepted.effects[0].payload)["checkpoints"][0]["status"],
        )

    def test_craft_review_wrong_state_explains_one_shot_sequence(self):
        code_path = ".mae-flow-work/reviews/REQ-1/CP1-code.md"
        current = self.state()
        current["checkpoints"][0]["status"] = "coding"
        result = record_craft_review(
            current,
            "CP1",
            code_path,
            "REQ-1",
            self.SOURCE_SHA,
            self.ports({}),
        )
        self.assertEqual(2, result.exit_code)
        self.assertIn("checkpoint ready CP1", result.stderr[0])
        self.assertIn("不会自动启动第二轮 Reviewer", result.stderr[0])

    def test_continuous_craft_review_moves_to_next_planned_cp(self):
        code_path = ".mae-flow-work/reviews/REQ-1/CP1-code.md"
        current = self.state(mode="continuous", count=2)
        current["checkpoints"][0].update({
            "status": "craft_pending",
            "compile_source_sha256": self.SOURCE_SHA,
            "head": "next-head",
        })
        result = record_craft_review(
            current,
            "CP1",
            code_path,
            "REQ-1",
            self.SOURCE_SHA,
            self.ports({
                code_path: review(
                    findings=0,
                    result="CLEAN",
                    target_sha=self.SOURCE_SHA,
                ),
            }),
        )
        updated = thaw(result.effects[0].payload)
        self.assertEqual("completed", updated["checkpoints"][0]["status"])
        self.assertEqual(1, updated["current_index"])
        self.assertEqual("planned", updated["checkpoints"][1]["status"])
        self.assertEqual(
            "next-head",
            updated["checkpoints"][1]["fixed_base"],
        )

    def test_moonlight_does_not_decide_human_review_findings(self):
        code_path = ".mae-flow-work/reviews/REQ-1/CP1-code.md"
        current = self.state(mode="continuous")
        current["checkpoints"][0].update({
            "status": "craft_pending",
            "compile_source_sha256": self.SOURCE_SHA,
        })
        result = record_craft_review(
            current,
            "CP1",
            code_path,
            "REQ-1",
            self.SOURCE_SHA,
            self.ports({
                code_path: review(
                    status="待处理",
                    disposition="人工裁决",
                    target_sha=self.SOURCE_SHA,
                ),
            }),
            moonlight=True,
        )
        self.assertEqual(2, result.exit_code)
        self.assertIn("moonlight blocked", result.stderr[0])


if __name__ == "__main__":
    unittest.main()
