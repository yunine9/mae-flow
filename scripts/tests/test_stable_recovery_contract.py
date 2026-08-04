#!/usr/bin/env python3
"""Characterize the stable-base recovery boundary before subtractive edits."""

import json
import os
import sys
import unittest


TESTS = os.path.abspath(os.path.dirname(__file__))
ROOT = os.path.abspath(os.path.join(TESTS, "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.cli_parser import parse_args  # noqa: E402


def load_contract():
    with open(
            os.path.join(TESTS, "stable_recovery_contract.json"),
            encoding="utf-8") as stream:
        return json.load(stream)


class StableRecoveryContractTests(unittest.TestCase):
    def test_declared_stable_capabilities_are_present(self):
        contract = load_contract()
        for argv in contract["preserved_cli_commands"]:
            with self.subTest(argv=argv):
                self.assertEqual(argv[0], parse_args(argv).cmd)
        for resource in contract["preserved_resources"]:
            with self.subTest(resource=resource):
                self.assertTrue(os.path.isfile(os.path.join(ROOT, resource)))

    def test_only_required_agents_remain_after_recovery(self):
        contract = load_contract()
        for agent in contract["required_agents"]:
            with self.subTest(agent=agent):
                self.assertTrue(os.path.isfile(os.path.join(
                    ROOT, "agents", agent + ".md")))
        for agent in contract["removed_agents"]:
            with self.subTest(agent=agent):
                self.assertFalse(os.path.exists(os.path.join(
                    ROOT, "agents", agent + ".md")))

    def test_legacy_composition_root_does_not_import_lean_runtime(self):
        contract = load_contract()
        with open(
                os.path.join(
                    ROOT, "scripts", "mae_flow_core", "cli_runtime.py"),
                encoding="utf-8") as stream:
            content = stream.read()
        for module in contract["forbidden_runtime_modules"]:
            with self.subTest(module=module):
                self.assertNotIn("import " + module, content)
                self.assertNotIn("from ." + module, content)


if __name__ == "__main__":
    unittest.main()
