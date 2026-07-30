#!/usr/bin/env python3
"""Tests for the pure COMPILE Agent contract."""

import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.quality.agent_contracts import (  # noqa: E402
    AgentContractContext,
)
from mae_flow_core.quality.compile_contract import (  # noqa: E402
    evaluate_compile_contract,
)
from mae_flow_core.quality.tool_transcript import ToolCall  # noqa: E402
from mae_flow_core import save_versioned_json  # noqa: E402
from mae_flow_core.adapters.hook_runtime import HookRuntimeAdapter  # noqa: E402


def call(name, value, result="", seen=True, error=False):
    return ToolCall(
        call_id="fixture",
        name=name,
        input=value,
        result_seen=seen,
        is_error=error,
        result=result,
    )


@contextlib.contextmanager
def in_directory(path):
    original = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(original)


def initialize_repository(root):
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "mae-flow@test.invalid"],
        cwd=root, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Mae Flow Test"],
        cwd=root, check=True,
    )
    with open(os.path.join(root, ".gitignore"), "w", encoding="utf-8") as stream:
        stream.write(".mae-flow*\n")
    config_path = os.path.join(root, "config", "runtime.json")
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as stream:
        stream.write('{"runtime": "before"}\n')
    subprocess.run(
        ["git", "add", ".gitignore", "config/runtime.json"],
        cwd=root, check=True,
    )
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def runtime_for(root, logs=None):
    return HookRuntimeAdapter(
        state=os.path.join(root, ".mae-flow.json"),
        exit_state=os.path.join(root, ".mae-flow.json.exited"),
        action_state=os.path.join(root, ".mae-flow-work", "action.json"),
        rejection_state=os.path.join(root, ".mae-flow.json.agent-rejections"),
        evidence_state=os.path.join(root, ".mae-flow.json.agent-evidence"),
        agent_writes_state=os.path.join(root, ".mae-flow.json.agent-writes"),
        moonlight_intent=os.path.join(root, ".mae-flow.json.moonlight-intent"),
        exit_intent=os.path.join(root, ".mae-flow.json.exit-intent"),
        maeflow=os.path.join(ROOT, "scripts", "mae-flow.py"),
        log=logs.append if logs is not None else lambda _message: None,
    )


def compile_task(root, head, worktree_snapshot):
    body = "# COMPILE fixture task\n"
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    task_path = os.path.join(root, ".mae-flow-work", "compile-task.md")
    os.makedirs(os.path.dirname(task_path), exist_ok=True)
    with open(task_path, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(body)
        stream.write("TASK_CARD_SHA256: %s\n" % digest)
    return {
        "step": "tw_compile",
        "path": task_path,
        "sha256": digest,
        "head": head,
        "worktree_snapshot": worktree_snapshot,
    }


def save_compile_state(root, task):
    save_versioned_json(
        os.path.join(root, ".mae-flow.json"),
        {
            "current": "tw_compile",
            "config": {"编译方式": "python build.py"},
            "choices": {},
            "history": [],
            "started": "2026-07-30 10:00:00",
            "agent_tasks": {"COMPILE": task},
        },
        "flow",
        project_root=root,
    )


def accepted_report(task):
    return (
        "COMPILE_RESULT: OK\n"
        "TASK_CARD_SHA256: %s\n"
        "EXECUTED_BUILD: python build.py\n"
        "BUILD_ERRORS: 0"
        % task["sha256"]
    )


class CompileContractTests(unittest.TestCase):
    def context(self, report, calls=(), status="OK", net=0, build=None):
        return AgentContractContext(
            kind="COMPILE",
            status=status,
            report=report,
            task={"step": "tw_compile"},
            config={"编译方式": build or "python build.py"},
            calls=tuple(calls),
            changed_paths=(),
            compile_net=net,
        )

    def test_ok_requires_the_configured_successful_build_call(self):
        report = "EXECUTED_BUILD: python build.py\nBUILD_ERRORS: 0"
        accepted = evaluate_compile_contract(self.context(
            report,
            [call(
                "Bash",
                {"command": "python build.py"},
                "build complete\nexit code: 0",
            )],
        ))
        self.assertTrue(accepted.accepted)

        missing = evaluate_compile_contract(self.context(report))
        self.assertFalse(missing.accepted)
        self.assertIn("没有真实执行配置的编译命令", missing.reason)

    def test_ok_rejects_failed_tool_and_nonzero_error_count(self):
        report = "EXECUTED_BUILD: python build.py\nBUILD_ERRORS: 0"
        failed = evaluate_compile_contract(self.context(
            report,
            [call(
                "Bash",
                {"command": "python build.py"},
                "process exited with code 2",
            )],
        ))
        self.assertIn("工具结果明确失败", failed.reason)

        contradictory = evaluate_compile_contract(self.context(
            "EXECUTED_BUILD: python build.py\nBUILD_ERRORS: 3",
            [call("Bash", {"command": "python build.py"}, "done")],
        ))
        self.assertEqual(
            "标记 OK 但 BUILD_ERRORS=3,自相矛盾。",
            contradictory.reason,
        )

    def test_blocked_accepts_a_real_failed_attempt_with_errors(self):
        decision = evaluate_compile_contract(self.context(
            "EXECUTED_BUILD: python build.py\nBUILD_ERRORS: 2",
            [call(
                "Bash",
                {"command": "python build.py"},
                "process exited with code 2",
            )],
            status="BLOCKED",
        ))
        self.assertTrue(decision.accepted)

    def test_skill_build_uses_the_last_matching_tool_result(self):
        decision = evaluate_compile_contract(self.context(
            "EXECUTED_BUILD: build-fix / mcde build -i\nBUILD_ERRORS: 0",
            [
                call(
                    "Skill",
                    {"skill": "build-fix"},
                    "first failed",
                    error=True,
                ),
                call(
                    "Skill",
                    {"skill": "build-fix"},
                    "fixed",
                ),
            ],
            build="build-fix",
        ))
        self.assertTrue(decision.accepted)

    def test_net_deletion_requires_a_nonempty_shrink_exemption(self):
        base = (
            "EXECUTED_BUILD: python build.py\n"
            "BUILD_ERRORS: 0\n"
        )
        calls = [call("Bash", {"command": "python build.py"}, "done")]
        rejected = evaluate_compile_contract(
            self.context(base, calls, net=-4))
        self.assertIn("代码净删 4 行", rejected.reason)

        accepted = evaluate_compile_contract(self.context(
            base + "SHRINK_EXEMPT:\nremoved duplicate wrapper\n",
            calls,
            net=-4,
        ))
        self.assertTrue(accepted.accepted)

    def test_honest_fail_does_not_require_execution_fields(self):
        decision = evaluate_compile_contract(self.context(
            "compiler unavailable",
            status="FAIL",
        ))
        self.assertTrue(decision.accepted)

    def test_accepted_compile_records_only_non_direct_worktree_effects(self):
        with tempfile.TemporaryDirectory() as td, in_directory(td):
            head = initialize_repository(td)
            runtime = runtime_for(td)
            baseline = runtime._worktree_snapshot(head)
            task = compile_task(td, head, baseline)
            save_compile_state(td, task)
            generated = os.path.join(td, "generated", "build.properties")
            os.makedirs(os.path.dirname(generated), exist_ok=True)
            with open(generated, "w", encoding="utf-8") as stream:
                stream.write("compiled=true\n")
            with open(
                    os.path.join(td, "config", "runtime.json"),
                    "w", encoding="utf-8") as stream:
                stream.write('{"runtime": "after"}\n')
            with open(
                    os.path.join(td, ".mae-flow.json.agent-writes"),
                    "w", encoding="utf-8") as stream:
                json.dump(
                    {"paths": {"legacy/write.cpp": {"tool": "file-write"}}},
                    stream,
                )

            runtime._compile_contract(
                "OK",
                accepted_report(task),
                [
                    {
                        "name": "Bash",
                        "input": {"command": "python build.py"},
                        "result_seen": True,
                        "result": "build complete\nexit code: 0",
                    },
                    {
                        "name": "Edit",
                        "input": {"file_path": "config/runtime.json"},
                        "result_seen": True,
                        "result": "updated runtime",
                    },
                ],
            )

            with open(
                    os.path.join(td, ".mae-flow.json.agent-writes"),
                    encoding="utf-8") as stream:
                ledger = json.load(stream)
            self.assertEqual(["generated/build.properties"], sorted(
                ledger["compile_side_effects"]))
            self.assertEqual(
                task["sha256"],
                ledger["compile_side_effects"]
                ["generated/build.properties"]["task_sha256"],
            )
            self.assertIn("legacy/write.cpp", ledger["paths"])

            runtime._record_agent_write("generated/build.properties")
            with open(
                    os.path.join(td, ".mae-flow.json.agent-writes"),
                    encoding="utf-8") as stream:
                superseded = json.load(stream)
            self.assertNotIn(
                "generated/build.properties",
                superseded["compile_side_effects"],
            )
            self.assertIn("generated/build.properties", superseded["paths"])

    def test_rejected_compile_contract_does_not_record_side_effects(self):
        with tempfile.TemporaryDirectory() as td, in_directory(td):
            head = initialize_repository(td)
            runtime = runtime_for(td)
            task = compile_task(td, head, runtime._worktree_snapshot(head))
            save_compile_state(td, task)
            generated = os.path.join(td, "generated", "build.properties")
            os.makedirs(os.path.dirname(generated), exist_ok=True)
            with open(generated, "w", encoding="utf-8") as stream:
                stream.write("compiled=true\n")

            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as rejected:
                    runtime._compile_contract("OK", accepted_report(task), [])
            self.assertEqual(2, rejected.exception.code)
            self.assertFalse(os.path.exists(
                os.path.join(td, ".mae-flow.json.agent-writes")))

    def test_compile_provenance_failures_are_logged_without_rejecting(self):
        with tempfile.TemporaryDirectory() as td, in_directory(td):
            head = initialize_repository(td)
            logs = []
            runtime = runtime_for(td, logs)
            task = compile_task(td, head, runtime._worktree_snapshot(head))
            save_compile_state(td, task)
            generated = os.path.join(td, "generated", "build.properties")
            os.makedirs(os.path.dirname(generated), exist_ok=True)
            with open(generated, "w", encoding="utf-8") as stream:
                stream.write("compiled=true\n")
            calls = [{
                "name": "Bash",
                "input": {"command": "python build.py"},
                "result_seen": True,
                "result": "build complete\nexit code: 0",
            }]

            with mock.patch.object(
                    runtime,
                    "_worktree_snapshot",
                    side_effect=OSError("snapshot fixture unavailable"),
            ):
                runtime._compile_contract("OK", accepted_report(task), calls)
            self.assertTrue(any(
                "COMPILE side-effect ledger EXC: snapshot fixture unavailable"
                in entry for entry in logs))

            logs.clear()
            with open(runtime.AGENT_WRITES_STATE, "w", encoding="utf-8") as stream:
                stream.write("{unreadable ledger")
            runtime._compile_contract("OK", accepted_report(task), calls)
            self.assertTrue(any(
                "COMPILE side-effect ledger recovering unreadable sidecar"
                in entry for entry in logs))

            logs.clear()
            with open(runtime.AGENT_WRITES_STATE, "w", encoding="utf-8") as stream:
                stream.write("{unreadable direct ledger")
            runtime._record_agent_write("config/runtime.json")
            self.assertTrue(any(
                "agent write ledger recovering unreadable sidecar" in entry
                for entry in logs))

            logs.clear()
            with mock.patch(
                    "mae_flow_core.adapters.hook_runtime_state.update_json",
                    side_effect=OSError("update fixture unavailable"),
            ):
                runtime._compile_contract("OK", accepted_report(task), calls)
            self.assertTrue(any(
                "COMPILE side-effect ledger EXC: update fixture unavailable"
                in entry for entry in logs))

    def test_worktree_snapshot_logs_git_failures(self):
        with tempfile.TemporaryDirectory() as td, in_directory(td):
            logs = []
            runtime = runtime_for(td, logs)
            failed_git = mock.Mock(
                returncode=1,
                stdout="",
                stderr="fixture git failure",
            )
            with mock.patch(
                    "mae_flow_core.adapters.hook_runtime_contracts.subprocess.run",
                    return_value=failed_git,
            ):
                self.assertEqual({}, runtime._worktree_snapshot("fixture-head"))
            self.assertTrue(any(
                "git output unavailable (exit 1)" in entry
                for entry in logs))


if __name__ == "__main__":
    unittest.main()
