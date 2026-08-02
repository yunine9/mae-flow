#!/usr/bin/env python3
"""Migration-only integrity checks for retained capability reference sources."""

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest


SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROOT = os.path.abspath(os.path.join(SCRIPTS, ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.capability_codecheck import _tree_sha256  # noqa: E402
from mae_flow_core.capability_packs import render_pack  # noqa: E402
from mae_flow_core.capability_shared import (  # noqa: E402
    CAPABILITY_PACKS,
    MANIFEST_PATH,
    VENDOR_ROOT,
)
from mae_flow_core.runtime import find_project_root  # noqa: E402


EXPECTED_RETIRED_TEST_SOURCES = {
    "scripts/tests/test_spec2code_artifacts.py",
    "scripts/tests/test_spec2code_artifact_use_cases.py",
    "scripts/tests/test_quality_artifact_cli.py",
    "scripts/tests/test_spec2code_workflow.py",
    "scripts/tests/test_role_task_documents.py",
    "scripts/tests/test_role_task_cli.py",
    "scripts/tests/test_checkpoint_quality.py",
    "scripts/tests/test_spec2code_recovery.py",
    "scripts/tests/test_spec2code_quality_flow.py",
    "scripts/tests/test_state_core.py",
    "scripts/tests/test_confirmation_receipts.py",
    "scripts/tests/test_specengine.py",
    "scripts/tests/test_checkpoints.py",
    "scripts/tests/test_full_checkpoint_compile_recovery.py",
    "scripts/tests/test_compile_wait_instructions.py",
    "scripts/tests/test_commit_ownership.py",
    "scripts/tests/test_codecheck_logging.py",
    "scripts/tests/test_task_scope.py",
    "scripts/tests/test_workflow_definition.py",
    "scripts/tests/test_workflow_advancement.py",
    "scripts/tests/test_workflow_completion.py",
    "scripts/tests/test_guard_intent.py",
    "scripts/tests/test_guard_gate.py",
    "scripts/tests/test_guard_permits.py",
    "scripts/tests/test_guard_ownership.py",
    "scripts/tests/test_guard_bash.py",
    "scripts/tests/test_guard_permit_integration.py",
    "scripts/tests/test_quality_task_cards.py",
    "scripts/tests/test_quality_task_card_use_cases.py",
    "scripts/tests/test_quality_codecheck.py",
    "scripts/tests/test_quality_codecheck_use_cases.py",
    "scripts/tests/test_quality_codecheck_state.py",
    "scripts/tests/test_delivery_policies.py",
    "scripts/tests/test_command_dispatch.py",
    "scripts/tests/test_cli_runtime_facade.py",
    "scripts/tests/test_differential_harness.py",
    "scripts/tests/differential/runner.py",
    "scripts/tests/test_evidence.py",
    "scripts/tests/test_evidence_rules.py",
    "scripts/tests/test_agent_evidence.py",
    "scripts/tests/test_delivery_evidence.py",
    "scripts/tests/test_delivery_models.py",
    "scripts/tests/test_delivery_checkpoint_use_cases.py",
    "scripts/tests/test_delivery_checkpoint_decisions.py",
    "scripts/tests/test_delivery_checkpoint_final.py",
    "scripts/tests/test_delivery_checkpoint_status.py",
    "scripts/tests/test_delivery_checkpoint_recovery.py",
    "scripts/tests/test_delivery_standalone_use_cases.py",
    "scripts/tests/test_delivery_moonlight_use_cases.py",
    "scripts/tests/test_quality_evidence.py",
    "scripts/tests/test_hook_tool_transcript.py",
    "scripts/tests/test_hook_agent_reports.py",
    "scripts/tests/test_hook_task_card_contracts.py",
    "scripts/tests/test_hook_receipts.py",
    "scripts/tests/test_hook_compile_contract.py",
    "scripts/tests/test_hook_grill_contract.py",
    "scripts/tests/test_hook_codecheck_contract.py",
    "scripts/tests/test_hook_unit_test_contract.py",
    "scripts/tests/test_hook_agent_completion.py",
    "scripts/tests/test_hook_events.py",
    "scripts/tests/test_compile_side_effects.py",
    "scripts/tests/test_delivery_checkpoint_navigation.py",
    "scripts/tests/test_hook_block_diagnostics.py",
    "scripts/tests/test_hook_protocol.py:HookProtocolTests."
    "test_missing_maeflow_script_fails_open",
    "scripts/tests/test_lightcheck.py:LightCheckTests."
    "test_existing_violation_without_regression_is_only_logged",
    "scripts/tests/test_refactor_completion.py:"
    "DifferentialCoverageContractTests."
    "test_registered_scenarios_have_complete_coverage_metadata",
    "scripts/tests/test_refactor_completion.py:"
    "DifferentialCoverageContractTests."
    "test_current_golden_covers_every_registered_scenario",
    "scripts/tests/test_refactor_completion.py:"
    "DifferentialCoverageContractTests."
    "test_coverage_rejects_unknown_domain_and_missing_scenario",
    "scripts/tests/test_refactor_completion.py:"
    "DifferentialCoverageContractTests."
    "test_coverage_rejects_invalid_schema_values_and_extra_fields",
    "scripts/tests/test_capabilities.py:EmbeddedCapabilityTests."
    "test_vendor_tree_hash_ignores_python_bytecode_cache",
    "scripts/tests/test_capabilities.py:EmbeddedCapabilityTests."
    "test_all_phase_packs_are_pinned_and_host_safe",
    "scripts/tests/test_capabilities.py:EmbeddedCapabilityTests."
    "test_full_spec_lifecycle_in_unicode_path",
    "scripts/tests/test_capabilities.py:EmbeddedCapabilityTests."
    "test_legacy_layout_change_still_flows",
    "scripts/tests/test_capabilities.py:EmbeddedCapabilityTests."
    "test_prepare_project_contract_and_untouched_project",
    "scripts/tests/test_capabilities.py:EmbeddedCapabilityTests."
    "test_prepare_and_diagnostics_survive_missing_node",
    "scripts/tests/test_capabilities.py:EmbeddedCapabilityTests."
    "test_host_runtime_diagnostics_show_versions_and_paths",
    "scripts/tests/test_capabilities.py:EmbeddedCapabilityTests."
    "test_windows_plugin_path_is_literal_in_embedded_commands",
    "scripts/tests/test_capabilities.py:EmbeddedCapabilityTests."
    "test_prepare_accepts_git_worktree_dot_git_file",
    "scripts/tests/test_capabilities.py:EmbeddedCapabilityTests."
    "test_missing_host_dependency_fails_before_project_files_are_written",
    "scripts/tests/test_capabilities.py:EmbeddedCapabilityTests."
    "test_codecheck_install_is_one_shot_and_does_not_mutate_npm_config",
    "scripts/tests/test_capabilities.py:EmbeddedCapabilityTests."
    "test_windows_cmd_launch_uses_pathex_compatible_shell",
    "scripts/tests/test_capabilities.py:EmbeddedCapabilityTests."
    "test_windows_runtime_discovers_git_bash_and_node_off_path",
    "scripts/tests/test_file_io.py:ManagedFileIOTests."
    "test_checkpoint_runtime_emits_no_resource_warnings",
}


def semantic_test_ids():
    result = set()
    tests = os.path.join(ROOT, "scripts", "tests")
    for directory, unused_names, filenames in os.walk(tests):
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
                    if (isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and method.name.startswith("test_")):
                        result.add(
                            "%s:%s.%s" % (
                                relative, node.name, method.name))
    return result


class ReferenceCapabilitySourceTests(unittest.TestCase):
    def manifest(self):
        with open(MANIFEST_PATH, encoding="utf-8") as stream:
            return json.load(stream)

    def test_vendored_sources_match_pinned_integrity_manifest(self):
        manifest = self.manifest()
        self.assertEqual(1, manifest["schema"])
        self.assertEqual(
            {"comet", "openspec", "superpowers", "ponytail", "lizard"},
            set(manifest["components"]),
        )
        for name, metadata in sorted(manifest["components"].items()):
            with self.subTest(component=name):
                root = os.path.join(VENDOR_ROOT, name)
                self.assertTrue(os.path.isdir(root), root)
                self.assertEqual(metadata["sha256"], _tree_sha256(root))
                license_path = os.path.join(ROOT, metadata["license"])
                self.assertTrue(os.path.isfile(license_path), license_path)

    def test_vendored_tree_hash_ignores_python_bytecode_cache(self):
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "analyzer.py")
            with open(source, "w", encoding="utf-8") as stream:
                stream.write("VALUE = 1\n")
            expected = _tree_sha256(root)
            cache = os.path.join(root, "__pycache__")
            os.makedirs(cache)
            with open(
                    os.path.join(cache, "analyzer.cpython-313.pyc"),
                    "w", encoding="utf-8") as stream:
                stream.write("runtime cache")
            with open(
                    os.path.join(root, "legacy.pyc"),
                    "w", encoding="utf-8") as stream:
                stream.write("legacy runtime cache")
            self.assertEqual(expected, _tree_sha256(root))
            with open(source, "w", encoding="utf-8") as stream:
                stream.write("VALUE = 2\n")
            self.assertNotEqual(expected, _tree_sha256(root))

    def test_lean_root_discovery_accepts_git_worktree_dot_git_file(self):
        with tempfile.TemporaryDirectory() as base:
            root = os.path.join(base, "worktree")
            nested = os.path.join(root, "src", "feature")
            os.makedirs(nested)
            with open(
                    os.path.join(root, ".git"),
                    "w", encoding="utf-8") as stream:
                stream.write("gitdir: ../main/.git/worktrees/feature\n")
            self.assertEqual(root, find_project_root(nested))

    def test_reference_prompt_pack_sources_remain_readable(self):
        self.assertTrue(CAPABILITY_PACKS)
        for pack, entries in sorted(CAPABILITY_PACKS.items()):
            with self.subTest(pack=pack):
                self.assertTrue(entries)
                rendered = render_pack(pack)
                self.assertIn("内嵌能力", rendered)
                for entry in entries:
                    relative = entry[1]
                    self.assertTrue(os.path.isfile(os.path.join(
                        VENDOR_ROOT, *relative.split("/"))))

    def test_reference_manifest_declares_native_runtime_cutover(self):
        runtime = self.manifest()["runtime_guidance"]
        self.assertFalse(runtime["loads_vendor_prompt_text"])
        self.assertEqual(
            "scripts/mae_flow_core/orchestration/native_guidance.py",
            runtime["loader"],
        )
        self.assertEqual(
            "runtime/guidance/capability-preservation.json",
            runtime["preservation"],
        )

    def test_production_cli_rejects_retired_capability_lifecycle(self):
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "mae-flow.py"),
             "capability", "status"],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("invalid choice", result.stderr)

    def test_every_retired_suite_and_method_has_an_itemized_classification(self):
        with open(
                os.path.join(
                    ROOT, "runtime", "guidance",
                    "capability-preservation.json"),
                encoding="utf-8") as stream:
            preservation = json.load(stream)
        inventory = preservation.get("retired_test_inventory", [])
        sources = [item.get("source") for item in inventory]
        self.assertEqual(EXPECTED_RETIRED_TEST_SOURCES, set(sources))
        self.assertEqual(len(sources), len(set(sources)))
        valid_ids = semantic_test_ids()
        for item in inventory:
            with self.subTest(source=item.get("source")):
                self.assertIn(item.get("classification"), {
                    "preserved behavior", "thin replacement",
                    "intentionally removed friction", "migration-only",
                })
                self.assertGreaterEqual(len(item.get("reason", "")), 20)
                replacements = item.get("replacement_semantic_tests", [])
                self.assertTrue(replacements)
                self.assertEqual([], sorted(
                    identifier for identifier in replacements
                    if identifier not in valid_ids))

    def test_unittest_discovery_contains_only_current_release_tests(self):
        from selftest_suites import REFACTOR_SAFETY_SUITES

        registered = {
            command[0]
            for unused_label, command, unused_timeout, unused_limit
            in REFACTOR_SAFETY_SUITES
        }
        raw_only_current = {
            "scripts/tests/test_capability_observation.py",
            "scripts/tests/test_codecheck_advisory.py",
            "scripts/tests/test_delivery_receipt.py",
            "scripts/tests/test_quality_selection.py",
            "scripts/tests/test_ut_handoff.py",
        }
        expected = registered | raw_only_current
        actual = {
            "scripts/tests/" + filename
            for filename in os.listdir(os.path.join(ROOT, "scripts", "tests"))
            if filename.startswith("test_") and filename.endswith(".py")
        }

        self.assertEqual(32, len(expected))
        self.assertEqual(expected, actual)
        self.assertTrue(os.path.isfile(os.path.join(
            ROOT, "scripts", "tests", "reference_specengine_diagnostic.py")))
        self.assertFalse(os.path.exists(os.path.join(
            ROOT, "scripts", "tests", "test_specengine.py")))

    def test_real_hook_protocol_is_classified_as_preserved_behavior(self):
        with open(
                os.path.join(
                    ROOT, "runtime", "guidance",
                    "capability-preservation.json"),
                encoding="utf-8") as stream:
            preservation = json.load(stream)
        classifications = [
            item["classification"]
            for item in preservation["retirement_test_classification"]
            if "scripts/tests/test_hook_protocol.py"
            in item.get("test_sources", [])
        ]
        self.assertEqual(["preserved behavior"], classifications)

    def test_platform_retirements_map_to_behaviorally_exact_successors(self):
        with open(
                os.path.join(
                    ROOT, "runtime", "guidance",
                    "capability-preservation.json"),
                encoding="utf-8") as stream:
            preservation = json.load(stream)
        by_source = {
            item["source"]: item["replacement_semantic_tests"]
            for item in preservation["retired_test_inventory"]
        }
        self.assertEqual([
            "scripts/tests/test_capabilities.py:"
            "ReferenceCapabilitySourceTests."
            "test_vendored_tree_hash_ignores_python_bytecode_cache",
        ], by_source[
            "scripts/tests/test_capabilities.py:EmbeddedCapabilityTests."
            "test_vendor_tree_hash_ignores_python_bytecode_cache"])
        self.assertEqual([
            "scripts/tests/test_capabilities.py:"
            "ReferenceCapabilitySourceTests."
            "test_lean_root_discovery_accepts_git_worktree_dot_git_file",
        ], by_source[
            "scripts/tests/test_capabilities.py:EmbeddedCapabilityTests."
            "test_prepare_accepts_git_worktree_dot_git_file"])

    def test_historic_method_differences_have_exact_current_successors(self):
        with open(
                os.path.join(
                    ROOT, "runtime", "guidance",
                    "capability-preservation.json"),
                encoding="utf-8") as stream:
            preservation = json.load(stream)
        by_source = {
            item["source"]: item["replacement_semantic_tests"]
            for item in preservation["retired_test_inventory"]
        }
        self.assertEqual([
            "scripts/tests/test_hook_protocol.py:HookProtocolTests."
            "test_unexpected_top_level_exception_fails_open",
        ], by_source[
            "scripts/tests/test_hook_protocol.py:HookProtocolTests."
            "test_missing_maeflow_script_fails_open"])
        self.assertEqual([
            "scripts/tests/test_lightcheck.py:LightCheckTests."
            "test_touched_preexisting_threshold_violation_is_reported",
            "scripts/tests/test_lightcheck.py:LightCheckTests."
            "test_cli_reports_findings_but_returns_success",
        ], by_source[
            "scripts/tests/test_lightcheck.py:LightCheckTests."
            "test_existing_violation_without_regression_is_only_logged"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
