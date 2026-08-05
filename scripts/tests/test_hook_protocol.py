#!/usr/bin/env python3
"""Protocol adapter tests kept at the Hook process boundary."""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
HOOK = os.path.join(ROOT, "hooks", "dispatch.py")


def load_dispatch():
    name = "mae_flow_hook_protocol_test"
    spec = importlib.util.spec_from_file_location(name, HOOK)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class HookProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dispatch = load_dispatch()

    def test_decodes_utf8_bom_and_gb18030_without_replacement(self):
        payload = {"prompt": "中文确认", "tool_name": "Edit"}
        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(
            payload,
            self.dispatch._decode_hook_json(
                b"\xef\xbb\xbf" + encoded.encode("utf-8")),
        )
        with mock.patch.object(
                self.dispatch.locale,
                "getpreferredencoding",
                return_value="ascii"):
            self.assertEqual(
                payload,
                self.dispatch._decode_hook_json(encoded.encode("gb18030")),
            )

    def test_invalid_payload_is_rejected_by_decoder(self):
        with self.assertRaises(ValueError):
            self.dispatch._decode_hook_json(b"\xff\xfe\x00not-json")

    def test_missing_maeflow_script_fails_open(self):
        original = self.dispatch.MAEFLOW
        try:
            self.dispatch.MAEFLOW = os.path.join(ROOT, "missing.py")
            self.assertEqual(0, self.dispatch.maeflow("gate", "edit", "x"))
        finally:
            self.dispatch.MAEFLOW = original

    def test_production_task_card_ports_construct_with_build_path_policy(self):
        """Production dispatch must wire every required task-card dependency."""
        try:
            ports = self.dispatch._task_card_ports()
        except TypeError as exc:
            self.fail("生产 Hook 任务卡端口装配不完整: %s" % exc)
        self.assertTrue(ports.build_like("CMakeLists.txt"))

    def test_project_launcher_uses_codeagent_plugin_root(self):
        from mae_flow_core.adapters.project_launcher import (
            install_project_launcher,
        )
        with tempfile.TemporaryDirectory() as root:
            plugin = os.path.join(root, "plugin")
            os.makedirs(os.path.join(plugin, "scripts"))
            entry = os.path.join(plugin, "scripts", "mae-flow.py")
            with open(entry, "w", encoding="utf-8") as stream:
                stream.write("raise SystemExit(0)\n")
            with mock.patch.dict(
                    os.environ,
                    {"CODEAGENT3_PLUGIN_ROOT": plugin},
                    clear=False):
                launcher = install_project_launcher(root)
            self.assertEqual(
                os.path.join(root, ".mae-flow-work", "bin", "mae-flow.py"),
                launcher,
            )
            with open(launcher, encoding="utf-8") as stream:
                content = stream.read()
            self.assertIn(repr(entry), content)
            self.assertNotIn("CLAUDE_PLUGIN_ROOT", content)

    def test_userprompt_hook_event_installs_project_launcher(self):
        from mae_flow_core.adapters.project_launcher import (
            install_launcher_for_event,
        )
        with tempfile.TemporaryDirectory() as root:
            original = os.getcwd()
            try:
                os.chdir(root)
                launcher = install_launcher_for_event("userprompt")
            finally:
                os.chdir(original)
            self.assertEqual(
                os.path.join(
                    os.path.realpath(root),
                    ".mae-flow-work", "bin", "mae-flow.py"),
                launcher,
            )
            self.assertTrue(os.path.isfile(launcher))

    def test_production_active_hook_uses_the_user_repository_root(self):
        with tempfile.TemporaryDirectory() as project:
            original = os.getcwd()
            try:
                os.chdir(project)
                ports = self.dispatch._hook_event_ports()
            finally:
                os.chdir(original)

        active = ports.pretool.__self__.pretool_handler.__self__
        self.assertEqual(os.path.realpath(project), active.repository_root)
        self.assertEqual(ROOT, active.plugin_root)

    def test_production_pretool_agent_gate_rejects_a_missing_story_task(self):
        with tempfile.TemporaryDirectory() as project:
            subprocess.run(
                ["git", "init", "-q", project], check=True,
                capture_output=True)
            with open(os.path.join(project, ".mae-flow.json"), "w",
                      encoding="utf-8") as stream:
                json.dump({
                    "current": "story",
                    "config": {"单号": "REQ-HOOK-E2E"},
                    "choices": {"workflow": "full"},
                    "history": [],
                    "started": time.strftime("%Y-%m-%d %H:%M:%S"),
                }, stream, ensure_ascii=False)
            payload = json.dumps({
                "cwd": project,
                "tool_name": "Agent",
                "tool_use_id": "toolu-story-e2e",
                "tool_input": {
                    "subagent_type": "story-generator-agent",
                },
            }, ensure_ascii=False) + "\n"

            result = subprocess.run(
                [sys.executable, HOOK, "pretooluse"],
                cwd=project, input=payload, text=True,
                capture_output=True, timeout=15)

        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn("派发前拦截:STORY 尚无本步任务卡", result.stderr)
        self.assertNotIn("TaskCardPorts.__init__", result.stderr)

    def test_production_pretool_records_started_story_lifecycle(self):
        with tempfile.TemporaryDirectory() as project:
            subprocess.run(
                ["git", "init", "-q", project], check=True,
                capture_output=True)
            state_path = os.path.join(project, ".mae-flow.json")
            with open(state_path, "w", encoding="utf-8") as stream:
                json.dump({
                    "current": "story",
                    "config": {"单号": "REQ-HOOK-E2E"},
                    "choices": {"workflow": "full"},
                    "history": [],
                    "started": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "agent_tasks": {"STORY": {"step": "story"}},
                }, stream, ensure_ascii=False)
            payload = json.dumps({
                "cwd": project,
                "tool_name": "Agent",
                "tool_use_id": "toolu-story-started",
                "tool_input": {
                    "subagent_type": "story-generator-agent",
                },
            }, ensure_ascii=False) + "\n"

            result = subprocess.run(
                [sys.executable, HOOK, "pretooluse"],
                cwd=project, input=payload, text=True,
                capture_output=True, timeout=15)
            with open(state_path + ".agent-observations",
                      encoding="utf-8") as stream:
                observations = json.load(stream)["observations"]

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("started", observations[-1]["lifecycle"])
        self.assertEqual("STORY", observations[-1]["kind"])
        self.assertEqual("toolu-story-started",
                         observations[-1]["invocation_id"])

    def test_hook_manifest_is_codeagent_only_and_observes_agent_tool(self):
        with open(os.path.join(ROOT, "hooks", "hooks.json"),
                  encoding="utf-8") as stream:
            content = stream.read()
        self.assertIn("CODEAGENT3_PLUGIN_ROOT", content)
        self.assertNotIn("CLAUDE_PLUGIN_ROOT", content)
        self.assertIn("AskUserQuestion|Task|Agent", content)
        manifest = json.loads(content)
        posttool = "|".join(
            item.get("matcher", "")
            for item in manifest["hooks"]["PostToolUse"])
        self.assertIn("Task", posttool)
        self.assertIn("Agent", posttool)

    def test_unexpected_top_level_exception_fails_open(self):
        with mock.patch.object(
                self.dispatch, "read_input", side_effect=RuntimeError("boom")):
            with mock.patch.object(self.dispatch, "_arm_watchdog"):
                with self.assertRaises(SystemExit) as caught:
                    self.dispatch.main()
        self.assertEqual(0, caught.exception.code)


if __name__ == "__main__":
    unittest.main()
