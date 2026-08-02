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
from mae_flow_core.application.hooks.models import HookResponse  # noqa: E402
from mae_flow_core.orchestration import (  # noqa: E402
    AdvanceRequest,
    CapabilityAttempt,
    CommitPace,
    DeliveryPath,
    FlowState,
    Phase,
    advance_flow,
)
from mae_flow_core.orchestration.delivery import (  # noqa: E402
    DELIVERY_RECEIPT_KEY,
    issue_delivery_receipt,
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

    def receipt_state(self):
        state = FlowState(
            ticket="REQ-5",
            path=DeliveryPath.FOCUSED,
            phase=Phase.DELIVERY,
            commit_pace=CommitPace.CONTINUOUS,
            delivery_files=("src/a.cpp", "tests/a_test.cpp"),
            decisions=(
                ("delivery.commit_message", "[REQ-5][fix]修复提交格式"),
                ("delivery.plan.remote", "origin"),
                ("delivery.plan.destination_ref", "refs/heads/main"),
                ("delivery.plan.expected_destination_sha", "a" * 40),
                ("delivery.plan.new_branch", "false"),
            ),
        )
        receipt = issue_delivery_receipt(
            state, "用户确认精确文件、提交信息和远端目标。")
        return replace(
            state,
            decisions=state.decisions + ((DELIVERY_RECEIPT_KEY, receipt),),
        )

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

    def test_legacy_stop_short_circuits_before_input_and_state_access(self):
        adapter = LeanHookAdapter(self.root, marker_root=self.marker_root)
        accesses = []

        def explosive_input():
            accesses.append("input")
            raise AssertionError("legacy stop read stdin")

        def explosive_runtime():
            accesses.append("runtime")
            raise AssertionError("legacy stop read state")

        adapter._runtime = explosive_runtime
        for event in ("Stop", "SubagentStop", "subagent_stop"):
            with self.subTest(event=event):
                self.assertEqual(
                    HookResponse(), adapter.handle(event, explosive_input))
        self.assertEqual([], accesses)

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

    def test_active_state_wins_over_stale_windows_separator_exit_pointer(self):
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

        self.assertEqual("flow", runtime.mode)
        self.assertIsNotNone(state)

    def test_exit_pointer_rejects_symlinked_snapshot_directory_components(self):
        pointer = {
            "status": "exited",
            "snapshot": ".mae-flow-work/exited/flow-77.json",
            "exited_at_ns": 77,
        }
        for component in ("work", "exited"):
            with self.subTest(component=component):
                case_root = os.path.join(self.root, "symlink-" + component)
                os.makedirs(case_root)
                with open(
                        os.path.join(case_root, ".mae-flow.json"),
                        "w", encoding="utf-8") as stream:
                    json.dump(FlowState.new(
                        "REQ-SYMLINK",
                        DeliveryPath.FULL,
                        CommitPace.CONTINUOUS,
                    ).to_dict(), stream)
                work = os.path.join(case_root, ".mae-flow-work")
                if component == "work":
                    target = os.path.join(case_root, "real-work")
                    snapshot_dir = os.path.join(target, "exited")
                    os.makedirs(snapshot_dir)
                    link = work
                else:
                    os.makedirs(work)
                    target = os.path.join(case_root, "real-exited")
                    os.makedirs(target)
                    snapshot_dir = target
                    link = os.path.join(work, "exited")
                try:
                    os.symlink(target, link)
                except (OSError, NotImplementedError) as exc:
                    self.skipTest("symlinks unavailable: %s" % exc)
                with open(
                        os.path.join(snapshot_dir, "flow-77.json"),
                        "w", encoding="utf-8") as stream:
                    stream.write("{}\n")
                with open(
                        os.path.join(case_root, ".mae-flow.json.exited"),
                        "w", encoding="utf-8") as stream:
                    json.dump(pointer, stream)

                runtime, state = LeanHookAdapter(
                    case_root,
                    marker_root=os.path.join(case_root, "markers"),
                )._runtime()

                self.assertEqual("flow", runtime.mode)
                self.assertIsNotNone(state)

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

    def test_canonical_apply_patch_extracts_exact_targets_for_safety(self):
        state = replace(self.write_state(), phase=Phase.STORY)
        self.write_state(state)
        cases = (
            (
                "*** Begin Patch\n"
                "*** Update File: .mae-flow.json\n"
                "@@\n-old\n+new\n"
                "*** End Patch\n",
                "control files",
            ),
            (
                "*** Begin Patch\n"
                "*** Add File: src/new_feature.py\n"
                "+value = 1\n"
                "*** End Patch\n",
                "semantic authorization",
            ),
        )
        for command, message in cases:
            with self.subTest(message=message):
                response = LeanHookAdapter(
                    self.root, marker_root=self.marker_root).handle(
                        "PreToolUse",
                        {
                            "tool_name": "apply_patch",
                            "tool_input": {"command": command},
                        },
                )
                self.assertEqual(2, response.exit_code)
                self.assertIn(message, response.stderr)

    def test_apply_patch_body_is_not_parsed_as_a_bash_command(self):
        state = replace(self.write_state(), phase=Phase.CONSTRUCTION)
        self.write_state(state)
        patch = (
            "*** Begin Patch\n"
            "*** Update File: src/help_text.py\n"
            "@@\n"
            "-message = 'old'\n"
            "+message = 'never run git reset --hard or rm -rf build'\n"
            "*** End Patch\n"
        )
        response = LeanHookAdapter(
            self.root, marker_root=self.marker_root).handle(
                "PreToolUse",
                {
                    "tool_name": "apply_patch",
                    "tool_input": {"command": patch},
                },
            )
        self.assertEqual(0, response.exit_code, response.stderr)

    def test_recursive_delete_uses_actual_commands_and_task_temp_fact(self):
        state = replace(self.write_state(), phase=Phase.CONSTRUCTION)
        self.write_state(state)
        task_temp = os.path.join(self.root, ".tmp", "task-5")
        facts = LeanHookFactPorts(
            task_owned_temp_dir=lambda unused: task_temp)
        adapter = LeanHookAdapter(
            self.root, marker_root=self.marker_root, fact_ports=facts)
        cases = (
            ("rm -rf build", 2),
            ("rm -rf %s" % task_temp, 0),
            ("echo rm -rf build", 0),
            ("printf 'rm -rf build'", 0),
        )
        for command, expected in cases:
            with self.subTest(command=command):
                response = adapter.handle("PreToolUse", {
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                })
                self.assertEqual(expected, response.exit_code, response.stderr)

    def test_corrupt_state_blocks_delivery_but_not_ordinary_unknown_work(self):
        with open(self.state_path, "wb") as stream:
            stream.write(b"broken-state")
        for command, expected in (
                ("git push origin HEAD", 2),
                ("git commit -m '[REQ-5][fix]修复状态'", 2),
                ("git reset --hard HEAD", 2),
                ("rm -rf build", 2),
                ("echo rm -rf build", 0),
                ("git status --short", 0),
                ("internal-codecheck --unknown", 0)):
            with self.subTest(command=command):
                result = self.invoke("PreToolUse", {
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                })
                self.assertEqual(expected, result.returncode)

    def test_exact_manifest_without_receipt_or_reservation_cannot_deliver(self):
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
        for command in (
                "git commit -m '[REQ-5][fix]修复提交格式'",
                "git push origin HEAD"):
            with self.subTest(command=command):
                response = adapter.handle("PreToolUse", {
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                })
                self.assertEqual(2, response.exit_code, response.stderr)

    def test_git_reservation_and_post_facts_complete_the_exact_receipt(self):
        self.write_state(self.receipt_state())
        repository = {
            "staged": (),
            "head": "1" * 40,
            "destination": "a" * 40,
            "head_files": (),
        }
        files = ("tests/a_test.cpp", "src/a.cpp")
        facts = LeanHookFactPorts(
            staged_files=lambda unused: repository["staged"],
            commit_files=lambda unused: files,
            head_sha=lambda unused: repository["head"],
            destination_sha=lambda unused: repository["destination"],
            head_commit_files=lambda unused: repository["head_files"],
        )
        adapter = LeanHookAdapter(
            self.root, marker_root=self.marker_root, fact_ports=facts)
        steps = (
            ("add-1", "git add src/a.cpp tests/a_test.cpp", "add"),
            (
                "commit-1",
                "git commit -m '[REQ-5][fix]修复提交格式'",
                "commit",
            ),
            (
                "push-1",
                "git push --force-with-lease=refs/heads/main:%s "
                "origin HEAD:refs/heads/main" % ("a" * 40),
                "push",
            ),
        )
        for tool_use_id, command, operation in steps:
            with self.subTest(operation=operation):
                pre = adapter.handle("PreToolUse", {
                    "tool_name": "Bash",
                    "tool_use_id": tool_use_id,
                    "tool_input": {"command": command},
                })
                self.assertEqual(0, pre.exit_code, pre.stderr)
                if operation == "add":
                    repository["staged"] = files
                elif operation == "commit":
                    repository["head"] = "b" * 40
                    repository["head_files"] = files
                else:
                    repository["destination"] = "b" * 40
                post = adapter.handle("PostToolUse", {
                    "tool_name": "Bash",
                    "tool_use_id": tool_use_id,
                    "tool_input": {"command": command},
                    "tool_response": "opaque host return",
                })
                self.assertEqual(0, post.exit_code, post.stderr)

        with open(self.state_path, encoding="utf-8") as stream:
            state = FlowState.from_dict(json.load(stream))
        keys = [key for key, unused in state.decisions]
        self.assertEqual(1, keys.count("delivery.git.commit_observation"))
        self.assertEqual(1, keys.count("delivery.git.push_observation"))
        completed = advance_flow(
            state,
            AdvanceRequest(
                "delivery-completed",
                decision_value="Hook observed the exact Git effects.",
            ),
        )
        self.assertEqual("complete", completed.state.status)

    def test_git_reservation_persistence_failure_is_fail_closed(self):
        self.write_state(self.receipt_state())
        facts = LeanHookFactPorts(
            staged_files=lambda unused: (),
            head_sha=lambda unused: "1" * 40,
        )
        adapter = LeanHookAdapter(
            self.root, marker_root=self.marker_root, fact_ports=facts)
        adapter._update_state = mock.Mock(side_effect=OSError("disk full"))

        response = adapter.handle("PreToolUse", {
            "tool_name": "Bash",
            "tool_use_id": "add-fail",
            "tool_input": {
                "command": "git add src/a.cpp tests/a_test.cpp",
            },
        })

        self.assertEqual(2, response.exit_code)
        self.assertIn("reservation", response.stderr.lower())

    def test_exact_manifest_does_not_bypass_commit_message_contract(self):
        state = replace(
            self.write_state(),
            phase=Phase.DELIVERY,
            delivery_files=("src/a.cpp", "tests/a_test.cpp"),
        )
        self.write_state(state)
        files = ("tests/a_test.cpp", "src/a.cpp")
        adapter = LeanHookAdapter(
            self.root,
            marker_root=self.marker_root,
            fact_ports=LeanHookFactPorts(staged_files=lambda unused: files),
        )

        response = adapter.handle("PreToolUse", {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m update"},
        })

        self.assertEqual(2, response.exit_code)
        self.assertIn("[REQ-5][feat|fix]", response.stderr)

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

    def test_posttool_records_only_reserved_opaque_capability_return(self):
        self.write_state()
        unknown = self.invoke("PostToolUse", {
            "tool_name": "Bash",
            "tool_response": "BUILD SUCCESS maybe -- private format",
        })
        self.assertEqual(0, unknown.returncode)
        with open(self.state_path, encoding="utf-8") as stream:
            unchanged = FlowState.from_dict(json.load(stream))
        self.assertEqual((), unchanged.capabilities)

        invocation = "tool-opaque-build-return"
        reserved = self.invoke("PreToolUse", {
            "tool_name": "Skill",
            "tool_use_id": invocation,
            "tool_input": {"skill": "build-fix"},
        })
        self.assertEqual(0, reserved.returncode, reserved.stderr.decode("utf-8"))
        summary = "host returned opaque data without output parsing"
        recorded = self.invoke("PostToolUse", {
            "tool_name": "Skill",
            "tool_use_id": invocation,
            "tool_input": {"skill": "build-fix"},
            "tool_response": summary,
        })
        self.assertEqual(0, recorded.returncode, recorded.stderr.decode("utf-8"))
        with open(self.state_path, encoding="utf-8") as stream:
            state = FlowState.from_dict(json.load(stream))
        self.assertEqual({
            "kind": "build",
            "source_revision": "build:startup:-",
            "environment_revision": "lean-workflow-v1",
            "outcome": "returned",
            "summary": summary,
        }, {
            "kind": state.capabilities[-1].kind,
            "source_revision": state.capabilities[-1].source_revision,
            "environment_revision": state.capabilities[-1].environment_revision,
            "outcome": state.capabilities[-1].outcome,
            "summary": state.capabilities[-1].summary,
        })


if __name__ == "__main__":
    unittest.main()
