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
            "compile_side_effects": (),
            "staged_compile_side_effects": (),
            "command_compile_side_effects": (),
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

    def test_non_authorizable_blocks_precede_and_summarize_user_exits(self):
        result = decide_ownership(self.facts(
            inherited=("legacy.txt",),
            foreign_openspec=("openspec/changes/other/change.md",),
            compile_side_effects=("config/generated.properties",),
            strong_artifacts=("build/a.o",),
        ))
        self.assertEqual(
            "bash-compile-side-effects", result.block.rule)
        self.assertIn(
            "config/generated.properties", result.block.message)
        self.assertIn("build/a.o", result.block.message)
        self.assertIn("legacy.txt", result.block.message)
        self.assertIn(
            "openspec/changes/other/change.md",
            result.block.message,
        )
        self.assertIn("同时检测到其他独立问题", result.block.message)

        result = decide_ownership(self.facts(
            foreign_openspec=("openspec/changes/other/change.md",),
            strong_artifacts=("build/a.o",),
        ))
        self.assertEqual("bash-build-artifacts", result.block.rule)

    def test_compile_side_effects_block_before_fallback_artifacts(self):
        result = decide_ownership(self.facts(
            compile_side_effects=("config/generated.properties",),
            strong_artifacts=("build/a.o",),
        ))

        self.assertEqual("bash-compile-side-effects", result.block.rule)
        self.assertIn("config/generated.properties", result.block.message)
        self.assertIn(
            "git restore --staged -- <上述路径>", result.block.message)

    def test_compile_side_effect_message_lists_every_staged_path(self):
        paths = tuple("config/generated-%d.properties" % index
                      for index in range(9))

        result = decide_ownership(self.facts(
            compile_side_effects=paths,
            staged_compile_side_effects=paths,
        ))

        self.assertEqual("bash-compile-side-effects", result.block.rule)
        self.assertTrue(all(path in result.block.message for path in paths))
        self.assertIn("git restore --staged --", result.block.message)
        self.assertNotIn("…", result.block.message)

    def test_command_only_compile_side_effect_says_to_remove_the_command_path(self):
        generated = "internal/generated/build.properties"

        result = decide_ownership(self.facts(
            compile_side_effects=(generated,),
            command_compile_side_effects=(generated,),
        ))

        self.assertEqual("bash-compile-side-effects", result.block.rule)
        self.assertIn(generated, result.block.message)
        self.assertIn("git add", result.block.message)
        self.assertNotIn("git restore --staged --", result.block.message)

    def test_mixed_compile_side_effects_have_separate_recovery_actions(self):
        staged = "config/staged.properties"
        command_only = "internal/generated/build.properties"

        result = decide_ownership(self.facts(
            compile_side_effects=(staged, command_only),
            staged_compile_side_effects=(staged,),
            command_compile_side_effects=(command_only,),
        ))

        self.assertIn(staged, result.block.message)
        self.assertIn(command_only, result.block.message)
        self.assertIn("git restore --staged --", result.block.message)
        self.assertIn("git add", result.block.message)

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
