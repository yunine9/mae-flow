#!/usr/bin/env python3
"""Tests for immutable Hook tool transcript interpretation."""

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.quality.tool_transcript import (  # noqa: E402
    bash_call,
    bash_calls,
    call_failed,
    parse_transcript,
    reported_bash_call,
    skill_call,
)


class ToolTranscriptTests(unittest.TestCase):
    def test_parse_transcript_links_both_host_tool_protocols(self):
        lines = [
            {
                "type": "user",
                "message": {"role": "user", "content": "run fixture"},
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "one",
                            "name": "Bash",
                            "input": {"command": "python -m unittest"},
                        },
                        {
                            "type": "tool_call",
                            "id": "two",
                            "name": "Read",
                            "input": {"file_path": "README.md"},
                        },
                    ],
                },
            },
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "one",
                            "content": [{"text": "1 passed"}],
                        },
                        {
                            "type": "tool_response",
                            "tool_call_id": "two",
                            "isError": True,
                            "content": "denied",
                        },
                    ],
                },
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": "UT_RESULT: PASS",
                },
            },
        ]

        transcript = parse_transcript(lines)

        self.assertEqual(("run fixture", ""), transcript.user_texts)
        self.assertEqual(("", "UT_RESULT: PASS"), transcript.assistant_texts)
        self.assertEqual(2, len(transcript.tool_calls))
        self.assertEqual("1 passed", transcript.tool_calls[0].result)
        self.assertTrue(transcript.tool_calls[0].result_seen)
        self.assertFalse(transcript.tool_calls[0].is_error)
        self.assertEqual("denied", transcript.tool_calls[1].result)
        self.assertTrue(transcript.tool_calls[1].is_error)

    def test_missing_result_and_nonzero_bash_are_failures(self):
        transcript = parse_transcript([{
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{
                    "type": "tool_use",
                    "id": "missing",
                    "name": "Bash",
                    "input": {"command": "make"},
                }],
            },
        }])
        self.assertTrue(call_failed(transcript.tool_calls[0]))

        failed = parse_transcript([
            {
                "message": {
                    "role": "assistant",
                    "content": [{
                        "type": "tool_use",
                        "id": "failed",
                        "name": "Bash",
                        "input": {"command": "make"},
                    }],
                },
            },
            {
                "message": {
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": "failed",
                        "content": "process exited with code 7",
                    }],
                },
            },
        ])
        self.assertTrue(call_failed(failed.tool_calls[0]))

    def test_skill_and_bash_lookup_use_the_last_real_matching_call(self):
        transcript = parse_transcript([
            {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "s1",
                            "name": "Skill",
                            "input": {"skill": "build-fix"},
                        },
                        {
                            "type": "tool_use",
                            "id": "b1",
                            "name": "Bash",
                            "input": {
                                "command": (
                                    "echo 'python -m unittest'; "
                                    "python -m unittest -v"
                                ),
                            },
                        },
                        {
                            "type": "tool_use",
                            "id": "s2",
                            "name": "Skill",
                            "input": {"name": "build-fix"},
                        },
                    ],
                },
            },
        ])

        self.assertEqual("s2", skill_call(
            transcript.tool_calls, "build-fix").call_id)
        self.assertEqual("b1", bash_call(
            transcript.tool_calls, "python -m unittest").call_id)
        self.assertEqual(
            [(transcript.tool_calls[1], 1)],
            bash_calls(transcript.tool_calls, "python -m unittest"),
        )
        self.assertEqual("b1", reported_bash_call(
            transcript.tool_calls,
            "python -m unittest -v（全量）",
        ).call_id)

if __name__ == "__main__":
    unittest.main()
