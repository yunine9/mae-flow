#!/usr/bin/env python3
"""Pure Gate decision tests."""

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.guard.gate import (  # noqa: E402
    EditGateContext,
    decide_edit,
)


class EditGateTests(unittest.TestCase):
    def context(self, **overrides):
        values = {
            "path": "README.md",
            "match_path": "README.md",
            "step": "build",
            "step_title": "实现",
            "inside_plugin": False,
            "specs_truth": r"(^|/)openspec/specs/",
            "allow_specs_write": False,
            "is_source": False,
            "checkpoint_locked": False,
            "checkpoint_label": "",
            "allow_source_edit": True,
            "tests_only_patterns": (),
            "source_unlocked": False,
        }
        values.update(overrides)
        return EditGateContext(**values)

    def test_internal_state_and_secret_are_absolute_blocks(self):
        for path, fragment in (
            (".mae-flow.json", "流程状态"),
            (".env.production", ".env 类密钥文件"),
            ("/plugin/scripts/mae-flow.py", "禁止修改插件自身"),
        ):
            with self.subTest(path=path):
                result = decide_edit(self.context(
                    path=path, match_path=path,
                    inside_plugin=path.startswith("/plugin/")))
                self.assertEqual("absolute", result.kind)
                self.assertIn(fragment, result.message)

    def test_specs_source_and_tests_only_are_permit_blocks(self):
        specs = decide_edit(self.context(
            path="openspec/specs/api/spec.md",
            match_path="openspec/specs/api/spec.md"))
        self.assertEqual("block", specs.kind)
        self.assertEqual("edit-specs", specs.rule)

        source = decide_edit(self.context(
            path="src/main.py", match_path="src/main.py",
            is_source=True, allow_source_edit=False))
        self.assertEqual(("block", "edit-source"),
                         (source.kind, source.rule))

        tests_only = decide_edit(self.context(
            path="src/main.py", match_path="src/main.py",
            is_source=True, tests_only_patterns=(r"(^|/)tests/",)))
        self.assertEqual(("block", "edit-tests-only"),
                         (tests_only.kind, tests_only.rule))

    def test_allowed_edit_has_no_rule_or_message(self):
        self.assertEqual(
            ("allow", "", ""),
            tuple(decide_edit(self.context())),
        )


if __name__ == "__main__":
    unittest.main()
