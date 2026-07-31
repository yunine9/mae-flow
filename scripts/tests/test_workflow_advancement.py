#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for pure workflow advancement policy."""

import copy
import contextlib
import io
import json
import os
import sys
import tempfile
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
from mae_flow_core import cli_runtime  # noqa: E402


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
            (1, "staged", "分阶段检查点已检视"),
            (1, "continuous", "一次完成模式改在质量链后统一检视"),
            (2, "staged", "分阶段检查点已检视"),
            (2, "continuous", "一次完成模式改在质量链后统一检视"),
        ]
        for version, mode, note in cases:
            with self.subTest(version=version, mode=mode):
                state = {
                    "choices": {},
                    "development_review": {
                        "version": version,
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

    def test_completed_checkpoints_replace_duplicate_compile_and_review(self):
        flow = {
            "steps": {
                "tw_change": {"next": "tw_compile"},
                "tw_compile": {"next": "tw_review"},
                "tw_review": {
                    "choice_key": "tw_review_decision",
                    "next": {"continue": "tw_codecheck"},
                },
                "tw_codecheck": {"next": "end"},
            },
        }
        state = {
            "choices": {},
            "development_review": {
                "version": 2,
                "status": "active",
                "mode": "staged",
                "current_index": 1,
                "checkpoints": [{
                    "id": "CP1",
                    "status": "accepted",
                }],
            },
        }
        self.assertEqual(
            [
                TransitionEvent(
                    "audit",
                    "tw_compile",
                    "checkpoint:replaced-duplicate-compile",
                    "检查点内已完成逐批编译",
                ),
                TransitionEvent(
                    "audit",
                    "tw_review",
                    "checkpoint:replaced-legacy-review",
                    "分阶段检查点已检视",
                ),
                TransitionEvent("target", "tw_codecheck"),
            ],
            list(transition_events(
                flow,
                state,
                "tw_change",
                flow["steps"]["tw_change"],
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


class WorkflowAdvanceAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mf = cli_runtime

    def test_advance_consumes_policy_events(self):
        flow = {
            "steps": {
                "source": {
                    "title": "source",
                    "next": "rf_compile",
                },
                "rf_compile": {
                    "title": "wrong target",
                    "terminal": True,
                },
                "end": {
                    "title": "policy target",
                    "terminal": True,
                },
            },
        }
        state = {
            "current": "source",
            "config": {},
            "choices": {},
            "history": [],
            "started": "2026-07-29 10:00:00",
        }

        def policy_events(_flow, _state, _step_id, _step):
            yield TransitionEvent(
                "audit",
                "compat",
                "compat:skipped",
                "literal audit",
            )
            yield TransitionEvent("target", "end")

        with tempfile.TemporaryDirectory() as project:
            previous = os.getcwd()
            original = (
                self.mf.workflow_advancement.transition_events
            )
            try:
                os.chdir(project)
                self.mf.workflow_advancement.transition_events = (
                    policy_events
                )
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.mf.advance(
                        flow,
                        state,
                        "source",
                        flow["steps"]["source"],
                        "done",
                    )
                with open(
                        self.mf.STATE_PATH,
                        encoding="utf-8") as stream:
                    saved = json.load(stream)
            finally:
                self.mf.workflow_advancement.transition_events = original
                os.chdir(previous)

        self.assertEqual("end", saved["current"])
        self.assertEqual(
            {
                "step": "source",
                "result": "done",
                "note": "",
            },
            {
                key: saved["history"][0][key]
                for key in ("step", "result", "note")
            },
        )
        self.assertEqual(
            {
                "step": "compat",
                "result": "compat:skipped",
                "note": "literal audit",
            },
            {
                key: saved["history"][1][key]
                for key in ("step", "result", "note")
            },
        )
        self.assertTrue(saved["history"][0]["at"])
        self.assertTrue(saved["history"][1]["at"])
        self.assertIn("end", saved["step_heads"])
        self.assertIn(
            "[mae-flow] source done → 进入 end\n",
            output.getvalue(),
        )

    def test_advance_preserves_unresolved_moonlight_error(self):
        flow = {
            "steps": {
                "source": {
                    "title": "source",
                    "next": "broken_review",
                },
                "broken_review": {
                    "title": "broken review",
                    "skip_in_moonlight": True,
                    "choice_key": "review",
                    "next": {"continue": "end"},
                },
                "end": {
                    "title": "end",
                    "terminal": True,
                },
            },
        }
        state = {
            "current": "source",
            "config": {},
            "choices": {},
            "history": [],
            "started": "2026-07-29 10:00:00",
            "moonlight": {"enabled": True},
        }
        error = io.StringIO()
        with tempfile.TemporaryDirectory() as project:
            previous = os.getcwd()
            try:
                os.chdir(project)
                with self.assertRaises(SystemExit) as raised:
                    with contextlib.redirect_stderr(error):
                        self.mf.advance(
                            flow,
                            state,
                            "source",
                            flow["steps"]["source"],
                            "done",
                        )
                state_file_exists = os.path.exists(
                    self.mf.STATE_PATH)
            finally:
                os.chdir(previous)

        self.assertEqual(2, raised.exception.code)
        self.assertEqual(
            "[mae-flow] 月光旁路步骤 broken_review "
            "缺少可解析的 moonlight_choice/next，拒绝卡死流程。\n",
            error.getvalue(),
        )
        self.assertEqual("source", state["current"])
        self.assertEqual("done", state["history"][0]["result"])
        self.assertFalse(state_file_exists)


if __name__ == "__main__":
    unittest.main()
