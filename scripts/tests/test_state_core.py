#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for the shared runtime/state core."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest


SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROOT = os.path.abspath(os.path.join(SCRIPTS, ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core import (  # noqa: E402
    CURRENT_SCHEMA_VERSION,
    RuntimeMode,
    StateConflictError,
    StateStoreError,
    atomic_write_json,
    normalize_document,
    read_json,
    resolve_runtime,
    save_versioned_json,
    update_json,
)


class RuntimeAndStateTests(unittest.TestCase):
    def test_runtime_matrix_schema_and_corrupt_preservation(self):
        with tempfile.TemporaryDirectory() as td:
            flow_path = os.path.join(td, ".mae-flow.json")
            action_path = os.path.join(
                td, ".mae-flow-work", "standalone-action.json")
            exit_path = os.path.join(td, ".mae-flow.json.exited")
            os.makedirs(os.path.dirname(action_path), exist_ok=True)
            self.assertEqual(RuntimeMode.INACTIVE, resolve_runtime(td).mode)

            save_versioned_json(
                flow_path, {"current": "config_confirm"}, "flow", project_root=td)
            migrated = read_json(flow_path)
            self.assertEqual(CURRENT_SCHEMA_VERSION, migrated["schema_version"])
            self.assertEqual(1, migrated["revision"])

            action = {
                "kind": "ut", "id": "conflict-fixture",
                "expires_epoch": time.time() + 3600,
                "work_dir": os.path.join(
                    td, ".mae-flow-work", "standalone", "fixture"),
            }
            save_versioned_json(
                action_path, action, "action", project_root=td)
            atomic_write_json(exit_path, {"status": "exited"})
            mixed = resolve_runtime(td)
            self.assertEqual(RuntimeMode.FLOW, mixed.mode)
            self.assertEqual(
                {"flow_and_action", "flow_and_exit"}, set(mixed.conflicts))

            os.remove(flow_path)
            self.assertEqual(RuntimeMode.STANDALONE, resolve_runtime(td).mode)
            action["expires_epoch"] = time.time() - 1
            action.pop("revision", None)
            save_versioned_json(
                action_path, action, "action", project_root=td)
            expired = resolve_runtime(td)
            self.assertEqual(RuntimeMode.DIRECT, expired.mode)
            self.assertIn("expired_action", expired.ignored)

            os.remove(exit_path)
            with open(flow_path, "w", encoding="utf-8") as stream:
                stream.write("{broken")
            self.assertEqual(RuntimeMode.CORRUPT, resolve_runtime(td).mode)
            with self.assertRaises(StateStoreError):
                save_versioned_json(
                    flow_path, {"current": "build"}, "flow", project_root=td)
            with open(flow_path, encoding="utf-8") as stream:
                self.assertEqual("{broken", stream.read())

    def test_compare_and_swap_rejects_stale_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            state_path = os.path.join(td, ".mae-flow.json")
            save_versioned_json(
                state_path, {"current": "config_confirm"},
                "flow", project_root=td)
            first = normalize_document(read_json(state_path), "flow")
            stale = normalize_document(read_json(state_path), "flow")
            first["config"]["单号"] = "REQ-FIRST"
            save_versioned_json(state_path, first, "flow", project_root=td)
            stale["config"]["单号"] = "REQ-STALE"
            with self.assertRaises(StateConflictError):
                save_versioned_json(state_path, stale, "flow", project_root=td)

    def test_corrupt_sidecar_is_quarantined_not_deadlocked(self):
        with tempfile.TemporaryDirectory() as td:
            sidecar = os.path.join(td, ".mae-flow.json.tokens")
            with open(sidecar, "w", encoding="utf-8") as stream:
                stream.write("{broken-token")
            update_json(
                sidecar, lambda value: {"UT": {"status": "PASS"}},
                default={}, project_root=td, recover_corrupt=True)
            self.assertEqual("PASS", read_json(sidecar)["UT"]["status"])
            quarantined = [
                name for name in os.listdir(td)
                if name.startswith(".mae-flow.json.tokens.corrupt.")
            ]
            self.assertEqual(1, len(quarantined))

    def test_posttooluse_records_direct_agent_write_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            source = os.path.join(td, "src", "feature.cpp")
            os.makedirs(os.path.dirname(source), exist_ok=True)
            with open(source, "w", encoding="utf-8") as stream:
                stream.write("int feature() { return 1; }\n")
            save_versioned_json(
                os.path.join(td, ".mae-flow.json"),
                {"current": "build", "config": {}, "choices": {},
                 "history": [], "started": "2026-07-26 12:00:00"},
                "flow", project_root=td)
            payload = json.dumps({
                "cwd": td,
                "tool_name": "Edit",
                "tool_input": {"file_path": source},
                "tool_response": {"ok": True},
            }, ensure_ascii=False) + "\n"
            env = dict(os.environ)
            env["PYTHONPYCACHEPREFIX"] = os.path.join(td, "pycache")
            hook = subprocess.run(
                [sys.executable, os.path.join(
                    ROOT, "hooks", "dispatch.py"), "posttooluse"],
                cwd=td, input=payload, text=True, capture_output=True,
                env=env, timeout=15)
            self.assertEqual(0, hook.returncode, hook.stderr)
            with open(
                    os.path.join(td, ".mae-flow.json.agent-writes"),
                    encoding="utf-8") as stream:
                ledger = json.load(stream)
            self.assertIn("src/feature.cpp", ledger["paths"])

    def test_terminal_flow_keeps_cli_state_but_all_hooks_bypass(self):
        with tempfile.TemporaryDirectory() as td:
            source = os.path.join(td, "src", "feature.cpp")
            os.makedirs(os.path.dirname(source), exist_ok=True)
            with open(source, "w", encoding="utf-8") as stream:
                stream.write("int feature() { return 1; }\n")
            save_versioned_json(
                os.path.join(td, ".mae-flow.json"),
                {"current": "end", "config": {"单号": "REQ-DONE"},
                 "choices": {}, "history": [],
                 "started": "2026-07-28 12:00:00",
                 "moonlight": {"enabled": True}},
                "flow", project_root=td)

            runtime = resolve_runtime(td)
            self.assertEqual(RuntimeMode.FLOW, runtime.mode)
            self.assertTrue(runtime.flow_terminal)

            env = dict(os.environ)
            env["PYTHONPYCACHEPREFIX"] = os.path.join(td, "pycache")

            def hook(event, payload):
                return subprocess.run(
                    [sys.executable, os.path.join(
                        ROOT, "hooks", "dispatch.py"), event],
                    cwd=td, input=json.dumps(
                        {"cwd": td, **payload}, ensure_ascii=False) + "\n",
                    text=True, capture_output=True, env=env, timeout=15)

            # 终态不是仍在运行的流程：六类 Hook 入口都不能继续使用旧步骤、
            # 旧月光设置或旧 Agent 任务卡接管普通开发。
            cases = [
                ("pretooluse", {
                    "tool_name": "Edit",
                    "tool_input": {"file_path": source},
                }),
                ("pretooluse", {
                    "tool_name": "Bash",
                    "tool_input": {"command": "git reset --hard"},
                }),
                ("pretooluse", {
                    "tool_name": "AskUserQuestion", "tool_input": {},
                }),
                ("pretooluse", {
                    "tool_name": "Task",
                    "tool_input": {
                        "subagent_type": "compile-agent",
                        "prompt": "run stale terminal task",
                    },
                }),
                ("posttooluse", {
                    "tool_name": "Write",
                    "tool_input": {"file_path": source},
                    "tool_response": {"ok": True},
                }),
                ("subagentstop", {}),
                ("stop", {}),
                ("userprompt", {"prompt": "流程结束后直接修改普通代码"}),
                ("sessionstart", {}),
            ]
            for event, payload in cases:
                result = hook(event, payload)
                self.assertEqual(
                    0, result.returncode,
                    "%s unexpectedly blocked:\n%s\n%s" % (
                        event, result.stdout, result.stderr))

            self.assertFalse(
                os.path.exists(os.path.join(
                    td, ".mae-flow.json.agent-writes")))
            self.assertFalse(
                os.path.exists(os.path.join(td, ".mae-flow.json.usermsg")))

            moonlight_intent = hook(
                "userprompt", {"prompt": "下一单开启月光宝盒继续"})
            self.assertEqual(
                0, moonlight_intent.returncode, moonlight_intent.stderr)
            with open(
                    os.path.join(td, ".mae-flow.json.usermsg"),
                    encoding="utf-8") as stream:
                messages = json.load(stream)
            self.assertEqual("end", messages[-1]["step"])
            self.assertIn("月光宝盒", messages[-1]["text"])

            # CLI 仍保留终态报告和下一单滚动所需的状态；只是门禁已解除。
            current = subprocess.run(
                [sys.executable, os.path.join(
                    ROOT, "scripts", "mae-flow.py"), "current"],
                cwd=td, text=True, capture_output=True, env=env, timeout=15)
            self.assertEqual(0, current.returncode, current.stderr)
            self.assertIn("流程已完成", current.stdout)

            direct_gate = subprocess.run(
                [sys.executable, os.path.join(
                    ROOT, "scripts", "mae-flow.py"),
                 "gate", "edit", source],
                cwd=td, text=True, capture_output=True, env=env, timeout=15)
            self.assertEqual(0, direct_gate.returncode, direct_gate.stderr)
            direct_bash_gate = subprocess.run(
                [sys.executable, os.path.join(
                    ROOT, "scripts", "mae-flow.py"),
                 "gate", "bash", "git reset --hard"],
                cwd=td, text=True, capture_output=True, env=env, timeout=15)
            self.assertEqual(
                0, direct_bash_gate.returncode, direct_bash_gate.stderr)

    def test_concurrent_read_modify_write_does_not_lose_updates(self):
        with tempfile.TemporaryDirectory() as td:
            counter = os.path.join(td, "counter.json")
            atomic_write_json(counter, {"count": 0})
            worker = (
                "from mae_flow_core import update_json\n"
                "p=" + repr(counter) + "\n"
                "for _ in range(30):\n"
                " update_json(p, lambda d: {'count': int(d.get('count', 0)) + 1},"
                " default={'count': 0}, project_root=" + repr(td) + ")\n"
            )
            env = dict(os.environ)
            env["PYTHONPATH"] = SCRIPTS + os.pathsep + env.get("PYTHONPATH", "")
            env["PYTHONPYCACHEPREFIX"] = os.path.join(td, "pycache")
            procs = [
                subprocess.Popen([sys.executable, "-c", worker], env=env)
                for _ in range(8)
            ]
            self.assertTrue(all(proc.wait(timeout=20) == 0 for proc in procs))
            self.assertEqual(240, read_json(counter)["count"])

    def test_cli_and_hook_share_conflict_precedence(self):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, ".mae-flow-work"), exist_ok=True)
            os.makedirs(os.path.join(td, "service"), exist_ok=True)
            source = os.path.join(td, "service", "Foo.cpp")
            with open(source, "w", encoding="utf-8") as stream:
                stream.write("int value = 1;\n")
            save_versioned_json(
                os.path.join(td, ".mae-flow.json"),
                {"current": "config_confirm", "config": {}, "choices": {},
                 "history": [], "started": "2026-01-01 00:00:00"},
                "flow", project_root=td)
            save_versioned_json(
                os.path.join(
                    td, ".mae-flow-work", "standalone-action.json"),
                {"kind": "ut", "id": "stale-action",
                 "expires_epoch": time.time() + 3600,
                 "work_dir": os.path.join(
                     td, ".mae-flow-work", "standalone", "stale")},
                "action", project_root=td)
            env = dict(os.environ)
            env["PYTHONPYCACHEPREFIX"] = os.path.join(td, "pycache")
            payload = json.dumps({
                "cwd": td, "tool_name": "Edit",
                "tool_input": {"file_path": source},
            }) + "\n"
            hook = subprocess.run(
                [sys.executable, os.path.join(
                    ROOT, "hooks", "dispatch.py"), "pretooluse"],
                cwd=td, input=payload, text=True, capture_output=True,
                env=env, timeout=15)
            self.assertEqual(2, hook.returncode, hook.stderr)

            atomic_write_json(
                os.path.join(td, ".mae-flow.json.exited"),
                {"status": "exited"})
            current = subprocess.run(
                [sys.executable, os.path.join(
                    ROOT, "scripts", "mae-flow.py"), "current"],
                cwd=td, text=True, capture_output=True, env=env, timeout=15)
            self.assertEqual(0, current.returncode, current.stderr)
            self.assertIn("config_confirm", current.stdout)
            self.assertNotIn("普通开发模式", current.stdout)

    def test_statusline_uses_repository_boundary_and_runtime_precedence(self):
        with tempfile.TemporaryDirectory() as td:
            parent = os.path.join(td, "parent")
            child = os.path.join(parent, "child")
            os.makedirs(os.path.join(parent, ".git"))
            os.makedirs(os.path.join(child, ".git"))
            atomic_write_json(
                os.path.join(parent, ".mae-flow.json.exited"),
                {"status": "exited"})
            payload = json.dumps({"cwd": child}, ensure_ascii=False)
            env = dict(os.environ)
            env["PYTHONPATH"] = SCRIPTS + os.pathsep + env.get("PYTHONPATH", "")
            env["PYTHONPYCACHEPREFIX"] = os.path.join(td, "pycache")
            first = subprocess.run(
                [sys.executable, os.path.join(SCRIPTS, "statusline.py")],
                input=payload, text=True, capture_output=True, env=env, timeout=15)
            self.assertNotIn("已退出", first.stdout)

            save_versioned_json(
                os.path.join(child, ".mae-flow.json"),
                {"current": "config_confirm", "config": {}, "choices": {},
                 "history": [], "started": "2026-01-01 00:00:00"},
                "flow", project_root=child)
            atomic_write_json(
                os.path.join(child, ".mae-flow.json.exited"),
                {"status": "exited"})
            second = subprocess.run(
                [sys.executable, os.path.join(SCRIPTS, "statusline.py")],
                input=payload, text=True, capture_output=True, env=env, timeout=15)
            self.assertIn("配置确认", second.stdout)
            self.assertNotIn("已退出", second.stdout)

    def test_corrupt_exit_marker_has_deterministic_repair(self):
        with tempfile.TemporaryDirectory() as td:
            with open(
                    os.path.join(td, ".mae-flow.json.exited"),
                    "w", encoding="utf-8") as stream:
                stream.write("{broken-exit")
            env = dict(os.environ)
            env["PYTHONPYCACHEPREFIX"] = os.path.join(td, "pycache")
            repaired = subprocess.run(
                [sys.executable, os.path.join(
                    ROOT, "scripts", "mae-flow.py"),
                 "doctor", "--repair-state"],
                cwd=td, text=True, capture_output=True, env=env, timeout=15)
            self.assertEqual(0, repaired.returncode, repaired.stderr)
            self.assertEqual(RuntimeMode.DIRECT, resolve_runtime(td).mode)
            bad_markers = [
                os.path.join(base, name)
                for base, _, names in os.walk(
                    os.path.join(td, ".mae-flow-work"))
                for name in names if name.endswith(".bad")
            ]
            self.assertEqual(1, len(bad_markers))


if __name__ == "__main__":
    unittest.main(verbosity=2)
