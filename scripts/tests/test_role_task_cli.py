#!/usr/bin/env python3
"""role-task CLI 表面回归。"""

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from mae_flow_core.cli_parser import parse_args  # noqa: E402
from mae_flow_core.quality.role_tasks import role_allowed  # noqa: E402


class RoleTaskCliTests(unittest.TestCase):
    def test_parser_accepts_all_roles_and_checkpoint(self):
        for role in (
            "test-design",
            "task-analysis",
            "craft-plan",
            "cp-implement",
            "craft-code",
        ):
            args = parse_args([
                "role-task",
                role,
                "--checkpoint",
                "CP2",
            ])
            self.assertEqual(role, args.role)
            self.assertEqual("CP2", args.checkpoint)

    def test_role_stage_matrix_is_narrow(self):
        self.assertTrue(role_allowed("test-design", "test_blueprint"))
        self.assertTrue(role_allowed("craft-plan", "build_plan"))
        self.assertTrue(role_allowed("cp-implement", "build"))
        self.assertFalse(role_allowed("cp-implement", "build_plan"))
        self.assertFalse(role_allowed("craft-code", "verify_ut"))


if __name__ == "__main__":
    unittest.main()
