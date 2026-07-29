#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for pure workflow advancement policy."""

import copy
import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.workflow.advancement import (  # noqa: E402
    TransitionEvent,
    TransitionResolutionError,
    transition_events,
)


class WorkflowAdvancementPolicyTests(unittest.TestCase):
    def test_plain_transition_emits_only_final_target(self):
        self.assertEqual(
            [TransitionEvent("target", "verify")],
            list(transition_events(
                {"steps": {"build": {"next": "verify"}}},
                {"choices": {}},
                "build",
                {"next": "verify"},
            )),
        )

    def test_legacy_state_bypasses_new_pace_node(self):
        flow = {
            "steps": {
                "open": {"next": "tw_pace"},
                "tw_pace": {
                    "choice_key": "development_pace",
                    "next": {"continuous": "change"},
                },
                "change": {"next": "end"},
            },
        }
        self.assertEqual(
            [
                TransitionEvent(
                    "audit",
                    "tw_pace",
                    "legacy:skipped-development-pace",
                    "旧版在途状态没有检查点协议标记，保持升级前路径",
                ),
                TransitionEvent("target", "change"),
            ],
            list(transition_events(
                flow,
                {"choices": {}},
                "open",
                flow["steps"]["open"],
            )),
        )

    def test_legacy_state_bypasses_new_final_review(self):
        flow = {
            "steps": {
                "verify": {"next": "delivery_review"},
                "delivery_review": {"next": "archive_confirm"},
                "archive_confirm": {"next": "archive"},
            },
        }
        self.assertEqual(
            [
                TransitionEvent(
                    "audit",
                    "delivery_review",
                    "legacy:skipped-final-review",
                    "旧版在途状态没有开发节奏收据，保持升级前路径",
                ),
                TransitionEvent("target", "archive_confirm"),
            ],
            list(transition_events(
                flow,
                {"choices": {}},
                "verify",
                flow["steps"]["verify"],
            )),
        )

    def test_active_checkpoint_replaces_legacy_review_nodes(self):
        flow = {
            "steps": {
                "compile": {"next": "build_review"},
                "build_review": {
                    "choice_key": "build_review_decision",
                    "next": {"continue": "tw_review"},
                },
                "tw_review": {
                    "choice_key": "tw_review_decision",
                    "next": {"continue": "quality"},
                },
                "quality": {"next": "end"},
            },
        }
        cases = [
            ("staged", "分阶段检查点已检视"),
            ("continuous", "一次完成模式改在质量链后统一检视"),
        ]
        for mode, note in cases:
            with self.subTest(mode=mode):
                state = {
                    "choices": {},
                    "development_review": {
                        "version": 1,
                        "status": "active",
                        "mode": mode,
                    },
                }
                self.assertEqual(
                    [
                        TransitionEvent(
                            "audit",
                            "build_review",
                            "checkpoint:replaced-legacy-review",
                            note,
                        ),
                        TransitionEvent(
                            "audit",
                            "tw_review",
                            "checkpoint:replaced-legacy-review",
                            note,
                        ),
                        TransitionEvent("target", "quality"),
                    ],
                    list(transition_events(
                        flow,
                        state,
                        "compile",
                        flow["steps"]["compile"],
                    )),
                )

    def test_moonlight_bypasses_consecutive_human_review_nodes(self):
        flow = {
            "steps": {
                "open": {"next": "build_pace"},
                "build_pace": {
                    "skip_in_moonlight": True,
                    "moonlight_choice": "continuous",
                    "choice_key": "pace",
                    "next": {"continuous": "build_review"},
                },
                "build_review": {
                    "skip_in_moonlight": True,
                    "moonlight_choice": "continue",
                    "choice_key": "review",
                    "next": {"continue": "verify"},
                },
                "verify": {"next": "end"},
            },
        }
        self.assertEqual(
            [
                TransitionEvent(
                    "audit",
                    "build_pace",
                    "moonlight:skipped-human-review",
                    "无人值守模式不进入编译后用户检视",
                ),
                TransitionEvent(
                    "audit",
                    "build_review",
                    "moonlight:skipped-human-review",
                    "无人值守模式不进入编译后用户检视",
                ),
                TransitionEvent("target", "verify"),
            ],
            list(transition_events(
                flow,
                {"choices": {}, "moonlight": {"enabled": True}},
                "open",
                flow["steps"]["open"],
            )),
        )

    def test_moonlight_cycle_stops_at_first_repeated_target(self):
        flow = {
            "steps": {
                "open": {"next": "review_one"},
                "review_one": {
                    "skip_in_moonlight": True,
                    "moonlight_choice": "continue",
                    "choice_key": "review",
                    "next": {"continue": "review_two"},
                },
                "review_two": {
                    "skip_in_moonlight": True,
                    "moonlight_choice": "continue",
                    "choice_key": "review",
                    "next": {"continue": "review_one"},
                },
            },
        }
        self.assertEqual(
            [
                TransitionEvent(
                    "audit",
                    "review_one",
                    "moonlight:skipped-human-review",
                    "无人值守模式不进入编译后用户检视",
                ),
                TransitionEvent(
                    "audit",
                    "review_two",
                    "moonlight:skipped-human-review",
                    "无人值守模式不进入编译后用户检视",
                ),
                TransitionEvent("target", "review_one"),
            ],
            list(transition_events(
                flow,
                {"choices": {}, "moonlight": {"enabled": True}},
                "open",
                flow["steps"]["open"],
            )),
        )

    def test_moonlight_defers_archive_and_push_enters_review(self):
        flow = {
            "steps": {
                "verify": {"next": "archive_confirm"},
                "archive_confirm": {"next": "archive"},
                "push": {"next": "end"},
            },
        }
        state = {"choices": {}, "moonlight": {"enabled": True}}
        self.assertEqual(
            [
                TransitionEvent(
                    "audit",
                    "verify",
                    "moonlight:archive-deferred",
                    "夜间先推送，规格定稿留到晨间 finalize",
                ),
                TransitionEvent("target", "push"),
            ],
            list(transition_events(
                flow,
                state,
                "verify",
                flow["steps"]["verify"],
            )),
        )
        self.assertEqual(
            [TransitionEvent("target", "moonlight_review")],
            list(transition_events(
                flow,
                state,
                "push",
                flow["steps"]["push"],
            )),
        )

    def test_malformed_moonlight_chain_raises_after_prior_audit(self):
        flow = {
            "steps": {
                "open": {"next": "good_review"},
                "good_review": {
                    "skip_in_moonlight": True,
                    "moonlight_choice": "continue",
                    "choice_key": "review",
                    "next": {"continue": "broken_review"},
                },
                "broken_review": {
                    "skip_in_moonlight": True,
                    "choice_key": "review",
                    "next": {"continue": "verify"},
                },
                "verify": {"next": "end"},
            },
        }
        state = {"choices": {}, "moonlight": {"enabled": True}}
        flow_before = copy.deepcopy(flow)
        state_before = copy.deepcopy(state)
        events = transition_events(
            flow,
            state,
            "open",
            flow["steps"]["open"],
        )
        self.assertEqual(
            TransitionEvent(
                "audit",
                "good_review",
                "moonlight:skipped-human-review",
                "无人值守模式不进入编译后用户检视",
            ),
            next(events),
        )
        with self.assertRaises(TransitionResolutionError) as raised:
            next(events)
        self.assertEqual("broken_review", raised.exception.step_id)
        self.assertEqual(flow_before, flow)
        self.assertEqual(state_before, state)

    def test_successful_transition_does_not_mutate_inputs(self):
        flow = {
            "steps": {
                "open": {"next": "tw_pace"},
                "tw_pace": {
                    "choice_key": "development_pace",
                    "next": {"continuous": "change"},
                },
                "change": {"next": "end"},
            },
        }
        state = {"choices": {}}
        flow_before = copy.deepcopy(flow)
        state_before = copy.deepcopy(state)
        list(transition_events(
            flow,
            state,
            "open",
            flow["steps"]["open"],
        ))
        self.assertEqual(flow_before, flow)
        self.assertEqual(state_before, state)


if __name__ == "__main__":
    unittest.main()
