#!/usr/bin/env python3
"""Machine-checked completion criteria for the Mae-Flow refactor."""

import json
import os
import sys
import tempfile
import unittest


TESTS = os.path.abspath(os.path.dirname(__file__))
ROOT = os.path.abspath(os.path.join(TESTS, "..", ".."))
if TESTS not in sys.path:
    sys.path.insert(0, TESTS)

from refactor_completion import load_contract, validate_contract  # noqa: E402
from selftest_suites import REFACTOR_SAFETY_SUITES  # noqa: E402


EXPECTED_RELEASE_SUITE_COMMANDS = (
    "python scripts/tests/test_lean_state.py",
    "python scripts/tests/test_lean_migration.py",
    "python scripts/tests/test_lean_migration_cli.py",
    "python scripts/tests/test_lean_transitions.py",
    "python scripts/tests/test_lean_guidance.py",
    "python scripts/tests/test_native_guidance.py",
    "python scripts/tests/test_lean_composition.py",
    "python scripts/tests/test_lean_delivery.py",
    "python scripts/tests/test_lean_documents.py",
    "python scripts/tests/test_lean_moonlight.py",
    "python scripts/tests/test_lean_toolbox.py",
    "python scripts/tests/test_delivery_manifest.py",
    "python scripts/tests/test_lean_safety_kernel.py",
    "python scripts/tests/test_lean_hook_events.py",
    "python scripts/tests/test_lean_hook_adapter.py",
    "python scripts/tests/test_hook_protocol.py",
    "python scripts/tests/test_lean_cli.py",
    "python scripts/tests/test_lean_capabilities.py",
    "python scripts/tests/test_capabilities.py",
    "python scripts/tests/test_spec2code_prompt_resources.py",
    "python scripts/tests/test_lightcheck.py",
    "python scripts/tests/test_architecture.py",
    "python scripts/tests/test_file_io.py",
    "python scripts/tests/test_refactor_completion.py",
    "python scripts/tests/test_fault_injection.py",
)


def registered_release_suite_commands():
    return tuple(
        "python " + " ".join(command)
        for unused_label, command, unused_timeout, unused_limit
        in REFACTOR_SAFETY_SUITES
    )


class RefactorCompletionContractTests(unittest.TestCase):
    def _write_reachability_fixture(self, baseline_modules, actual_modules):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        tests = os.path.join(temporary.name, "scripts", "tests")
        core = os.path.join(temporary.name, "scripts", "mae_flow_core")
        os.makedirs(tests)
        os.makedirs(core)
        actual_files = ["scripts/mae-flow.py"] + [
            "scripts/mae_flow_core/%s.py" % name
            for name in actual_modules
        ]
        baseline_files = ["scripts/mae-flow.py"] + [
            "scripts/mae_flow_core/%s.py" % name
            for name in baseline_modules
        ]
        with open(
                os.path.join(temporary.name, "scripts", "mae-flow.py"),
                "w", encoding="utf-8") as stream:
            stream.write("\n".join(
                "import mae_flow_core.%s" % name
                for name in actual_modules) + "\n")
        for name in set(baseline_modules) | set(actual_modules):
            with open(
                    os.path.join(core, name + ".py"),
                    "w", encoding="utf-8") as stream:
                stream.write("VALUE = %r\n" % name)
        with open(
                os.path.join(tests, "architecture_baseline.json"),
                "w", encoding="utf-8") as stream:
            json.dump({
                "max_lines": {
                    "scripts/mae-flow.py": 1500,
                    "hooks/dispatch.py": 800,
                },
                "production_reachable_python_files": sorted(baseline_files),
            }, stream)
        return temporary.name

    def test_declared_release_suites_exactly_match_runner_registry(self):
        contract = load_contract(os.path.join(
            TESTS, "refactor_completion_contract.json"))
        self.assertEqual(
            EXPECTED_RELEASE_SUITE_COMMANDS,
            tuple(contract["required_verifications"].get(
                "release_suites", ())),
        )
        self.assertEqual(
            EXPECTED_RELEASE_SUITE_COMMANDS,
            registered_release_suite_commands(),
        )

    def test_real_hook_protocol_is_a_registered_release_boundary(self):
        self.assertIn(
            "python scripts/tests/test_hook_protocol.py",
            registered_release_suite_commands(),
        )

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
        self.assertEqual(
            0, contract["final_targets"]["private_monolith_test_imports"])
        self.assertEqual(
            66,
            contract["final_targets"]["production_reachable_python_files"],
        )
        self.assertEqual(
            {
                "release_suites": list(EXPECTED_RELEASE_SUITE_COMMANDS),
                "selftest": [
                    "python scripts/selftest.py",
                ],
            },
            contract["required_verifications"],
        )
        self.assertEqual(list(range(10)), [
            item["id"] for item in contract["stages"]])
        self.assertEqual([], validate_contract(ROOT, contract))

    def test_contract_rejects_nonpositive_entrypoint_target(self):
        with open(
                os.path.join(TESTS, "refactor_completion_contract.json"),
                encoding="utf-8") as stream:
            contract = json.load(stream)
        contract["final_targets"]["max_entrypoint_lines"][
            "scripts/mae-flow.py"] = 0
        self.assertIn(
            "scripts/mae-flow.py: final target 0 must be a positive integer",
            validate_contract(ROOT, contract),
        )

    def test_contract_rejects_relaxed_or_missing_final_targets(self):
        contract = load_contract(os.path.join(
            TESTS, "refactor_completion_contract.json"))
        contract["final_targets"]["private_monolith_test_imports"] = 1
        self.assertIn(
            "final_targets must match the approved completion thresholds",
            validate_contract(ROOT, contract),
        )
        del contract["final_targets"]["private_monolith_test_imports"]
        self.assertIn(
            "final_targets must match the approved completion thresholds",
            validate_contract(ROOT, contract),
        )

    def test_contract_rejects_relaxed_or_missing_required_verification(self):
        contract = load_contract(os.path.join(
            TESTS, "refactor_completion_contract.json"))
        contract["required_verifications"]["release_suites"] = []
        self.assertIn(
            "required_verifications must match the approved release gates",
            validate_contract(ROOT, contract),
        )
        del contract["required_verifications"]["release_suites"]
        self.assertIn(
            "required_verifications must match the approved release gates",
            validate_contract(ROOT, contract),
        )

    def test_contract_rejects_baseline_and_actual_both_above_reachability_cap(self):
        root = self._write_reachability_fixture(
            ["module_%02d" % index for index in range(66)],
            ["module_%02d" % index for index in range(66)],
        )
        contract = load_contract(os.path.join(
            TESTS, "refactor_completion_contract.json"))
        errors = validate_contract(root, contract)
        self.assertIn(
            "production reachability baseline count 67 does not match "
            "contract target 66",
            errors,
        )
        self.assertIn(
            "production reachability actual count 67 does not match "
            "contract target 66",
            errors,
        )

    def test_contract_reports_reachability_files_added_and_removed(self):
        root = self._write_reachability_fixture(
            ["module_%02d" % index for index in range(65)],
            ["module_%02d" % index for index in range(64)] + ["added"],
        )
        contract = load_contract(os.path.join(
            TESTS, "refactor_completion_contract.json"))
        errors = validate_contract(root, contract)
        self.assertIn(
            "production reachability added: "
            "scripts/mae_flow_core/added.py",
            errors,
        )
        self.assertIn(
            "production reachability removed: "
            "scripts/mae_flow_core/module_64.py",
            errors,
        )


from differential.coverage import (  # noqa: E402
    load_coverage,
    validate_coverage,
)
from differential.runner import load_goldens  # noqa: E402
from differential.scenarios import SCENARIOS  # noqa: E402


class DifferentialCoverageContractTests(unittest.TestCase):
    def test_registered_scenarios_have_complete_coverage_metadata(self):
        coverage = load_coverage(os.path.join(
            TESTS, "differential", "coverage.json"))
        self.assertEqual(
            [],
            validate_coverage(coverage, set(SCENARIOS)),
        )

    def test_current_golden_covers_every_registered_scenario(self):
        goldens = load_goldens(os.path.join(
            TESTS, "differential", "goldens", "phase15.json"))
        self.assertEqual(set(SCENARIOS), set(goldens))

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

    def test_coverage_rejects_invalid_schema_values_and_extra_fields(self):
        coverage = {
            "schema": 999,
            "extra": True,
            "scenarios": {
                "action_status": {
                    "domain": "quality",
                    "runtime": None,
                    "workflow": "",
                    "transition": "typo",
                    "delivery": [],
                    "fault": "none",
                    "surprise": "ignored",
                }
            },
        }
        errors = validate_coverage(coverage, {"action_status"})
        self.assertIn("coverage schema must be 1", errors)
        self.assertIn("coverage has unknown top-level fields extra", errors)
        self.assertIn("action_status: unknown fields surprise", errors)
        self.assertIn("action_status: invalid runtime None", errors)
        self.assertIn("action_status: invalid workflow ", errors)
        self.assertIn("action_status: invalid transition typo", errors)
        self.assertIn("action_status: invalid delivery []", errors)


if __name__ == "__main__":
    unittest.main()
