#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Strict delivery-receipt contracts for irreversible Git effects."""

import json
import os
import sys
import unittest
from dataclasses import replace


SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.orchestration import (  # noqa: E402
    CommitPace,
    DeliveryPath,
    FlowState,
    Phase,
)
from mae_flow_core.orchestration.delivery import (  # noqa: E402
    issue_delivery_receipt,
    load_delivery_receipt,
    valid_delivery_receipt,
)
from mae_flow_core.guard.manifest import (  # noqa: E402
    git_receipt_error,
    git_receipt_reservation,
)


def continuous_state():
    return FlowState(
        ticket="REQ-42",
        path=DeliveryPath.FULL,
        phase=Phase.DELIVERY,
        commit_pace=CommitPace.CONTINUOUS,
        delivery_files=("src/a.cpp", "tests/a_test.cpp"),
        decisions=(
            ("delivery.commit_message", "[REQ-42][fix]bind delivery"),
            ("delivery.plan.remote", "origin"),
            ("delivery.plan.destination_ref", "refs/heads/fix/receipt"),
            ("delivery.plan.expected_destination_sha", "b" * 40),
            ("delivery.plan.new_branch", "false"),
            ("delivery.plan.source_sha", "b" * 40),
        ),
    )


class DeliveryReceiptTests(unittest.TestCase):
    def test_final_receipt_is_strict_canonical_json_with_recomputed_digest(self):
        state = continuous_state()

        receipt = issue_delivery_receipt(
            state, "Ship this exact plan after review.")
        decoded = json.loads(receipt)
        loaded = load_delivery_receipt(receipt)

        self.assertEqual(2, decoded["version"])
        self.assertEqual("delivery", decoded["scope"])
        self.assertEqual(
            ["add", "commit", "push"], decoded["requested_actions"])
        self.assertEqual(64, len(decoded["digest"]))
        self.assertEqual(receipt, json.dumps(
            decoded, ensure_ascii=False, sort_keys=True,
            separators=(",", ":")))
        self.assertEqual(decoded["digest"], loaded.digest)
        self.assertTrue(valid_delivery_receipt(state, receipt))

    def test_caller_digest_and_any_bound_plan_change_are_rejected(self):
        state = continuous_state()
        receipt = issue_delivery_receipt(state, "Ship the reviewed plan.")
        decoded = json.loads(receipt)
        decoded["digest"] = "0" * 64
        forged = json.dumps(
            decoded, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"))

        self.assertFalse(valid_delivery_receipt(state, forged))
        for changed in (
                replace(state, delivery_files=("src/b.cpp",)),
                replace(state, decisions=tuple(
                    (key, "[REQ-42][fix]different message")
                    if key == "delivery.commit_message" else (key, value)
                    for key, value in state.decisions)),
                replace(state, decisions=tuple(
                    (key, "upstream") if key == "delivery.plan.remote"
                    else (key, value) for key, value in state.decisions)),
                replace(state, decisions=tuple(
                    (key, "refs/heads/other")
                    if key == "delivery.plan.destination_ref"
                    else (key, value) for key, value in state.decisions)),
                replace(state, decisions=tuple(
                    (key, "c" * 40)
                    if key == "delivery.plan.expected_destination_sha"
                    else (key, value) for key, value in state.decisions)),
                replace(state, commit_pace=CommitPace.STAGED),
                replace(state, decisions=tuple(
                    (key, "c" * 40)
                    if key == "delivery.plan.source_sha" else (key, value)
                    for key, value in state.decisions)),
        ):
            with self.subTest(changed=changed):
                self.assertFalse(valid_delivery_receipt(changed, receipt))

    def test_checkpoint_receipt_binds_exact_cp_files_and_message(self):
        state = FlowState(
            ticket="REQ-42",
            path=DeliveryPath.FULL,
            phase=Phase.CONSTRUCTION,
            commit_pace=CommitPace.STAGED,
            current_cp="CP1",
            decisions=(
                ("delivery.cp.CP1.file", "src/a.cpp"),
                ("delivery.cp.CP1.message", "[REQ-42][feat]complete CP1"),
                ("delivery.cp.CP1.source_sha", "b" * 40),
            ),
        )

        receipt = issue_delivery_receipt(
            state, "I reviewed CP1 and authorize its local commit.", "CP1")

        self.assertTrue(valid_delivery_receipt(state, receipt, "CP1"))
        changed = replace(state, decisions=(
            ("delivery.cp.CP1.file", "src/b.cpp"),
            ("delivery.cp.CP1.message", "[REQ-42][feat]complete CP1"),
        ))
        self.assertFalse(valid_delivery_receipt(changed, receipt, "CP1"))

    def test_receipt_requires_real_user_prose_and_exact_target_shape(self):
        state = continuous_state()
        with self.assertRaisesRegex(ValueError, "natural-language"):
            issue_delivery_receipt(state, " \t\r\n")

        bad_ref = replace(state, decisions=tuple(
            (key, "fix/receipt")
            if key == "delivery.plan.destination_ref" else (key, value)
            for key, value in state.decisions))
        with self.assertRaisesRegex(ValueError, "refs/heads"):
            issue_delivery_receipt(bad_ref, "Ship after review.")

    def test_new_branch_push_is_bound_to_the_observed_source_chain(self):
        state = replace(
            continuous_state(),
            decisions=tuple(
                (key, "" if key == "delivery.plan.expected_destination_sha"
                 else "true" if key == "delivery.plan.new_branch"
                 else value)
                for key, value in continuous_state().decisions
            ),
        )
        receipt_raw = issue_delivery_receipt(
            state, "Publish this exact new-branch chain.")
        receipt = load_delivery_receipt(receipt_raw)
        observation = json.dumps({
            "files": list(receipt.files),
            "pre_head": "b" * 40,
            "receipt_digest": receipt.digest,
            "sha": "c" * 40,
            "tool_use_id": "commit-1",
        }, sort_keys=True, separators=(",", ":"))
        authorized = replace(
            state,
            decisions=state.decisions + (
                ("delivery.receipt", receipt_raw),
                ("delivery.git.commit_observation", observation),
            ),
        )
        arguments = (
            "--force-with-lease=refs/heads/fix/receipt:",
            "origin",
            "HEAD:refs/heads/fix/receipt",
        )

        self.assertEqual("b" * 40, receipt.source_base_sha)
        self.assertEqual(
            "",
            git_receipt_error(
                authorized, "push", (), arguments),
        )
        self.assertEqual(
            "c" * 40,
            git_receipt_reservation(
                authorized, "push", (), arguments)["expected_source_sha"],
        )

        broken_observation = json.loads(observation)
        broken_observation["pre_head"] = "d" * 40
        broken = replace(
            authorized,
            decisions=tuple(
                (key, json.dumps(
                    broken_observation, sort_keys=True, separators=(",", ":")))
                if key == "delivery.git.commit_observation" else (key, value)
                for key, value in authorized.decisions
            ),
        )
        self.assertNotEqual(
            "",
            git_receipt_error(broken, "push", (), arguments),
        )


if __name__ == "__main__":
    unittest.main()
