#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Architecture boundaries for behavior-preserving Mae-Flow refactoring."""

import json
import os
import sys
import tempfile
import unittest


TESTS = os.path.abspath(os.path.dirname(__file__))
if TESTS not in sys.path:
    sys.path.insert(0, TESTS)

from architecture_rules import (  # noqa: E402
    assert_foundation_dependencies,
    line_count,
)


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class ArchitectureTests(unittest.TestCase):
    def _write_foundation_fixture(self, source):
        temporary = tempfile.TemporaryDirectory()
        path = os.path.join(
            temporary.name,
            "scripts",
            "mae_flow_core",
            "foundation",
            "fixture.py",
        )
        os.makedirs(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(source)
        self.addCleanup(temporary.cleanup)
        return temporary.name

    def test_existing_monoliths_do_not_grow(self):
        baseline_path = os.path.join(
            ROOT, "scripts", "tests", "architecture_baseline.json")
        with open(baseline_path, encoding="utf-8") as stream:
            baseline = json.load(stream)
        for relative, maximum in baseline["max_lines"].items():
            with self.subTest(relative=relative):
                self.assertLessEqual(
                    line_count(os.path.join(ROOT, relative)), maximum)

    def test_foundation_has_no_reverse_dependencies(self):
        self.assertEqual([], assert_foundation_dependencies(ROOT))

    def test_foundation_rejects_relative_reverse_imports(self):
        root = self._write_foundation_fixture(
            "from ..workflow import engine\n")
        self.assertEqual(
            [
                "scripts/mae_flow_core/foundation/fixture.py:1: "
                "forbidden import mae_flow_core.workflow"
            ],
            assert_foundation_dependencies(root),
        )

    def test_foundation_rejects_parent_relative_module_imports(self):
        root = self._write_foundation_fixture(
            "from .. import workflow\n")
        self.assertEqual(
            [
                "scripts/mae_flow_core/foundation/fixture.py:1: "
                "forbidden import mae_flow_core.workflow"
            ],
            assert_foundation_dependencies(root),
        )

    def test_foundation_rejects_aliased_forbidden_calls(self):
        root = self._write_foundation_fixture(
            "import subprocess as sp\nsp.run(['git', 'status'])\n")
        self.assertEqual(
            [
                "scripts/mae_flow_core/foundation/fixture.py:2: "
                "forbidden call subprocess.run"
            ],
            assert_foundation_dependencies(root),
        )

    def test_selftest_runs_refactor_safety_suites(self):
        with open(
                os.path.join(ROOT, "scripts", "selftest.py"),
                encoding="utf-8") as stream:
            text = stream.read()
        self.assertIn("test_differential_harness.py", text)
        self.assertIn("test_architecture.py", text)


if __name__ == "__main__":
    unittest.main()
