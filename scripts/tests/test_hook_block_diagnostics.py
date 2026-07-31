#!/usr/bin/env python3
"""Integration tests for privacy-safe Hook block diagnostics."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DISPATCH = os.path.join(ROOT, "hooks", "dispatch.py")


class HookBlockDiagnosticsTests(unittest.TestCase):
    def _run_pretooluse(self, project, log_dir, command):
        payload = json.dumps({
            "cwd": project,
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }) + "\n"
        env = dict(os.environ)
        env["TMPDIR"] = log_dir
        env["PYTHONPYCACHEPREFIX"] = os.path.join(log_dir, "pycache")
        result = subprocess.run(
            [sys.executable, DISPATCH, "pretooluse"],
            cwd=project,
            input=payload,
            text=True,
            capture_output=True,
            env=env,
            timeout=15,
        )
        log_path = os.path.join(log_dir, "mae-flow-hook.log")
        with open(log_path, encoding="utf-8") as stream:
            return result, stream.read()

    def _init_flow(self, project):
        subprocess.run(
            ["git", "init", "-q", project],
            check=True,
            capture_output=True,
        )
        with open(
                os.path.join(project, ".mae-flow.json"),
                "w",
                encoding="utf-8") as stream:
            json.dump({
                "current": "config_confirm",
                "config": {},
                "choices": {},
                "history": [],
                "started": time.strftime("%Y-%m-%d %H:%M:%S"),
            }, stream)

    def test_blocked_bash_logs_rule_and_hash_without_command(self):
        command = "git add . # secret-token-123"
        with tempfile.TemporaryDirectory() as project:
            with tempfile.TemporaryDirectory() as log_dir:
                self._init_flow(project)
                result, log_text = self._run_pretooluse(
                    project, log_dir, command)

        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn(
            "decision event=pretooluse tool=Bash result=blocked "
            "source=mae-flow rule=bash-wide-add "
            "command_sha256=7d3319b51c438fda9df539ef0b62c134"
            "b3ab1e470147919d2481670df1814379",
            log_text,
        )
        self.assertNotIn(command, log_text)
        self.assertNotIn("secret-token-123", log_text)
        self.assertNotIn("mae-flow-rule=", result.stderr)

    def test_allowed_bash_does_not_log_decision(self):
        with tempfile.TemporaryDirectory() as project:
            with tempfile.TemporaryDirectory() as log_dir:
                self._init_flow(project)
                result, log_text = self._run_pretooluse(
                    project, log_dir, "git status --short")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn(" decision event=pretooluse ", log_text)

    def test_direct_hook_block_uses_stable_fallback_rule(self):
        command = "python nested/dispatch.py # private-fragment"
        with tempfile.TemporaryDirectory() as project:
            with tempfile.TemporaryDirectory() as log_dir:
                subprocess.run(
                    ["git", "init", "-q", project],
                    check=True,
                    capture_output=True,
                )
                action_dir = os.path.join(
                    project, ".mae-flow-work", "standalone", "action-1")
                os.makedirs(action_dir)
                with open(
                        os.path.join(
                            project,
                            ".mae-flow-work",
                            "standalone-action.json",
                        ),
                        "w",
                        encoding="utf-8") as stream:
                    json.dump({
                        "id": "action-1",
                        "kind": "ut",
                        "status": "active",
                        "expires_epoch": time.time() + 3600,
                        "work_dir": action_dir,
                        "config": {},
                        "agent_tasks": {},
                        "tokens": {},
                    }, stream)
                result, log_text = self._run_pretooluse(
                    project, log_dir, command)

        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn(
            "decision event=pretooluse tool=Bash result=blocked "
            "source=mae-flow rule=hook-policy "
            "command_sha256=b151683355a6241f4dbd7230a8514025"
            "3f1ebf6d947ce7e276caa7789eff0b99",
            log_text,
        )
        self.assertNotIn(command, log_text)
        self.assertNotIn("private-fragment", log_text)


if __name__ == "__main__":
    unittest.main()
