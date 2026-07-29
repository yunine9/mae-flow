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
    assert_policy_dependencies,
    function_complexity,
    line_count,
    new_module_size_violations,
    workflow_complexity_violations,
)


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class ArchitectureTests(unittest.TestCase):
    def _write_core_fixture(self, package, source):
        temporary = tempfile.TemporaryDirectory()
        path = os.path.join(
            temporary.name,
            "scripts",
            "mae_flow_core",
            package,
            "fixture.py",
        )
        os.makedirs(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(source)
        self.addCleanup(temporary.cleanup)
        return temporary.name

    def _write_foundation_fixture(self, source):
        return self._write_core_fixture("foundation", source)

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

    def test_workflow_policy_has_no_direct_side_effects(self):
        self.assertEqual([], assert_policy_dependencies(ROOT))

    def test_workflow_rejects_aliased_process_calls(self):
        root = self._write_core_fixture(
            "workflow",
            "import subprocess as sp\nsp.run(['git', 'status'])\n",
        )
        self.assertEqual(
            [
                "scripts/mae_flow_core/workflow/fixture.py:2: "
                "forbidden call subprocess.run"
            ],
            assert_policy_dependencies(root),
        )

    def test_refactored_core_modules_stay_within_size_limit(self):
        self.assertEqual([], new_module_size_violations(ROOT))

    def test_workflow_functions_stay_within_complexity_limit(self):
        self.assertEqual([], workflow_complexity_violations(ROOT))

    def test_workflow_complexity_reports_oversized_function(self):
        root = self._write_core_fixture(
            "workflow",
            "def crowded(value):\n"
            + "".join(
                "    if value == %d:\n        value += 1\n" % index
                for index in range(16)
            ),
        )
        self.assertEqual(
            [
                "scripts/mae_flow_core/workflow/fixture.py:1: "
                "crowded complexity 17 exceeds 15"
            ],
            workflow_complexity_violations(root),
        )

    def test_function_complexity_counts_boolean_decisions(self):
        root = self._write_core_fixture(
            "workflow",
            "def choose(one, two, three):\n"
            "    if one and two and three:\n"
            "        return one\n"
            "    return two\n",
        )
        path = os.path.join(
            root,
            "scripts",
            "mae_flow_core",
            "workflow",
            "fixture.py",
        )
        self.assertEqual(4, function_complexity(path, "choose"))

    def test_new_core_module_rejects_more_than_500_lines(self):
        root = self._write_core_fixture(
            "workflow",
            "value = 1\n" * 501,
        )
        self.assertEqual(
            [
                "scripts/mae_flow_core/workflow/fixture.py: "
                "501 lines exceeds 500"
            ],
            new_module_size_violations(root),
        )

    def test_configured_adapter_complexity_limits_are_enforced(self):
        baseline_path = os.path.join(
            ROOT, "scripts", "tests", "architecture_baseline.json")
        with open(baseline_path, encoding="utf-8") as stream:
            baseline = json.load(stream)
        self.assertIn("max_complexity", baseline)
        for relative, functions in baseline["max_complexity"].items():
            for name, maximum in functions.items():
                with self.subTest(relative=relative, function=name):
                    self.assertLessEqual(
                        function_complexity(
                            os.path.join(ROOT, relative),
                            name,
                        ),
                        maximum,
                    )

    def test_selftest_runs_refactor_safety_suites(self):
        with open(
                os.path.join(ROOT, "scripts", "selftest.py"),
                encoding="utf-8") as stream:
            text = stream.read()
        self.assertIn("test_differential_harness.py", text)
        self.assertIn("test_architecture.py", text)
        self.assertIn("test_workflow_advancement.py", text)


if __name__ == "__main__":
    unittest.main()
