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
    def test_defaults_match_only_exact_task_and_skill_identities(self):
        cases = (
            ("Task", {"subagent_type": "compile-agent"}, "build"),
            ("Task", {"subagent_type": "ut-generator-agent"}, "ut"),
            ("Task", {"subagent_type": "codecheck-fix-agent"}, "codecheck"),
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

    def test_invalid_optional_config_fails_open_to_defaults(self):
        with tempfile.TemporaryDirectory() as root:
            with open(
                    os.path.join(root, ".mae-flow-defaults.json"),
                    "w", encoding="utf-8") as stream:
                stream.write("{broken")

            registry = load_capability_registry(root)

            self.assertEqual("build", match_capability({
                "tool_name": "Task",
                "tool_input": {"subagent_type": "compile-agent"},
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


class LeanCapabilityObservationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = self.temporary.name
        self.state_path = os.path.join(self.root, ".mae-flow.json")
        self.audit_path = os.path.join(
            self.root, ".mae-flow-work", "lean-hook-user-events.json")
        self.write_state()

    def write_state(self):
        state = FlowState.new(
            "REQ-OBSERVE", DeliveryPath.FULL, CommitPace.CONTINUOUS)
        with open(self.state_path, "w", encoding="utf-8") as stream:
            json.dump(state.to_dict(), stream)

    def read_state(self):
        with open(self.state_path, encoding="utf-8") as stream:
            return FlowState.from_dict(json.load(stream))

    def read_audit(self):
        with open(self.audit_path, encoding="utf-8") as stream:
            return json.load(stream)

    def test_matching_posttool_records_return_without_quality_parsing(self):
        raw = "PASS CLEAN warnings=41 disabled=7 count=900"
        response = LeanHookAdapter(
            self.root, marker_root=os.path.join(self.root, "markers"),
            clock_ns=lambda: 123,
        ).handle("PostToolUse", {
            "tool_name": "Skill",
            "tool_input": {"skill": "build-fix"},
            "tool_response": raw,
            "capability_context": {
                "source_revision": "src-1",
                "environment_revision": "env-1",
            },
        })

        self.assertEqual(0, response.exit_code)
        attempt = self.read_state().capabilities[-1]
        self.assertEqual(
            ("build", "src-1", "env-1", "returned", raw),
            (
                attempt.kind,
                attempt.source_revision,
                attempt.environment_revision,
                attempt.outcome,
                attempt.summary,
            ),
        )
        with open(self.state_path, encoding="utf-8") as stream:
            persisted = json.load(stream)
        self.assertEqual(3, persisted["schema_version"])
        self.assertEqual({
            "kind", "source_revision", "environment_revision", "outcome",
            "summary",
        }, set(persisted["capabilities"][-1]))
        self.assertEqual({
            "event": "CapabilityObservation",
            "captured_at_ns": 123,
            "payload": {
                "kind": "build",
                "tool_name": "Skill",
                "identity_field": "skill",
                "identity": "build-fix",
                "return_present": True,
                "summary": raw,
            },
        }, self.read_audit()[0])

    def test_missing_context_is_audited_without_fabricating_attempt(self):
        response = LeanHookAdapter(
            self.root, marker_root=os.path.join(self.root, "markers"),
            clock_ns=lambda: 456,
        ).handle("PostToolUse", {
            "tool_name": "Task",
            "tool_input": {"subagent_type": "ut-generator-agent"},
            "tool_response": {"opaque": ["shape"]},
        })

        self.assertEqual(0, response.exit_code)
        self.assertEqual((), self.read_state().capabilities)
        observation = self.read_audit()[0]["payload"]
        self.assertEqual("ut-generator-agent", observation["identity"])
        self.assertTrue(observation["return_present"])

    def test_explicit_record_fallback_accepts_only_opaque_outcomes(self):
        adapter = LeanHookAdapter(
            self.root, marker_root=os.path.join(self.root, "markers"),
            clock_ns=lambda: 789,
        )
        rejected = adapter.handle("PostToolUse", {
            "tool_name": "Bash",
            "capability_record": {
                "kind": "ut",
                "identity": "cpp-ut-host",
                "source_revision": "src-2",
                "environment_revision": "env-2",
                "outcome": "PASS",
                "summary": "manufactured conclusion",
            },
        })
        accepted = adapter.handle("PostToolUse", {
            "tool_name": "Bash",
            "capability_record": {
                "kind": "ut",
                "identity": "cpp-ut-host",
                "source_revision": "src-2",
                "environment_revision": "env-2",
                "outcome": "timed-out",
                "summary": "host stopped waiting",
            },
        })

        self.assertEqual(0, rejected.exit_code)
        self.assertEqual(0, accepted.exit_code)
        self.assertEqual(1, len(self.read_state().capabilities))
        attempt = self.read_state().capabilities[0]
        self.assertEqual(("ut", "timed-out", "host stopped waiting"), (
            attempt.kind, attempt.outcome, attempt.summary))
        audit = self.read_audit()
        self.assertEqual(1, len(audit))
        self.assertEqual("cpp-ut-host", audit[0]["payload"]["identity"])
        self.assertNotIn("PASS", json.dumps(audit))

    def test_explicit_record_fallback_preserves_all_opaque_outcomes(self):
        adapter = LeanHookAdapter(
            self.root, marker_root=os.path.join(self.root, "markers"))

        for index, outcome in enumerate((
                "returned", "failed-to-start", "timed-out", "not-observed")):
            response = adapter.handle("PostToolUse", {
                "tool_name": "Bash",
                "capability_record": {
                    "kind": "codecheck",
                    "identity": "host-codecheck",
                    "source_revision": "src-%s" % index,
                    "environment_revision": "env-1",
                    "outcome": outcome,
                    "summary": "opaque %s" % outcome,
                },
            })
            self.assertEqual(0, response.exit_code)

        attempts = self.read_state().capabilities
        self.assertEqual(
            ("returned", "failed-to-start", "timed-out", "not-observed"),
            tuple(attempt.outcome for attempt in attempts),
        )

    def test_observation_and_persistence_errors_fail_open(self):
        def unavailable(*unused):
            raise OSError("audit unavailable")

        audit_failure = LeanHookAdapter(
            self.root,
            marker_root=os.path.join(self.root, "markers"),
            event_sink=unavailable,
        ).handle("PostToolUse", {
            "tool_name": "Skill",
            "tool_input": {"skill": "build-fix"},
            "tool_response": "opaque",
        })
        adapter = LeanHookAdapter(
            self.root, marker_root=os.path.join(self.root, "markers"))
        adapter._update_state = unavailable
        persistence_failure = adapter.handle("PostToolUse", {
            "tool_name": "Task",
            "tool_input": {"subagent_type": "compile-agent"},
            "tool_response": "opaque",
            "capability_context": {
                "source_revision": "src-fail",
                "environment_revision": "env-fail",
            },
        })

        self.assertEqual(0, audit_failure.exit_code)
        self.assertEqual(0, persistence_failure.exit_code)


if __name__ == "__main__":
    unittest.main()
