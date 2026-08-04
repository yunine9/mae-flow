#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Exact identity and opaque-return contracts for capability observation."""

import json
import os
import sys
import tempfile
import unittest


TESTS = os.path.abspath(os.path.dirname(__file__))
SCRIPTS = os.path.abspath(os.path.join(TESTS, ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.adapters.lean_hook import LeanHookAdapter  # noqa: E402
from mae_flow_core.application.hooks.capability_observation import (  # noqa: E402
    SUMMARY_LIMIT,
    observe_return,
)
from mae_flow_core.orchestration import (  # noqa: E402
    CommitPace,
    DeliveryPath,
    FlowState,
)
from mae_flow_core.orchestration.capability_registry import (  # noqa: E402
    CapabilitySelector,
    load_capability_registry,
    match_capability,
)


class CapabilityRegistryTests(unittest.TestCase):
    def test_current_agent_hosts_match_only_exact_capability_identities(self):
        registry = load_capability_registry("/missing")
        cases = (
            (
                {"tool_name": "Agent", "tool_input": {
                    "subagent_type": "mae-flow:ut-generator-agent"}},
                "ut",
            ),
            (
                {"tool_name": "Task", "tool_input": {
                    "subagent_type": "story-generator-agent"}},
                "story",
            ),
            (
                {"tool_name": "Skill", "tool_input": {
                    "skill": "mae-flow:build-fix"}},
                "build",
            ),
        )
        for payload, kind in cases:
            with self.subTest(payload=payload):
                matched = match_capability(payload, registry)
                self.assertIsNotNone(matched)
                self.assertEqual(kind, matched.kind)

        self.assertIsNone(match_capability({
            "tool_name": "spawn_agent",
            "tool_input": {
                "task_name": "codecheck_advisor_agent",
                "message": "the async acknowledgement is not a return",
            },
        }, registry))

    def test_defaults_match_only_exact_task_and_skill_identities(self):
        cases = (
            ("Task", {"subagent_type": "ut-generator-agent"}, "ut"),
            ("Task", {"subagent_type": "codecheck-advisor-agent"},
             "codecheck"),
            ("Task", {"subagent_type": "compile-agent"}, "build"),
            ("Agent", {"agent_type": "mae-flow:craft-reviewer-agent"},
             "reviewer"),
            ("Skill", {"skill": "build-fix"}, "build"),
            ("Skill", {"name": "build-fix"}, "build"),
        )
        registry = load_capability_registry("/path/that/does/not/exist")

        for tool_name, tool_input, kind in cases:
            with self.subTest(tool_name=tool_name, tool_input=tool_input):
                matched = match_capability({
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                }, registry)
                self.assertIsNotNone(matched)
                self.assertEqual(kind, matched.kind)
                self.assertEqual(next(iter(tool_input.values())), matched.identity)

    def test_missing_or_inexact_identity_and_unknown_tools_are_ignored(self):
        registry = load_capability_registry("/missing")
        payloads = (
            {"tool_name": "Task", "tool_input": {}},
            {"tool_name": "Task"},
            {"tool_name": "Task", "tool_input": {
                "description": "run compile-agent",
                "prompt": "please use compile-agent",
            }},
            {"tool_name": "Task", "tool_input": {
                "subagent_type": "compile-agent-extra",
            }},
            {"tool_name": "Skill", "tool_input": {"skill": "BUILD-FIX"}},
            {"tool_name": "Bash", "tool_input": {
                "command": "build-fix && echo PASS",
            }},
            {"tool_name": "FutureTool", "tool_input": {
                "subagent_type": "compile-agent",
            }},
        )

        for payload in payloads:
            with self.subTest(payload=payload):
                self.assertIsNone(match_capability(payload, registry))

    def test_project_selectors_add_language_specific_ut_skill(self):
        with tempfile.TemporaryDirectory() as root:
            with open(
                    os.path.join(root, ".mae-flow-defaults.json"),
                    "w", encoding="utf-8") as stream:
                json.dump({
                    "capability_selectors": [{
                        "tool_name": "Skill",
                        "identity_fields": ["skill", "name"],
                        "values": {
                            "cpp-ut": "ut",
                            "java-unit-test": "ut",
                        },
                    }],
                }, stream)
            registry = load_capability_registry(root)

            for field, identity in (
                    ("skill", "cpp-ut"), ("name", "java-unit-test")):
                matched = match_capability({
                    "tool_name": "Skill",
                    "tool_input": {field: identity},
                }, registry)
                self.assertEqual(("ut", identity), (
                    matched.kind, matched.identity))

            self.assertEqual("build", match_capability({
                "tool_name": "Skill",
                "tool_input": {"skill": "build-fix"},
            }, registry).kind)

    def test_project_config_cannot_treat_async_spawn_ack_as_a_return(self):
        with tempfile.TemporaryDirectory() as root:
            with open(
                    os.path.join(root, ".mae-flow-defaults.json"),
                    "w", encoding="utf-8") as stream:
                json.dump({
                    "capability_selectors": [{
                        "tool_name": "spawn_agent",
                        "identity_fields": ["task_name"],
                        "values": {"ut_generator_agent": "ut"},
                    }],
                }, stream)

            matched = match_capability({
                "tool_name": "spawn_agent",
                "tool_input": {"task_name": "ut_generator_agent"},
            }, load_capability_registry(root))

            self.assertIsNone(matched)

    def test_custom_bash_selector_requires_exact_command_value(self):
        registry = (
            CapabilitySelector(
                "Bash", ("command",), {"run-project-ut": "ut"}),
        )
        exact = match_capability({
            "tool_name": "Bash",
            "tool_input": {"command": "run-project-ut"},
        }, registry)
        mentioned = match_capability({
            "tool_name": "Bash",
            "tool_input": {"command": "echo run-project-ut"},
        }, registry)

        self.assertEqual(("ut", "run-project-ut"), (
            exact.kind, exact.identity))
        self.assertIsNone(mentioned)

    def test_project_selector_cannot_redefine_the_trusted_build_skill(self):
        registry = (
            CapabilitySelector(
                "Bash", ("command",), {"pretend-build": "build"}),
            CapabilitySelector(
                "Skill", ("skill",), {"other-build": "build"}),
        )

        for tool_name, tool_input in (
                ("Bash", {"command": "pretend-build"}),
                ("Skill", {"skill": "other-build"})):
            with self.subTest(tool_name=tool_name):
                self.assertIsNone(match_capability({
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                }, registry))

    def test_selector_rejects_string_in_place_of_identity_field_list(self):
        with self.assertRaises(ValueError):
            CapabilitySelector(
                "Skill", "name", {"cpp-ut": "ut"})

    def test_conflicting_exact_identity_fields_fail_open(self):
        registry = (
            CapabilitySelector(
                "Skill", ("skill", "name"), {
                    "cpp-ut": "ut",
                    "java-unit-test": "ut",
                }),
        )

        matched = match_capability({
            "tool_name": "Skill",
            "tool_input": {
                "skill": "cpp-ut",
                "name": "java-unit-test",
            },
        }, registry)

        self.assertIsNone(matched)

    def test_known_and_unknown_identity_fields_fail_open_but_same_is_valid(self):
        registry = load_capability_registry("/missing")

        unknown = match_capability({
            "tool_name": "Skill",
            "tool_input": {
                "skill": "build-fix",
                "name": "unknown-skill",
            },
        }, registry)
        same = match_capability({
            "tool_name": "Skill",
            "tool_input": {
                "skill": "build-fix",
                "name": "build-fix",
            },
        }, registry)

        self.assertIsNone(unknown)
        self.assertEqual(("build", "build-fix"), (
            same.kind, same.identity))

    def test_invalid_optional_config_fails_open_to_defaults(self):
        with tempfile.TemporaryDirectory() as root:
            with open(
                    os.path.join(root, ".mae-flow-defaults.json"),
                    "w", encoding="utf-8") as stream:
                stream.write("{broken")

            registry = load_capability_registry(root)

            self.assertEqual("build", match_capability({
                "tool_name": "Skill",
                "tool_input": {"skill": "build-fix"},
            }, registry).kind)


class ReturnObservationTests(unittest.TestCase):
    def test_return_presence_distinguishes_absent_from_present_null(self):
        absent = observe_return({"tool_name": "Skill"})
        present = observe_return({
            "tool_name": "Skill",
            "tool_response": None,
        })

        self.assertFalse(absent.return_present)
        self.assertEqual("", absent.summary)
        self.assertTrue(present.return_present)
        self.assertEqual("null", present.summary)

    def test_summary_is_bounded_without_interpreting_quality_text(self):
        raw = "PASS CLEAN warnings=41 disabled=7 count=900 " + ("x" * 700)

        observation = observe_return({"tool_response": raw})

        self.assertTrue(observation.return_present)
        self.assertEqual(SUMMARY_LIMIT, len(observation.summary))
        self.assertEqual(raw[:SUMMARY_LIMIT], observation.summary)


class LeanCapabilityHookBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = self.temporary.name
        self.state_path = os.path.join(self.root, ".mae-flow.json")
        state = FlowState.new(
            "REQ-OBSERVE", DeliveryPath.FULL, CommitPace.CONTINUOUS)
        with open(self.state_path, "w", encoding="utf-8") as stream:
            json.dump(state.to_dict(), stream)

    def read_state(self):
        with open(self.state_path, encoding="utf-8") as stream:
            return FlowState.from_dict(json.load(stream))

    def test_capability_tool_callbacks_are_noops_at_the_hook_boundary(self):
        adapter = LeanHookAdapter(
            self.root, marker_root=os.path.join(self.root, "markers"))
        payload = {
            "tool_name": "Skill",
            "tool_use_id": "tool-build-1",
            "tool_input": {"skill": "build-fix"},
        }

        pre = adapter.handle("PreToolUse", payload)
        post = adapter.handle("PostToolUse", dict(
            payload, tool_response="opaque synchronous host return"))

        self.assertEqual(0, pre.exit_code)
        self.assertEqual(0, post.exit_code)
        self.assertEqual((), self.read_state().capabilities)
        self.assertFalse(os.path.exists(os.path.join(
            self.root, ".mae-flow-work", "lean-hook-user-events.json")))

    def test_fictional_capability_fields_do_not_create_attempts(self):
        response = LeanHookAdapter(
            self.root, marker_root=os.path.join(self.root, "markers"),
        ).handle("PostToolUse", {
            "tool_name": "Bash",
            "tool_input": {"command": "echo ordinary"},
            "tool_response": "ordinary",
            "capability_record": {
                "kind": "build",
                "outcome": "returned",
                "summary": "invented",
            },
        })

        self.assertEqual(0, response.exit_code)
        self.assertEqual((), self.read_state().capabilities)


if __name__ == "__main__":
    unittest.main()
