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

    def test_business_message_uses_exact_literal_ticket_and_trimmed_description(self):
        literal_ticket = "REQ.42+$"
        accepted = (
            "[REQ.42+$][feat]add query planning",
            "[REQ.42+$][fix]修复查询条件",
            "[REQ.42+$][feat]document [scope] in description",
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
            "[REQ.42+$][feat]trailing ",
            "[REQ.42+$][feat]line\nbreak",
        )
        for message in rejected:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, "commit message"):
                    plan_delivery(flow(
                        ticket=literal_ticket,
                        files=("src/a.cpp",),
                        decisions=((MESSAGE_KEY, message),),
                    ))

    def test_ticket_brackets_are_rejected_as_message_ambiguity(self):
        with self.assertRaisesRegex(ValueError, "bracket"):
            plan_delivery(flow(
                ticket="REQ[42]",
                files=("src/a.cpp",),
                decisions=((MESSAGE_KEY, "[REQ[42]][feat]change"),),
            ))

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

    def test_staged_rejects_overlapping_windows_file_ownership(self):
        state = flow(pace=CommitPace.STAGED, files=("Src/A.cpp",))
        manifests = (
            checkpoint("CP1", "[REQ-42][feat]first", ("Src/A.cpp",)),
            checkpoint("CP2", "[REQ-42][fix]second", (r"src\a.cpp",)),
        )

        with self.assertRaisesRegex(ValueError, "owned by more than one"):
            plan_delivery(state, manifests)

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

    def test_explicit_durable_conditional_document_is_allowed(self):
        story = "docs/mae-flow/requirements/REQ-42/story.md"
        plan = plan_delivery(self.continuous(("src/a.cpp", story)))

        self.assertEqual(("src/a.cpp", story), plan.commits[0].manifest.files)

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
