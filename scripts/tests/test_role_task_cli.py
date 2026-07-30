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

    def test_survey_neighbor_files_are_frozen_as_context_refs(self):
        with tempfile.TemporaryDirectory() as repository:
            outside = tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                delete=False,
            )
            outside.write("OUTSIDE = True\n")
            outside.close()
            os.makedirs(os.path.join(repository, ".mae-flow-work"))
            os.makedirs(os.path.join(repository, "src"))
            with open(
                    os.path.join(repository, "src", "service.py"),
                    "w",
                    encoding="utf-8",
            ) as stream:
                stream.write("VALUE = 1\n")
            with open(
                    os.path.join(
                        repository,
                        ".mae-flow-work",
                        "survey-REQ-1.md",
                    ),
                    "w",
                    encoding="utf-8",
            ) as stream:
                stream.write(
                    "关键邻近代码：`src/service.py`\n"
                    "禁止扩展：`%s`\n" % outside.name
                )
            previous = os.getcwd()
            try:
                os.chdir(repository)
                refs = role_task_cli._existing_context_paths(
                    {"config": {"单号": "REQ-1"}},
                    (),
                )
            finally:
                os.chdir(previous)
                os.unlink(outside.name)
        body = "\n".join(refs)
        self.assertIn("/src/service.py | SHA256 ", body)
        self.assertIn("/survey-REQ-1.md | SHA256 ", body)
        self.assertNotIn(outside.name, body)


if __name__ == "__main__":
    unittest.main()
