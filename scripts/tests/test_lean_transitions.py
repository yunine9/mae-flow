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
    CapabilityAttempt,
    CommitPace,
    DeliveryPath,
    FlowState,
    Phase,
    advance_flow,
)
from mae_flow_core.orchestration.delivery import (  # noqa: E402
    DELIVERY_RECEIPT_KEY,
    valid_delivery_receipt,
)


def flow(path=DeliveryPath.FULL, phase=Phase.STARTUP, status="active"):
    return FlowState(
        ticket="REQ-42",
        path=path,
        phase=phase,
        commit_pace=CommitPace.STAGED,
        status=status,
    )


def with_returned_review(state):
    if state.phase == Phase.SPEC:
        attempt = CapabilityAttempt(
            "grill", "grill:spec:-", "lean-workflow-v1", "returned")
    elif state.phase == Phase.STORY:
        attempt = CapabilityAttempt(
            "reviewer", "reviewer:design", "lean-workflow-v1", "returned")
    else:
        return state
    return replace(state, capabilities=state.capabilities + (attempt,))


class FullTransitionTests(unittest.TestCase):
    def test_user_confirmation_requires_real_prose_and_issues_bound_receipt(self):
        startup = flow()
        blank = advance_flow(startup, AdvanceRequest("startup-confirmed"))
        self.assertIs(startup, blank.state)
        self.assertTrue(blank.needs_user)

        delivery = replace(
            flow(phase=Phase.DELIVERY),
            commit_pace=CommitPace.CONTINUOUS,
            delivery_files=("src/a.cpp",),
        )
        confirmed = advance_flow(delivery, AdvanceRequest(
            "delivery-confirmed",
            decision_value="Deliver these exact files without Git.",
        ))
        values = [value for key, value in confirmed.state.decisions
                  if key == DELIVERY_RECEIPT_KEY]
        self.assertEqual(1, len(values))
        self.assertTrue(valid_delivery_receipt(confirmed.state, values[0]))

    def test_material_exception_is_persisted_and_blocks_phase_progression(self):
        state = flow(phase=Phase.CONSTRUCTION)
        stopped = advance_flow(state, AdvanceRequest(
            "meaningful-design-deviation",
            decision_value="The public behavior differs from Story.",
        ))
        advanced = advance_flow(
            stopped.state, AdvanceRequest("construction-complete"))

        self.assertTrue(stopped.needs_user)
        self.assertEqual(1, len(stopped.state.risks))
        self.assertEqual(Phase.CONSTRUCTION, advanced.state.phase)
        self.assertTrue(advanced.needs_user)

    def test_quality_defect_repair_returns_to_construction_and_clears_downstream(self):
        state = replace(
            flow(phase=Phase.QUALITY),
            decisions=(
                ("review.design", "clear"),
                ("quality.selection", "UT and CodeCheck"),
                ("delivery.receipt", "stale"),
            ),
            delivery_files=("src/a.cpp",),
        )

        result = advance_flow(state, AdvanceRequest(
            "quality-defect-repair",
            decision_value="Repair the reproduced defect in CP2.",
        ))

        self.assertEqual(Phase.CONSTRUCTION, result.state.phase)
        self.assertFalse(result.state.delivery_files)
        self.assertFalse(any(
            key.startswith(("quality.", "delivery."))
            for key, unused in result.state.decisions))

    def test_review_fact_requires_matching_returned_capability_attempt(self):
        cases = (
            (Phase.SPEC, "grill-clear", "grill", "grill:spec:-",
             "review.grill"),
            (Phase.STORY, "design-review-approved", "reviewer",
             "reviewer:design", "review.design"),
        )
        for phase, event, kind, slot, review_key in cases:
            with self.subTest(phase=phase):
                missing = advance_flow(
                    flow(phase=phase), AdvanceRequest(event))
                ready = replace(
                    flow(phase=phase),
                    capabilities=(CapabilityAttempt(
                        kind, slot, "lean-workflow-v1", "returned"),),
                )
                recorded = advance_flow(ready, AdvanceRequest(event))

                self.assertFalse(any(
                    key == review_key
                    for key, unused in missing.state.decisions))
                self.assertIn("attempt", missing.reason.lower())
                self.assertTrue(any(
                    key == review_key
                    for key, unused in recorded.state.decisions))

    def test_failed_review_attempt_is_visible_without_blocking_confirmation(self):
        state = replace(
            flow(phase=Phase.SPEC),
            capabilities=(CapabilityAttempt(
                "grill", "grill:spec:-", "lean-workflow-v1",
                "timed-out"),),
        )

        failed = advance_flow(state, AdvanceRequest("grill-failed"))
        confirmation = advance_flow(
            failed.state,
            AdvanceRequest(
                "spec-confirmed",
                decision_value="用户看到 Grill 超时事实后确认 Spec。",
            ),
        )

        self.assertFalse(failed.state.risks)
        self.assertFalse(any(
            key == "review.grill"
            for key, unused in failed.state.decisions))
        self.assertTrue(any(
            key == "review.grill.attempted"
            for key, unused in failed.state.decisions))
        self.assertEqual(Phase.STORY, confirmation.state.phase)

    def test_confirmation_fact_key_cannot_be_overridden_by_request(self):
        result = advance_flow(flow(), AdvanceRequest(
            "startup-confirmed",
            "moonlight.enabled",
            "Proceed with the reviewed Full path.",
        ))

        self.assertIn((
            "startup.confirmation",
            "Proceed with the reviewed Full path.",
        ), result.state.decisions)
        self.assertFalse(any(
            key == "moonlight.enabled"
            for key, unused in result.state.decisions))

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
                if phase == Phase.CONSTRUCTION:
                    original = replace(
                        original, commit_pace=CommitPace.CONTINUOUS)
                if phase == Phase.SPEC:
                    original = with_returned_review(original)
                    original = advance_flow(
                        original, AdvanceRequest("grill-clear")).state
                elif phase == Phase.STORY:
                    original = with_returned_review(original)
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
                result = advance_flow(state, AdvanceRequest(
                    event, decision_value="Confirm after review."))
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
                    with_returned_review(flow(phase=phase)),
                    AdvanceRequest(review_event))
                result = advance_flow(
                    reviewed.state, AdvanceRequest(
                        confirmation, decision_value="Confirm after review."))
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
                state = with_returned_review(flow(phase=phase))
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
                    second.state, AdvanceRequest(
                        confirmation, decision_value="Confirm after review."))
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
                self.assertEqual(state.phase, result.state.phase)

    def test_cp_confirmation_records_pace_decision_without_changing_phase(self):
        state = replace(
            flow(phase=Phase.CONSTRUCTION),
            decisions=(
                ("delivery.cp.CP1.file", "src/a.cpp"),
                ("delivery.cp.CP1.message", "[REQ-42][fix]complete CP1"),
            ),
        )
        result = advance_flow(state, AdvanceRequest(
            "cp-confirmed",
            "construction.commit_pace",
            "Keep staged commits at meaningful checkpoint boundaries.",
        ))
        self.assertEqual(Phase.CONSTRUCTION, result.state.phase)
        self.assertIn((
            "construction.cp.CP1.confirmation",
            "Keep staged commits at meaningful checkpoint boundaries.",
        ), result.state.decisions)
        self.assertFalse(result.needs_user)

    def test_each_checkpoint_has_its_own_current_confirmation(self):
        state = replace(
            flow(phase=Phase.CONSTRUCTION),
            current_cp="CP1",
            decisions=(
                ("delivery.cp.CP1.file", "src/a.cpp"),
                ("delivery.cp.CP1.message", "[REQ-42][fix]complete CP1"),
                ("delivery.cp.CP2.file", "src/b.cpp"),
                ("delivery.cp.CP2.message", "[REQ-42][fix]complete CP2"),
            ),
        )
        cp1 = advance_flow(
            state,
            AdvanceRequest("cp-confirmed", decision_value="CP1 reviewed."),
        ).state
        cp2_ready = advance_flow(
            cp1,
            AdvanceRequest("cp-ready", decision_key="CP2"),
        )
        cp2 = advance_flow(
            cp2_ready.state,
            AdvanceRequest("cp-confirmed", decision_value="CP2 reviewed."),
        ).state

        self.assertTrue(cp2_ready.needs_user)
        self.assertEqual("CP2", cp2_ready.state.current_cp)
        self.assertIn((
            "construction.cp.CP1.confirmation", "CP1 reviewed."),
            cp2.decisions,
        )
        self.assertIn((
            "construction.cp.CP2.confirmation", "CP2 reviewed."),
            cp2.decisions,
        )

    def test_full_staged_cannot_finish_with_unplanned_current_checkpoint(self):
        state = replace(
            flow(phase=Phase.CONSTRUCTION),
            commit_pace=CommitPace.STAGED,
            current_cp="CP1",
            decisions=(
                ("delivery.cp.CP1.file", "src/a.cpp"),
                ("delivery.cp.CP1.message", "[REQ-42][fix]complete CP1"),
            ),
        )
        cp1 = advance_flow(
            state,
            AdvanceRequest("cp-confirmed", decision_value="CP1 reviewed."),
        ).state
        cp2 = advance_flow(
            cp1, AdvanceRequest("cp-ready", decision_key="CP2"))

        result = advance_flow(cp2.state, AdvanceRequest("construction-complete"))

        self.assertEqual("CP2", result.state.current_cp)
        self.assertEqual(Phase.CONSTRUCTION, result.state.phase)
        self.assertIn("current CP", result.reason)

    def test_delivery_confirmation_authorizes_without_completing_full_flow(self):
        state = replace(
            flow(phase=Phase.DELIVERY),
            commit_pace=CommitPace.CONTINUOUS,
            delivery_files=("src/a.cpp",),
        )
        result = advance_flow(
            state,
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

    def test_delivery_confirmation_is_bound_to_nonempty_exact_manifest(self):
        empty = advance_flow(
            flow(phase=Phase.DELIVERY),
            AdvanceRequest("delivery-confirmed", decision_value="Deliver."),
        )
        ready = replace(
            flow(phase=Phase.DELIVERY),
            commit_pace=CommitPace.CONTINUOUS,
            delivery_files=("src/a.cpp", "tests/a_test.cpp"),
        )
        confirmed = advance_flow(
            ready,
            AdvanceRequest(
                "delivery-confirmed",
                decision_value="Deliver these exact files.",
            ),
        )

        self.assertFalse(any(
            key == "delivery.confirmation"
            for key, unused in empty.state.decisions))
        self.assertIn("manifest", empty.reason.lower())
        self.assertEqual(
            ["src/a.cpp", "tests/a_test.cpp"],
            [value for key, value in confirmed.state.decisions
             if key == "delivery.confirmed_file"],
        )

    def test_delivery_completion_rejects_manifest_changed_after_confirmation(self):
        ready = replace(
            flow(phase=Phase.DELIVERY),
            commit_pace=CommitPace.CONTINUOUS,
            delivery_files=("src/a.cpp",),
        )
        confirmed = advance_flow(
            ready,
            AdvanceRequest("delivery-confirmed", decision_value="Deliver A."),
        ).state
        changed = replace(confirmed, delivery_files=("src/b.cpp",))

        result = advance_flow(
            changed,
            AdvanceRequest("delivery-completed", decision_value="Pushed."),
        )

        self.assertEqual("active", result.state.status)
        self.assertIn("receipt", result.reason.lower())

    def test_staged_completion_requires_recorded_final_checkpoint_union(self):
        state = replace(
            flow(path=DeliveryPath.FOCUSED, phase=Phase.DELIVERY),
            delivery_files=("src/a.cpp", "src/b.cpp"),
            decisions=(
                ("delivery.cp.CP1.file", "src/a.cpp"),
                ("delivery.cp.CP1.message", "[REQ-42][fix]complete CP1"),
                ("delivery.cp.CP2.file", "src/b.cpp"),
                ("delivery.cp.CP2.message", "[REQ-42][fix]complete CP2"),
            ),
        )
        missing_final = advance_flow(
            state,
            AdvanceRequest("delivery-confirmed", decision_value="Deliver union."),
        )
        finalized = replace(
            state,
            decisions=state.decisions + (
                ("delivery.staged_final_file", "src/a.cpp"),
                ("delivery.staged_final_file", "src/b.cpp"),
            ),
        )
        confirmed = advance_flow(
            finalized,
            AdvanceRequest("delivery-confirmed", decision_value="Deliver union."),
        ).state
        completed = advance_flow(
            confirmed,
            AdvanceRequest("delivery-completed", decision_value="Pushed."),
        )

        self.assertIs(state, missing_final.state)
        self.assertIn("final", missing_final.reason.lower())
        self.assertEqual("complete", completed.state.status)

    def test_delivery_completion_requires_authorization_and_a_later_event(self):
        state = replace(
            flow(phase=Phase.DELIVERY),
            commit_pace=CommitPace.CONTINUOUS,
            delivery_files=("src/a.cpp",),
        )
        premature = advance_flow(
            state, AdvanceRequest("delivery-completed"))
        authorized = advance_flow(
            state, AdvanceRequest(
                "delivery-confirmed", decision_value="Deliver without Git."))
        completed = advance_flow(
            authorized.state,
            AdvanceRequest(
                "delivery-completed",
                "delivery.result",
                "The commit and push completed successfully.",
            ),
        )
        self.assertEqual("active", premature.state.status)
        self.assertIn("receipt", premature.reason.lower())
        self.assertEqual("active", authorized.state.status)
        self.assertEqual("complete", completed.state.status)
        self.assertIn((
            "delivery.result",
            "The commit and push completed successfully.",
        ), completed.state.decisions)

    def test_grill_clear_is_non_blocking_and_recorded_only_once(self):
        state = with_returned_review(flow(phase=Phase.SPEC))
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
        state = with_returned_review(flow(phase=Phase.STORY))
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

    def test_review_failure_records_attempt_without_blocking_user_confirmation(self):
        cases = (
            (
                Phase.SPEC,
                "grill-failed",
                "grill",
                "grill:spec:-",
                "review.grill",
                "spec-confirmed",
            ),
            (
                Phase.STORY,
                "design-review-failed",
                "reviewer",
                "reviewer:design",
                "review.design",
                "story-confirmed",
            ),
        )
        for phase, failure, kind, slot, key, confirmation in cases:
            with self.subTest(phase=phase):
                state = replace(
                    flow(phase=phase),
                    capabilities=(CapabilityAttempt(
                        kind, slot, "lean-workflow-v1", "timed-out"),),
                )
                failed = advance_flow(
                    state, AdvanceRequest(failure))
                advanced = advance_flow(
                    failed.state,
                    AdvanceRequest(
                        confirmation,
                        decision_value="用户看过审查失败事实并决定继续。",
                    ),
                )
                self.assertFalse(failed.needs_user)
                self.assertFalse(failed.state.risks)
                self.assertEqual(
                    0,
                    sum(existing == key
                        for existing, unused in failed.state.decisions),
                )
                self.assertIn(
                    (key + ".attempted",
                     "The required reviewer was attempted once and did not return."),
                    failed.state.decisions,
                )
                self.assertNotEqual(phase, advanced.state.phase)


class FocusedTransitionTests(unittest.TestCase):
    def test_startup_confirmation_atomically_authorizes_focused_scope(self):
        result = advance_flow(
            flow(path=DeliveryPath.FOCUSED),
            AdvanceRequest(
                "startup-confirmed",
                decision_value="Modify only the reviewed parser boundary.",
            ),
        )

        self.assertEqual(Phase.CONSTRUCTION, result.state.phase)
        self.assertIn((
            "focused.scope_approved",
            "Modify only the reviewed parser boundary.",
        ), result.state.decisions)

    def test_focused_uses_only_startup_and_delivery_confirmation_stops(self):
        startup = advance_flow(
            flow(path=DeliveryPath.FOCUSED), AdvanceRequest("startup-ready"))
        construction = advance_flow(
            flow(path=DeliveryPath.FOCUSED),
            AdvanceRequest(
                "startup-confirmed", decision_value="Confirm focused scope."),
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

    def test_focused_staged_cp_progress_updates_internal_cursor_without_stop(self):
        state = replace(
            flow(path=DeliveryPath.FOCUSED, phase=Phase.CONSTRUCTION),
            commit_pace=CommitPace.STAGED,
            current_cp="CP1",
        )

        result = advance_flow(
            state, AdvanceRequest("cp-ready", decision_key="CP2"))

        self.assertEqual("CP2", result.state.current_cp)
        self.assertFalse(result.needs_user)

    def test_migrated_focused_spec_and_story_resume_without_mandatory_reviews(self):
        cases = (
            (Phase.SPEC, "spec-confirmed"),
            (Phase.STORY, "story-confirmed"),
        )
        for phase, event in cases:
            with self.subTest(phase=phase):
                result = advance_flow(
                    flow(path=DeliveryPath.FOCUSED, phase=phase),
                    AdvanceRequest(event, decision_value="Resume migrated work."),
                )
                self.assertEqual(Phase.CONSTRUCTION, result.state.phase)
                self.assertFalse(result.needs_user)
                self.assertNotIn("review", result.reason.lower())

    def test_focused_delivery_confirmation_only_authorizes_flow(self):
        result = advance_flow(
            replace(
                flow(path=DeliveryPath.FOCUSED, phase=Phase.DELIVERY),
                commit_pace=CommitPace.CONTINUOUS,
                delivery_files=("src/a.cpp",),
            ),
            AdvanceRequest(
                "delivery-confirmed", decision_value="Deliver without Git."),
        )
        self.assertEqual("active", result.state.status)
        self.assertFalse(result.needs_user)

    def test_focused_can_upgrade_semantically_to_full_specification(self):
        original = replace(
            flow(path=DeliveryPath.FOCUSED, phase=Phase.CONSTRUCTION),
            decisions=(
                ("focused.scope_approved", "small scope"),
                ("delivery.cp.CP1.file", "src/a.cpp"),
                ("quality.selection", "Lightcheck"),
                ("delivery.receipt", "stale"),
            ),
            delivery_files=("src/a.cpp",),
        )
        result = advance_flow(
            original,
            AdvanceRequest(
                "upgrade-to-full",
                "workflow.path",
                "Shared interfaces need explicit specification and story design.",
            ),
        )
        self.assertEqual(DeliveryPath.FULL, result.state.path)
        self.assertEqual(Phase.SPEC, result.state.phase)
        self.assertFalse(result.state.delivery_files)
        self.assertFalse(any(
            key.startswith(("focused.", "construction.", "quality.",
                            "delivery."))
            for key, unused in result.state.decisions))
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

    def test_inactive_risk_resolution_is_an_exact_no_op(self):
        risk = "The historical flow retained an unresolved risk."
        for status in ("paused", "complete", "exited"):
            with self.subTest(status=status):
                state = replace(
                    flow(phase=Phase.QUALITY, status=status),
                    decisions=(("existing.decision", "preserve exactly"),),
                    risks=(risk,),
                )

                result = advance_flow(state, AdvanceRequest(
                    "risk-resolved",
                    decision_key=risk,
                    decision_value="用户现在给出了解决说明，但终态不能被回写。",
                ))

                self.assertIs(state, result.state)
                self.assertEqual((risk,), result.state.risks)
                self.assertEqual(
                    (("existing.decision", "preserve exactly"),),
                    result.state.decisions,
                )
                self.assertFalse(result.needs_user)
                self.assertIn("inactive", result.reason.lower())

    def test_complete_alias_only_finishes_authorized_delivery(self):
        for phase in Phase:
            with self.subTest(phase=phase):
                state = flow(phase=phase)
                if phase == Phase.DELIVERY:
                    state = replace(
                        state,
                        commit_pace=CommitPace.CONTINUOUS,
                        delivery_files=("src/a.cpp",),
                    )
                    state = advance_flow(
                        state, AdvanceRequest(
                            "delivery-confirmed",
                            decision_value="Deliver without Git.")).state
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
