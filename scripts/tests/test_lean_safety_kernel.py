#!/usr/bin/env python3
"""Fixture-level contract for the future lean safety-kernel public API.

This deliberately validates only the JSON characterization.  Runtime kernel
imports begin in the later implementation task, once that API exists.
"""

import json
import os
import unittest


FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "lean_git_cases.json"
)


EXPECTED_CASES = {
    "blocked_recursive_delete_outside_task_temp": ("filesystem", False),
    "blocked_git_reset_hard": ("git_destructive", False),
    "blocked_git_add_dot": ("git_staging", False),
    "blocked_git_add_all": ("git_staging", False),
    "blocked_git_add_directory_pathspec": ("git_staging", False),
    "blocked_git_commit_all": ("git_commit", False),
    "blocked_git_commit_without_authorized_manifest": ("git_commit", False),
    "blocked_git_push_without_authorized_manifest": ("git_publish", False),
    "blocked_protected_mae_flow_control_edit": ("protected_control", False),
    "blocked_source_edit_before_confirmation": ("source_edit", False),
    "blocked_preexisting_dirty_file_smuggling": ("git_staging", False),
    "allowed_authorized_source_edit": ("source_edit", True),
    "allowed_exact_file_git_add": ("git_staging", True),
    "allowed_read_only_git": ("git_read_only", True),
    "allowed_build_command": ("build", True),
    "allowed_user_owned_dirty_file_untouched": ("source_edit", True),
    "allowed_malformed_non_dangerous_command": ("malformed_non_dangerous", True),
    "allowed_immediate_exit": ("immediate_exit", True),
}


class LeanSafetyKernelFixtureTest(unittest.TestCase):
    def setUp(self):
        with open(FIXTURE_PATH, "r", encoding="utf-8") as fixture_file:
            self.fixture = json.load(fixture_file)

    def test_fixture_has_the_versioned_public_api_input_shape(self):
        self.assertEqual(1, self.fixture["schema_version"])
        self.assertEqual(
            [
                "case",
                "operation_family",
                "command",
                "context",
                "expected",
            ],
            self.fixture["case_fields"],
        )
        self.assertIsInstance(self.fixture["cases"], list)

        for item in self.fixture["cases"]:
            self.assertEqual(self.fixture["case_fields"], list(item.keys()))
            self.assertIsInstance(item["case"], str)
            self.assertIsInstance(item["operation_family"], str)
            self.assertIsInstance(item["command"]["argv"], list)
            self.assertTrue(item["command"]["argv"])
            self.assertIsInstance(item["context"]["working_directory"], str)
            self.assertIsInstance(item["context"]["task_owned_temp_dir"], str)
            self.assertIsInstance(item["context"]["source_edit_confirmed"], bool)
            self.assertIsInstance(item["context"]["authorized_manifest"], dict)
            self.assertIsInstance(item["context"]["preexisting_dirty_files"], list)
            self.assertIsInstance(item["expected"]["allowed"], bool)

    def test_fixture_characterizes_the_complete_narrow_safety_boundary(self):
        actual_cases = {
            item["case"]: (item["operation_family"], item["expected"]["allowed"])
            for item in self.fixture["cases"]
        }
        self.assertEqual(EXPECTED_CASES, actual_cases)


if __name__ == "__main__":
    unittest.main()
