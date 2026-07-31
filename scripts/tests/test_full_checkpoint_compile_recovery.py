#!/usr/bin/env python3
"""End-to-end regressions for staged Full compile evidence recovery."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MAE = os.path.join(ROOT, "scripts", "mae-flow.py")
HOOK = os.path.join(ROOT, "hooks", "dispatch.py")
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from mae_flow_core import cli_runtime as mf  # noqa: E402


with open(
        os.path.join(ROOT, "flow", "flow.json"),
        encoding="utf-8") as stream:
    FLOW = json.load(stream)
mf.FLOW = FLOW


def git(cwd, *arguments):
    return subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


class FullCheckpointCompileRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mae-flow-full-compile-")
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(self.repo, "src"))
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "compile@test.invalid")
        git(self.repo, "config", "user.name", "Compile Recovery Test")
        with open(
                os.path.join(self.repo, ".gitignore"),
                "w", encoding="utf-8") as stream:
            stream.write(".mae-flow*\n")
        with open(
                os.path.join(self.repo, "src", "main.cpp"),
                "w", encoding="utf-8") as stream:
            stream.write("int value = 1;\n")
        git(self.repo, "add", ".gitignore", "src/main.cpp")
        git(self.repo, "commit", "-qm", "base")
        self.base = git(self.repo, "rev-parse", "HEAD")
        self.old_cwd = os.getcwd()
        os.chdir(self.repo)
        self._save_state()
        self._write_source("int value = 2;\n")
        self._issue_compile_task()

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _save_state(self):
        mf.save_state({
            "current": "build",
            "config": {
                "单号": "REQ-COMPILE",
                "单号类型": "fix",
                "CHANGE_NAME": "compile-recovery",
                "编译方式": "build-fix",
            },
            "choices": {"workflow": "full"},
            "history": [{
                "step": "build", "at": "2000-01-01 00:00:00",
            }],
            "started": "2000-01-01 00:00:00",
            "step_heads": {"build": self.base},
            "initial_dirty": [],
            "initial_dirty_fingerprints": {},
            "development_review": {
                "version": 2,
                "status": "active",
                "mode": "staged",
                "review_before_commit": True,
                "code_reviewer": "disabled",
                "delivery_base": self.base,
                "current_index": 0,
                "task_structure_sha256": "",
                "checkpoints": [{
                    "id": "CP1",
                    "title": "small C++ change",
                    "status": "coding",
                    "fixed_base": self.base,
                }],
            },
        })

    def _write_source(self, value):
        with open(
                os.path.join(self.repo, "src", "main.cpp"),
                "w", encoding="utf-8") as stream:
            stream.write(value)

    def _issue_compile_task(self):
        state = mf.load_state()
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_agent_task(
                FLOW,
                state,
                types.SimpleNamespace(
                    kind="compile",
                    scope="CP1 C++ change",
                    checkpoint="CP1",
                ),
            )
        self.task = mf.load_state()["agent_tasks"]["COMPILE"]
        self.assertTrue(self.task["precommit_review"])

    def _write_transcript(self):
        path = os.path.join(
            self.repo, ".mae-flow-work", "compile-transcript.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        rows = [
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{
                        "type": "tool_use",
                        "id": "build-call",
                        "name": "Skill",
                        "input": {"skill": "build-fix"},
                    }],
                },
            },
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": "build-call",
                        "is_error": False,
                        "content": "opaque internal result",
                    }],
                },
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": (
                        "COMPILE_RESULT: OK\n"
                        "TASK_CARD_SHA256: " + self.task["sha256"]
                    ),
                },
            },
        ]
        with open(path, "w", encoding="utf-8", newline="\n") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        return path

    def _run_hook(self):
        payload = json.dumps({
            "cwd": self.repo,
            "agent_transcript_path": self._write_transcript(),
        }, ensure_ascii=False) + "\n"
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, HOOK, "subagentstop"],
            cwd=self.repo,
            input=payload,
            text=True,
            capture_output=True,
            env=env,
            timeout=20,
        )

    def _ready(self):
        state = mf.load_state()
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_checkpoint_ready(
                FLOW,
                state,
                types.SimpleNamespace(checkpoint_id="CP1"),
            )
        return mf.load_state()

    def _authorize_risk(self):
        with open(
                mf.STATE_PATH + ".usermsg",
                "w", encoding="utf-8") as stream:
            json.dump([{
                "id": "compile-risk",
                "at": "9999-12-31 23:59:59",
                "step": "build",
                "text": "确认承担本检查点的编译风险",
            }], stream, ensure_ascii=False)
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_accept_risk(
                FLOW,
                mf.load_state(),
                types.SimpleNamespace(
                    agent="compile",
                    reason="内部编译环境暂不可用",
                    message_id="compile-risk",
                ),
            )

    def test_minimal_build_fix_report_issues_token_and_reaches_review(self):
        hook = self._run_hook()
        self.assertEqual(0, hook.returncode, hook.stdout + hook.stderr)
        with open(mf.STATE_PATH + ".tokens", encoding="utf-8") as stream:
            token = json.load(stream)["COMPILE"]
        self.assertEqual("OK", token["status"])
        self.assertIn("src/main.cpp", token["source_snapshot"])

        state = self._ready()

        item = state["development_review"]["checkpoints"][0]
        self.assertEqual("review_pending", item["status"])
        self.assertEqual(self.base, git(self.repo, "rev-parse", "HEAD"))

    def test_compile_token_rejects_a_later_source_edit(self):
        hook = self._run_hook()
        self.assertEqual(0, hook.returncode, hook.stdout + hook.stderr)
        self._write_source("int value = 3;\n")

        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as rejected:
                self._ready()

        self.assertEqual(2, rejected.exception.code)

    def test_snapshot_risk_reaches_review_without_compile_transcript(self):
        self._authorize_risk()

        state = self._ready()

        self.assertEqual(
            "review_pending",
            state["development_review"]["checkpoints"][0]["status"],
        )

    def test_snapshot_risk_rejects_a_later_source_edit(self):
        self._authorize_risk()
        self._write_source("int value = 4;\n")

        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as rejected:
                self._ready()

        self.assertEqual(2, rejected.exception.code)


if __name__ == "__main__":
    unittest.main()
