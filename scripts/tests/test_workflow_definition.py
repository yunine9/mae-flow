#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for workflow definition and pure transition policy."""

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.workflow.transitions import (  # noqa: E402
    next_step,
    resolved_next,
    transition_targets,
    workflow_chain,
)


class WorkflowTransitionTests(unittest.TestCase):
    def test_transition_targets_preserves_declared_order(self):
        self.assertEqual(
            ("build", "skip"),
            transition_targets({"next": {"yes": "build", "no": "skip"}}),
        )

    def test_next_step_resolves_plain_next_and_state_choices(self):
        self.assertEqual(
            "build",
            next_step({"next": "build"}, {"choices": {}}),
        )
        self.assertEqual(
            "hotfix-open",
            next_step(
                {
                    "next_by": "workflow",
                    "next": {
                        "full": "design",
                        "hotfix": "hotfix-open",
                    },
                },
                {"choices": {"workflow": "hotfix"}},
            ),
        )
        self.assertEqual(
            "revise",
            next_step(
                {
                    "choice_key": "review",
                    "next": {
                        "continue": "verify",
                        "revise": "revise",
                    },
                },
                {"choices": {"review": "continue"}},
                "revise",
            ),
        )

    def test_next_step_returns_none_for_missing_or_malformed_choice(self):
        step = {
            "choice_key": "review",
            "next": {"continue": "verify"},
        }
        self.assertIsNone(next_step(step, {"choices": {}}))
        self.assertIsNone(next_step(step, {"choices": []}))

    def test_resolved_next_uses_empty_step_for_unknown_history_entry(self):
        self.assertIsNone(
            resolved_next(
                {"steps": {"build": {"next": "verify"}}},
                {"choices": {}},
                "missing",
            )
        )

    def test_workflow_chain_selects_workflow_and_complete_optional_branch(self):
        flow = {
            "start": "start",
            "steps": {
                "start": {
                    "next_by": "workflow",
                    "next": {
                        "full": "ask",
                        "hotfix": "fix",
                    },
                },
                "ask": {"next": {"yes": "design", "no": "fix"}},
                "design": {"next": "end"},
                "fix": {"next": "end"},
                "end": {"terminal": True},
            },
        }
        self.assertEqual(
            ["start", "ask", "design", "end"],
            workflow_chain(flow, "full"),
        )
        self.assertEqual(
            ["start", "fix", "end"],
            workflow_chain(flow, "hotfix"),
        )

    def test_workflow_chain_stops_at_first_cycle(self):
        flow = {
            "start": "one",
            "steps": {
                "one": {"next": "two"},
                "two": {"next": "one"},
            },
        }
        self.assertEqual(
            ["one", "two"],
            workflow_chain(flow, "full"),
        )


if __name__ == "__main__":
    unittest.main()
