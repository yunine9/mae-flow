#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Portable tests for behavior that must hold on real Windows runners."""

import json
import ntpath
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


TESTS = os.path.abspath(os.path.dirname(__file__))
ROOT = os.path.abspath(os.path.join(TESTS, "..", ".."))
SCRIPTS = os.path.abspath(os.path.join(TESTS, ".."))
HOOK_HARNESS = os.path.join(TESTS, "lean_hook_harness.py")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core import state_store  # noqa: E402
from mae_flow_core.adapters.lean_hook import LeanHookAdapter  # noqa: E402
from mae_flow_core.guard.manifest import DeliveryManifest  # noqa: E402
from mae_flow_core.orchestration import (  # noqa: E402
    CommitPace,
    DeliveryPath,
    FlowState,
    Phase,
)
from mae_flow_core.orchestration.documents import DocumentPaths  # noqa: E402
from mae_flow_core.orchestration.guidance import render_guidance  # noqa: E402
import mae_flow_core.orchestration.guidance as guidance_module  # noqa: E402


class WindowsPathAndEncodingTests(unittest.TestCase):
    def test_nt_paths_preserve_display_and_fold_backslash_case_identity(self):
        paths = DocumentPaths.for_ticket(r"C:\Repo", "REQ-WIN")
        self.assertEqual(r"C:\Repo", ntpath.splitdrive(paths.spec)[0] + "\\Repo")
        self.assertTrue(paths.spec.startswith(r"C:\Repo\docs\specs"))

        drive = DeliveryManifest.from_paths(
            [r"C:\Repo\Src\Feature.cpp"],
            repository_root=r"c:\repo",
        )
        unc = DeliveryManifest.from_paths(
            [r"\\Server\Share\Src\Feature.cpp"],
            repository_root=r"\\server\share",
        )
        self.assertEqual(("Src/Feature.cpp",), drive.files)
        self.assertEqual(("Src/Feature.cpp",), unc.files)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            DeliveryManifest.from_paths(
                [r"Src\Feature.cpp", "src/feature.cpp"])

    def test_utf8_bom_state_and_gb18030_hook_payload_are_accepted(self):
        with tempfile.TemporaryDirectory() as root:
            bom_path = os.path.join(root, "defaults.json")
            with open(bom_path, "wb") as stream:
                stream.write(b"\xef\xbb\xbf" + json.dumps({
                    "name": "中文配置",
                }, ensure_ascii=False).encode("utf-8"))
            self.assertEqual(
                {"name": "中文配置"}, state_store.read_json(bom_path))

            state_path = os.path.join(root, ".mae-flow.json")
            with open(state_path, "w", encoding="utf-8") as stream:
                json.dump(FlowState.new(
                    "REQ-GB", DeliveryPath.FOCUSED,
                    CommitPace.CONTINUOUS).to_dict(), stream)
            events = []
            adapter = LeanHookAdapter(
                root,
                marker_root=os.path.join(root, "markers"),
                event_sink=lambda event, payload: events.append(
                    (event, dict(payload))),
            )
            payload = {
                "session_id": "gb18030",
                "prompt": "请继续局部修复，不要猜测输出。",
            }
            response = adapter.handle(
                "UserPromptSubmit",
                json.dumps(payload, ensure_ascii=False).encode("gb18030"),
            )
            self.assertEqual(0, response.exit_code)
            self.assertEqual(
                [("UserPromptSubmit", payload)], events)

    def test_crlf_phase_resource_is_read_with_universal_newlines(self):
        with tempfile.TemporaryDirectory() as root:
            resource = os.path.join(root, "startup.md")
            with open(resource, "wb") as stream:
                stream.write(
                    b"# Intake\r\n\r\nObjective: inspect scope.\r\n"
                    b"Inspect: repository facts.\r\n"
                    b"Stop for the user: startup.\r\n"
                    b"Outputs: cursor.\r\nNext: Spec.\r\n")
            state = FlowState.new(
                "REQ-CRLF", DeliveryPath.FULL, CommitPace.CONTINUOUS)
            with mock.patch.object(guidance_module, "_PHASE_ROOT", root):
                rendered = render_guidance(state)

            self.assertIn("# Intake\n\nObjective", rendered)
            self.assertNotIn("\r", rendered)


class WindowsLockedFileTests(unittest.TestCase):
    def test_replace_retry_stops_on_success_and_is_bounded_without_waiting(self):
        transient_attempts = []
        transient_delays = []

        def transient_replace(source, destination):
            transient_attempts.append((source, destination))
            if len(transient_attempts) < 3:
                raise PermissionError("simulated transient Windows file lock")

        with mock.patch.object(
                state_store.os, "replace",
                side_effect=transient_replace), mock.patch.object(
                    state_store.time, "sleep",
                    side_effect=transient_delays.append):
            state_store._replace_with_retry(
                "source.tmp", "state.json", attempts=5, base_delay=0.1)

        self.assertEqual(3, len(transient_attempts))
        self.assertEqual([0.1, 0.2], transient_delays)

        permanent_attempts = []
        permanent_delays = []

        def locked_replace(source, destination):
            permanent_attempts.append((source, destination))
            raise PermissionError("simulated Windows file lock")

        with mock.patch.object(
                state_store.os, "replace", side_effect=locked_replace), mock.patch.object(
                    state_store.time, "sleep",
                    side_effect=permanent_delays.append):
            with self.assertRaises(PermissionError):
                state_store._replace_with_retry(
                    "source.tmp", "state.json", attempts=4, base_delay=0.25)

        self.assertEqual(4, len(permanent_attempts))
        self.assertEqual([0.25, 0.5, 1.0], permanent_delays)

    def test_delete_retry_stops_on_success_and_is_bounded_on_permanent_lock(self):
        transient_attempts = []
        transient_delays = []

        def transient_delete(path):
            transient_attempts.append(path)
            if len(transient_attempts) < 3:
                raise PermissionError("simulated transient lock")

        with mock.patch.object(
                state_store.os, "remove", side_effect=transient_delete), mock.patch.object(
                    state_store.time, "sleep",
                    side_effect=transient_delays.append):
            state_store.remove_with_retry(
                "state.json", attempts=5, base_delay=0.1)

        self.assertEqual(3, len(transient_attempts))
        self.assertEqual([0.1, 0.2], transient_delays)

        permanent_attempts = []
        permanent_delays = []

        def permanent_delete(path):
            permanent_attempts.append(path)
            raise PermissionError("simulated permanent lock")

        with mock.patch.object(
                state_store.os, "remove", side_effect=permanent_delete), mock.patch.object(
                    state_store.time, "sleep",
                    side_effect=permanent_delays.append):
            with self.assertRaises(PermissionError):
                state_store.remove_with_retry(
                    "state.json", attempts=3, base_delay=0.1)
        self.assertEqual(3, len(permanent_attempts))
        self.assertEqual([0.1, 0.2], permanent_delays)


class WindowsProcessBoundaryTests(unittest.TestCase):
    def invoke(self, root, event, payload):
        return subprocess.run(
            [
                sys.executable,
                HOOK_HARNESS,
                event,
                "--root", root,
                "--marker-root", os.path.join(root, "markers"),
            ],
            input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            capture_output=True,
            check=False,
            timeout=5,
        )

    def test_python_command_is_discoverable_without_assuming_python3(self):
        with tempfile.TemporaryDirectory() as root:
            name = "python.exe" if os.name == "nt" else "python"
            launcher = os.path.join(root, name)
            with open(launcher, "wb") as stream:
                stream.write(b"fake launcher for discovery only\n")
            os.chmod(launcher, os.stat(launcher).st_mode | stat.S_IXUSR)

            discovered = shutil.which("python", path=root)

            self.assertIsNotNone(discovered)
            self.assertEqual(name.casefold(), os.path.basename(discovered).casefold())

    def test_capability_return_fact_is_recorded_without_output_parsing(self):
        with tempfile.TemporaryDirectory() as root:
            state_path = os.path.join(root, ".mae-flow.json")
            with open(state_path, "w", encoding="utf-8") as stream:
                json.dump(FlowState.new(
                    "REQ-SYNC", DeliveryPath.FULL,
                    CommitPace.CONTINUOUS).to_dict(), stream)
            returned = subprocess.run(
                [
                    sys.executable,
                    os.path.join(SCRIPTS, "mae-flow.py"),
                    "advance", "capability-returned",
                    "--key", "build",
                    "--decision",
                    '{"private":"UNKNOWN","returncode":0}',
                ],
                cwd=root,
                capture_output=True,
                check=False,
                timeout=10,
            )

            self.assertEqual(0, returned.returncode, returned.stderr)
            with open(state_path, encoding="utf-8") as stream:
                state = FlowState.from_dict(json.load(stream))
            self.assertEqual(1, len(state.capabilities))
            self.assertEqual("returned", state.capabilities[0].outcome)
            self.assertEqual(
                '{"private":"UNKNOWN","returncode":0}',
                state.capabilities[0].summary,
            )

    def test_ci_uses_real_windows_python38_lane_and_commit_range_diff(self):
        workflow_path = os.path.join(
            ROOT, ".github", "workflows", "selftest.yml")
        with open(workflow_path, encoding="utf-8") as stream:
            workflow = stream.read()
        self.assertIn("windows-latest", workflow)
        self.assertIn("ubuntu-latest", workflow)
        self.assertIn("python: '3.8'", workflow)
        self.assertIn("python: '3.11'", workflow)
        self.assertIn("actions/setup-python", workflow)
        self.assertIn("python-version: ${{ matrix.python }}", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn(
            'git diff --check "${{ github.event.pull_request.base.sha '
            '|| github.event.before }}..${{ github.sha }}"',
            workflow,
        )
        self.assertNotIn("run: git diff --check\n", workflow)
        self.assertIn("python scripts/selftest.py", workflow)
        self.assertNotIn("python3", workflow)

        operational_docs = (
            "README.md",
            "MAINTAINERS.md",
            "FIELD-TEST.md",
            "CLEAN-ROOM-TEST.md",
        )
        for relative in operational_docs:
            with self.subTest(relative=relative):
                with open(
                        os.path.join(ROOT, relative), encoding="utf-8") as stream:
                    self.assertNotIn("python3", stream.read())


if __name__ == "__main__":
    unittest.main()
