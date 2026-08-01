#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Moonlight is a narrow authorization policy over the lean workflow."""

import os
import sys
import unittest
from dataclasses import replace


SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.orchestration.models import (  # noqa: E402
    CapabilityAttempt,
    CommitPace,
    DeliveryPath,
    FlowState,
    MoonlightAuthorization,
    Phase,
)
from mae_flow_core.orchestration.moonlight_policy import (  # noqa: E402
    apply_moonlight_policy,
)
from mae_flow_core.orchestration.transitions import AdvanceRequest  # noqa: E402


def flow(phase=Phase.CONSTRUCTION, **overrides):
    values = {
        "ticket": "REQ-42",
        "path": DeliveryPath.FULL,
        "phase": phase,
        "commit_pace": CommitPace.CONTINUOUS,
    }
    values.update(overrides)
    return FlowState(**values)


def authorize(state, files, allow_commit=True, allow_push=True):
    return apply_moonlight_policy(
        state,
        MoonlightAuthorization(
            enabled=True,
            business_files=files,
            allow_commit=allow_commit,
            allow_push=allow_push,
        ),
    ).state


class MoonlightAuthorizationTests(unittest.TestCase):
    def test_exact_windows_business_file_identity_can_be_preauthorized(self):
        state = flow(delivery_files=("src/Service.cpp",))

        result = apply_moonlight_policy(
            state,
            MoonlightAuthorization(
                True, (r"SRC\service.cpp",), True, True),
        )

        self.assertEqual(("SRC/service.cpp",), result.authorization.business_files)
        self.assertTrue(result.authorization.allow_commit)
        self.assertTrue(result.authorization.allow_push)
        self.assertEqual(state.phase, result.state.phase)
        self.assertEqual(state.capabilities, result.state.capabilities)

    def test_manifest_must_be_an_exact_subset_of_preauthorized_files(self):
        state = flow(delivery_files=("src/a.cpp", "src/unplanned.cpp"))

        result = apply_moonlight_policy(
            state,
            MoonlightAuthorization(True, ("src/a.cpp",), True, True),
        )

        self.assertFalse(result.authorization.allow_commit)
        self.assertFalse(result.authorization.allow_push)
        self.assertTrue(result.safe_stop)
        self.assertIn("manifest", result.reason.lower())

    def test_duplicate_alias_preauthorization_requests_renewed_authorization(self):
        state = flow(delivery_files=("src/a.cpp",))

        result = apply_moonlight_policy(
            state,
            MoonlightAuthorization(
                True, ("src/A.cpp", r"SRC\a.cpp"), True, True),
        )

        self.assertFalse(result.authorization.allow_commit)
        self.assertFalse(result.authorization.allow_push)
        self.assertTrue(result.needs_user)
        self.assertTrue(result.safe_stop)
        self.assertIn("reauthor", result.reason.lower())
        self.assertEqual(state.decisions, result.state.decisions)

    def test_conditional_document_is_excluded_unless_explicitly_named(self):
        story = ".mae-flow-work/REQ-42/story.md"
        state = flow(delivery_files=("src/a.cpp", story))

        excluded = apply_moonlight_policy(
            state,
            MoonlightAuthorization(True, ("src/a.cpp",), True, True),
        )
        included = apply_moonlight_policy(
            state,
            MoonlightAuthorization(
                True, ("src/a.cpp", story), True, True),
        )

        self.assertFalse(excluded.authorization.allow_commit)
        self.assertFalse(excluded.authorization.allow_push)
        self.assertTrue(included.authorization.allow_commit)
        self.assertTrue(included.authorization.allow_push)

    def test_unowned_dirty_file_allows_work_but_not_automatic_delivery(self):
        state = flow(
            delivery_files=("src/a.cpp",),
            initial_dirty=("notes/private.txt",),
        )
        state = authorize(state, ("src/a.cpp",))

        progress = apply_moonlight_policy(
            state, AdvanceRequest("cp-progress"))
        delivery = apply_moonlight_policy(
            replace(state, phase=Phase.DELIVERY),
            AdvanceRequest("delivery-ready"),
        )

        self.assertFalse(progress.needs_user)
        self.assertFalse(progress.safe_stop)
        self.assertFalse(progress.authorization.allow_commit)
        self.assertFalse(progress.authorization.allow_push)
        self.assertTrue(delivery.needs_user)
        self.assertTrue(delivery.safe_stop)
        self.assertIn("dirty", delivery.reason.lower())

    def test_explicitly_adopted_startup_dirty_file_can_be_delivered(self):
        state = flow(
            delivery_files=("src/a.cpp", "src/existing.cpp"),
            initial_dirty=("src/existing.cpp",),
            decisions=(("delivery.adopted_dirty", "SRC\\EXISTING.CPP"),),
        )

        result = apply_moonlight_policy(
            state,
            MoonlightAuthorization(
                True,
                ("src/a.cpp", "src/existing.cpp"),
                True,
                True,
            ),
        )

        self.assertTrue(result.authorization.allow_commit)
        self.assertTrue(result.authorization.allow_push)
        self.assertFalse(result.safe_stop)


class MoonlightPolicyTests(unittest.TestCase):
    def test_exit_is_immediate_even_with_existing_or_push_failure_risks(self):
        existing = authorize(
            flow(risks=("The environment is unavailable.",)),
            ("src/a.cpp",),
        )
        pushed = authorize(
            flow(phase=Phase.DELIVERY, delivery_files=("src/a.cpp",)),
            ("src/a.cpp",),
        )
        pushed = apply_moonlight_policy(
            pushed,
            AdvanceRequest(
                "push-failed",
                decision_value="The remote rejected the push.",
            ),
        ).state

        for state in (existing, pushed):
            with self.subTest(risks=state.risks):
                result = apply_moonlight_policy(
                    state, AdvanceRequest("exit"))

                self.assertEqual("exited", result.state.status)
                self.assertFalse(result.needs_user)
                self.assertFalse(result.safe_stop)
                self.assertEqual(state.risks, result.state.risks)

    def test_corrupt_authorization_fails_closed_without_breaking_normal_flow(self):
        corrupt_decisions = (
            (
                (
                    ("moonlight.enabled", "true"),
                    ("moonlight.allow_commit", "true"),
                    ("moonlight.allow_push", "true"),
                    ("moonlight.business_file", "src/A.cpp"),
                    ("moonlight.business_file", r"SRC\a.cpp"),
                ),
                "duplicate Windows aliases",
            ),
            (
                (
                    ("moonlight.enabled", "true"),
                    ("moonlight.enabled", "false"),
                    ("moonlight.allow_commit", "true"),
                    ("moonlight.allow_push", "true"),
                    ("moonlight.business_file", "src/a.cpp"),
                ),
                "conflicting reserved keys",
            ),
            (
                (
                    ("moonlight.enabled", "true"),
                    ("moonlight.allow_commit", "yes"),
                    ("moonlight.allow_push", "true"),
                    ("moonlight.business_file", "src/a.cpp"),
                ),
                "invalid reserved value",
            ),
        )
        for decisions, label in corrupt_decisions:
            with self.subTest(label=label):
                state = flow(
                    decisions=decisions,
                    delivery_files=("src/a.cpp",),
                )

                result = apply_moonlight_policy(
                    state, AdvanceRequest("cp-progress"))

                self.assertFalse(result.authorization.allow_commit)
                self.assertFalse(result.authorization.allow_push)
                self.assertFalse(result.safe_stop)
                self.assertFalse(result.needs_user)
                self.assertEqual(Phase.CONSTRUCTION, result.state.phase)
                self.assertIn("reauthor", result.reason.lower())

                push = apply_moonlight_policy(
                    replace(state, phase=Phase.DELIVERY),
                    AdvanceRequest("final-push"),
                )
                self.assertTrue(push.safe_stop)
                self.assertTrue(push.needs_user)
                self.assertFalse(push.authorization.allow_push)

    def test_routine_confirmation_is_suppressed_without_changing_transitions(self):
        state = flow(phase=Phase.STARTUP)
        state = authorize(state, ("src/a.cpp",))

        ready = apply_moonlight_policy(
            state, AdvanceRequest("startup-ready"))
        advanced = apply_moonlight_policy(
            ready.state, AdvanceRequest("startup-confirmed"))

        self.assertFalse(ready.needs_user)
        self.assertEqual(Phase.STARTUP, ready.state.phase)
        self.assertEqual(Phase.SPEC, advanced.state.phase)

    def test_existing_unresolved_risk_is_not_hidden_by_routine_suppression(self):
        state = flow(
            phase=Phase.STARTUP,
            risks=("The required API contract is unavailable.",),
        )

        activated = apply_moonlight_policy(
            state,
            MoonlightAuthorization(True, ("src/a.cpp",), True, True),
        )
        ready = apply_moonlight_policy(
            activated.state, AdvanceRequest("startup-ready"))

        self.assertTrue(activated.safe_stop)
        self.assertTrue(activated.needs_user)
        self.assertTrue(ready.safe_stop)
        self.assertTrue(ready.needs_user)
        self.assertEqual(Phase.STARTUP, ready.state.phase)

    def test_staged_checkpoint_without_commit_authorization_stops_safely(self):
        state = flow(
            commit_pace=CommitPace.STAGED,
            delivery_files=("src/a.cpp",),
        )
        state = authorize(
            state, ("src/a.cpp",), allow_commit=False, allow_push=True)

        result = apply_moonlight_policy(
            state, AdvanceRequest("cp-ready"))

        self.assertTrue(result.safe_stop)
        self.assertTrue(result.needs_user)
        self.assertIn("commit", result.reason.lower())

    def test_push_authorization_does_not_require_commit_authorization(self):
        state = flow(
            phase=Phase.DELIVERY,
            delivery_files=("src/a.cpp",),
        )
        state = authorize(
            state, ("src/a.cpp",), allow_commit=False, allow_push=True)

        result = apply_moonlight_policy(
            state, AdvanceRequest("final-push"))

        self.assertFalse(result.safe_stop)
        self.assertFalse(result.needs_user)
        self.assertFalse(result.authorization.allow_commit)
        self.assertTrue(result.authorization.allow_push)

    def test_capability_failure_safe_stops_without_rewriting_attempts(self):
        attempt = CapabilityAttempt(
            "build", "source-1", "env-1", "timed-out", "return observed")
        state = flow(
            phase=Phase.QUALITY,
            capabilities=(attempt,),
            delivery_files=("src/a.cpp",),
        )
        state = authorize(state, ("src/a.cpp",))

        result = apply_moonlight_policy(
            state, AdvanceRequest("quality-complete"))

        self.assertTrue(result.needs_user)
        self.assertTrue(result.safe_stop)
        self.assertEqual(Phase.QUALITY, result.state.phase)
        self.assertEqual((attempt,), result.state.capabilities)
        self.assertTrue(any("capability" in risk.lower()
                            for risk in result.state.risks))

    def test_expensive_retry_requires_user_and_does_not_add_an_attempt(self):
        attempt = CapabilityAttempt(
            "ut", "source-1", "env-1", "returned", "opaque return")
        state = authorize(
            flow(capabilities=(attempt,), delivery_files=("src/a.cpp",)),
            ("src/a.cpp",),
        )

        result = apply_moonlight_policy(
            state,
            AdvanceRequest(
                "expensive-capability-retry",
                decision_value="UT retry requested for unchanged inputs.",
            ),
        )

        self.assertTrue(result.needs_user)
        self.assertEqual((attempt,), result.state.capabilities)
        self.assertIn(
            "UT retry requested for unchanged inputs.", result.state.risks)

    def test_real_uncertainty_and_external_blockers_become_unresolved_risks(self):
        cases = (
            ("ambiguity", "Two observable outcomes remain plausible."),
            ("unavailable-material", "The required interface contract is unavailable."),
            ("irreversible-risk", "The migration cannot be safely rolled back."),
            ("blocked-external-dependency", "The internal registry is unavailable."),
        )
        for kind, reason in cases:
            with self.subTest(kind=kind):
                state = authorize(
                    flow(delivery_files=("src/a.cpp",)), ("src/a.cpp",))

                result = apply_moonlight_policy(
                    state, AdvanceRequest(kind, decision_value=reason))

                self.assertTrue(result.needs_user)
                self.assertTrue(result.safe_stop)
                self.assertEqual(Phase.CONSTRUCTION, result.state.phase)
                self.assertIn(reason, result.state.risks)
                self.assertFalse(result.authorization.allow_push)

    def test_final_push_needs_exact_authorization_and_real_completion(self):
        state = authorize(
            flow(phase=Phase.DELIVERY, delivery_files=("src/a.cpp",)),
            ("src/a.cpp",),
        )

        ready = apply_moonlight_policy(
            state, AdvanceRequest("delivery-ready"))
        premature = apply_moonlight_policy(
            ready.state, AdvanceRequest("delivery-completed"))
        confirmed = apply_moonlight_policy(
            ready.state, AdvanceRequest("delivery-confirmed"))
        completed = apply_moonlight_policy(
            confirmed.state,
            AdvanceRequest(
                "delivery-completed",
                decision_value="The adapter observed commit and push success.",
            ),
        )

        self.assertFalse(ready.needs_user)
        self.assertTrue(ready.authorization.allow_push)
        self.assertEqual("active", premature.state.status)
        self.assertEqual("active", confirmed.state.status)
        self.assertEqual("complete", completed.state.status)
        self.assertIn(
            ("delivery.result", "The adapter observed commit and push success."),
            completed.state.decisions,
        )

    def test_delivery_completion_requires_nonempty_adapter_observation(self):
        state = authorize(
            flow(phase=Phase.DELIVERY, delivery_files=("src/a.cpp",)),
            ("src/a.cpp",),
        )
        state = apply_moonlight_policy(
            state, AdvanceRequest("delivery-confirmed")).state

        for observation in ("", "  \t\r\n"):
            with self.subTest(observation=repr(observation)):
                result = apply_moonlight_policy(
                    state,
                    AdvanceRequest(
                        "delivery-completed",
                        decision_value=observation,
                    ),
                )

                self.assertEqual("active", result.state.status)
                self.assertTrue(result.needs_user)
                self.assertTrue(result.safe_stop)
                self.assertFalse(any(
                    key == "delivery.result"
                    for key, unused in result.state.decisions
                ))
                self.assertIn("adapter", result.reason.lower())

        completed = apply_moonlight_policy(
            state,
            AdvanceRequest(
                "delivery-completed",
                decision_value="  observed remote update  ",
            ),
        )
        self.assertEqual("complete", completed.state.status)
        self.assertIn(
            ("delivery.result", "observed remote update"),
            completed.state.decisions,
        )

    def test_push_failure_never_completes_or_retains_automatic_permission(self):
        state = authorize(
            flow(phase=Phase.DELIVERY, delivery_files=("src/a.cpp",)),
            ("src/a.cpp",),
        )

        result = apply_moonlight_policy(
            state,
            AdvanceRequest(
                "push-failed",
                decision_value="Remote rejected the final push.",
            ),
        )

        self.assertTrue(result.safe_stop)
        self.assertTrue(result.needs_user)
        self.assertEqual("active", result.state.status)
        self.assertIn("Remote rejected the final push.", result.state.risks)
        self.assertFalse(result.authorization.allow_push)

    def test_authorization_survives_schema_v3_round_trip(self):
        state = authorize(
            flow(phase=Phase.DELIVERY, delivery_files=("src/a.cpp",)),
            ("src/a.cpp",),
        )

        restored = FlowState.from_dict(state.to_dict())
        result = apply_moonlight_policy(
            restored, AdvanceRequest("delivery-ready"))

        self.assertFalse(result.needs_user)
        self.assertTrue(result.authorization.allow_commit)
        self.assertTrue(result.authorization.allow_push)

    def test_disabled_policy_delegates_to_normal_user_stops(self):
        state = flow(phase=Phase.STARTUP)

        result = apply_moonlight_policy(
            state, AdvanceRequest("startup-ready"))

        self.assertTrue(result.needs_user)
        self.assertFalse(result.safe_stop)
        self.assertFalse(result.authorization.enabled)


if __name__ == "__main__":
    unittest.main()
