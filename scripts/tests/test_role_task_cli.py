#!/usr/bin/env python3
"""role-task CLI 表面回归。"""

import os
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from mae_flow_core.cli_parser import parse_args  # noqa: E402
from mae_flow_core import cli_runtime as mf  # noqa: E402,F401
from mae_flow_core.cli_commands import role_task as role_task_cli  # noqa: E402
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

    def test_staged_code_review_receives_tracked_and_untracked_content(self):
        with tempfile.TemporaryDirectory() as repository:
            subprocess.run(
                ["git", "init", "-q"], cwd=repository, check=True)
            subprocess.run(
                ["git", "config", "user.email", "role@test.invalid"],
                cwd=repository,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Role Test"],
                cwd=repository,
                check=True,
            )
            os.makedirs(os.path.join(repository, "src"))
            tracked = os.path.join(repository, "src", "service.py")
            with open(tracked, "w", encoding="utf-8") as stream:
                stream.write("VALUE = 1\n")
            subprocess.run(
                ["git", "add", "src/service.py"],
                cwd=repository,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "-qm", "base"],
                cwd=repository,
                check=True,
            )
            with open(tracked, "w", encoding="utf-8") as stream:
                stream.write("VALUE = 2\n")
            with open(
                    os.path.join(repository, "src", "new.py"),
                    "w",
                    encoding="utf-8",
            ) as stream:
                stream.write("NEW = True\n")
            state = {
                "development_review": {
                    "version": 2,
                    "current_index": 0,
                    "checkpoints": [{
                        "id": "CP1",
                        "receipt": {"snapshot": {
                            "src/service.py": "tracked",
                            "src/new.py": "untracked",
                        }},
                    }],
                },
            }
            previous = os.getcwd()
            try:
                os.chdir(repository)
                body = role_task_cli._role_diff(
                    state,
                    "craft-code",
                    ("src/service.py", "src/new.py"),
                )
            finally:
                os.chdir(previous)
        self.assertIn("-VALUE = 1", body)
        self.assertIn("+VALUE = 2", body)
        self.assertIn("### 未跟踪文件: src/new.py", body)
        self.assertIn("NEW = True", body)


if __name__ == "__main__":
    unittest.main()
