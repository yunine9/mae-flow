#!/usr/bin/env python3
"""Pure contracts for the recoverable Interactive Grill subflow."""

import json
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
)
from mae_flow_core.orchestration.grill_session import (  # noqa: E402
    apply_grill_event,
    grill_confirmation_gap,
    grill_status,
)


def compact(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


QUESTION = compact({
    "parent": "",
    "evidence": "接口当前只定义主载波行为。",
    "impact": "SUL 选择语义不明确。",
    "recommendation": "仅在配置 SUL 时选择 SUL 资源。",
})
CONVERGENCE = compact({
    "answer_count": 1,
    "grill_sha256": "a" * 64,
})
CRITIC = compact({
    "grill_sha256": "a" * 64,
    "input_coverage": "complete",
    "spec_sha256": "b" * 64,
})


class LeanGrillSessionTests(unittest.TestCase):
    def state(self, path=DeliveryPath.FULL, phase=Phase.SPEC):
        return FlowState(
            ticket="REQ-GRILL",
            path=path,
            phase=phase,
            commit_pace=CommitPace.CONTINUOUS,
        )

    def apply(self, state, kind, key="", value=""):
        result = apply_grill_event(
            state, AdvanceRequest(kind, key, value))
        self.assertIsNotNone(result)
        return result

    def answered(self):
        state = self.state()
        state, needs_user, unused = self.apply(
            state, "grill-question", "GQ-001", QUESTION)
        self.assertTrue(needs_user)
        state, needs_user, unused = self.apply(
            state, "grill-answer", "GQ-001", "用户选择推荐边界。")
        self.assertFalse(needs_user)
        return state

    def test_unrelated_event_is_not_owned_by_grill_policy(self):
        result = apply_grill_event(
            self.state(), AdvanceRequest("story-confirmed"))
        self.assertIsNone(result)

    def test_grill_events_require_full_spec(self):
        cases = (
            self.state(path=DeliveryPath.FOCUSED),
            self.state(phase=Phase.STORY),
        )
        for state in cases:
            with self.subTest(path=state.path, phase=state.phase):
                updated, needs_user, reason = self.apply(
                    state, "grill-question", "GQ-001", QUESTION)
                self.assertEqual(state, updated)
                self.assertFalse(needs_user)
                self.assertIn("Full Spec", reason)

    def test_question_requires_complete_metadata_and_one_open_slot(self):
        state = self.state()
        invalid = compact({
            "parent": "",
            "evidence": "有代码证据",
            "impact": "",
            "recommendation": "采用 SUL",
        })
        unchanged, unused, reason = self.apply(
            state, "grill-question", "GQ-001", invalid)
        self.assertEqual(state, unchanged)
        self.assertIn("impact", reason)

        opened, needs_user, unused = self.apply(
            state, "grill-question", "GQ-001", QUESTION)
        self.assertTrue(needs_user)
        blocked, unused, reason = self.apply(
            opened, "grill-question", "GQ-002", QUESTION)
        self.assertEqual(opened, blocked)
        self.assertIn("GQ-001", reason)

    def test_duplicate_question_and_wrong_answer_key_are_rejected(self):
        opened, unused, unused_reason = self.apply(
            self.state(), "grill-question", "GQ-001", QUESTION)

        duplicate, unused, reason = self.apply(
            opened, "grill-question", "GQ-001", QUESTION)
        self.assertEqual(opened, duplicate)
        self.assertIn("already", reason.lower())

        wrong, needs_user, reason = self.apply(
            opened, "grill-answer", "GQ-002", "确认。")
        self.assertEqual(opened, wrong)
        self.assertTrue(needs_user)
        self.assertIn("GQ-001", reason)

    def test_answer_closes_the_only_open_question(self):
        state = self.answered()
        status = grill_status(state)

        self.assertEqual("", status.open_question)
        self.assertEqual(("GQ-001",), status.question_ids)
        self.assertEqual(("GQ-001",), status.answered_ids)

    def test_convergence_requires_one_answer_and_no_open_question(self):
        empty = self.state()
        unchanged, unused, reason = self.apply(
            empty, "grill-converged", value=CONVERGENCE)
        self.assertEqual(empty, unchanged)
        self.assertIn("one answered", reason.lower())

        opened, unused, unused_reason = self.apply(
            empty, "grill-question", "GQ-001", QUESTION)
        unchanged, needs_user, reason = self.apply(
            opened, "grill-converged", value=CONVERGENCE)
        self.assertEqual(opened, unchanged)
        self.assertTrue(needs_user)
        self.assertIn("GQ-001", reason)

        answered = self.answered()
        converged, needs_user, unused = self.apply(
            answered, "grill-converged", value=CONVERGENCE)
        self.assertFalse(needs_user)
        self.assertEqual(
            "a" * 64, grill_status(converged).convergence["grill_sha256"])

    def test_critic_requires_convergence_and_matching_complete_coverage(self):
        answered = self.answered()
        unchanged, unused, reason = self.apply(
            answered, "grill-clear", value=CRITIC)
        self.assertEqual(answered, unchanged)
        self.assertIn("converge", reason.lower())

        converged, unused, unused_reason = self.apply(
            answered, "grill-converged", value=CONVERGENCE)
        mismatch = compact({
            "grill_sha256": "c" * 64,
            "input_coverage": "complete",
            "spec_sha256": "b" * 64,
        })
        unchanged, unused, reason = self.apply(
            converged, "grill-clear", value=mismatch)
        self.assertEqual(converged, unchanged)
        self.assertIn("digest", reason.lower())

        reviewed, needs_user, unused = self.apply(
            converged, "grill-clear", value=CRITIC)
        self.assertFalse(needs_user)
        self.assertEqual(
            "complete", grill_status(reviewed).critic["input_coverage"])
        self.assertEqual("", grill_confirmation_gap(reviewed))

    def test_new_question_invalidates_convergence_and_critic(self):
        state = self.answered()
        state, unused, unused_reason = self.apply(
            state, "grill-converged", value=CONVERGENCE)
        state, unused, unused_reason = self.apply(
            state, "grill-clear", value=CRITIC)

        derived = compact({
            "parent": "GQ-001",
            "evidence": "回答引入了新的资源选择状态。",
            "impact": "回退条件尚不明确。",
            "recommendation": "资源不可用时回退主载波。",
        })
        reopened, needs_user, unused = self.apply(
            state, "grill-question", "GQ-002", derived)
        status = grill_status(reopened)

        self.assertTrue(needs_user)
        self.assertEqual({}, status.convergence)
        self.assertEqual({}, status.critic)
        self.assertIn("GQ-002", grill_confirmation_gap(reopened))


if __name__ == "__main__":
    unittest.main()
