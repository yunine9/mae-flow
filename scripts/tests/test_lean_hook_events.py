#!/usr/bin/env python3
"""Tests for the pure four-event lean Hook router."""

import os
import sys
import unittest
from dataclasses import FrozenInstanceError
from types import SimpleNamespace


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from mae_flow_core.application.hooks.lean_events import (  # noqa: E402
    LeanHookPorts,
    handle_lean_hook_event,
)
from mae_flow_core.application.hooks.models import HookResponse  # noqa: E402


class LeanHookEventTests(unittest.TestCase):
    def ports(self, failures=()):
        calls = []

        def handler(name):
            def call(*args):
                calls.append((name, args))
                if name in failures:
                    raise RuntimeError(name + " failed")
                return HookResponse(stdout=name + "\n")
            return call

        return LeanHookPorts(
            resume=handler("resume"),
            prompt=handler("prompt"),
            pretool=handler("pretool"),
            posttool=handler("posttool"),
            inactive=handler("inactive"),
        ), calls

    def test_normalized_public_events_route_to_the_four_ports(self):
        expected = {
            "SessionStart": "resume",
            "session_start": "resume",
            "UserPromptSubmit": "prompt",
            "USER-PROMPT": "prompt",
            "PreToolUse": "pretool",
            "pre_tool_use": "pretool",
            "PostToolUse": "posttool",
            "post-tool-use": "posttool",
        }
        for event, target in expected.items():
            with self.subTest(event=event):
                ports, calls = self.ports()
                response = handle_lean_hook_event(
                    event, {}, SimpleNamespace(status="active"), ports)
                self.assertEqual(target + "\n", response.stdout)
                self.assertEqual([target], [name for name, _args in calls])

    def test_legacy_stop_events_and_unrelated_names_never_call_ports(self):
        for event in (
                "Stop", "stop", "SubagentStop", "subagent_stop",
                "BeforePreToolUse", "UserPromptSubmitted", "tooluse"):
            with self.subTest(event=event):
                ports, calls = self.ports()
                response = handle_lean_hook_event(
                    event, {}, SimpleNamespace(status="active"), ports)
                self.assertEqual(HookResponse(), response)
                self.assertEqual([], calls)

    def test_inactive_complete_and_exited_states_bypass_ordinary_ports(self):
        for status in ("inactive", "complete", "exited"):
            with self.subTest(status=status):
                ports, calls = self.ports()
                response = handle_lean_hook_event(
                    "PreToolUse", {"tool_name": "Edit"},
                    SimpleNamespace(status=status), ports)
                self.assertEqual("inactive\n", response.stdout)
                self.assertEqual(["inactive"], [name for name, _args in calls])

    def test_corrupt_state_routes_only_commit_and_push_to_pretool(self):
        blocked = HookResponse(exit_code=2, stderr="manifest mismatch\n")
        calls = []

        def pretool(payload):
            calls.append(payload)
            return blocked

        ports = LeanHookPorts(
            resume=lambda payload: HookResponse(stdout="resume\n"),
            prompt=lambda payload: HookResponse(stdout="prompt\n"),
            pretool=pretool,
            posttool=lambda payload: HookResponse(stdout="posttool\n"),
            inactive=lambda event, payload: HookResponse(stdout="inactive\n"),
        )
        runtime = SimpleNamespace(status="corrupt")
        deliveries = (
            {"tool_name": "Bash", "tool_input": {
                "command": "git commit -m update"}},
            {"tool_name": "bash", "tool_input": {
                "command": "git add src/a.py && git push origin HEAD"}},
            {"tool_name": "Bash", "tool_input": {
                "command": r"C:\Git\bin\git.exe push origin HEAD"}},
            {"tool_name": "Bash", "tool_input": {
                "command": "LC_ALL=C git commit -m update"}},
            {"tool_name": "Bash", "tool_input": {
                "command": "env LC_ALL=C git push origin HEAD"}},
            {"tool_name": "Bash", "tool_input": {
                "command": "env -S 'git push origin HEAD'"}},
            {"tool_name": "Bash", "tool_input": {
                "command": "command git commit -m update"}},
            {"tool_name": "Bash", "tool_input": {
                "command": "exec git commit -m update"}},
            {"tool_name": "Bash", "tool_input": {
                "command": "sudo git push origin HEAD"}},
            {"tool_name": "Bash", "tool_input": {
                "command": "bash -c 'git push origin HEAD'"}},
            {"tool_name": "Bash", "tool_input": {
                "command": (
                    "bash -c \"sh -c 'zsh -c \\\"git push origin HEAD\\\"'\"")}},
            {"tool_name": "Bash", "tool_input": {
                "command": "cmd.exe /c git commit -m update"}},
        )
        for payload in deliveries:
            with self.subTest(payload=payload):
                response = handle_lean_hook_event(
                    "PreToolUse", payload, runtime, ports)
                self.assertIs(blocked, response)

        call_count = len(calls)
        ordinary = (
            ("SessionStart", {}),
            ("UserPromptSubmit", {"prompt": "continue"}),
            ("PostToolUse", {"tool_name": "Bash"}),
            ("PreToolUse", {"tool_name": "Edit", "tool_input": {}}),
            ("PreToolUse", {"tool_name": "Bash", "tool_input": {
                "command": "git add src/a.py"}}),
            ("PreToolUse", {"tool_name": "Bash", "tool_input": {
                "command": "echo git commit"}}),
            ("PreToolUse", {"tool_name": "Bash", "tool_input": {
                "command": "cmd.exe /c echo git push"}}),
            ("PreToolUse", {"tool_name": "Bash", "tool_input": {
                "command": "cmd.exe -c git push"}}),
            ("PreToolUse", {"tool_name": "Bash", "tool_input": {
                "command": "bash -c git push"}}),
        )
        for event, payload in ordinary:
            with self.subTest(event=event, payload=payload):
                self.assertEqual(
                    HookResponse(),
                    handle_lean_hook_event(event, payload, runtime, ports),
                )
        self.assertEqual(call_count, len(calls))

    def test_malformed_inputs_and_port_exceptions_fail_open(self):
        malformed = (
            (None, {}, SimpleNamespace(status="active")),
            ("SessionStart", [], SimpleNamespace(status="active")),
            ("SessionStart", {}, object()),
            ("PreToolUse", {
                "tool_name": "Bash", "tool_input": {"command": 7}},
             SimpleNamespace(status="corrupt")),
        )
        for event, payload, runtime in malformed:
            with self.subTest(event=event, payload=payload, runtime=runtime):
                ports, calls = self.ports()
                self.assertEqual(
                    HookResponse(),
                    handle_lean_hook_event(event, payload, runtime, ports),
                )
                self.assertEqual([], calls)

        for failing_port, event in (
                ("resume", "SessionStart"),
                ("prompt", "UserPromptSubmit"),
                ("pretool", "PreToolUse"),
                ("posttool", "PostToolUse")):
            with self.subTest(port=failing_port):
                ports, _calls = self.ports((failing_port,))
                self.assertEqual(
                    HookResponse(),
                    handle_lean_hook_event(
                        event, {}, SimpleNamespace(status="active"), ports),
                )

    def test_ports_are_immutable(self):
        ports, _calls = self.ports()
        with self.assertRaises(FrozenInstanceError):
            ports.prompt = lambda payload: HookResponse()


if __name__ == "__main__":
    unittest.main()
