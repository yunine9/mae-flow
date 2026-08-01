#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pure exact-file delivery planning for Continuous and Staged work."""

import os
import sys
import unittest
from dataclasses import FrozenInstanceError


SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.guard import DeliveryManifest  # noqa: E402
from mae_flow_core.orchestration import (  # noqa: E402
    CheckpointManifest,
    CommitPace,
    DeliveryPath,
    FlowState,
    Phase,
    plan_delivery,
)


MESSAGE_KEY = "delivery.commit_message"
CONDITIONAL_DOCUMENT_KEY = "delivery.conditional_document"


def flow(pace=CommitPace.CONTINUOUS, files=(), decisions=(), ticket="REQ-42"):
    return FlowState(
        ticket=ticket,
        path=DeliveryPath.FULL,
        phase=Phase.DELIVERY,
        commit_pace=pace,
        delivery_files=files,
        decisions=decisions,
    )


def checkpoint(name, message, files, approved=True):
    return CheckpointManifest(
        checkpoint=name,
        message=message,
        manifest=DeliveryManifest.from_paths(files),
        user_approved=approved,
    )


class ContinuousDeliveryPlanningTests(unittest.TestCase):
    def test_continuous_plans_one_exact_commit_and_one_final_push(self):
        state = flow(
            files=("src/feature.cpp", "tests/feature_test.cpp"),
            decisions=((MESSAGE_KEY, "[REQ-42][feat]add feature"),),
        )

        plan = plan_delivery(state)

        self.assertEqual(1, len(plan.commits))
        self.assertTrue(plan.push_once)
        self.assertEqual(
            ("src/feature.cpp", "tests/feature_test.cpp"),
            plan.commits[0].manifest.files,
        )
        self.assertEqual(
            "[REQ-42][feat]add feature", plan.commits[0].message)
        self.assertTrue(plan.commits[0].requires_user)

    def test_continuous_requires_one_unambiguous_commit_message(self):
        cases = (
            (),
            ((MESSAGE_KEY, "[REQ-42][feat]first"),
             (MESSAGE_KEY, "[REQ-42][fix]second")),
        )
        for decisions in cases:
            with self.subTest(decisions=decisions):
                with self.assertRaisesRegex(ValueError, "commit message"):
                    plan_delivery(flow(files=("src/a.cpp",), decisions=decisions))

    def test_business_message_uses_existing_exact_prefix_semantics(self):
        literal_ticket = "REQ.42+$"
        accepted = (
            "[REQ.42+$][feat]add query planning",
            "[REQ.42+$][fix]修复查询条件",
            "[REQ.42+$][feat]document [scope] in description",
            "[REQ.42+$][feat]trailing space is preserved ",
            "[REQ.42+$][fix]summary\nmultiline body",
        )
        for message in accepted:
            with self.subTest(message=message):
                plan = plan_delivery(flow(
                    ticket=literal_ticket,
                    files=("src/a.cpp",),
                    decisions=((MESSAGE_KEY, message),),
                ))
                self.assertEqual(message, plan.commits[0].message)

        rejected = (
            "[REQX42+$][feat]wrong ticket",
            "[REQ.42+$][docs]wrong kind",
            "[REQ.42+$][feat]",
            "[REQ.42+$][feat] leading",
        )
        for message in rejected:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, "commit message"):
                    plan_delivery(flow(
                        ticket=literal_ticket,
                        files=("src/a.cpp",),
                        decisions=((MESSAGE_KEY, message),),
                    ))

    def test_ticket_is_matched_literally_even_when_it_contains_brackets(self):
        plan = plan_delivery(flow(
            ticket="REQ[42]",
            files=("src/a.cpp",),
            decisions=((MESSAGE_KEY, "[REQ[42]][feat]change"),),
        ))

        self.assertEqual("[REQ[42]][feat]change", plan.commits[0].message)

    def test_continuous_rejects_cp_manifests_instead_of_guessing(self):
        state = flow(
            files=("src/a.cpp",),
            decisions=((MESSAGE_KEY, "[REQ-42][feat]change"),),
        )
        item = checkpoint(
            "CP1", "[REQ-42][feat]change", ("src/a.cpp",))

        with self.assertRaisesRegex(ValueError, "Continuous"):
            plan_delivery(state, (item,))


class StagedDeliveryPlanningTests(unittest.TestCase):
    def test_staged_plans_each_approved_cp_locally_and_pushes_only_once(self):
        state = flow(
            pace=CommitPace.STAGED,
            files=("src/a.cpp", "tests/a_test.cpp", "src/b.cpp"),
        )
        manifests = (
            checkpoint(
                "CP1",
                "[REQ-42][feat]add query builder",
                ("src/a.cpp", "tests/a_test.cpp"),
            ),
            checkpoint(
                "CP2", "[REQ-42][fix]wire result mapping", ("src/b.cpp",)),
        )

        plan = plan_delivery(state, manifests)

        self.assertEqual(2, len(plan.commits))
        self.assertEqual(
            tuple(item.message for item in manifests),
            tuple(commit.message for commit in plan.commits),
        )
        self.assertEqual(
            tuple(item.manifest.files for item in manifests),
            tuple(commit.manifest.files for commit in plan.commits),
        )
        self.assertTrue(all(commit.requires_user for commit in plan.commits))
        self.assertTrue(plan.push_once)

    def test_staged_requires_an_ordered_nonempty_cp_collection(self):
        state = flow(pace=CommitPace.STAGED, files=("src/a.cpp",))
        item = checkpoint(
            "CP1", "[REQ-42][feat]change", ("src/a.cpp",))
        invalid = (None, (), item, {item}, frozenset((item,)))

        for manifests in invalid:
            with self.subTest(kind=type(manifests).__name__):
                with self.assertRaisesRegex(ValueError, "ordered|non-empty"):
                    plan_delivery(state, manifests)

    def test_staged_requires_explicit_cp_manifest_approval(self):
        state = flow(pace=CommitPace.STAGED, files=("src/a.cpp",))
        unapproved = checkpoint(
            "CP1", "[REQ-42][feat]change", ("src/a.cpp",), approved=False)

        with self.assertRaisesRegex(ValueError, "approved"):
            plan_delivery(state, (unapproved,))
        with self.assertRaisesRegex(ValueError, "bool"):
            CheckpointManifest(
                "CP1",
                "[REQ-42][feat]change",
                DeliveryManifest.from_paths(("src/a.cpp",)),
                1,
            )

    def test_staged_rejects_empty_or_duplicate_checkpoint_identity(self):
        state = flow(
            pace=CommitPace.STAGED,
            files=("src/a.cpp", "src/b.cpp"),
        )
        invalid_names = (
            ("", "CP2"),
            ("   ", "CP2"),
            ("CP1", "CP1"),
        )
        for first_name, second_name in invalid_names:
            with self.subTest(names=(first_name, second_name)):
                manifests = (
                    checkpoint(
                        first_name,
                        "[REQ-42][feat]first",
                        ("src/a.cpp",),
                    ),
                    checkpoint(
                        second_name,
                        "[REQ-42][feat]second",
                        ("src/b.cpp",),
                    ),
                )
                with self.assertRaisesRegex(ValueError, "checkpoint"):
                    plan_delivery(state, manifests)

    def test_staged_rejects_empty_manifest_and_missing_message(self):
        state = flow(pace=CommitPace.STAGED, files=("src/a.cpp",))
        cases = (
            checkpoint("CP1", "[REQ-42][feat]change", ()),
            checkpoint("CP1", "", ("src/a.cpp",)),
        )
        for item in cases:
            with self.subTest(item=item):
                with self.assertRaisesRegex(ValueError, "manifest|commit message"):
                    plan_delivery(state, (item,))

    def test_staged_allows_a_file_to_evolve_across_ordered_checkpoints(self):
        state = flow(pace=CommitPace.STAGED, files=("Src/A.cpp",))
        manifests = (
            CheckpointManifest(
                "CP1",
                "[REQ-42][feat]first",
                DeliveryManifest.from_paths(
                    ("Src/A.cpp",), adopted_dirty=("Src/A.cpp",)),
                True,
            ),
            checkpoint("CP2", "[REQ-42][fix]second", (r"src\a.cpp",)),
        )

        plan = plan_delivery(state, manifests)

        self.assertEqual(2, len(plan.commits))
        self.assertEqual(("Src/A.cpp",), plan.commits[0].manifest.files)
        self.assertEqual(
            ("Src/A.cpp",), plan.commits[0].manifest.adopted_dirty)
        self.assertEqual(("src/a.cpp",), plan.commits[1].manifest.files)

    def test_staged_union_must_equal_final_delivery_manifest(self):
        cases = (
            (
                ("src/a.cpp", "src/b.cpp"),
                (checkpoint(
                    "CP1", "[REQ-42][feat]change", ("src/a.cpp",)),),
            ),
            (
                ("src/a.cpp",),
                (checkpoint(
                    "CP1",
                    "[REQ-42][feat]change",
                    ("src/a.cpp", "src/extra.cpp"),
                ),),
            ),
        )
        for final_files, manifests in cases:
            with self.subTest(final_files=final_files):
                with self.assertRaisesRegex(ValueError, "final delivery manifest"):
                    plan_delivery(
                        flow(pace=CommitPace.STAGED, files=final_files),
                        manifests,
                    )


class DeliveryManifestBoundaryTests(unittest.TestCase):
    def continuous(self, files):
        return flow(
            files=files,
            decisions=((MESSAGE_KEY, "[REQ-42][feat]change"),),
        )

    def test_rejects_broad_or_control_file_staging_inputs(self):
        invalid = (
            ".",
            "src/",
            "src/*.cpp",
            "-A",
            "--all",
            ":(exclude)README.md",
            ":/src/a.cpp",
            ".mae-flow.json",
            ".mae-flow.json.failures",
            "state/.MAE-FLOW.JSON.backup",
            ".mae-flow-work/REQ-42/story.md",
            r".MAE-FLOW-WORK\REQ-42\story.md",
        )
        for path in invalid:
            with self.subTest(path=path):
                with self.assertRaisesRegex(ValueError, "delivery|stage|path"):
                    plan_delivery(self.continuous((path,)))

    def test_exact_special_looking_files_are_not_broad_staging_expressions(self):
        plan = plan_delivery(self.continuous(("all", "-notes.txt")))

        self.assertEqual(
            ("all", "-notes.txt"), plan.commits[0].manifest.files)

    def test_empty_final_manifest_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "manifest"):
            plan_delivery(self.continuous(()))

    def test_conditional_documents_require_an_exact_independent_selection(self):
        documents = (
            "story.md",
            "decisions.md",
            "engineering.md",
            "chain.md",
            "review-ledger.md",
            "codecheck-ledger.md",
            "delivery-notes.md",
        )
        for filename in documents:
            path = "docs/mae-flow/requirements/REQ-42/%s" % filename
            state = self.continuous(("src/a.cpp", path))
            with self.subTest(filename=filename, selection="missing"):
                with self.assertRaisesRegex(ValueError, "conditional document"):
                    plan_delivery(state)

            selected = flow(
                files=("src/a.cpp", path),
                decisions=(
                    (MESSAGE_KEY, "[REQ-42][feat]change"),
                    (CONDITIONAL_DOCUMENT_KEY, path),
                ),
            )
            with self.subTest(filename=filename, selection="exact"):
                plan = plan_delivery(selected)
                self.assertEqual(
                    ("src/a.cpp", path), plan.commits[0].manifest.files)

    def test_conditional_selection_is_not_satisfied_by_a_different_path(self):
        story = "docs/mae-flow/requirements/REQ-42/story.md"
        state = flow(
            files=("src/a.cpp", story),
            decisions=(
                (MESSAGE_KEY, "[REQ-42][feat]change"),
                (
                    CONDITIONAL_DOCUMENT_KEY,
                    "docs/mae-flow/requirements/REQ-42/decisions.md",
                ),
            ),
        )

        with self.assertRaisesRegex(ValueError, "conditional document"):
            plan_delivery(state)

    def test_staged_conditional_document_uses_the_same_selection_fact(self):
        story = "docs/mae-flow/requirements/REQ-42/story.md"
        item = checkpoint(
            "CP1", "[REQ-42][feat]ship story", ("src/a.cpp", story))
        state = flow(
            pace=CommitPace.STAGED,
            files=("src/a.cpp", story),
        )

        with self.assertRaisesRegex(ValueError, "conditional document"):
            plan_delivery(state, (item,))

        selected = flow(
            pace=CommitPace.STAGED,
            files=("src/a.cpp", story),
            decisions=((CONDITIONAL_DOCUMENT_KEY, story),),
        )
        self.assertEqual(1, len(plan_delivery(selected, (item,)).commits))

    def test_result_and_cp_inputs_are_immutable_values(self):
        item = checkpoint(
            "CP1", "[REQ-42][feat]change", ("src/a.cpp",))
        plan = plan_delivery(
            flow(pace=CommitPace.STAGED, files=("src/a.cpp",)), (item,))

        with self.assertRaises(FrozenInstanceError):
            item.user_approved = False
        with self.assertRaises(FrozenInstanceError):
            plan.push_once = False
        with self.assertRaises(FrozenInstanceError):
            plan.commits[0].message = "changed"


if __name__ == "__main__":
    unittest.main()
