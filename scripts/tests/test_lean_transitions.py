#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pure transition contract for Full and Focused lean workflows."""

import os
import sys
import unittest
from dataclasses import replace


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

    def test_delivery_confirmation_authorizes_without_completing_full_flow(self):
        result = advance_flow(
            flow(phase=Phase.DELIVERY),
            AdvanceRequest(
                "delivery-confirmed",
                "delivery.decision",
                "Deliver the reviewed manifest to the target branch.",
            ),
        )
        self.assertEqual("active", result.state.status)
        self.assertEqual(Phase.DELIVERY, result.state.phase)
        self.assertIn((
            "delivery.confirmation",
            "Deliver the reviewed manifest to the target branch.",
        ), result.state.decisions)
        self.assertFalse(result.needs_user)

    def test_delivery_completion_requires_authorization_and_a_later_event(self):
        state = flow(phase=Phase.DELIVERY)
        premature = advance_flow(
            state, AdvanceRequest("delivery-completed"))
        authorized = advance_flow(
            state, AdvanceRequest("delivery-confirmed"))
        completed = advance_flow(
            authorized.state,
            AdvanceRequest(
                "delivery-completed",
                "delivery.result",
                "The commit and push completed successfully.",
            ),
        )
        self.assertEqual("active", premature.state.status)
        self.assertIn("authorization", premature.reason.lower())
        self.assertEqual("active", authorized.state.status)
        self.assertEqual("complete", completed.state.status)
        self.assertIn((
            "delivery.result",
            "The commit and push completed successfully.",
        ), completed.state.decisions)

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

    def test_review_failure_is_recorded_once_without_retry_or_user_stop(self):
        cases = (
            (
                Phase.SPEC,
                "grill-failed",
                "grill-clear",
                "review.grill",
                "spec-confirmed",
                Phase.STORY,
            ),
            (
                Phase.STORY,
                "design-review-failed",
                "design-review-approved",
                "review.design",
                "story-confirmed",
                Phase.CONSTRUCTION,
            ),
        )
        for phase, failure, retry, key, confirmation, target in cases:
            with self.subTest(phase=phase):
                failed = advance_flow(
                    flow(phase=phase), AdvanceRequest(failure))
                repeated = advance_flow(
                    failed.state, AdvanceRequest(retry))
                advanced = advance_flow(
                    repeated.state, AdvanceRequest(confirmation))
                self.assertFalse(failed.needs_user)
                self.assertEqual(failed.state, repeated.state)
                self.assertEqual(
                    1,
                    sum(existing == key
                        for existing, unused in repeated.state.decisions),
                )
                self.assertEqual(target, advanced.state.phase)


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

    def test_migrated_focused_spec_and_story_resume_without_mandatory_reviews(self):
        cases = (
            (Phase.SPEC, "spec-confirmed"),
            (Phase.STORY, "story-confirmed"),
        )
        for phase, event in cases:
            with self.subTest(phase=phase):
                result = advance_flow(
                    flow(path=DeliveryPath.FOCUSED, phase=phase),
                    AdvanceRequest(event),
                )
                self.assertEqual(Phase.CONSTRUCTION, result.state.phase)
                self.assertFalse(result.needs_user)
                self.assertNotIn("review", result.reason.lower())

    def test_focused_delivery_confirmation_only_authorizes_flow(self):
        result = advance_flow(
            flow(path=DeliveryPath.FOCUSED, phase=Phase.DELIVERY),
            AdvanceRequest("delivery-confirmed"),
        )
        self.assertEqual("active", result.state.status)
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
    def test_exact_risks_resolve_one_at_a_time_for_full_and_focused(self):
        first_risk = "The migrated phase has two plausible meanings."
        second_risk = "The delivery scope still needs confirmation."
        for path in (DeliveryPath.FULL, DeliveryPath.FOCUSED):
            with self.subTest(path=path):
                state = replace(
                    flow(path=path, phase=Phase.QUALITY),
                    risks=(first_risk, second_risk),
                )

                first = advance_flow(state, AdvanceRequest(
                    "risk-resolved",
                    decision_key=first_risk,
                    decision_value="用户确认按兼容语义继续，并保留第二项待决。",
                ))
                second = advance_flow(first.state, AdvanceRequest(
                    "risk-resolved",
                    decision_key=second_risk,
                    decision_value="  用户逐文件确认了最终交付范围。  ",
                ))

                self.assertEqual((second_risk,), first.state.risks)
                self.assertTrue(first.needs_user)
                self.assertEqual((), second.state.risks)
                self.assertFalse(second.needs_user)
                self.assertTrue(any(
                    key == "risk.resolution"
                    and first_risk in value
                    and "用户确认按兼容语义继续" in value
                    for key, value in first.state.decisions
                ))
                self.assertTrue(any(
                    key == "risk.resolution"
                    and value.startswith("用户逐文件确认")
                    for key, value in second.state.decisions
                ))

    def test_invalid_risk_resolution_never_mutates_general_flow(self):
        risk = "The migrated delivery boundary is ambiguous."
        cases = (
            ((risk,), "", "The user omitted the risk identity."),
            ((risk,), "A different risk.", "The selected risk is stale."),
            ((risk, risk), risk, "The duplicate risk is ambiguous."),
            ((risk,), risk, "  \t\r\n"),
        )
        for risks, identity, resolution in cases:
            with self.subTest(risks=risks, identity=identity):
                state = replace(
                    flow(phase=Phase.QUALITY), risks=risks)

                result = advance_flow(state, AdvanceRequest(
                    "risk-resolved",
                    decision_key=identity,
                    decision_value=resolution,
                ))

                self.assertIs(state, result.state)
                self.assertTrue(result.needs_user)
                self.assertIn("risk", result.reason.lower())

    def test_unresolved_risk_blocks_quality_to_delivery_for_both_paths(self):
        for path in (DeliveryPath.FULL, DeliveryPath.FOCUSED):
            with self.subTest(path=path):
                state = replace(
                    flow(path=path, phase=Phase.QUALITY),
                    risks=("The migration needs a user decision.",),
                )

                result = advance_flow(
                    state, AdvanceRequest("quality-complete"))

                self.assertIs(state, result.state)
                self.assertEqual(Phase.QUALITY, result.state.phase)
                self.assertTrue(result.needs_user)
                self.assertIn("risk", result.reason.lower())

    def test_unresolved_risk_prevents_delivery_completion(self):
        authorized = advance_flow(
            flow(phase=Phase.DELIVERY),
            AdvanceRequest("delivery-confirmed"),
        ).state
        state = replace(
            authorized, risks=("The final remote target is uncertain.",))

        result = advance_flow(
            state,
            AdvanceRequest(
                "delivery-completed",
                decision_value="The adapter observed a successful push.",
            ),
        )

        self.assertIs(state, result.state)
        self.assertEqual("active", result.state.status)
        self.assertTrue(result.needs_user)
        self.assertIn("risk", result.reason.lower())

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
    def test_exit_succeeds_from_every_valid_phase_and_status(self):
        for phase in Phase:
            for status in ("active", "paused", "complete", "exited"):
                with self.subTest(phase=phase, status=status):
                    result = advance_flow(
                        flow(phase=phase, status=status),
                        AdvanceRequest("exit"),
                    )
                    self.assertEqual("exited", result.state.status)
                    self.assertEqual(phase, result.state.phase)
                    self.assertFalse(result.needs_user)

    def test_exit_remains_unconditional_with_unresolved_risks(self):
        state = replace(
            flow(phase=Phase.QUALITY),
            risks=("The migration still needs a user decision.",),
        )

        result = advance_flow(state, AdvanceRequest("exit"))

        self.assertEqual("exited", result.state.status)
        self.assertEqual(state.risks, result.state.risks)
        self.assertFalse(result.needs_user)

    def test_complete_alias_only_finishes_authorized_delivery(self):
        for phase in Phase:
            with self.subTest(phase=phase):
                state = flow(phase=phase)
                if phase == Phase.DELIVERY:
                    state = advance_flow(
                        state, AdvanceRequest("delivery-confirmed")).state
                result = advance_flow(state, AdvanceRequest("complete"))
                expected = "complete" if phase == Phase.DELIVERY else "active"
                self.assertEqual(expected, result.state.status)
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
