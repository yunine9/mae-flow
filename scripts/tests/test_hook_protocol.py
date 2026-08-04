#!/usr/bin/env python3
"""Protocol adapter tests kept at the Hook process boundary."""

import importlib.util
import json
import os
import sys
import tempfile
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

    def test_hook_manifest_is_codeagent_only_and_observes_agent_tool(self):
        with open(os.path.join(ROOT, "hooks", "hooks.json"),
                  encoding="utf-8") as stream:
            content = stream.read()
        self.assertIn("CODEAGENT3_PLUGIN_ROOT", content)
        self.assertNotIn("CLAUDE_PLUGIN_ROOT", content)
        self.assertIn("AskUserQuestion|Task|Agent", content)

    def test_unexpected_top_level_exception_fails_open(self):
        with mock.patch.object(
                self.dispatch, "read_input", side_effect=RuntimeError("boom")):
            with mock.patch.object(self.dispatch, "_arm_watchdog"):
                with self.assertRaises(SystemExit) as caught:
                    self.dispatch.main()
        self.assertEqual(0, caught.exception.code)


if __name__ == "__main__":
    unittest.main()
