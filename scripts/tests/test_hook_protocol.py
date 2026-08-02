#!/usr/bin/env python3
"""Protocol adapter tests kept at the Hook process boundary."""

import importlib.util
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
import sys
import tempfile
import unittest
from unittest import mock


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
HOOK = os.path.join(ROOT, "hooks", "dispatch.py")
HOOKS_CONFIG = os.path.join(ROOT, "hooks", "hooks.json")
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.application.hooks.models import HookResponse  # noqa: E402


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

    def test_production_registration_is_exactly_the_four_lean_events(self):
        with open(HOOKS_CONFIG, encoding="utf-8") as stream:
            raw = stream.read()
        config = json.loads(raw)["hooks"]

        self.assertEqual(
            {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse"},
            set(config),
        )
        self.assertNotIn("Stop", raw)
        self.assertNotIn("SubagentStop", raw)

    def test_registration_covers_write_and_capability_boundaries(self):
        with open(HOOKS_CONFIG, encoding="utf-8") as stream:
            config = json.load(stream)["hooks"]

        pretool = set(config["PreToolUse"][0]["matcher"].split("|"))
        posttool = set(config["PostToolUse"][0]["matcher"].split("|"))
        self.assertEqual(
            {"Edit", "Write", "MultiEdit", "Bash", "Task", "Skill"},
            pretool,
        )
        self.assertEqual({"Task", "Skill"}, posttool)

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

    def test_unexpected_top_level_exception_fails_open(self):
        with mock.patch.object(
                self.dispatch, "read_input", side_effect=RuntimeError("boom")):
            with mock.patch.object(self.dispatch, "_arm_watchdog"):
                with self.assertRaises(SystemExit) as caught:
                    self.dispatch.main()
        self.assertEqual(0, caught.exception.code)

    def test_main_delegates_decoded_event_to_the_lean_adapter(self):
        response = HookResponse(
            exit_code=2, stdout="lean stdout\n", stderr="lean stderr\n")
        payload = {"cwd": ROOT, "tool_name": "Edit"}

        class ExactAdapter:
            def handle(self, event, value):
                if event != "PreToolUse" or value != payload:
                    raise AssertionError("wrong lean adapter protocol call")
                return response

        adapter = ExactAdapter()

        with mock.patch.object(self.dispatch, "read_input", return_value=payload):
            with mock.patch.object(self.dispatch, "_arm_watchdog"):
                with mock.patch.object(
                        self.dispatch, "_lean_adapter", return_value=adapter):
                    stdout = StringIO()
                    stderr = StringIO()
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        with self.assertRaises(SystemExit) as caught:
                            self.dispatch.main(["dispatch.py", "PreToolUse"])

        self.assertEqual(2, caught.exception.code)
        self.assertEqual("lean stdout\n", stdout.getvalue())
        self.assertEqual("lean stderr\n", stderr.getvalue())

    def test_legacy_stop_events_succeed_without_touching_state(self):
        with tempfile.TemporaryDirectory() as root:
            state_path = os.path.join(root, ".mae-flow.json")
            original = b"state-must-remain-byte-identical"
            with open(state_path, "wb") as stream:
                stream.write(original)
            before = set(os.listdir(root))

            with mock.patch.object(self.dispatch.os, "getcwd", return_value=root):
                adapter = self.dispatch._lean_adapter()
            for event in ("Stop", "SubagentStop"):
                with self.subTest(event=event):
                    response = adapter.handle(event, {"tool_name": "Bash"})
                    self.assertEqual(HookResponse(), response)
                    with open(state_path, "rb") as stream:
                        self.assertEqual(original, stream.read())
                    self.assertEqual(before, set(os.listdir(root)))


if __name__ == "__main__":
    unittest.main()
