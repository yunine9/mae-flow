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

    def test_ut_step_still_blocks_editing_product_code(self):
        """瘦身保留项:改产品代码让测试变绿是破坏信任，不是可逆的流程瑕疵。"""
        tests_only = decide_edit(self.context(
            path="src/main.py", match_path="src/main.py",
            is_source=True, tests_only_patterns=(r"(^|/)tests/",)))
        self.assertEqual(("block", "edit-tests-only"),
                         (tests_only.kind, tests_only.rule))
        self.assertIn("unlock source", tests_only.message)

    def test_process_nudges_no_longer_block_editing(self):
        """本步不许改源码/写规格/写需求文档已退役:可逆动作交给 done 的证据检查。"""
        for label, context in (
                ("specs", self.context(
                    path="openspec/specs/api/spec.md",
                    match_path="openspec/specs/api/spec.md")),
                ("source", self.context(
                    path="src/main.py", match_path="src/main.py",
                    is_source=True, allow_source_edit=False)),
                ("docs-req", self.context(
                    path="docs/req/REQ1.md", match_path="docs/req/REQ1.md",
                    step="config_confirm")),
        ):
            with self.subTest(rule=label):
                self.assertEqual("allow", decide_edit(context).kind)

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

    def test_process_nudges_no_longer_block_bash_writes(self):
        """经 Bash 写需求/规格/源码的流程督促已退役。"""
        for label, context in (
                ("docs-req", self.context(
                    step="config_confirm", writeish=True,
                    hits_requirement=True)),
                ("specs", self.context(
                    writeish=True, hits_specs_truth=True)),
                ("source", self.context(
                    offenders=("src/main.py",), allow_source_edit=False)),
                ("weak-source", self.context(
                    weak_write=True, source_tokens=("src/main.py",),
                    allow_source_edit=False)),
        ):
            with self.subTest(rule=label):
                self.assertEqual("allow", decide_bash_write(context).kind)

    def test_ut_step_still_blocks_bash_writes_to_product_code(self):
        result = decide_bash_write(self.context(
            offenders=("src/main.py",),
            allow_source_edit=True,
            tests_only_patterns=(r"(^|/)tests/",),
            bad_test_sources=("src/main.py",),
        ))
        self.assertEqual(("block", "bash-tests-only"),
                         (result.kind, result.rule))


if __name__ == "__main__":
    unittest.main()
