#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for pure workflow completion policy."""

import copy
import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.workflow.completion import (  # noqa: E402
    CompletionEvent,
    choice_config,
    choice_error,
    completion_events,
    evidence_failures,
    resolve_choice,
)


class WorkflowCompletionPolicyTests(unittest.TestCase):
    def test_resolve_choice_only_supplies_moonlight_compatibility_default(self):
        step = {
            "skip_in_moonlight": True,
            "moonlight_choice": "continue",
        }
        self.assertEqual(
            "continue",
            resolve_choice(
                step,
                {"moonlight": {"enabled": True}},
                "",
            ),
        )
        self.assertEqual(
            "adjust",
            resolve_choice(
                step,
                {"moonlight": {"enabled": True}},
                "adjust",
            ),
        )
        self.assertEqual(
            "",
            resolve_choice(step, {}, ""),
        )

    def test_choice_error_preserves_public_message(self):
        step = {
            "choice_key": "workflow",
            "choices": ["full", "tweak"],
        }
        self.assertEqual(
            "--choice 必须为: full|tweak",
            choice_error(step, "review"),
        )
        self.assertEqual("", choice_error(step, "full"))
        self.assertEqual("", choice_error({}, "anything"))

    def test_choice_config_returns_a_detached_string_mapping(self):
        step = {
            "choice_sets": {
                "tweak": {
                    "提交方式": "local",
                    "重试": 2,
                },
            },
        }
        selected = choice_config(step, "tweak")
        self.assertEqual(
            {"提交方式": "local", "重试": "2"},
            selected,
        )
        selected["提交方式"] = "changed"
        self.assertEqual(
            "local",
            step["choice_sets"]["tweak"]["提交方式"],
        )

    def test_evidence_failures_preserves_definition_order(self):
        calls = []

        def first(spec, state):
            calls.append((spec["type"], state["current"]))
            return False, "first failed"

        def second(spec, state):
            calls.append((spec["type"], state["current"]))
            return True, ""

        def third(spec, state):
            calls.append((spec["type"], state["current"]))
            return False, "third failed"

        state = {"current": "verify"}
        self.assertEqual(
            ["first failed", "third failed"],
            evidence_failures(
                {
                    "evidence": [
                        {"type": "first"},
                        {"type": "second"},
                        {"type": "third"},
                    ],
                },
                state,
                {
                    "first": first,
                    "second": second,
                    "third": third,
                },
            ),
        )
        self.assertEqual(
            [
                ("first", "verify"),
                ("second", "verify"),
                ("third", "verify"),
            ],
            calls,
        )

    def test_checkpoint_adjust_is_terminal_completion_event(self):
        state = {
            "choices": {},
            "development_review": {"version": 1},
        }
        self.assertEqual(
            [CompletionEvent("adjust_checkpoint")],
            list(completion_events(
                "build_pace",
                {},
                state,
                "adjust",
                "",
            )),
        )

    def test_checkpoint_activation_precedes_advance(self):
        state = {
            "moonlight": {"enabled": False},
        }
        self.assertEqual(
            [
                CompletionEvent("activate_checkpoint", "continuous"),
                CompletionEvent("advance", note="approved"),
            ],
            list(completion_events(
                "build_pace",
                {},
                state,
                "continuous",
                "approved",
            )),
        )

    def test_story_localization_precedes_advance(self):
        state = {
            "config": {"STORY入库": "不入库", "单号": "REQ-1"},
        }
        self.assertEqual(
            [
                CompletionEvent("localize_story", "REQ-1"),
                CompletionEvent("advance", note=""),
            ],
            list(completion_events(
                "story",
                {},
                state,
                "",
                "",
            )),
        )

    def test_moonlight_quality_resolution_precedes_automatic_advance(self):
        state = {"moonlight": {"enabled": True}}
        self.assertEqual(
            [
                CompletionEvent("resolve_moonlight", "codecheck"),
                CompletionEvent(
                    "advance",
                    note="月光宝盒自动决策",
                ),
            ],
            list(completion_events(
                "rf_codecheck",
                {"user_ack": True},
                state,
                "",
                "",
            )),
        )

    def test_policy_does_not_mutate_inputs(self):
        step = {
            "choice_key": "pace",
            "choice_sets": {"continuous": {"mode": "one"}},
            "user_ack": True,
        }
        state = {
            "moonlight": {"enabled": True},
            "config": {"STORY入库": "提交"},
        }
        original_step = copy.deepcopy(step)
        original_state = copy.deepcopy(state)
        resolve_choice(step, state, "")
        choice_config(step, "continuous")
        list(completion_events(
            "build_pace",
            step,
            state,
            "continuous",
            "",
        ))
        self.assertEqual(original_step, step)
        self.assertEqual(original_state, state)


if __name__ == "__main__":
    unittest.main()
