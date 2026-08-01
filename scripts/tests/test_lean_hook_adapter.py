#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Process and state contracts for the test-only lean Hook adapter."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace


TESTS = os.path.abspath(os.path.dirname(__file__))
SCRIPTS = os.path.abspath(os.path.join(TESTS, ".."))
HARNESS = os.path.join(TESTS, "lean_hook_harness.py")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.adapters.lean_hook import (  # noqa: E402
    LeanHookAdapter,
    LeanHookFactPorts,
)
from mae_flow_core.orchestration import (  # noqa: E402
    CapabilityAttempt,
    CommitPace,
    DeliveryPath,
    FlowState,
    Phase,
)


class LeanHookAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = self.temporary.name
        self.marker_root = os.path.join(self.root, "markers")

    def invoke(self, event, payload):
        raw = (
            payload if isinstance(payload, bytes)
            else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        )
        return subprocess.run(
            [
                sys.executable,
                HARNESS,
                event,
                "--root", self.root,
                "--marker-root", self.marker_root,
            ],
            input=raw,
            capture_output=True,
            check=False,
        )

    @property
    def state_path(self):
        return os.path.join(self.root, ".mae-flow.json")

    @property
    def pointer_path(self):
        return os.path.join(self.root, ".mae-flow.json.exited")

    @property
    def events_path(self):
        return os.path.join(
            self.root, ".mae-flow-work", "lean-hook-user-events.json")

    def write_state(self, state=None):
        state = state or FlowState.new(
            "REQ-5", DeliveryPath.FULL, CommitPace.CONTINUOUS)
        with open(self.state_path, "w", encoding="utf-8") as stream:
            json.dump(state.to_dict(), stream, ensure_ascii=False)
        return state

    def test_malformed_ordinary_event_fails_open_at_protocol_boundary(self):
        result = self.invoke("PostToolUse", b"{not-json")
        self.assertEqual(0, result.returncode, result.stderr.decode("utf-8"))
        self.assertEqual(b"", result.stdout)

    def test_timeout_and_non_object_payloads_fail_open(self):
        adapter = LeanHookAdapter(self.root, marker_root=self.marker_root)

        def timeout():
            raise TimeoutError("host did not finish stdin")

        self.assertEqual(0, adapter.handle("PostToolUse", timeout).exit_code)
        for raw in (b"[]", b'"prompt"', b"null", object()):
            with self.subTest(raw=raw):
                self.assertEqual(
                    0, adapter.handle("PostToolUse", raw).exit_code)

    def test_session_resume_is_minimal_and_once_per_session(self):
        state = FlowState(
            ticket="REQ-5",
            path=DeliveryPath.FULL,
            phase=Phase.QUALITY,
            commit_pace=CommitPace.STAGED,
            current_cp="CP-2",
            artifacts=(
                ("spec", "docs/mae-flow/requirements/REQ-5/spec.md"),
                ("story", ".mae-flow-work/REQ-5/story.md"),
            ),
            decisions=(("private.long.history", "MUST-NOT-BE-INJECTED"),),
            risks=("database compatibility",),
            capabilities=(
                CapabilityAttempt(
                    "codecheck", "src-old", "env-old", "returned", "old"),
                CapabilityAttempt(
                    "build", "src-now", "env-now", "opaque-return", "latest"),
            ),
        )
        self.write_state(state)
        payload = {"session_id": "session-5", "cwd": self.root}

        first = self.invoke("SessionStart", payload)
        second = self.invoke("SessionStart", payload)

        self.assertEqual(0, first.returncode, first.stderr.decode("utf-8"))
        text = first.stdout.decode("utf-8")
        for fact in (
                "Mode: full", "Phase: quality", "CP: CP-2",
                "spec=docs/mae-flow/requirements/REQ-5/spec.md",
                "database compatibility", "build", "opaque-return",
                "latest"):
            self.assertIn(fact, text)
        self.assertNotIn("MUST-NOT-BE-INJECTED", text)
        self.assertNotIn("src-old", text)
        self.assertLess(len(text), 1800)
        self.assertEqual(b"", second.stdout)

    def test_prompt_is_recorded_raw_without_ack_or_choice_validation(self):
        self.write_state()
        payload = {
            "session_id": "session-natural",
            "prompt": "把 Story 的数据库边界改一下，我不接受固定 ACK。",
            "host_extension": {"unchanged": [1, "二"]},
        }
        result = self.invoke("UserPromptSubmit", payload)
        self.assertEqual(0, result.returncode, result.stderr.decode("utf-8"))
        self.assertEqual(b"", result.stdout)
        with open(self.events_path, encoding="utf-8") as stream:
            events = json.load(stream)
        self.assertEqual("UserPromptSubmit", events[-1]["event"])
        self.assertEqual(payload, events[-1]["payload"])

    def test_corrupt_active_state_does_not_lose_raw_user_prompt(self):
        with open(self.state_path, "wb") as stream:
            stream.write(b"corrupt-flow-state")
        payload = {
            "session_id": "corrupt-prompt",
            "prompt": "继续普通调查，不要猜测工具输出。",
        }
        result = self.invoke("UserPromptSubmit", payload)
        self.assertEqual(0, result.returncode, result.stderr.decode("utf-8"))
        with open(self.events_path, encoding="utf-8") as stream:
            events = json.load(stream)
        self.assertEqual(payload, events[-1]["payload"])

    def test_exit_releases_corrupt_active_state_and_is_idempotent(self):
        corrupt = b'{"engine":"lean-v1","broken":'
        with open(self.state_path, "wb") as stream:
            stream.write(corrupt)

        first = self.invoke(
            "UserPromptSubmit",
            {"session_id": "exit-1", "prompt": "/mae-flow:mae-flow exit"},
        )
        self.assertEqual(0, first.returncode, first.stderr.decode("utf-8"))
        self.assertFalse(os.path.exists(self.state_path))
        with open(self.pointer_path, encoding="utf-8") as stream:
            pointer = json.load(stream)
        snapshot = os.path.join(self.root, *pointer["snapshot"].split("/"))
        with open(snapshot, "rb") as stream:
            self.assertEqual(corrupt, stream.read())

        second = self.invoke(
            "UserPromptSubmit",
            {"session_id": "exit-1", "prompt": "退出 mae-flow"},
        )
        self.assertEqual(0, second.returncode, second.stderr.decode("utf-8"))
        with open(self.pointer_path, encoding="utf-8") as stream:
            self.assertEqual(pointer, json.load(stream))
        snapshots = os.listdir(os.path.dirname(snapshot))
        self.assertEqual(1, len(snapshots))

    def test_exit_release_precedes_best_effort_prompt_audit(self):
        self.write_state()
        observed = []

        def failing_sink(event, payload):
            observed.append((
                event,
                os.path.exists(self.state_path),
                os.path.isfile(self.pointer_path),
            ))
            raise OSError("audit unavailable")

        response = LeanHookAdapter(
            self.root,
            marker_root=self.marker_root,
            event_sink=failing_sink,
        ).handle(
            "UserPromptSubmit",
            json.dumps({"prompt": "请退出这个工作流"}),
        )
        self.assertEqual(0, response.exit_code)
        self.assertEqual([("UserPromptSubmit", False, True)], observed)

    def test_unambiguous_natural_exit_variants_release_immediately(self):
        prompts = (
            "我想退出 mae-flow。",
            "我决定停止这个工作流，直接开发。",
            "不再使用 mae-flow 了",
            "please disable this workflow now",
        )
        for index, prompt in enumerate(prompts):
            with self.subTest(prompt=prompt):
                self.write_state()
                result = self.invoke("UserPromptSubmit", {
                    "session_id": "explicit-%s" % index,
                    "prompt": prompt,
                })
                self.assertEqual(0, result.returncode)
                self.assertFalse(os.path.exists(self.state_path))
                os.remove(self.pointer_path)

    def test_exit_questions_and_other_natural_language_do_not_exit(self):
        prompts = (
            "怎么退出 mae-flow？",
            "能退出这个工作流吗?",
            "退出后会怎样",
            "请继续实现，别退出",
        )
        for index, prompt in enumerate(prompts):
            with self.subTest(prompt=prompt):
                self.write_state()
                result = self.invoke(
                    "UserPromptSubmit",
                    {"session_id": "question-%s" % index, "prompt": prompt},
                )
                self.assertEqual(0, result.returncode)
                self.assertTrue(os.path.isfile(self.state_path))
                os.remove(self.state_path)

    def test_shared_safety_kernel_blocks_only_confirmed_pretool_risks(self):
        state = replace(
            self.write_state(),
            phase=Phase.CONSTRUCTION,
        )
        self.write_state(state)
        cases = (
            ("git reset --hard HEAD", 2),
            ("git add .", 2),
            ("git commit -m update", 2),
            ("git status --short", 0),
            ("echo git commit", 0),
            ("build-tool --opaque-output", 0),
        )
        for command, expected in cases:
            with self.subTest(command=command):
                result = self.invoke("PreToolUse", {
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                })
                self.assertEqual(
                    expected, result.returncode,
                    (result.stdout + result.stderr).decode("utf-8"),
                )

    def test_corrupt_state_blocks_delivery_but_not_ordinary_unknown_work(self):
        with open(self.state_path, "wb") as stream:
            stream.write(b"broken-state")
        for command, expected in (
                ("git push origin HEAD", 2),
                ("git commit -m update", 2),
                ("git status --short", 0),
                ("internal-codecheck --unknown", 0)):
            with self.subTest(command=command):
                result = self.invoke("PreToolUse", {
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                })
                self.assertEqual(expected, result.returncode)

    def test_exact_manifest_facts_allow_commit_and_push(self):
        state = replace(
            self.write_state(),
            phase=Phase.DELIVERY,
            delivery_files=("src/a.cpp", "tests/a_test.cpp"),
        )
        self.write_state(state)
        files = ("tests/a_test.cpp", "src/a.cpp")
        facts = LeanHookFactPorts(
            staged_files=lambda unused: files,
            commit_files=lambda unused: files,
        )
        adapter = LeanHookAdapter(
            self.root, marker_root=self.marker_root, fact_ports=facts)
        for command in ("git commit -m update", "git push origin HEAD"):
            with self.subTest(command=command):
                response = adapter.handle("PreToolUse", {
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                })
                self.assertEqual(0, response.exit_code, response.stderr)

    def test_fact_port_failure_does_not_hide_an_independent_danger(self):
        state = replace(self.write_state(), phase=Phase.CONSTRUCTION)
        self.write_state(state)

        def unavailable(unused):
            raise OSError("Git fact provider unavailable")

        adapter = LeanHookAdapter(
            self.root,
            marker_root=self.marker_root,
            fact_ports=LeanHookFactPorts(staged_files=unavailable),
        )
        reset = adapter.handle("PreToolUse", {
            "tool_name": "Bash",
            "tool_input": {"command": "git reset --hard HEAD"},
        })
        ordinary = adapter.handle("PreToolUse", {
            "tool_name": "Bash",
            "tool_input": {"command": "internal-build --opaque"},
        })
        self.assertEqual(2, reset.exit_code)
        self.assertEqual(0, ordinary.exit_code)

    def test_posttool_records_only_explicit_opaque_capability_facts(self):
        self.write_state()
        unknown = self.invoke("PostToolUse", {
            "tool_name": "Bash",
            "tool_response": "BUILD SUCCESS maybe -- private format",
        })
        self.assertEqual(0, unknown.returncode)
        with open(self.state_path, encoding="utf-8") as stream:
            unchanged = FlowState.from_dict(json.load(stream))
        self.assertEqual((), unchanged.capabilities)

        fact = {
            "kind": "build",
            "source_revision": "opaque-source-fact",
            "environment_revision": "opaque-env-fact",
            "outcome": "returned",
            "summary": "host supplied this fact without output parsing",
        }
        recorded = self.invoke("PostToolUse", {
            "tool_name": "Skill",
            "capability_fact": fact,
            "tool_response": {"unknown": ["shape"]},
        })
        self.assertEqual(0, recorded.returncode, recorded.stderr.decode("utf-8"))
        with open(self.state_path, encoding="utf-8") as stream:
            state = FlowState.from_dict(json.load(stream))
        self.assertEqual(fact, {
            "kind": state.capabilities[-1].kind,
            "source_revision": state.capabilities[-1].source_revision,
            "environment_revision": state.capabilities[-1].environment_revision,
            "outcome": state.capabilities[-1].outcome,
            "summary": state.capabilities[-1].summary,
        })


if __name__ == "__main__":
    unittest.main()
