#!/usr/bin/env python3
"""Spec2Code 最小上下文恢复与摘要漂移回归。"""

import hashlib
import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from mae_flow_core.quality.spec2code_recovery import (  # noqa: E402
    recovery_guidance,
)
from mae_flow_core.cli_commands.direct_reentry import (  # noqa: E402
    _rewind_checkpoint_after_direct_changes,
)


class Spec2CodeRecoveryTests(unittest.TestCase):
    def state(self, status):
        files = {
            "blueprint.md": "blueprint",
            "roadmap.md": "roadmap",
            "plan.md": "plan",
            "cp2-plan.md": "plan review",
            "cp2-code.md": "code review",
        }
        process = {
            kind: {
                "path": kind + ".md",
                "sha256": hashlib.sha256(
                    files[kind + ".md"].encode("utf-8")
                ).hexdigest(),
            }
            for kind in ("blueprint", "roadmap", "plan")
        }
        item = {
            "id": "CP2",
            "status": status,
            "plan_receipt": {
                "review_path": "cp2-plan.md",
                "review_sha256": hashlib.sha256(
                    files["cp2-plan.md"].encode("utf-8")
                ).hexdigest(),
            },
            "craft_review": {
                "path": "cp2-code.md",
                "sha256": hashlib.sha256(
                    files["cp2-code.md"].encode("utf-8")
                ).hexdigest(),
            },
        }
        return ({
            "current": "build",
            "spec2code": process,
            "development_review": {
                "version": 2,
                "current_index": 0,
                "checkpoints": [item],
            },
        }, files)

    def guidance(self, state, files):
        return recovery_guidance(
            state,
            is_file=lambda path: path in files,
            read_text=lambda path: files[path],
        )

    def test_plan_review_wait_reads_plan_and_plan_review_only(self):
        state, files = self.state("plan_review_pending")
        lines = self.guidance(state, files)
        self.assertIn("plan.md", "\n".join(lines))
        self.assertIn("cp2-plan.md", "\n".join(lines))
        self.assertNotIn("cp2-code.md", "\n".join(lines))

    def test_craft_review_wait_reads_plan_code_review_and_diff(self):
        state, files = self.state("craft_pending")
        lines = self.guidance(state, files)
        body = "\n".join(lines)
        self.assertIn("plan.md", body)
        self.assertIn("cp2-code.md", body)
        self.assertIn("Git diff", body)

    def test_changed_artifact_returns_to_own_loop_without_deleting_it(self):
        state, files = self.state("coding")
        files["plan.md"] = "changed"
        body = "\n".join(self.guidance(state, files))
        self.assertIn("摘要已变化", body)
        self.assertIn("当前 CP 计划 Loop", body)

    def test_verify_ut_restores_only_blueprint_and_final_diff(self):
        state, files = self.state("completed")
        state["current"] = "verify_ut"
        body = "\n".join(self.guidance(state, files))
        self.assertIn("blueprint.md", body)
        self.assertIn("最终 Git diff", body)
        self.assertNotIn("roadmap.md", body)

    def test_direct_source_change_invalidates_pending_plan_review(self):
        state, _files = self.state("plan_review_pending")
        review_state = state["development_review"]
        _rewind_checkpoint_after_direct_changes(review_state)
        item = review_state["checkpoints"][0]
        self.assertEqual("planned", item["status"])
        self.assertNotIn("plan_receipt", item)

    def test_direct_source_change_returns_post_code_review_to_coding(self):
        state, _files = self.state("craft_pending")
        review_state = state["development_review"]
        item = review_state["checkpoints"][0]
        item.update({
            "receipt": {"snapshot": {"src/a.py": "digest"}},
            "compile_source_sha256": "a" * 64,
        })
        _rewind_checkpoint_after_direct_changes(review_state)
        self.assertEqual("coding", item["status"])
        self.assertNotIn("receipt", item)
        self.assertNotIn("compile_source_sha256", item)


if __name__ == "__main__":
    unittest.main()
