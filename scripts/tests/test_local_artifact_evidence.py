#!/usr/bin/env python3
"""Semantic evidence for local-only Spec and verification artifacts."""

import os
import sys
import tempfile
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.cli_commands.evidence_registry import (  # noqa: E402
    _local_spec_valid,
    _verification_passed,
)
from mae_flow_core.orchestration.work_package import (  # noqa: E402
    ensure_work_package,
)


VALID_SPEC = """# 需求规格

## 范围
支持 NRPRACH SUL 模式。

## 可观察行为
SUL + N95 映射为 TYPE_2。

## 验收条件
- 给定 SUL + N95，返回 TYPE_2。

## 不在范围
- 不扩展 isRBNumMode。

## Grill 决策
- GQ-01：N98 使用 TYPE_1。
"""


class LocalArtifactEvidenceTests(unittest.TestCase):
    def test_local_spec_requires_complete_semantic_content(self):
        with tempfile.TemporaryDirectory() as root:
            package = ensure_work_package(root, "REQ-1")
            before = os.getcwd()
            try:
                os.chdir(root)
                self._write(package.spec, "# 只有标题\n")
                self.assertFalse(_local_spec_valid(
                    {"config": {"单号": "REQ-1"}})[0])
                self._write(package.spec, VALID_SPEC)
                self.assertEqual(
                    (True, ""),
                    _local_spec_valid({"config": {"单号": "REQ-1"}}),
                )
            finally:
                os.chdir(before)

    def test_verification_requires_pass_and_fail_wins(self):
        with tempfile.TemporaryDirectory() as root:
            package = ensure_work_package(root, "REQ-1")
            report = os.path.join(package.root, "verification.md")
            state = {"config": {"单号": "REQ-1"}}
            before = os.getcwd()
            try:
                os.chdir(root)
                self._write(report, "已核对全部范围。\n")
                self.assertFalse(_verification_passed(state)[0])
                self._write(report, "已核对全部范围。\nPASS\n")
                self.assertEqual((True, ""), _verification_passed(state))
                self._write(report, "PASS\n发现回归：FAIL\n")
                self.assertFalse(_verification_passed(state)[0])
            finally:
                os.chdir(before)

    @staticmethod
    def _write(path, content):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(content)


if __name__ == "__main__":
    unittest.main()
