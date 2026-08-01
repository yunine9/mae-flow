#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Process and state contracts for the test-only lean Hook adapter."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from unittest import mock


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
from mae_flow_core.state_store import ProjectStateLock  # noqa: E402


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

    def test_session_marker_falls_back_from_unavailable_primary(self):
        state = self.write_state()
        primary_file = os.path.join(self.root, "occupied-primary")
        with open(primary_file, "w", encoding="utf-8") as stream:
            stream.write("not a directory")
        fallback = os.path.join(
            self.root, ".mae-flow-work", ".lean-hook-sessions")
        adapter = LeanHookAdapter(
            self.root,
            marker_root=primary_file,
            local_marker_root=fallback,
        )
        payload = {"session_id": "windows-permission-session"}

        first = adapter.handle("SessionStart", payload)
        second = adapter.handle("SessionStart", payload)

        self.assertIn("Phase: %s" % state.phase.value, first.stdout)
        self.assertEqual("", second.stdout)
        self.assertEqual(1, len(os.listdir(fallback)))

    def test_session_marker_falls_back_from_permission_error(self):
        state = self.write_state()
        primary = os.path.join(self.root, "permission-denied-primary")
        fallback = os.path.join(
            self.root, ".mae-flow-work", ".lean-hook-sessions")
        adapter = LeanHookAdapter(
            self.root,
            marker_root=primary,
            local_marker_root=fallback,
        )
        real_makedirs = os.makedirs

        def makedirs(path, *args, **kwargs):
            if os.path.abspath(path) == os.path.abspath(primary):
                raise PermissionError("simulated Windows access denial")
            return real_makedirs(path, *args, **kwargs)

        payload = {"session_id": "permission-error-session"}
        with mock.patch(
                "mae_flow_core.adapters.lean_hook.os.makedirs",
                side_effect=makedirs):
            first = adapter.handle("SessionStart", payload)
            second = adapter.handle("SessionStart", payload)

        self.assertIn("Phase: %s" % state.phase.value, first.stdout)
        self.assertEqual("", second.stdout)
        self.assertEqual(1, len(os.listdir(fallback)))

    def test_session_summary_stays_quiet_if_both_marker_roots_fail(self):
        self.write_state()
        primary = os.path.join(self.root, "occupied-primary")
        fallback = os.path.join(self.root, "occupied-fallback")
        for path in (primary, fallback):
            with open(path, "w", encoding="utf-8") as stream:
                stream.write("not a directory")
        adapter = LeanHookAdapter(
            self.root,
            marker_root=primary,
            local_marker_root=fallback,
        )

        first = adapter.handle(
            "SessionStart", {"session_id": "unwritable-session"})
        second = adapter.handle(
            "SessionStart", {"session_id": "unwritable-session"})

        self.assertEqual("", first.stdout)
        self.assertEqual("", second.stdout)

    def test_missing_session_id_uses_one_stable_cursor_marker(self):
        self.write_state()
        adapter = LeanHookAdapter(self.root, marker_root=self.marker_root)

        first = adapter.handle("SessionStart", {})
        second = adapter.handle("SessionStart", {})

        self.assertIn("Phase: startup", first.stdout)
        self.assertEqual("", second.stdout)
        self.assertEqual(1, len(os.listdir(self.marker_root)))

    def test_resume_summary_has_total_budget_and_omission_counts(self):
        long_text = "长字段" * 400
        state = FlowState(
            ticket="REQ-BUDGET",
            path=DeliveryPath.FULL,
            phase=Phase.DELIVERY,
            commit_pace=CommitPace.STAGED,
            current_cp="CP-FINAL-" + long_text,
            artifacts=tuple(
                ("artifact-%02d-%s" % (index, long_text),
                 "path/%02d/%s" % (index, long_text))
                for index in range(20)),
            risks=tuple(
                "risk-%02d-%s" % (index, long_text)
                for index in range(20)),
            capabilities=(CapabilityAttempt(
                "build-opaque-" + long_text,
                "source-opaque-" + long_text,
                "environment-opaque-" + long_text,
                "returned-opaque-" + long_text,
                "summary-opaque-" + long_text,
            ),),
        )
        self.write_state(state)

        response = LeanHookAdapter(
            self.root, marker_root=self.marker_root).handle(
                "SessionStart", {"session_id": "budget-session"})

        self.assertLessEqual(len(response.stdout), 1200)
        self.assertIn("Phase: delivery", response.stdout)
        self.assertIn("CP: CP-FINAL-", response.stdout)
        self.assertEqual(2, response.stdout.count("另有 18 项"))
        self.assertIn("Last capability: build-opaque-", response.stdout)
        self.assertIn("outcome=returned-opaque-", response.stdout)

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

    def test_exit_falls_back_to_snapshot_pointer_when_state_move_fails(self):
        original = b'{"engine":"lean-v1","partial":"bytes"}'
        with open(self.state_path, "wb") as stream:
            stream.write(original)

        def fail_move(unused_source, unused_target):
            raise PermissionError("Windows scanner holds state path")

        adapter = LeanHookAdapter(
            self.root,
            marker_root=self.marker_root,
            move_state=fail_move,
        )
        response = adapter.handle(
            "UserPromptSubmit", {"prompt": "退出 mae-flow"})

        self.assertEqual(0, response.exit_code, response.stderr)
        self.assertTrue(os.path.isfile(self.state_path))
        with open(self.pointer_path, encoding="utf-8") as stream:
            pointer = json.load(stream)
        snapshot = os.path.join(self.root, *pointer["snapshot"].split("/"))
        with open(snapshot, "rb") as stream:
            self.assertEqual(original, stream.read())
        resumed = adapter.handle(
            "SessionStart", {"session_id": "after-exit"})
        self.assertEqual("", resumed.stdout)
        with open(self.events_path, encoding="utf-8") as stream:
            captured_before = json.load(stream)
        adapter.handle("UserPromptSubmit", {"prompt": "普通开发继续"})
        with open(self.events_path, encoding="utf-8") as stream:
            self.assertEqual(captured_before, json.load(stream))

    def test_exit_pointer_rejects_non_snapshot_and_lexical_escape_paths(self):
        self.write_state()
        snapshot_dir = os.path.join(
            self.root, ".mae-flow-work", "exited")
        os.makedirs(snapshot_dir, exist_ok=True)
        ordinary = os.path.join(self.root, "ordinary.json")
        wrong_name = os.path.join(snapshot_dir, "notes.json")
        for path in (ordinary, wrong_name):
            with open(path, "w", encoding="utf-8") as stream:
                stream.write("{}\n")
        root_name = os.path.basename(self.root)
        cases = (
            "ordinary.json",
            ".mae-flow-work/exited/notes.json",
            "../%s/ordinary.json" % root_name,
            ordinary,
            r"C:\repo\.mae-flow-work\exited\flow-1.json",
        )
        adapter = LeanHookAdapter(self.root, marker_root=self.marker_root)

        for relative in cases:
            with self.subTest(snapshot=relative):
                with open(self.pointer_path, "w", encoding="utf-8") as stream:
                    json.dump({
                        "status": "exited",
                        "snapshot": relative,
                        "exited_at_ns": 1,
                    }, stream)
                self.assertEqual("flow", adapter._runtime()[0].mode)

    def test_exit_pointer_rejects_pointer_and_snapshot_symlink_escape(self):
        self.write_state()
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        snapshot_dir = os.path.join(
            self.root, ".mae-flow-work", "exited")
        os.makedirs(snapshot_dir, exist_ok=True)
        real_snapshot = os.path.join(snapshot_dir, "flow-1.json")
        with open(real_snapshot, "w", encoding="utf-8") as stream:
            stream.write("{}\n")
        pointer_data = {
            "status": "exited",
            "snapshot": ".mae-flow-work/exited/flow-1.json",
            "exited_at_ns": 1,
        }
        external_pointer = os.path.join(
            outside.name, "external-pointer.json")
        with open(external_pointer, "w", encoding="utf-8") as stream:
            json.dump(pointer_data, stream)
        try:
            os.symlink(external_pointer, self.pointer_path)
        except (OSError, NotImplementedError) as exc:
            self.skipTest("symlinks unavailable: %s" % exc)
        adapter = LeanHookAdapter(self.root, marker_root=self.marker_root)
        self.assertEqual("flow", adapter._runtime()[0].mode)

        os.unlink(self.pointer_path)
        os.unlink(real_snapshot)
        external_snapshot = os.path.join(
            outside.name, "external-snapshot.json")
        with open(external_snapshot, "w", encoding="utf-8") as stream:
            stream.write("{}\n")
        os.symlink(external_snapshot, real_snapshot)
        with open(self.pointer_path, "w", encoding="utf-8") as stream:
            json.dump(pointer_data, stream)
        self.assertEqual("flow", adapter._runtime()[0].mode)

    def test_exit_pointer_accepts_dedicated_windows_separator_snapshot(self):
        self.write_state()
        snapshot_dir = os.path.join(
            self.root, ".mae-flow-work", "exited")
        os.makedirs(snapshot_dir, exist_ok=True)
        snapshot = os.path.join(snapshot_dir, "flow-123-2.json")
        with open(snapshot, "w", encoding="utf-8") as stream:
            stream.write("{}\n")
        with open(self.pointer_path, "w", encoding="utf-8") as stream:
            json.dump({
                "status": "exited",
                "snapshot": r".mae-flow-work\exited\flow-123-2.json",
                "exited_at_ns": 123,
            }, stream)

        runtime, state = LeanHookAdapter(
            self.root, marker_root=self.marker_root)._runtime()

        self.assertEqual("inactive", runtime.mode)
        self.assertIsNone(state)

    def test_exit_does_not_wait_twice_when_project_lock_is_held(self):
        original = b"corrupt active bytes"
        with open(self.state_path, "wb") as stream:
            stream.write(original)
        adapter = LeanHookAdapter(self.root, marker_root=self.marker_root)

        started = time.monotonic()
        with ProjectStateLock(self.root):
            response = adapter.handle(
                "UserPromptSubmit", {"prompt": "退出 mae-flow"})
        elapsed = time.monotonic() - started

        self.assertEqual(0, response.exit_code, response.stderr)
        self.assertLess(elapsed, 0.5)
        self.assertTrue(os.path.isfile(self.state_path))
        with open(self.pointer_path, encoding="utf-8") as stream:
            pointer = json.load(stream)
        with open(
                os.path.join(self.root, *pointer["snapshot"].split("/")),
                "rb") as stream:
            self.assertEqual(original, stream.read())

    def test_failed_snapshot_release_returns_two_without_audit(self):
        self.write_state()
        audited = []

        def fail_snapshot(unused_path, unused_data):
            raise OSError("snapshot directory is unavailable")

        adapter = LeanHookAdapter(
            self.root,
            marker_root=self.marker_root,
            snapshot_writer=fail_snapshot,
            event_sink=lambda event, payload: audited.append((event, payload)),
        )
        with ProjectStateLock(self.root):
            response = adapter.handle(
                "UserPromptSubmit", {"prompt": "退出 mae-flow"})

        self.assertEqual(2, response.exit_code)
        self.assertIn("exit", response.stderr.casefold())
        self.assertTrue(os.path.isfile(self.state_path))
        self.assertFalse(os.path.exists(self.pointer_path))
        self.assertEqual([], audited)

    def test_failed_pointer_release_returns_two_without_audit(self):
        self.write_state()
        audited = []

        def fail_pointer(unused_path, unused_data):
            raise OSError("pointer cannot be replaced")

        response = LeanHookAdapter(
            self.root,
            marker_root=self.marker_root,
            pointer_writer=fail_pointer,
            event_sink=lambda event, payload: audited.append((event, payload)),
        ).handle("UserPromptSubmit", {"prompt": "退出 mae-flow"})

        self.assertEqual(2, response.exit_code)
        self.assertIn("exit", response.stderr.casefold())
        self.assertFalse(os.path.exists(self.pointer_path))
        self.assertEqual([], audited)

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
