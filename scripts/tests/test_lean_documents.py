#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Requirement-scoped workflow document paths and commit defaults."""

import os
import sys
import tempfile
import unittest


SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.orchestration.documents import (  # noqa: E402
    DocumentPaths,
    commit_policy,
)


class LeanDocumentPathTests(unittest.TestCase):
    def test_requirement_paths_are_grouped_without_creating_them(self):
        with tempfile.TemporaryDirectory() as root:
            paths = DocumentPaths.for_ticket(root, "REQ-42")

            self.assertEqual("REQ-42", paths.ticket)
            self.assertEqual("REQ-42", paths.safe_ticket)
            self.assertEqual(
                os.path.join(root, ".mae-flow-work", "REQ-42"),
                paths.local_root,
            )
            self.assertEqual(
                os.path.join(
                    root, "docs", "mae-flow", "requirements", "REQ-42",
                    "spec.md",
                ),
                paths.spec,
            )
            self.assertEqual(
                os.path.join(root, "docs", "mae-flow", "behavior"),
                paths.behavior_root,
            )
            self.assertEqual(
                os.path.join(root, ".mae-flow-work", "REQ-42", "story.md"),
                paths.local_story,
            )
            self.assertEqual(
                os.path.join(
                    root, ".mae-flow-work", "REQ-42", "ut-handoff.md"),
                paths.ut_handoff,
            )
            self.assertEqual(
                os.path.join(
                    root, ".mae-flow-work", "REQ-42", "review-notes.md"),
                paths.review_notes,
            )
            self.assertEqual(
                os.path.join(
                    root, ".mae-flow-work", "REQ-42", "codecheck-ledger.md"),
                paths.codecheck_ledger,
            )
            self.assertEqual(
                os.path.join(
                    root, ".mae-flow-work", "REQ-42", "delivery-notes.md"),
                paths.delivery_notes,
            )
            self.assertEqual(
                os.path.join(
                    root, "docs", "mae-flow", "requirements", "REQ-42",
                    "story.md",
                ),
                paths.story,
            )
            self.assertEqual(
                os.path.join(
                    root, "docs", "mae-flow", "requirements", "REQ-42",
                    "decisions.md",
                ),
                paths.decisions,
            )
            self.assertEqual(
                os.path.join(
                    root, "docs", "mae-flow", "requirements", "REQ-42",
                    "engineering.md",
                ),
                paths.engineering_notes,
            )
            self.assertEqual(
                os.path.join(
                    root, "docs", "mae-flow", "requirements", "REQ-42",
                    "chain.md",
                ),
                paths.chain,
            )
            self.assertEqual((), tuple(os.listdir(root)))
            self.assertFalse(hasattr(paths, "archive_root"))
            self.assertFalse(hasattr(paths, "openspec_root"))

    def test_windows_root_uses_windows_separators(self):
        paths = DocumentPaths.for_ticket(r"C:\repo", "REQ-42")

        self.assertEqual(
            r"C:\repo\.mae-flow-work\REQ-42", paths.local_root)
        self.assertEqual(
            r"C:\repo\docs\mae-flow\requirements\REQ-42\spec.md",
            paths.spec,
        )
        self.assertEqual(
            r"C:\repo\docs\mae-flow\behavior", paths.behavior_root)

    def test_empty_traversal_and_drive_tickets_are_rejected(self):
        rejected = (
            "",
            "   ",
            ".",
            "..",
            "REQ..42",
            "REQ/42",
            r"REQ\42",
            "C:REQ-42",
            "C:\\REQ-42",
        )
        for ticket in rejected:
            with self.subTest(ticket=ticket):
                with self.assertRaises((TypeError, ValueError)):
                    DocumentPaths.for_ticket("root", ticket)

    def test_unsafe_windows_tickets_get_distinct_deterministic_segments(self):
        tickets = (
            "REQ:42",
            "REQ?42",
            "REQ\x01-42",
            "REQ-42.",
            "REQ-42 ",
            "CON",
            "PRN",
            "AUX",
            "NUL",
            "prn.txt",
            "COM1",
            "COM2",
            "COM3",
            "COM4",
            "COM5",
            "COM6",
            "COM7",
            "COM8",
            "COM9",
            "LPT1",
            "LPT2",
            "LPT3",
            "LPT4",
            "LPT5",
            "LPT6",
            "LPT7",
            "LPT8",
            "lpt9.log",
            "req-42",
        )
        safe_segments = []
        for ticket in tickets:
            with self.subTest(ticket=ticket):
                first = DocumentPaths.for_ticket("root", ticket)
                second = DocumentPaths.for_ticket("root", ticket)
                self.assertEqual(ticket, first.ticket)
                self.assertEqual(first.safe_ticket, second.safe_ticket)
                self.assertNotIn(first.safe_ticket.upper().split(".", 1)[0], {
                    "CON", "PRN", "AUX", "NUL",
                    *("COM%d" % number for number in range(1, 10)),
                    *("LPT%d" % number for number in range(1, 10)),
                })
                self.assertFalse(first.safe_ticket.endswith((" ", ".")))
                self.assertFalse(any(
                    character in first.safe_ticket
                    for character in '<>:"/\\|?*'
                ))
                safe_segments.append(first.safe_ticket.casefold())

        self.assertEqual(len(safe_segments), len(set(safe_segments)))

    def test_case_aliases_have_distinct_windows_identities(self):
        upper = DocumentPaths.for_ticket("root", "REQ-42")
        lower = DocumentPaths.for_ticket("root", "req-42")
        mixed = DocumentPaths.for_ticket("root", "Req-42")

        identities = {
            upper.safe_ticket.casefold(),
            lower.safe_ticket.casefold(),
            mixed.safe_ticket.casefold(),
        }
        self.assertEqual(3, len(identities))

    def test_long_ticket_stays_within_windows_component_limit(self):
        original = "REQ-" + ("LONG-" * 80)
        paths = DocumentPaths.for_ticket("root", original)

        self.assertEqual(original, paths.ticket)
        self.assertLessEqual(
            len(paths.safe_ticket.encode("utf-16-le")) // 2,
            255,
        )
        self.assertEqual(
            paths.safe_ticket,
            DocumentPaths.for_ticket("root", original).safe_ticket,
        )


class LeanDocumentCommitPolicyTests(unittest.TestCase):
    def test_spec_and_behavior_baseline_are_durable_by_default(self):
        for kind in ("spec", "behavior", "behavior-baseline"):
            with self.subTest(kind=kind):
                self.assertTrue(commit_policy(kind, False))
                self.assertTrue(commit_policy(kind, True))

    def test_conditional_documents_require_explicit_commit_request(self):
        conditional = (
            "story",
            "decisions",
            "engineering-notes",
            "chain",
            "review-ledger",
            "codecheck-ledger",
            "delivery-notes",
        )
        for kind in conditional:
            with self.subTest(kind=kind):
                self.assertFalse(commit_policy(kind, False))
                self.assertTrue(commit_policy(kind, True))

    def test_story_and_unknown_documents_remain_local_without_explicit_request(self):
        self.assertFalse(commit_policy("story", False))
        self.assertFalse(commit_policy("unexpected-new-document", False))
        self.assertFalse(commit_policy("unexpected-new-document", True))

    def test_policy_rejects_invalid_arguments_instead_of_guessing(self):
        for kind in (None, "", "   ", b"story"):
            with self.subTest(kind=kind):
                with self.assertRaises((TypeError, ValueError)):
                    commit_policy(kind, False)
        for requested in (None, 0, 1, "yes"):
            with self.subTest(requested=requested):
                with self.assertRaises((TypeError, ValueError)):
                    commit_policy("story", requested)


if __name__ == "__main__":
    unittest.main()
