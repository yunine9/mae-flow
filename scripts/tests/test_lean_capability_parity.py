#!/usr/bin/env python3
"""Release gate for old-to-Lean user-journey capability parity."""

import ast
import json
import os
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MATRIX = os.path.join(
    ROOT, "runtime", "guidance", "user-journey-preservation.json")
EXPECTED_FAMILIES = {
    "startup",
    "path",
    "grill-spec",
    "design-construction",
    "quality",
    "delivery",
    "recovery-platform-moonlight",
    "standalone-chain",
}
ALLOWED_CLASSIFICATIONS = {
    "preserved behavior",
    "intentional semantic change",
}


def semantic_test_ids():
    identifiers = set()
    tests_root = os.path.join(ROOT, "scripts", "tests")
    for directory, unused_names, filenames in os.walk(tests_root):
        for filename in filenames:
            if not filename.startswith("test_") or not filename.endswith(".py"):
                continue
            path = os.path.join(directory, filename)
            relative = os.path.relpath(path, ROOT).replace(os.sep, "/")
            with open(path, encoding="utf-8") as stream:
                tree = ast.parse(stream.read(), filename=path)
            for node in tree.body:
                if not isinstance(node, ast.ClassDef):
                    continue
                for method in node.body:
                    if (isinstance(method, ast.FunctionDef)
                            and method.name.startswith("test_")):
                        identifiers.add("%s:%s.%s" % (
                            relative, node.name, method.name))
    return identifiers


class LeanCapabilityParityTests(unittest.TestCase):
    def test_every_critical_user_journey_has_an_executable_parity_contract(self):
        with open(MATRIX, encoding="utf-8") as stream:
            matrix = json.load(stream)
        self.assertEqual(1, matrix.get("schema"))
        journeys = matrix.get("journeys")
        self.assertIsInstance(journeys, list)
        self.assertGreaterEqual(len(journeys), 16)
        identifiers = [item.get("id") for item in journeys]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertEqual(EXPECTED_FAMILIES, {
            item.get("family") for item in journeys
        })
        valid_tests = semantic_test_ids()
        for item in journeys:
            with self.subTest(journey=item.get("id")):
                self.assertRegex(item.get("id", ""), r"^[a-z0-9][a-z0-9-]+$")
                self.assertIn(item.get("classification"),
                              ALLOWED_CLASSIFICATIONS)
                self.assertTrue(item.get("critical"))
                self.assertGreaterEqual(len(item.get("legacy_behavior", "")), 20)
                self.assertGreaterEqual(len(item.get("lean_behavior", "")), 20)
                tests = item.get("tests")
                self.assertIsInstance(tests, list)
                self.assertTrue(tests)
                self.assertEqual([], sorted(
                    identifier for identifier in tests
                    if identifier not in valid_tests))

    def test_critical_journeys_cannot_be_classified_as_removed_friction(self):
        with open(MATRIX, encoding="utf-8") as stream:
            matrix = json.load(stream)
        forbidden = {
            "removed friction", "intentionally removed friction",
            "migration-only", "unverified",
        }
        self.assertEqual([], [
            item.get("id") for item in matrix.get("journeys", [])
            if item.get("critical") and item.get("classification") in forbidden
        ])


if __name__ == "__main__":
    unittest.main(verbosity=2)
