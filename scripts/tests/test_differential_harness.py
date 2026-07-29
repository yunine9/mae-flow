#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the behavior-preserving differential harness."""

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TESTS = os.path.join(ROOT, "scripts", "tests")
if TESTS not in sys.path:
    sys.path.insert(0, TESTS)

from differential.normalize import normalize_text, normalize_value  # noqa: E402
from differential.runner import (  # noqa: E402
    assert_matches_golden,
    load_goldens,
    run_scenario,
)
from differential.snapshot import Snapshot  # noqa: E402


class DifferentialNormalizationTests(unittest.TestCase):
    def test_normalize_text_replaces_only_explicit_dynamic_values(self):
        replacements = {
            "/tmp/mf-123": "<TMP>",
            "2026-07-29 12:34:56": "<TIME>",
            "receipt-abcd": "<RECEIPT>",
        }
        actual = normalize_text(
            "path=/tmp/mf-123 at=2026-07-29 12:34:56 "
            "id=receipt-abcd semantic=2026-07-29",
            replacements,
        )
        self.assertEqual(
            "path=<TMP> at=<TIME> id=<RECEIPT> semantic=2026-07-29",
            actual,
        )

    def test_normalize_value_preserves_types_and_unknown_fields(self):
        source = {
            "path": "/tmp/mf-123/state.json",
            "nested": [{"at": "2026-07-29 12:34:56", "count": 2}],
            "unknown": {"keep": True},
        }
        actual = normalize_value(
            source,
            {
                "/tmp/mf-123": "<TMP>",
                "2026-07-29 12:34:56": "<TIME>",
            },
        )
        self.assertEqual(
            {
                "path": "<TMP>/state.json",
                "nested": [{"at": "<TIME>", "count": 2}],
                "unknown": {"keep": True},
            },
            actual,
        )

    def test_snapshot_round_trip_is_lossless(self):
        snapshot = Snapshot(
            stdout="out",
            stderr="err",
            returncode=2,
            files={"a.txt": {"sha256": "abc", "size": 3}},
            state={"flow": {"current": "build", "unknown": 7}},
            git={"branch": "main", "head": "deadbeef", "status": ""},
        )
        self.assertEqual(snapshot, Snapshot.from_dict(snapshot.to_dict()))


class DifferentialRunnerTests(unittest.TestCase):
    def test_stage0_runtime_scenarios_are_registered(self):
        from differential.scenarios import SCENARIOS
        self.assertTrue({
            "direct_current",
            "standalone_action_status",
            "corrupt_exit_repair",
            "terminal_pretooluse_bypass",
        }.issubset(SCENARIOS))

    def test_phase1_scenarios_match_fixed_baseline(self):
        golden_path = os.path.join(
            ROOT,
            "scripts",
            "tests",
            "differential",
            "goldens",
            "phase1.json",
        )
        goldens = load_goldens(golden_path)
        for name in (
                "inactive_pretooluse_bypass",
                "terminal_status",
                "corrupt_state_doctor"):
            with self.subTest(name=name):
                actual = run_scenario(ROOT, name)
                assert_matches_golden(self, name, actual, goldens)

    def test_unknown_scenario_is_rejected_without_running_process(self):
        with self.assertRaisesRegex(ValueError, "unknown scenario"):
            run_scenario(ROOT, "not-registered")

    def test_phase2_workflow_steps_matches_fixed_baseline(self):
        golden_path = os.path.join(
            ROOT,
            "scripts",
            "tests",
            "differential",
            "goldens",
            "phase2.json",
        )
        goldens = load_goldens(golden_path)
        actual = run_scenario(ROOT, "workflow_steps")
        assert_matches_golden(
            self,
            "workflow_steps",
            actual,
            goldens,
        )

    def test_phase3_ordinary_advance_matches_fixed_baseline(self):
        golden_path = os.path.join(
            ROOT,
            "scripts",
            "tests",
            "differential",
            "goldens",
            "phase3.json",
        )
        goldens = load_goldens(golden_path)
        actual = run_scenario(ROOT, "ordinary_advance")
        assert_matches_golden(
            self,
            "ordinary_advance",
            actual,
            goldens,
        )

    def test_phase4_evidence_rejection_matches_fixed_baseline(self):
        golden_path = os.path.join(
            ROOT,
            "scripts",
            "tests",
            "differential",
            "goldens",
            "phase4.json",
        )
        goldens = load_goldens(golden_path)
        actual = run_scenario(ROOT, "evidence_rejection")
        assert_matches_golden(
            self,
            "evidence_rejection",
            actual,
            goldens,
        )

    def test_phase5_active_gate_matches_fixed_baseline(self):
        golden_path = os.path.join(
            ROOT,
            "scripts",
            "tests",
            "differential",
            "goldens",
            "phase5.json",
        )
        goldens = load_goldens(golden_path)
        for name in ("active_gate_edit", "dangerous_gate_bash"):
            with self.subTest(name=name):
                actual = run_scenario(ROOT, name)
                assert_matches_golden(
                    self,
                    name,
                    actual,
                    goldens,
                )

    def test_phase6_compile_task_card_matches_fixed_baseline(self):
        golden_path = os.path.join(
            ROOT,
            "scripts",
            "tests",
            "differential",
            "goldens",
            "phase6.json",
        )
        goldens = load_goldens(golden_path)
        actual = run_scenario(ROOT, "compile_task_card")
        assert_matches_golden(
            self,
            "compile_task_card",
            actual,
            goldens,
        )

    def test_phase7_moonlight_finalize_matches_fixed_baseline(self):
        golden_path = os.path.join(
            ROOT,
            "scripts",
            "tests",
            "differential",
            "goldens",
            "phase7.json",
        )
        goldens = load_goldens(golden_path)
        actual = run_scenario(ROOT, "moonlight_finalize")
        assert_matches_golden(
            self,
            "moonlight_finalize",
            actual,
            goldens,
        )

    def test_phase9_combined_git_add_flags_matches_corrected_behavior(self):
        golden_path = os.path.join(
            ROOT,
            "scripts",
            "tests",
            "differential",
            "goldens",
            "phase9.json",
        )
        goldens = load_goldens(golden_path)
        actual = run_scenario(ROOT, "combined_git_add_flags")
        assert_matches_golden(
            self,
            "combined_git_add_flags",
            actual,
            goldens,
        )


if __name__ == "__main__":
    unittest.main()
