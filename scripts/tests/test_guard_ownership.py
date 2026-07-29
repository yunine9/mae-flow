#!/usr/bin/env python3
"""Pure commit ownership policy tests."""

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.guard.ownership import (  # noqa: E402
    OwnershipFacts,
    decide_ownership,
)


class OwnershipPolicyTests(unittest.TestCase):
    def facts(self, **overrides):
        values = {
            "review_required": False,
            "expected_snapshot": {},
            "current_snapshot": {},
            "candidate_paths": (),
            "inherited": (),
            "foreign_openspec": (),
            "strong_artifacts": (),
            "unproven_paths": (),
            "artifact_hints": (),
        }
        values.update(overrides)
        return OwnershipFacts(**values)

    def test_review_snapshot_and_file_set_are_checked_first(self):
        changed = decide_ownership(self.facts(
            review_required=True,
            expected_snapshot={"src/a.py": "old"},
            current_snapshot={"src/a.py": "new"},
            candidate_paths=("src/a.py",),
            inherited=("legacy.txt",),
        ))
        self.assertEqual(
            "bash-checkpoint-reviewed-snapshot", changed.block.rule)

        mismatch = decide_ownership(self.facts(
            review_required=True,
            expected_snapshot={"src/a.py": "same"},
            current_snapshot={"src/a.py": "same"},
            candidate_paths=("src/b.py",),
        ))
        self.assertEqual(
            "bash-checkpoint-reviewed-files", mismatch.block.rule)
        self.assertIn("漏掉 src/a.py", mismatch.block.message)
        self.assertIn("夹带 src/b.py", mismatch.block.message)

    def test_block_precedence_preserves_historical_order(self):
        result = decide_ownership(self.facts(
            inherited=("legacy.txt",),
            foreign_openspec=("openspec/changes/other/change.md",),
            strong_artifacts=("build/a.o",),
        ))
        self.assertEqual(
            "bash-cross-delivery-carryover", result.block.rule)
        self.assertIn("legacy.txt", result.block.message)

    def test_advisories_are_ordered_and_non_blocking(self):
        result = decide_ownership(self.facts(
            unproven_paths=("src/generated.py",),
            artifact_hints=("dist/app.js",),
        ))
        self.assertIsNone(result.block)
        self.assertEqual(2, len(result.advisories))
        self.assertIn("提交提示", result.advisories[0])
        self.assertIn("产物提示", result.advisories[1])


if __name__ == "__main__":
    unittest.main()
