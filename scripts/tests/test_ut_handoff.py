#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Append-only construction handoff and final UT context contracts."""

import os
import sys
import tempfile
import unittest


SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.quality import (  # noqa: E402
    append_ut_handoff,
    render_ut_context,
)


class AppendUtHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = os.path.join(
            self.temporary.name,
            ".mae-flow-work",
            "REQ-42",
            "ut-handoff.md",
        )

    def test_each_cp_appends_natural_language_without_a_schema(self):
        first = (
            "CP1 changed the visible retry behavior. It extracted the "
            "deterministic delay calculation into retry_delay()."
        )
        second = (
            "CP2 kept the stable execution framework real instead of mocking "
            "it. No Story deviation was needed."
        )

        append_ut_handoff(self.path, first)
        append_ut_handoff(self.path, second)

        with open(self.path, encoding="utf-8", newline="") as stream:
            self.assertEqual(first + "\n" + second + "\n", stream.read())

    def test_append_preserves_existing_text_and_adds_a_missing_separator(self):
        os.makedirs(os.path.dirname(self.path))
        original = "earlier free-form note"
        with open(self.path, "wb") as stream:
            stream.write(original.encode("utf-8"))

        append_ut_handoff(self.path, "later CP note")

        with open(self.path, "rb") as stream:
            content = stream.read()
        self.assertTrue(content.startswith(original.encode("utf-8")))
        self.assertEqual(
            "earlier free-form note\nlater CP note\n",
            content.decode("utf-8"),
        )

    def test_utf8_content_and_mixed_newlines_are_windows_safe(self):
        append_ut_handoff(
            self.path,
            "行为：查询条件已抽取。\r\n映射逻辑可直接测试。\r无实现偏差。",
        )

        with open(self.path, "rb") as stream:
            content = stream.read()
        self.assertEqual(
            "行为：查询条件已抽取。\n映射逻辑可直接测试。\n无实现偏差。\n",
            content.decode("utf-8"),
        )
        self.assertNotIn(b"\r", content)

    def test_arbitrary_local_path_does_not_need_a_git_repository(self):
        plain_path = os.path.join(self.temporary.name, "notes", "handoff.txt")

        append_ut_handoff(plain_path, "ordinary prose; no heading or hash")

        with open(plain_path, encoding="utf-8") as stream:
            self.assertEqual(
                "ordinary prose; no heading or hash\n",
                stream.read(),
            )


class RenderUtContextTests(unittest.TestCase):
    def test_missing_spec_or_story_paths_are_context_not_a_gate(self):
        cases = (
            ("", "story.md", "Story path (exact): story.md"),
            ("spec.md", "", "Spec path (exact): spec.md"),
            ("", "", "Final diff paths:"),
        )
        for spec, story, remaining_path in cases:
            with self.subTest(spec=spec, story=story):
                context = render_ut_context(
                    spec,
                    story,
                    "CP history remains available.",
                    ("src/final.cpp",),
                )

                self.assertIn("not provided", context.lower())
                self.assertIn("continue", context.lower())
                self.assertIn(remaining_path, context)
                self.assertIn("CP history remains available.", context)
                self.assertIn("src/final.cpp", context)

    def test_context_combines_exact_paths_handoff_and_final_diff_paths(self):
        spec = r"C:\repo\docs\REQ-42\spec.md"
        story = r"C:\repo\.mae-flow-work\REQ-42\story.md"
        handoff = "CP1 covered query filters.\nCP2 extracted result mapping."
        diff_paths = (
            r"src\query_builder.cpp",
            "src/result_mapper.cpp",
        )

        context = render_ut_context(spec, story, handoff, diff_paths)

        self.assertIn(spec, context)
        self.assertIn(story, context)
        self.assertIn(handoff, context)
        for path in diff_paths:
            self.assertIn(path, context)

    def test_context_assigns_complete_ut_work_to_the_ut_skill(self):
        context = render_ut_context(
            "docs/REQ-42/spec.md",
            ".mae-flow-work/REQ-42/story.md",
            "The business query predicate now has a deterministic seam.",
            ("src/query.py",),
        ).lower()

        self.assertIn("final implementation", context)
        self.assertIn("review coverage", context)
        self.assertIn("write", context)
        self.assertIn("compile", context)
        self.assertIn("run", context)
        self.assertIn("ut skill", context)

    def test_final_implementation_outranks_historical_handoff(self):
        context = render_ut_context(
            "confirmed-spec.md",
            "confirmed-story.md",
            "An early CP expected the old result mapping.",
            ("src/final-result-mapper.cpp",),
        ).lower()

        self.assertIn("historical coverage", context)
        self.assertIn("may be outdated", context)
        self.assertIn("not an authority or deviation baseline", context)
        self.assertIn("final implementation", context)
        self.assertIn("final diff", context)
        self.assertIn("authoritative", context)
        self.assertIn("confirmed spec and story when provided", context)
        self.assertNotIn(
            "deviation from spec, story, or the cumulative handoff",
            context,
        )

    def test_context_avoids_framework_output_and_mock_contracts(self):
        context = render_ut_context(
            "spec.md",
            "story.md",
            "Query conditions and row mapping are directly testable.",
            ("query.cpp",),
        ).lower()

        self.assertIn("query conditions", context)
        self.assertIn("mapping", context)
        self.assertIn("do not require mocks", context)
        self.assertIn("database connection", context)
        self.assertIn("execution framework", context)
        self.assertIn("do not prescribe", context)
        self.assertIn("output format", context)

    def test_missing_handoff_or_empty_diff_is_context_not_a_gate(self):
        context = render_ut_context("spec.md", "story.md", "", ())

        self.assertIn("No construction handoff text was recorded", context)
        self.assertIn("No paths are present in the final diff", context)
        self.assertIn("continue", context.lower())


if __name__ == "__main__":
    unittest.main()
