#!/usr/bin/env python3
"""Thin role-task surface regressions."""

import contextlib
import io
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
    def test_only_review_story_and_grill_roles_exist(self):
        for role in ("code-review", "story-generate", "story-review"):
            self.assertEqual(role, parse_args(["role-task", role]).role)
        args = parse_args([
            "role-task", "grill-critic", "--stage", "prep",
            "--document", ".mae-flow-work/REQ-1/grill.md",
        ])
        self.assertEqual("prep", args.stage)
        self.assertFalse(hasattr(args, "checkpoint"))

    def test_role_stage_matrix_has_no_implementation_or_batch_roles(self):
        self.assertTrue(role_allowed("code-review", "build_agent_review"))
        self.assertTrue(role_allowed("story-generate", "story"))
        self.assertTrue(role_allowed("story-review", "story"))
        self.assertTrue(role_allowed("grill-critic", "grill"))
        for role in ("implement", "cp-implement", "task-analysis", "craft-plan"):
            self.assertFalse(role_allowed(role, "build"))

    def test_code_review_card_contains_whole_uncommitted_change(self):
        with tempfile.TemporaryDirectory() as repository:
            subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
            subprocess.run(["git", "config", "user.email", "role@test.invalid"], cwd=repository, check=True)
            subprocess.run(["git", "config", "user.name", "Role Test"], cwd=repository, check=True)
            os.makedirs(os.path.join(repository, ".mae-flow-work", "REQ-1"))
            tracked = os.path.join(repository, "service.py")
            with open(tracked, "w", encoding="utf-8") as stream:
                stream.write("VALUE = 1\n")
            subprocess.run(["git", "add", "service.py"], cwd=repository, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=repository, check=True)
            base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip()
            with open(tracked, "w", encoding="utf-8") as stream:
                stream.write("VALUE = 2\n")
            with open(os.path.join(repository, "new.py"), "w", encoding="utf-8") as stream:
                stream.write("NEW = True\n")
            package = role_task_cli.ensure_work_package(repository, "REQ-1")
            for path in (package.spec, package.story):
                with open(path, "w", encoding="utf-8") as stream:
                    stream.write("confirmed\n")
            state = {
                "current": "build_agent_review",
                "config": {"单号": "REQ-1"},
                "implementation_base_head": base,
            }
            previous = os.getcwd()
            try:
                os.chdir(repository)
                with contextlib.redirect_stdout(io.StringIO()):
                    role_task_cli.cmd_role_task(
                        {}, state, parse_args(["role-task", "code-review"]))
            finally:
                os.chdir(previous)
            with open(
                    state["agent_tasks"]["REVIEWER"]["path"],
                    encoding="utf-8") as stream:
                body = stream.read()
            self.assertIn("-VALUE = 1", body)
            self.assertIn("+VALUE = 2", body)
            self.assertIn("### 未跟踪文件: new.py", body)
            self.assertIn(os.path.abspath(package.spec), body)
            self.assertIn(os.path.abspath(package.story), body)


if __name__ == "__main__":
    unittest.main()
