#!/usr/bin/env python3
"""File receipt contracts binding Interactive Grill to the final Spec."""

from dataclasses import replace
import hashlib
import json
import os
import sys
import tempfile
import unittest


SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.cli_commands.grill_receipts import (  # noqa: E402
    prepare_grill_request,
    validate_spec_confirmation,
)
from mae_flow_core.orchestration import (  # noqa: E402
    AdvanceRequest,
    CapabilityAttempt,
    CommitPace,
    DeliveryPath,
    FlowState,
    Phase,
    advance_flow,
)
from mae_flow_core.orchestration.documents import DocumentPaths  # noqa: E402


def compact(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class LeanGrillReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = self.temporary.name
        self.paths = DocumentPaths.for_ticket(self.root, "REQ-RECEIPT")
        os.makedirs(self.paths.local_root)
        self.write(self.paths.local_grill, "# Grill\n\nGQ-001 已确认。\n")
        self.write(self.paths.local_spec, "# Spec\n\nGQ-001 -> AC-001\n")
        self.state = FlowState(
            ticket="REQ-RECEIPT",
            path=DeliveryPath.FULL,
            phase=Phase.SPEC,
            commit_pace=CommitPace.CONTINUOUS,
        )
        question = compact({
            "parent": "",
            "evidence": "当前实现只覆盖主载波。",
            "impact": "SUL 行为不明确。",
            "recommendation": "仅配置 SUL 时选择 SUL。",
        })
        for request in (
                AdvanceRequest("grill-question", "GQ-001", question),
                AdvanceRequest(
                    "grill-answer", "GQ-001", "用户确认推荐边界。")):
            self.state = advance_flow(self.state, request).state

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, path, text):
        with open(path, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)

    def digest(self, path):
        with open(path, "rb") as stream:
            return hashlib.sha256(stream.read()).hexdigest()

    def test_convergence_receipt_uses_current_grill_digest_and_answer_count(self):
        prepared = prepare_grill_request(
            self.root, self.state, AdvanceRequest("grill-converged"))
        receipt = json.loads(prepared.decision_value)

        self.assertEqual(1, receipt["answer_count"])
        self.assertEqual(
            self.digest(self.paths.local_grill), receipt["grill_sha256"])

    def test_critic_receipt_binds_grill_spec_and_complete_coverage(self):
        convergence = prepare_grill_request(
            self.root, self.state, AdvanceRequest("grill-converged"))
        converged = advance_flow(self.state, convergence).state
        converged = replace(
            converged,
            capabilities=converged.capabilities + (CapabilityAttempt(
                "grill", "grill:spec:-", "lean-workflow-v1", "returned"),),
        )

        prepared = prepare_grill_request(
            self.root, converged, AdvanceRequest("grill-clear"))
        receipt = json.loads(prepared.decision_value)

        self.assertEqual("complete", receipt["input_coverage"])
        self.assertEqual(
            self.digest(self.paths.local_grill), receipt["grill_sha256"])
        self.assertEqual(
            self.digest(self.paths.local_spec), receipt["spec_sha256"])

    def test_confirmation_detects_grill_or_spec_mutation_after_criticism(self):
        convergence = prepare_grill_request(
            self.root, self.state, AdvanceRequest("grill-converged"))
        state = advance_flow(self.state, convergence).state
        state = replace(
            state,
            capabilities=(CapabilityAttempt(
                "grill", "grill:spec:-", "lean-workflow-v1", "returned"),),
        )
        critic = prepare_grill_request(
            self.root, state, AdvanceRequest("grill-clear"))
        state = advance_flow(state, critic).state

        self.assertEqual("", validate_spec_confirmation(self.root, state))
        self.write(self.paths.local_spec, "# Spec\n\nchanged\n")
        self.assertIn(
            "Spec", validate_spec_confirmation(self.root, state))

        self.write(self.paths.local_spec, "# Spec\n\nGQ-001 -> AC-001\n")
        self.write(self.paths.local_grill, "# Grill\n\nchanged\n")
        self.assertIn(
            "Grill", validate_spec_confirmation(self.root, state))

    def test_missing_or_empty_artifact_is_rejected(self):
        os.remove(self.paths.local_grill)
        with self.assertRaisesRegex(ValueError, "grill.md"):
            prepare_grill_request(
                self.root, self.state, AdvanceRequest("grill-converged"))

        self.write(self.paths.local_grill, "")
        with self.assertRaisesRegex(ValueError, "empty"):
            prepare_grill_request(
                self.root, self.state, AdvanceRequest("grill-converged"))


if __name__ == "__main__":
    unittest.main()
