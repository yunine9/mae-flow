#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pure transition contract for Full and Focused lean workflows."""

import os
import sys
import unittest


SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.orchestration import (  # noqa: E402
    AdvanceRequest,
    CommitPace,
    DeliveryPath,
    FlowState,
    Phase,
    advance_flow,
)


def flow(path=DeliveryPath.FULL, phase=Phase.STARTUP, status="active"):
    return FlowState(
        ticket="REQ-42",
        path=path,
        phase=phase,
        commit_pace=CommitPace.STAGED,
        status=status,
    )


class FullTransitionTests(unittest.TestCase):
    def test_full_confirmation_sequence_visits_every_phase(self):
        cases = (
            (Phase.STARTUP, "startup-confirmed", Phase.SPEC),
            (Phase.SPEC, "spec-confirmed", Phase.STORY),
            (Phase.STORY, "story-confirmed", Phase.CONSTRUCTION),
            (Phase.CONSTRUCTION, "construction-complete", Phase.QUALITY),
            (Phase.QUALITY, "quality-complete", Phase.DELIVERY),
        )
        for phase, event, expected in cases:
            with self.subTest(phase=phase, event=event):
                original = flow(phase=phase)
                if phase == Phase.SPEC:
                    original = advance_flow(
                        original, AdvanceRequest("grill-clear")).state
                elif phase == Phase.STORY:
                    original = advance_flow(
                        original,
                        AdvanceRequest("design-review-approved"),
                    ).state
                result = advance_flow(original, AdvanceRequest(
                    event,
                    "%s.decision" % phase.value,
                    "Proceed based on the reviewed scope and risks.",
                ))
                self.assertEqual(expected, result.state.phase)
                self.assertFalse(result.needs_user)
                self.assertEqual(phase, original.phase)

    def test_full_confirmation_cannot_skip_required_review(self):
        cases = (
            (Phase.SPEC, "spec-confirmed"),
            (Phase.STORY, "story-confirmed"),
        )
        for phase, event in cases:
            with self.subTest(phase=phase):
                state = flow(phase=phase)
                result = advance_flow(state, AdvanceRequest(event))
                self.assertIs(state, result.state)
                self.assertEqual(phase, result.state.phase)
                self.assertFalse(result.needs_user)
                self.assertIn("review", result.reason.lower())

    def test_clear_or_approved_review_completion_allows_confirmation(self):
        cases = (
            (Phase.SPEC, "grill-clear", "spec-confirmed", Phase.STORY),
            (
                Phase.STORY,
                "design-review-approved",
                "story-confirmed",
                Phase.CONSTRUCTION,
            ),
        )
        for phase, review_event, confirmation, expected in cases:
            with self.subTest(phase=phase):
                reviewed = advance_flow(
                    flow(phase=phase), AdvanceRequest(review_event))
                result = advance_flow(
                    reviewed.state, AdvanceRequest(confirmation))
                self.assertFalse(reviewed.needs_user)
                self.assertEqual(expected, result.state.phase)

    def test_user_resolved_reviewer_tradeoff_completes_review_once(self):
        cases = (
            (
                Phase.SPEC,
                "review.grill",
                "spec-confirmed",
                Phase.STORY,
            ),
            (
                Phase.STORY,
                "review.design",
                "story-confirmed",
                Phase.CONSTRUCTION,
            ),
        )
        for phase, review_key, confirmation, expected in cases:
            with self.subTest(phase=phase):
                state = flow(phase=phase)
                tradeoff = advance_flow(
                    state, AdvanceRequest("reviewer-tradeoff"))
                first = advance_flow(tradeoff.state, AdvanceRequest(
                    "reviewer-tradeoff-resolved",
                    "review.resolution",
                    "The user selected the documented reviewer tradeoff.",
                ))
                second = advance_flow(first.state, AdvanceRequest(
                    "reviewer-tradeoff-resolved",
                    "review.second_resolution",
                    "The user selected the documented reviewer tradeoff.",
                ))
                advanced = advance_flow(
                    second.state, AdvanceRequest(confirmation))
                self.assertTrue(tradeoff.needs_user)
                self.assertFalse(first.needs_user)
                self.assertEqual(first.state, second.state)
                self.assertEqual(
                    1,
                    sum(key == review_key
                        for key, unused in second.state.decisions),
                )
                self.assertEqual(expected, advanced.state.phase)

    def test_full_high_value_points_ask_for_user_confirmation(self):
        cases = (
            (Phase.STARTUP, "startup-ready"),
            (Phase.SPEC, "spec-ready"),
            (Phase.STORY, "story-ready"),
            (Phase.CONSTRUCTION, "cp-ready"),
            (Phase.DELIVERY, "delivery-ready"),
        )
        for phase, event in cases:
            with self.subTest(phase=phase, event=event):
                state = flow(phase=phase)
                result = advance_flow(state, AdvanceRequest(event))
                self.assertTrue(result.needs_user)
                self.assertIs(state, result.state)

    def test_cp_confirmation_records_pace_decision_without_changing_phase(self):
        state = flow(phase=Phase.CONSTRUCTION)
        result = advance_flow(state, AdvanceRequest(
            "cp-confirmed",
            "construction.commit_pace",
            "Keep staged commits at meaningful checkpoint boundaries.",
        ))
        self.assertEqual(Phase.CONSTRUCTION, result.state.phase)
        self.assertIn((
            "construction.commit_pace",
            "Keep staged commits at meaningful checkpoint boundaries.",
        ), result.state.decisions)
        self.assertFalse(result.needs_user)

    def test_delivery_confirmation_completes_full_flow(self):
        result = advance_flow(
            flow(phase=Phase.DELIVERY),
            AdvanceRequest(
                "delivery-confirmed",
                "delivery.decision",
                "Deliver the reviewed manifest to the target branch.",
            ),
        )
        self.assertEqual("complete", result.state.status)
        self.assertEqual(Phase.DELIVERY, result.state.phase)
        self.assertFalse(result.needs_user)

    def test_grill_clear_is_non_blocking_and_recorded_only_once(self):
        state = flow(phase=Phase.SPEC)
        first = advance_flow(state, AdvanceRequest(
            "grill-clear",
            "review.grill",
            "The critic found no unresolved product ambiguity.",
        ))
        second = advance_flow(first.state, AdvanceRequest(
            "grill-clear",
            "review.grill.repeated_request",
            "The critic found no unresolved product ambiguity.",
        ))
        self.assertFalse(first.needs_user)
        self.assertEqual(Phase.SPEC, first.state.phase)
        self.assertEqual(first.state, second.state)
        self.assertEqual(
            1,
            sum(key == "review.grill" for key, unused in second.state.decisions),
        )

    def test_design_reviewer_clear_is_non_blocking_and_recorded_once(self):
        state = flow(phase=Phase.STORY)
        first = advance_flow(state, AdvanceRequest(
            "design-review-approved",
            "review.design",
            "The design is coherent with the approved specification.",
        ))
        second = advance_flow(first.state, AdvanceRequest(
            "design-review-approved",
            "review.design.repeated_request",
            "The design is coherent with the approved specification.",
        ))
        self.assertFalse(first.needs_user)
        self.assertEqual(Phase.STORY, first.state.phase)
        self.assertEqual(first.state, second.state)
        self.assertEqual(
            1,
            sum(key == "review.design" for key, unused in second.state.decisions),
        )


class FocusedTransitionTests(unittest.TestCase):
    def test_focused_uses_only_startup_and_delivery_confirmation_stops(self):
        startup = advance_flow(
            flow(path=DeliveryPath.FOCUSED), AdvanceRequest("startup-ready"))
        construction = advance_flow(
            flow(path=DeliveryPath.FOCUSED),
            AdvanceRequest("startup-confirmed"),
        )
        cp = advance_flow(
            flow(path=DeliveryPath.FOCUSED, phase=Phase.CONSTRUCTION),
            AdvanceRequest("cp-ready"),
        )
        delivery = advance_flow(
            flow(path=DeliveryPath.FOCUSED, phase=Phase.DELIVERY),
            AdvanceRequest("delivery-ready"),
        )
        self.assertTrue(startup.needs_user)
        self.assertEqual(Phase.CONSTRUCTION, construction.state.phase)
        self.assertFalse(construction.needs_user)
        self.assertFalse(cp.needs_user)
        self.assertTrue(delivery.needs_user)

    def test_focused_delivery_confirmation_completes_flow(self):
        result = advance_flow(
            flow(path=DeliveryPath.FOCUSED, phase=Phase.DELIVERY),
            AdvanceRequest("delivery-confirmed"),
        )
        self.assertEqual("complete", result.state.status)
        self.assertFalse(result.needs_user)

    def test_focused_can_upgrade_semantically_to_full_specification(self):
        result = advance_flow(
            flow(path=DeliveryPath.FOCUSED, phase=Phase.CONSTRUCTION),
            AdvanceRequest(
                "upgrade-to-full",
                "workflow.path",
                "Shared interfaces need explicit specification and story design.",
            ),
        )
        self.assertEqual(DeliveryPath.FULL, result.state.path)
        self.assertEqual(Phase.SPEC, result.state.phase)
        self.assertFalse(result.needs_user)


class SemanticGuardTests(unittest.TestCase):
    def test_only_material_exception_categories_stop_for_the_user(self):
        stop_events = (
            "ambiguity",
            "meaningful-design-deviation",
            "reviewer-tradeoff",
            "expensive-capability-retry",
            "irreversible-risk",
            "delivery-manifest-changed",
        )
        for event in stop_events:
            with self.subTest(event=event):
                result = advance_flow(
                    flow(phase=Phase.CONSTRUCTION),
                    AdvanceRequest(
                        event,
                        "exception.context",
                        "The choice changes observable behavior or risk.",
                    ),
                )
                self.assertTrue(result.needs_user)

    def test_clear_reviews_capability_success_and_ordinary_cp_progress_do_not_stop(self):
        cases = (
            (Phase.SPEC, "grill-clear"),
            (Phase.STORY, "design-review-approved"),
            (Phase.QUALITY, "reviewer-clear"),
            (Phase.CONSTRUCTION, "capability-success"),
            (Phase.CONSTRUCTION, "cp-progress"),
        )
        for phase, event in cases:
            with self.subTest(event=event):
                result = advance_flow(flow(phase=phase), AdvanceRequest(event))
                self.assertFalse(result.needs_user)

    def test_cross_cp_review_is_requested_only_for_semantic_coupling(self):
        review_cases = (
            ("checkpoint.coupling", "Two components now coordinate."),
            ("checkpoint.shared_state", "The checkpoints mutate shared state."),
            ("checkpoint.interface_change", "A public interface changed."),
            (
                "checkpoint.late_design_drift",
                "Late implementation drifted from design.",
            ),
        )
        for key, value in review_cases:
            with self.subTest(key=key):
                result = advance_flow(
                    flow(phase=Phase.CONSTRUCTION),
                    AdvanceRequest("cp-progress", key, value),
                )
                self.assertFalse(result.needs_user)
                self.assertIn("integration review", result.reason.lower())

        ordinary = advance_flow(
            flow(phase=Phase.CONSTRUCTION),
            AdvanceRequest(
                "cp-progress",
                "checkpoint.local_change",
                "The local change has no interface change or shared state.",
            ),
        )
        self.assertFalse(ordinary.needs_user)
        self.assertNotIn("integration review", ordinary.reason.lower())

    def test_cross_cp_review_rejects_compound_or_non_late_cause_keys(self):
        rejected = (
            "checkpoint.no_coupling",
            "checkpoint.decoupling",
            "checkpoint.interface_change_absent",
            "checkpoint.design_drift",
            "checkpoint.ordinary_design_drift",
        )
        for key in rejected:
            with self.subTest(key=key):
                result = advance_flow(
                    flow(phase=Phase.CONSTRUCTION),
                    AdvanceRequest("cp-progress", key, "Ordinary local work."),
                )
                self.assertFalse(result.needs_user)
                self.assertNotIn("integration review", result.reason.lower())

    def test_cross_cp_review_is_never_requested_outside_construction(self):
        for phase in Phase:
            if phase == Phase.CONSTRUCTION:
                continue
            with self.subTest(phase=phase):
                result = advance_flow(
                    flow(phase=phase),
                    AdvanceRequest(
                        "cp-progress",
                        "checkpoint.coupling",
                        "Two components now coordinate.",
                    ),
                )
                self.assertFalse(result.needs_user)
                self.assertNotIn("integration review", result.reason.lower())


class TerminalTransitionTests(unittest.TestCase):
    def test_exit_succeeds_from_every_valid_phase(self):
        for phase in Phase:
            with self.subTest(phase=phase):
                result = advance_flow(flow(phase=phase), AdvanceRequest("exit"))
                self.assertEqual("exited", result.state.status)
                self.assertEqual(phase, result.state.phase)
                self.assertFalse(result.needs_user)

    def test_complete_succeeds_from_every_valid_phase(self):
        for phase in Phase:
            with self.subTest(phase=phase):
                result = advance_flow(
                    flow(phase=phase), AdvanceRequest("complete"))
                self.assertEqual("complete", result.state.status)
                self.assertEqual(phase, result.state.phase)
                self.assertFalse(result.needs_user)

    def test_terminal_flows_ignore_further_transition_events(self):
        for status in ("complete", "exited"):
            with self.subTest(status=status):
                state = flow(status=status)
                result = advance_flow(
                    state, AdvanceRequest("startup-confirmed"))
                self.assertIs(state, result.state)
                self.assertFalse(result.needs_user)
                self.assertIn("inactive", result.reason.lower())


if __name__ == "__main__":
    unittest.main()
