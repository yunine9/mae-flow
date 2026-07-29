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


from differential.coverage import (  # noqa: E402
    load_coverage,
    validate_coverage,
)
from differential.scenarios import SCENARIOS  # noqa: E402


class DifferentialCoverageContractTests(unittest.TestCase):
    def test_phase9_scenarios_have_complete_coverage_metadata(self):
        coverage = load_coverage(os.path.join(
            TESTS, "differential", "coverage.json"))
        self.assertEqual(
            [],
            validate_coverage(coverage, set(SCENARIOS)),
        )

    def test_coverage_rejects_unknown_domain_and_missing_scenario(self):
        coverage = {
            "schema": 1,
            "scenarios": {
                "ghost": {
                    "domain": "unknown",
                    "runtime": "inactive",
                    "workflow": "none",
                    "transition": "none",
                    "delivery": "none",
                    "fault": "none",
                }
            },
        }
        self.assertEqual(
            [
                "coverage missing registered scenario action_status",
                "coverage references unknown scenario ghost",
                "ghost: unknown domain unknown",
            ],
            validate_coverage(coverage, {"action_status"}),
        )


if __name__ == "__main__":
    unittest.main()
