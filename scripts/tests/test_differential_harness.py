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

STAGE0_SCENARIOS = {
    "direct_current",
    "standalone_action_status",
    "corrupt_exit_repair",
    "terminal_pretooluse_bypass",
    "checkpoint_status",
    "moonlight_report_issue",
    "active_pretooluse_edit",
    "subagentstop_missing_task_card",
}
STAGE1_EVIDENCE_SCENARIOS = {
    "evidence_agent_rejection",
    "evidence_archive_rejection",
    "evidence_branch_rejection",
    "evidence_checkpoint_rejection",
    "evidence_codecheck_rejection",
    "evidence_push_rejection",
    "evidence_review_rejection",
    "evidence_spec_rejection",
}
STAGE2_GUARD_SCENARIOS = {
    "guard_expired_permit",
    "guard_internal_state_edit",
    "guard_requirement_bash_write",
    "ownership_foreign_openspec",
}

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

    def test_stage0_domain_scenarios_are_registered(self):
        from differential.scenarios import SCENARIOS
        self.assertTrue({
            "checkpoint_status",
            "moonlight_report_issue",
            "active_pretooluse_edit",
            "subagentstop_missing_task_card",
        }.issubset(SCENARIOS))

    def test_stage1_evidence_scenarios_are_registered(self):
        from differential.scenarios import SCENARIOS
        self.assertTrue(STAGE1_EVIDENCE_SCENARIOS.issubset(SCENARIOS))

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

    def test_phase10_preserves_every_phase9_snapshot(self):
        phase9 = load_goldens(os.path.join(
            ROOT,
            "scripts",
            "tests",
            "differential",
            "goldens",
            "phase9.json",
        ))
        phase10 = load_goldens(os.path.join(
            ROOT,
            "scripts",
            "tests",
            "differential",
            "goldens",
            "phase10.json",
        ))
        self.assertEqual(set(phase9), set(phase10) - STAGE0_SCENARIOS)
        for name, expected in phase9.items():
            with self.subTest(name=name):
                self.assertEqual(expected, phase10[name])

    def test_phase10_stage0_scenarios_match_fixed_baseline(self):
        goldens = load_goldens(os.path.join(
            ROOT,
            "scripts",
            "tests",
            "differential",
            "goldens",
            "phase10.json",
        ))
        for name in sorted(STAGE0_SCENARIOS):
            with self.subTest(name=name):
                assert_matches_golden(
                    self,
                    name,
                    run_scenario(ROOT, name),
                    goldens,
                )

    def test_phase11_preserves_every_phase10_snapshot(self):
        phase10 = load_goldens(os.path.join(
            ROOT,
            "scripts",
            "tests",
            "differential",
            "goldens",
            "phase10.json",
        ))
        phase11 = load_goldens(os.path.join(
            ROOT,
            "scripts",
            "tests",
            "differential",
            "goldens",
            "phase11.json",
        ))
        self.assertEqual(
            set(phase10),
            set(phase11) - STAGE1_EVIDENCE_SCENARIOS,
        )
        for name, expected in phase10.items():
            with self.subTest(name=name):
                self.assertEqual(expected, phase11[name])

    def test_phase11_evidence_scenarios_match_fixed_baseline(self):
        goldens = load_goldens(os.path.join(
            ROOT,
            "scripts",
            "tests",
            "differential",
            "goldens",
            "phase11.json",
        ))
        for name in sorted(STAGE1_EVIDENCE_SCENARIOS):
            with self.subTest(name=name):
                assert_matches_golden(
                    self,
                    name,
                    run_scenario(ROOT, name),
                    goldens,
                )

    def test_phase12_preserves_every_phase11_snapshot(self):
        phase11 = load_goldens(os.path.join(
            ROOT, "scripts", "tests", "differential",
            "goldens", "phase11.json"))
        phase12 = load_goldens(os.path.join(
            ROOT, "scripts", "tests", "differential",
            "goldens", "phase12.json"))
        self.assertEqual(
            set(phase11), set(phase12) - STAGE2_GUARD_SCENARIOS)
        for name, expected in phase11.items():
            with self.subTest(name=name):
                self.assertEqual(expected, phase12[name])

    def test_phase12_guard_scenarios_match_fixed_baseline(self):
        goldens = load_goldens(os.path.join(
            ROOT, "scripts", "tests", "differential",
            "goldens", "phase12.json"))
        for name in sorted(STAGE2_GUARD_SCENARIOS):
            with self.subTest(name=name):
                assert_matches_golden(
                    self, name, run_scenario(ROOT, name), goldens)


if __name__ == "__main__":
    unittest.main()
