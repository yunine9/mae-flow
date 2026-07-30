#!/usr/bin/env python3
"""Tests for pure compile-side-effect attribution."""

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.quality.compile_side_effects import (  # noqa: E402
    compile_side_effect_paths,
    successful_direct_write_paths,
)
from mae_flow_core.quality.tool_transcript import ToolCall  # noqa: E402


class CompileSideEffectTests(unittest.TestCase):
    def test_normal_named_compile_outputs_are_attributed_by_delta(self):
        self.assertEqual(
            ("config/generated.properties", "tracked/settings.json"),
            compile_side_effect_paths(
                {"tracked/settings.json": "before", "notes.txt": "same"},
                {
                    "config/generated.properties": "new",
                    "tracked/settings.json": "after",
                    "notes.txt": "same",
                },
                (),
            ),
        )

    def test_successful_direct_agent_edits_are_not_compile_side_effects(self):
        calls = (
            ToolCall("1", "Edit", {"file_path": "/repo/tracked/settings.json"},
                     result_seen=True, result="ok"),
            ToolCall("2", "Write", {"file_path": "/repo/failed.json"},
                     result_seen=True, is_error=True, result="failed"),
        )
        direct = successful_direct_write_paths(calls, "/repo")
        self.assertEqual(("tracked/settings.json",), direct)
        self.assertEqual(
            ("config/generated.properties",),
            compile_side_effect_paths(
                {},
                {
                    "config/generated.properties": "new",
                    "tracked/settings.json": "after",
                },
                direct,
            ),
        )

    def test_direct_writes_normalize_paths_and_reject_paths_outside_repository(self):
        calls = (
            ToolCall("1", "MultiEdit", {"file_path": "/repo/nested\\settings.json"},
                     result_seen=True, result="ok"),
            ToolCall("2", "Write", {"file_path": "config/generated.properties"},
                     result_seen=True, result="ok"),
            ToolCall("3", "Edit", {"file_path": "../outside.json"},
                     result_seen=True, result="ok"),
            ToolCall("4", "Bash", {"file_path": "/repo/ignored.json"},
                     result_seen=True, result="ok"),
        )

        self.assertEqual(
            ("config/generated.properties", "nested/settings.json"),
            successful_direct_write_paths(calls, "/repo"),
        )


if __name__ == "__main__":
    unittest.main()
