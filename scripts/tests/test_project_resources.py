#!/usr/bin/env python3
"""Project-local launcher resources and readable work-package paths."""

import importlib
import importlib.util
import os
import sys
import tempfile
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)


class ProjectResourceTests(unittest.TestCase):
    def test_plugin_resources_are_materialized_project_locally(self):
        runtime = importlib.import_module("mae_flow_core.cli_runtime")
        self.assertTrue(hasattr(runtime, "materialize_plugin_resources"))
        with tempfile.TemporaryDirectory() as root:
            paths = runtime.materialize_plugin_resources(root, ROOT)
            expected = os.path.join(
                root, ".mae-flow-work", "plugin-resources",
                "guidance", "grill.md")
            self.assertIn(expected, paths)
            self.assertTrue(os.path.isfile(expected))
            domain_template = os.path.join(
                root, ".mae-flow-work", "plugin-resources",
                "assets", "DOMAIN-SPEC-TEMPLATE.md")
            self.assertIn(domain_template, paths)
            self.assertTrue(os.path.isfile(domain_template))
            implementation_template = os.path.join(
                root, ".mae-flow-work", "plugin-resources",
                "assets", "IMPLEMENTATION-TEMPLATE.md")
            self.assertIn(implementation_template, paths)
            self.assertTrue(os.path.isfile(implementation_template))

    def test_ordinary_ticket_keeps_readable_work_directory(self):
        self.assertIsNotNone(importlib.util.find_spec(
            "mae_flow_core.orchestration.work_package"))
        module = importlib.import_module(
            "mae_flow_core.orchestration.work_package")
        with tempfile.TemporaryDirectory() as root:
            package = module.ensure_work_package(root, "REQ-123")
            self.assertEqual("REQ-123", package.safe_ticket)
            self.assertEqual(
                os.path.join(root, ".mae-flow-work", "REQ-123"),
                package.root,
            )
            self.assertEqual("REQ-123", self._read(package.ticket_marker))
            self.assertEqual(
                os.path.join(package.root, "implementation.md"),
                package.implementation,
            )

    def test_case_collision_gets_short_stable_suffix(self):
        self.assertIsNotNone(importlib.util.find_spec(
            "mae_flow_core.orchestration.work_package"))
        module = importlib.import_module(
            "mae_flow_core.orchestration.work_package")
        with tempfile.TemporaryDirectory() as root:
            first = module.ensure_work_package(root, "REQ-123")
            second = module.ensure_work_package(root, "req-123")
            repeated = module.ensure_work_package(root, "req-123")
            self.assertEqual("REQ-123", first.safe_ticket)
            self.assertRegex(second.safe_ticket, r"^req-123-[0-9a-f]{8}$")
            self.assertEqual(second.safe_ticket, repeated.safe_ticket)

    def test_pre_marker_exact_directory_is_adopted_in_place(self):
        module = importlib.import_module(
            "mae_flow_core.orchestration.work_package")
        with tempfile.TemporaryDirectory() as root:
            existing = os.path.join(root, ".mae-flow-work", "REQ-123")
            os.makedirs(existing)
            with open(os.path.join(existing, "survey.md"), "w", encoding="utf-8") as stream:
                stream.write("legacy local context")
            package = module.ensure_work_package(root, "REQ-123")
            self.assertEqual(existing, package.root)
            self.assertEqual("REQ-123", self._read(package.ticket_marker))

    @staticmethod
    def _read(path):
        with open(path, encoding="utf-8") as stream:
            return stream.read()


if __name__ == "__main__":
    unittest.main()
