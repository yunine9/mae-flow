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
from mae_flow_core.workflow.agent_observations import (  # noqa: E402
    record_agent_finished, record_agent_started,
)
from mae_flow_core.workflow.quality_executions import (  # noqa: E402
    quality_input_snapshot, record_quality_execution,
)


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

    def _record_success(self):
        state = mf.load_state()
        invocation = "compile-run"
        record_agent_started(
            mf.STATE_PATH, "COMPILE", "build", invocation,
            "9999-12-31 23:59:57")
        record_agent_finished(
            mf.STATE_PATH, invocation, "returned",
            "9999-12-31 23:59:58", "任意自然语言返回")
        record_quality_execution(
            mf.STATE_PATH, "COMPILE", "build", invocation, "build-fix",
            True, quality_input_snapshot(state, "COMPILE", "build"),
            "9999-12-31 23:59:58")

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

    def test_lifecycle_and_real_execution_reach_review_without_token(self):
        self._record_success()
        with open(mf.STATE_PATH + ".tokens", encoding="utf-8") as stream:
            self.assertNotIn("COMPILE", json.load(stream))

        state = self._ready()

        item = state["development_review"]["checkpoints"][0]
        self.assertEqual("review_pending", item["status"])
        self.assertEqual(self.base, git(self.repo, "rev-parse", "HEAD"))

    def test_reissued_compile_task_requires_a_new_real_execution(self):
        self._record_success()
        self._write_source("int value = 3;\n")
        self._issue_compile_task()

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
