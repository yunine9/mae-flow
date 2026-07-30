#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for pure workflow completion policy."""

import copy
import os
import sys
import tempfile
from argparse import Namespace
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
    evidence_error,
    evidence_failures,
    resolve_choice,
)
from mae_flow_core import cli_runtime  # noqa: E402


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

    def test_repeated_evidence_error_exposes_the_original_user_exit(self):
        self.assertEqual(
            "证据不足,拒绝推进:\n  - missing",
            evidence_error(
                ["missing"], 1, False, "next", "/tmp/mae-flow.py"),
        )
        message = evidence_error(
            ["missing"],
            2,
            False,
            "next",
            "/tmp/mae-flow.py",
        )
        self.assertIn(
            '执行 python "/tmp/mae-flow.py" goto next '
            '--force --ack "用户原话"',
            message,
        )
        self.assertIn("本步证据已连续 2 次不满足", message)

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

    def test_moonlight_build_plan_prepares_checkpoints_before_advance(self):
        state = {"moonlight": {"enabled": True}}
        self.assertEqual(
            [
                CompletionEvent(
                    "confirm_spec2code",
                    "roadmap,plan",
                    "moonlight",
                ),
                CompletionEvent("prepare_moonlight_checkpoint"),
                CompletionEvent(
                    "advance",
                    note="月光宝盒自动决策",
                ),
            ],
            list(completion_events(
                "build_plan",
                {"user_ack": True},
                state,
                "continue",
                "",
            )),
        )

    def test_continue_confirms_blueprint_as_user_before_advance(self):
        self.assertEqual(
            [
                CompletionEvent(
                    "confirm_spec2code",
                    "blueprint",
                    "user",
                ),
                CompletionEvent("advance", note="approved"),
            ],
            list(completion_events(
                "test_blueprint",
                {"user_ack": True},
                {},
                "continue",
                "approved",
            )),
        )

    def test_revise_does_not_confirm_spec2code_artifacts(self):
        self.assertEqual(
            [CompletionEvent("advance", note="needs changes")],
            list(completion_events(
                "build_plan",
                {"user_ack": True},
                {},
                "revise",
                "needs changes",
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


class WorkflowCompletionAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mf = cli_runtime

    def test_cmd_done_consumes_completion_policy_events(self):
        flow = {
            "steps": {
                "source": {"next": "end"},
                "end": {"terminal": True},
            },
        }
        state = {
            "current": "source",
            "config": {},
            "choices": {},
            "history": [],
            "started": "2026-07-29 10:00:00",
        }
        args = Namespace(
            ack="",
            choice="",
            set=[],
        )
        observed = []

        def events(step_id, step, current, choice, ack):
            observed.append(
                (step_id, step, current, choice, ack)
            )
            yield CompletionEvent(
                "confirm_spec2code",
                "blueprint",
                "user",
            )
            yield CompletionEvent(
                "advance",
                note="policy note",
            )

        def confirm_spec2code(current, kinds, actor):
            observed.append(
                ("confirm_spec2code", current, kinds, actor)
            )

        def advance(flow_value, state_value, sid, step, result, note):
            observed.append(
                (
                    flow_value,
                    state_value,
                    sid,
                    step,
                    result,
                    note,
                )
            )

        original_events = (
            self.mf.workflow_completion.completion_events
        )
        original_advance = self.mf.advance
        original_confirm = self.mf._confirm_spec2code_artifacts
        with tempfile.TemporaryDirectory() as project:
            previous = os.getcwd()
            try:
                os.chdir(project)
                self.mf.workflow_completion.completion_events = events
                self.mf.advance = advance
                self.mf._confirm_spec2code_artifacts = (
                    confirm_spec2code
                )
                self.mf.cmd_done(flow, state, args)
            finally:
                self.mf.workflow_completion.completion_events = (
                    original_events
                )
                self.mf.advance = original_advance
                self.mf._confirm_spec2code_artifacts = original_confirm
                os.chdir(previous)

        self.assertEqual(
            ("source", flow["steps"]["source"], state, "", ""),
            observed[0],
        )
        self.assertEqual(
            (
                "confirm_spec2code",
                state,
                ("blueprint",),
                "user",
            ),
            observed[1],
        )
        self.assertEqual(
            (
                flow,
                state,
                "source",
                flow["steps"]["source"],
                "done",
                "policy note",
            ),
            observed[2],
        )


if __name__ == "__main__":
    unittest.main()
