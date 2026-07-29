#!/usr/bin/env python3
"""Machine-checked completion criteria for the Mae-Flow refactor."""

import json
import os
import sys
import unittest


TESTS = os.path.abspath(os.path.dirname(__file__))
ROOT = os.path.abspath(os.path.join(TESTS, "..", ".."))
if TESTS not in sys.path:
    sys.path.insert(0, TESTS)

from refactor_completion import load_contract, validate_contract  # noqa: E402


class RefactorCompletionContractTests(unittest.TestCase):
    def test_repository_contract_has_strict_final_targets(self):
        contract = load_contract(os.path.join(
            TESTS, "refactor_completion_contract.json"))
        self.assertEqual(1, contract["schema"])
        self.assertEqual("phase9", contract["behavior_baseline"])
        self.assertEqual(
            {
                "scripts/mae-flow.py": 1500,
                "hooks/dispatch.py": 800,
            },
            contract["final_targets"]["max_entrypoint_lines"],
        )
        self.assertEqual(
            500, contract["final_targets"]["max_business_module_lines"])
        self.assertEqual(
            15, contract["final_targets"]["max_policy_complexity"])
        self.assertEqual(list(range(10)), [
            item["id"] for item in contract["stages"]])
        self.assertEqual([], validate_contract(ROOT, contract))

    def test_contract_rejects_target_above_current_monolith_baseline(self):
        with open(
                os.path.join(TESTS, "refactor_completion_contract.json"),
                encoding="utf-8") as stream:
            contract = json.load(stream)
        contract["final_targets"]["max_entrypoint_lines"][
            "scripts/mae-flow.py"] = 20000
        self.assertIn(
            "scripts/mae-flow.py: final target 20000 must be below "
            "current architecture baseline 10408",
            validate_contract(ROOT, contract),
        )


if __name__ == "__main__":
    unittest.main()
