#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lean phase guidance and test-only harness contracts."""

import json
import os
import subprocess
import sys
import tempfile
import unittest


SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.orchestration.models import (  # noqa: E402
    CommitPace,
    DeliveryPath,
    FlowState,
    Phase,
)
from mae_flow_core.orchestration.guidance import render_guidance  # noqa: E402
import lean_harness  # noqa: E402


HARNESS = os.path.join(os.path.dirname(__file__), "lean_harness.py")


def state_for(phase):
    return FlowState(
        ticket="REQ-42",
        path=DeliveryPath.FULL,
        phase=phase,
        commit_pace=CommitPace.STAGED,
        current_cp="CP2",
        artifacts=(
            ("request", "docs/requests/REQ-42.md"),
            ("spec", "openspec/changes/req-42/change.md"),
            ("story", "docs/story/STORY-REQ-42.md"),
        ),
        decisions=(("private.detail", "must not be rendered"),),
        risks=("database migration remains unresolved",),
    )


class LeanGuidanceTests(unittest.TestCase):
    def test_each_phase_renders_outcome_focused_recovery_guidance(self):
        for phase in Phase:
            with self.subTest(phase=phase):
                text = render_guidance(state_for(phase))
                self.assertIn("Ticket: REQ-42", text)
                self.assertIn("Path: full", text)
                self.assertIn("Phase: %s" % phase.value, text)
                self.assertIn("CP: CP2", text)
                self.assertIn("Objective", text)
                self.assertIn("Inspect", text)
                self.assertIn("Stop for the user", text)
                self.assertIn("Outputs", text)
                self.assertIn("Next", text)
                self.assertIn("docs/requests/REQ-42.md", text)
                self.assertIn("database migration remains unresolved", text)

    def test_guidance_omits_legacy_ritual_and_irrelevant_state(self):
        forbidden = (
            "done --ack",
            "证据令牌",
            "任务卡",
            "report-hash",
            "exact ACK",
            "sleep",
            "poll",
            "must not be rendered",
        )
        for phase in Phase:
            with self.subTest(phase=phase):
                text = render_guidance(state_for(phase))
                for term in forbidden:
                    self.assertNotIn(term, text)

    def test_phase_ownership_and_quality_retry_policy_are_explicit(self):
        spec = render_guidance(state_for(Phase.SPEC))
        story = render_guidance(state_for(Phase.STORY))
        construction = render_guidance(state_for(Phase.CONSTRUCTION))
        quality = render_guidance(state_for(Phase.QUALITY))
        self.assertIn("WHAT", spec)
        self.assertIn("HOW", story)
        self.assertIn("cumulative UT handoff", construction)
        self.assertIn("at most once", quality)
        self.assertIn("meaningful change", quality)
        self.assertIn("user chooses", quality)


class LeanHarnessTests(unittest.TestCase):
    def run_harness(self, state_path, *arguments):
        return subprocess.run(
            [sys.executable, HARNESS, "--state", state_path, *arguments],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )

    def test_end_to_end_commands_persist_direct_orchestration_results(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "flow.json")
            started = self.run_harness(
                path, "start", "REQ-9", "focused", "continuous")
            advanced = self.run_harness(
                path, "advance", "startup-confirmed")
            decided = self.run_harness(
                path, "decision", "construction.scope", "Keep the fix local.")
            current = self.run_harness(path, "current")
            exited = self.run_harness(path, "exit")

            self.assertEqual(0, started.returncode, started.stderr)
            self.assertEqual(0, advanced.returncode, advanced.stderr)
            self.assertEqual(0, decided.returncode, decided.stderr)
            self.assertEqual(0, current.returncode, current.stderr)
            self.assertEqual(0, exited.returncode, exited.stderr)
            self.assertIn("Phase: construction", current.stdout)
            with open(path, encoding="utf-8") as stream:
                persisted = json.load(stream)
            self.assertEqual("exited", persisted["status"])
            self.assertEqual("construction", persisted["phase"])
            self.assertIn(
                {"key": "construction.scope", "value": "Keep the fix local."},
                persisted["decisions"],
            )

    def test_exit_succeeds_from_every_phase(self):
        with tempfile.TemporaryDirectory() as root:
            for phase in Phase:
                with self.subTest(phase=phase):
                    path = os.path.join(root, "%s.json" % phase.value)
                    with open(path, "w", encoding="utf-8") as stream:
                        json.dump(state_for(phase).to_dict(), stream)
                    result = self.run_harness(path, "exit")
                    self.assertEqual(0, result.returncode, result.stderr)
                    with open(path, encoding="utf-8") as stream:
                        persisted = json.load(stream)
                    self.assertEqual("exited", persisted["status"])
                    self.assertEqual(phase.value, persisted["phase"])

    def test_invalid_command_does_not_rewrite_caller_state(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "flow.json")
            with open(path, "w", encoding="utf-8") as stream:
                json.dump(state_for(Phase.SPEC).to_dict(), stream)
            with open(path, "rb") as stream:
                before = stream.read()

            result = self.run_harness(path, "advance", "")

            self.assertEqual(2, result.returncode)
            self.assertIn("error:", result.stderr)
            with open(path, "rb") as stream:
                self.assertEqual(before, stream.read())

    def test_encoding_failure_preserves_state_and_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "flow.json")
            seeded = b'{"known":"recovery cursor"}\n'
            with open(path, "wb") as stream:
                stream.write(seeded)
            state = state_for(Phase.CONSTRUCTION).with_decision(
                "construction.note", "invalid surrogate: \ud800")

            with self.assertRaises(UnicodeEncodeError):
                lean_harness._save(path, state)

            with open(path, "rb") as stream:
                self.assertEqual(seeded, stream.read())
            self.assertEqual(["flow.json"], os.listdir(root))


if __name__ == "__main__":
    unittest.main()
