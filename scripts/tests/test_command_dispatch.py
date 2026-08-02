#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Contracts for the side-effect-free CLI command routing table."""

import os
import inspect
import sys
import unittest


SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.command_dispatch import (  # noqa: E402
    LEAN_ROUTES,
    CommandRoute,
    lean_route,
    invoke,
)
from mae_flow_core import cli_runtime  # noqa: E402


class CommandDispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cli = cli_runtime

    def test_lean_routes_expose_only_workflow_and_one_shot_commands(self):
        workflow = {
            "start", "current", "advance", "decision",
            "capability-record", "manifest", "exit",
        }
        toolbox = {"ut", "codecheck", "grill", "story", "chain"}
        utilities = {"lightcheck"}
        self.assertEqual(workflow | toolbox | utilities, set(LEAN_ROUTES))
        self.assertEqual(
            CommandRoute("cmd_lean_start", ("root", "args")),
            LEAN_ROUTES["start"],
        )
        for command in toolbox:
            self.assertEqual(
                CommandRoute("cmd_lean_toolbox", ("root", "args")),
                LEAN_ROUTES[command],
            )

    def test_unknown_routes_are_explicitly_unhandled(self):
        self.assertIsNone(lean_route("unknown"))

    def test_route_tables_cannot_be_mutated(self):
        with self.assertRaises(TypeError):
            LEAN_ROUTES["new"] = CommandRoute("handler", ())

    def test_every_route_resolves_to_a_callable_handler(self):
        for route in LEAN_ROUTES.values():
            with self.subTest(handler=route.handler):
                self.assertTrue(callable(getattr(
                    self.cli, route.handler, None)))
                self.assertTrue(set(route.arguments) <= {
                    "root", "args"})
                self.assertEqual(
                    len(route.arguments),
                    len(inspect.signature(getattr(
                        self.cli, route.handler)).parameters),
                )

    def test_invoke_uses_the_declared_argument_order(self):
        calls = []

        def handler(*values):
            calls.append(values)
            return "handled"

        route = CommandRoute("handler", ("state", "flow", "args"))
        self.assertEqual(
            "handled",
            invoke(
                route,
                {"handler": handler},
                flow="FLOW",
                state="STATE",
                args="ARGS",
            ),
        )
        self.assertEqual([("STATE", "FLOW", "ARGS")], calls)

    def test_invoke_rejects_an_unknown_handler(self):
        with self.assertRaisesRegex(
                RuntimeError, "unknown Mae-Flow command handler"):
            invoke(CommandRoute("missing", ()), {})


if __name__ == "__main__":
    unittest.main()
