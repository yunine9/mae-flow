#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Requirement-scoped workflow document paths and commit defaults."""

import hashlib
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
    conditional_document_kind,
)


class LeanDocumentPathTests(unittest.TestCase):
    def test_behavior_paths_are_portable_and_scoped_to_one_business_domain(self):
        paths = DocumentPaths.for_ticket(r"C:\Repo", "REQ-DOMAIN")

        self.assertEqual(
            r"C:\Repo\docs\specs\index.md",
            getattr(paths, "behavior_index", None),
        )
        behavior_document = getattr(paths, "behavior_document", None)
        self.assertIsNotNone(behavior_document)
        self.assertEqual(
            r"C:\Repo\docs\specs\order-query.md",
            behavior_document("order-query"),
        )
        for unsafe in ("../order", r"sales\order", "CON", "order/query"):
            with self.subTest(domain=unsafe):
                with self.assertRaises(ValueError):
                    behavior_document(unsafe)

    def test_requirement_paths_are_grouped_without_creating_them(self):
        with tempfile.TemporaryDirectory() as root:
            paths = DocumentPaths.for_ticket(root, "REQ-42")
            safe = (
                "REQ-42-"
                "4ffce8ccc00b8a32ab7d1d2b3610c96a90062aa0c40a286e21788c1840061d7a"
            )

            self.assertEqual("REQ-42", paths.ticket)
            self.assertEqual(safe, paths.safe_ticket)
            self.assertEqual(
                os.path.join(root, ".mae-flow-work", safe),
                paths.local_root,
            )
            self.assertEqual(
                os.path.join(root, ".mae-flow-work", safe, "spec.md"),
                paths.local_spec,
            )
            self.assertEqual(
                os.path.join(
                    root, "docs", "specs", "requirements", safe,
                    "spec.md",
                ),
                paths.spec,
            )
            self.assertEqual(
                os.path.join(root, "docs", "specs"),
                paths.behavior_root,
            )
            self.assertEqual(
                os.path.join(root, ".mae-flow-work", safe, "story.md"),
                paths.local_story,
            )
            self.assertEqual(
                os.path.join(
                    root, ".mae-flow-work", safe, "ut-handoff.md"),
                paths.ut_handoff,
            )
            self.assertEqual(
                os.path.join(
                    root, ".mae-flow-work", safe, "review-notes.md"),
                paths.local_review_notes,
            )
            self.assertEqual(
                os.path.join(
                    root, ".mae-flow-work", safe, "codecheck-ledger.md"),
                paths.local_codecheck_ledger,
            )
            self.assertEqual(
                os.path.join(
                    root, ".mae-flow-work", safe, "delivery-notes.md"),
                paths.local_delivery_notes,
            )
            self.assertEqual(
                os.path.join(
                    root, "docs", "specs", "requirements", safe,
                    "story.md",
                ),
                paths.story,
            )
            self.assertEqual(
                os.path.join(
                    root, "docs", "specs", "requirements", safe,
                    "decisions.md",
                ),
                paths.decisions,
            )
            self.assertEqual(
                os.path.join(
                    root, "docs", "specs", "requirements", safe,
                    "chain.md",
                ),
                paths.chain,
            )
            requirement_root = os.path.join(
                root, "docs", "specs", "requirements", safe)
            expected_mappings = {
                "story": (
                    paths.local_story, paths.story, "story.md", "story.md"),
                "decisions": (
                    paths.local_decisions,
                    paths.decisions,
                    "decisions.md",
                    "decisions.md",
                ),
                "chain": (
                    paths.local_chain, paths.chain, "chain.md", "chain.md"),
                "review-ledger": (
                    paths.local_review_notes,
                    paths.review_ledger,
                    "review-notes.md",
                    "review-ledger.md",
                ),
                "codecheck-ledger": (
                    paths.local_codecheck_ledger,
                    paths.codecheck_ledger,
                    "codecheck-ledger.md",
                    "codecheck-ledger.md",
                ),
                "delivery-notes": (
                    paths.local_delivery_notes,
                    paths.delivery_notes,
                    "delivery-notes.md",
                    "delivery-notes.md",
                ),
            }
            for kind, mapping in expected_mappings.items():
                with self.subTest(kind=kind):
                    local, durable, local_filename, durable_filename = mapping
                    self.assertEqual(
                        os.path.join(paths.local_root, local_filename), local)
                    self.assertEqual(
                        os.path.join(requirement_root, durable_filename), durable)
                    self.assertFalse(commit_policy(kind, False))
                    self.assertTrue(commit_policy(kind, True))
            self.assertEqual((), tuple(os.listdir(root)))
            self.assertFalse(hasattr(paths, "archive_root"))
            self.assertFalse(hasattr(paths, "openspec_root"))
            self.assertFalse(hasattr(paths, "engineering_notes"))
            self.assertFalse(hasattr(paths, "local_engineering_notes"))

    def test_windows_root_uses_windows_separators(self):
        paths = DocumentPaths.for_ticket(r"C:\repo", "REQ-42")
        safe = (
            "REQ-42-"
            "4ffce8ccc00b8a32ab7d1d2b3610c96a90062aa0c40a286e21788c1840061d7a"
        )

        self.assertEqual(
            "C:\\repo\\.mae-flow-work\\" + safe, paths.local_root)
        self.assertEqual(
            "C:\\repo\\docs\\specs\\requirements\\%s\\spec.md" % safe,
            paths.spec,
        )
        self.assertEqual(
            r"C:\repo\docs\specs", paths.behavior_root)

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
            "COM¹",
            "COM²",
            "COM³",
            "LPT1",
            "LPT2",
            "LPT3",
            "LPT4",
            "LPT5",
            "LPT6",
            "LPT7",
            "LPT8",
            "lpt9.log",
            "LPT¹",
            "LPT²",
            "LPT³",
            "req-42",
        )
        safe_segments = []
        for ticket in tickets:
            with self.subTest(ticket=ticket):
                first = DocumentPaths.for_ticket("root", ticket)
                second = DocumentPaths.for_ticket("root", ticket)
                self.assertEqual(ticket, first.ticket)
                self.assertEqual(first.safe_ticket, second.safe_ticket)
                self.assertEqual(64, len(first.safe_ticket.rsplit("-", 1)[1]))
                self.assertFalse(first.safe_ticket.endswith((" ", ".")))
                self.assertFalse(any(
                    character in first.safe_ticket
                    for character in '<>:"/\\|?*'
                ))
                safe_segments.append(first.safe_ticket.casefold())

        self.assertEqual(len(safe_segments), len(set(safe_segments)))

    def test_encoded_alias_cannot_claim_another_tickets_safe_segment(self):
        # The old conditional-digest scheme mapped these exact values to the
        # same Windows segment because the first digest happened to be digits.
        unsafe = DocumentPaths.for_ticket("root", "ALIAS:356")
        encoded_alias = DocumentPaths.for_ticket(
            "root", "ALIAS-356-513813835430")

        self.assertNotEqual(
            unsafe.safe_ticket.casefold(),
            encoded_alias.safe_ticket.casefold(),
        )
        self.assertTrue(unsafe.safe_ticket.endswith(
            "513813835430fa1547208d99f97267365c088838ee5b0fdb6e28989c762c7df6"
        ))
        self.assertTrue(encoded_alias.safe_ticket.endswith(
            "87cadcd7c72a6453e36350b8818d66aff2d0dcbdec372c0d6afa389f3eb4acdc"
        ))

    def test_unicode_normalization_aliases_keep_distinct_full_digests(self):
        composed = DocumentPaths.for_ticket("root", "É")
        decomposed = DocumentPaths.for_ticket("root", "E\u0301")

        self.assertNotEqual(
            composed.safe_ticket.casefold(), decomposed.safe_ticket.casefold())
        self.assertEqual(
            "É-a755f65d4e5201d92b6f264d1508ea0bec9913dd7b20a96ebde25de3cda84a84",
            composed.safe_ticket,
        )
        self.assertEqual(
            "É-ef0a931437dd85e4b2e95c16738b76b3175149e1d4b0281ec15e955fa7c41b37",
            decomposed.safe_ticket,
        )

    def test_superscript_device_aliases_are_never_windows_device_names(self):
        expected_prefixes = {
            "COM¹": "ticket-COM¹-",
            "COM²": "ticket-COM²-",
            "COM³": "ticket-COM³-",
            "LPT¹": "ticket-LPT¹-",
            "LPT²": "ticket-LPT²-",
            "LPT³": "ticket-LPT³-",
        }
        for ticket, prefix in expected_prefixes.items():
            with self.subTest(ticket=ticket):
                paths = DocumentPaths.for_ticket("root", ticket)
                self.assertTrue(paths.safe_ticket.startswith(prefix))

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
        self.assertTrue(paths.safe_ticket.endswith(
            hashlib.sha256(original.encode("utf-8")).hexdigest()))


class LeanDocumentCommitPolicyTests(unittest.TestCase):
    def test_conditional_durable_paths_reuse_document_kind_policy(self):
        expected = {
            "spec.md": "spec",
            "story.md": "story",
            "decisions.md": "decisions",
            "chain.md": "chain",
            "review-ledger.md": "review-ledger",
            "codecheck-ledger.md": "codecheck-ledger",
            "delivery-notes.md": "delivery-notes",
        }
        for filename, kind in expected.items():
            path = "docs/specs/requirements/REQ-42/%s" % filename
            with self.subTest(path=path):
                self.assertEqual(kind, conditional_document_kind(path))
                self.assertTrue(commit_policy(kind, True))
                self.assertFalse(commit_policy(kind, False))

        self.assertEqual(
            "story",
            conditional_document_kind(
                r"DOCS\SPECS\REQUIREMENTS\REQ-42\STORY.MD"),
        )
        self.assertEqual(
            "story",
            conditional_document_kind(
                "docs/mae-flow/requirements/REQ-42/story.md"),
        )

    def test_nonconditional_or_local_paths_have_no_conditional_kind(self):
        paths = (
            "docs/specs/query.md",
            ".mae-flow-work/REQ-42/spec.md",
            ".mae-flow-work/REQ-42/story.md",
            "docs/mae-flow/requirements/REQ-42/nested/story.md",
            "src/story.md",
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual("", conditional_document_kind(path))

    def test_only_behavior_baselines_are_durable_by_default(self):
        for kind in ("behavior", "behavior-baseline"):
            with self.subTest(kind=kind):
                self.assertTrue(commit_policy(kind, False))
                self.assertTrue(commit_policy(kind, True))
        self.assertFalse(commit_policy("spec", False))
        self.assertTrue(commit_policy("spec", True))

    def test_conditional_documents_require_explicit_commit_request(self):
        conditional = (
            "spec", "story",
            "decisions",
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
