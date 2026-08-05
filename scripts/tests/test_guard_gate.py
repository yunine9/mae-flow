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
    BashWriteContext,
    EditGateContext,
    decide_bash_write,
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


class BashWriteGateTests(unittest.TestCase):
    def context(self, **overrides):
        values = {
            "command": "echo ok",
            "tokens": (),
            "writeish": False,
            "strong_write": False,
            "weak_write": False,
            "hits_requirement": False,
            "hits_internal_state": False,
            "hits_specs_truth": False,
            "step": "build",
            "allow_specs_write": False,
            "offenders": (),
            "source_tokens": (),
            "allow_source_edit": True,
            "tests_only_patterns": (),
            "source_unlocked": False,
            "bad_test_sources": (),
        }
        values.update(overrides)
        return BashWriteContext(**values)

    def test_retired_engine_and_internal_state_are_absolute(self):
        retired = decide_bash_write(self.context(
            command="COMET_FORCE_PHASE=verify tool"))
        self.assertEqual("absolute", retired.kind)
        self.assertIn("已退役", retired.message)
        internal = decide_bash_write(self.context(
            writeish=True, hits_internal_state=True))
        self.assertEqual("absolute", internal.kind)
        self.assertIn("流程状态", internal.message)

    def test_requirement_specs_and_source_are_permit_blocks(self):
        requirement = decide_bash_write(self.context(
            step="config_confirm", writeish=True,
            hits_requirement=True))
        self.assertEqual(("block", "bash-docs-req"),
                         (requirement.kind, requirement.rule))
        specs = decide_bash_write(self.context(
            writeish=True, hits_specs_truth=True))
        self.assertEqual(("block", "bash-specs"),
                         (specs.kind, specs.rule))
        source = decide_bash_write(self.context(
            offenders=("src/main.py",), allow_source_edit=False))
        self.assertEqual(("block", "bash-source"),
                         (source.kind, source.rule))

    def test_weak_source_reference_is_advisory(self):
        result = decide_bash_write(self.context(
            weak_write=True,
            source_tokens=("src/main.py",),
            allow_source_edit=False,
        ))
        self.assertEqual("advisory", result.kind)
        self.assertIn("软提醒", result.message)


if __name__ == "__main__":
    unittest.main()
