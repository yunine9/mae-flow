#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for workflow definition and pure transition policy."""

import json
import os
import sys
import tempfile
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.workflow.definition import (  # noqa: E402
    definition_errors,
    load_definition,
)
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


class WorkflowDefinitionTests(unittest.TestCase):
    def test_load_definition_preserves_unknown_fields(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "flow.json")
            with open(path, "w", encoding="utf-8") as stream:
                json.dump(
                    {
                        "start": "end",
                        "steps": {"end": {"terminal": True}},
                        "future_field": {"keep": 7},
                    },
                    stream,
                )
            self.assertEqual(
                {"keep": 7},
                load_definition(path)["future_field"],
            )

    def test_load_definition_preserves_json_decode_error(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "flow.json")
            with open(path, "w", encoding="utf-8") as stream:
                stream.write("{broken")
            with self.assertRaises(json.JSONDecodeError):
                load_definition(path)

    def test_definition_errors_reports_invalid_root_structures(self):
        self.assertEqual(
            ["flow root must be an object"],
            definition_errors([]),
        )
        self.assertEqual(
            ["steps must be an object"],
            definition_errors({"start": "begin", "steps": []}),
        )

    def test_definition_errors_reports_invalid_step_structures(self):
        cases = [
            (
                {
                    "start": "broken",
                    "steps": {"broken": []},
                },
                ["step broken must be an object"],
            ),
            (
                {
                    "start": "begin",
                    "steps": {
                        "begin": {"next": []},
                        "end": {"terminal": True},
                    },
                },
                ["step begin has unsupported next type: list"],
            ),
            (
                {
                    "start": "begin",
                    "steps": {
                        "begin": {"next": {"yes": None}},
                        "end": {"terminal": True},
                    },
                },
                ["step begin has invalid next target: None"],
            ),
            (
                {
                    "start": 7,
                    "steps": {7: {"terminal": True}},
                },
                ["step id must be a non-empty string: 7"],
            ),
        ]
        for definition, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(expected, definition_errors(definition))

    def test_definition_errors_reports_unknown_start_and_edge(self):
        self.assertEqual(
            [
                "start references unknown step: missing",
                "step begin references unknown step: gone",
            ],
            definition_errors(
                {
                    "start": "missing",
                    "steps": {
                        "begin": {"next": {"yes": "gone"}},
                        "end": {"terminal": True},
                    },
                }
            ),
        )

    def test_definition_errors_reports_missing_step_document(self):
        with tempfile.TemporaryDirectory() as steps_dir:
            self.assertEqual(
                ["step begin is missing document: begin.md"],
                definition_errors(
                    {
                        "start": "begin",
                        "steps": {
                            "begin": {"next": "end"},
                            "end": {"terminal": True},
                        },
                    },
                    steps_dir,
                ),
            )

    def test_repository_definition_is_valid(self):
        definition = load_definition(
            os.path.join(ROOT, "flow", "flow.json")
        )
        self.assertEqual(
            [],
            definition_errors(
                definition,
                os.path.join(ROOT, "flow", "steps"),
            ),
        )


if __name__ == "__main__":
    unittest.main()
