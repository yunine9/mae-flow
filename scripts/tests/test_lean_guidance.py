#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lean phase guidance and test-only harness contracts."""

import json
import os
import sys
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


def state_for(phase):
    return FlowState(
        ticket="REQ-42",
        path=DeliveryPath.FULL,
        phase=phase,
        commit_pace=CommitPace.STAGED,
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
        self.assertIn("whole-change UT handoff", construction)
        self.assertIn("at most once", quality)
        self.assertIn("meaningful change", quality)
        self.assertIn("user chooses", quality)

    def test_empty_artifacts_render_as_none(self):
        text = render_guidance(FlowState.new(
            "REQ-EMPTY", DeliveryPath.FULL, CommitPace.CONTINUOUS))
        self.assertIn("Artifacts: none", text)

    def test_spec_and_story_render_one_shot_review_policy(self):
        spec = render_guidance(state_for(Phase.SPEC))
        story = render_guidance(state_for(Phase.STORY))
        for guidance in (spec, story):
            self.assertIn("exactly once", guidance)
            self.assertIn("without a user stop", guidance)
            self.assertIn("without automatic retry", guidance)
            self.assertIn("real reviewer tradeoff", guidance)

    def test_construction_keeps_implementation_direct_and_ut_in_quality(self):
        construction = render_guidance(state_for(Phase.CONSTRUCTION))
        self.assertIn("main Agent implements the whole", construction)
        self.assertIn("whole-change UT handoff", construction)
        self.assertIn("formal UT remains in Quality", construction)
        self.assertIn("compile-agent", construction)


if __name__ == "__main__":
    unittest.main()
