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
    prepare_phase_request,
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
        self.write(
            os.path.join(self.paths.local_root, "survey.md"),
            "# Survey\n\nRelevant code facts.\n")
        sections = (
            "## 1 状态机完备性", "## 2 边界值", "## 3 并发时序",
            "## 4 失败路径与残留清理", "## 5 数据一致性",
            "## 6 存量升级兼容", "## 7 规格性能", "## 8 可观测",
            "## 9 结论汇总",
        )
        self.write(
            os.path.join(self.paths.local_root, "grill-prep.md"),
            "# Grill preparation\n\n" + "\n\n".join(
                section + "\n\n结论：已基于代码证据检查。"
                for section in sections) + "\n")
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

    def test_persisted_legacy_artifacts_remain_authoritative(self):
        ticket = "REQ-LEGACY"
        old_segment = ticket + "-" + hashlib.sha256(
            ticket.encode("utf-8")).hexdigest()
        old_root = os.path.join(self.root, ".mae-flow-work", old_segment)
        os.makedirs(old_root)
        relative_root = ".mae-flow-work/" + old_segment
        artifacts = (
            ("grill", relative_root + "/grill.md"),
            ("spec", relative_root + "/spec.md"),
            ("story", relative_root + "/story.md"),
            ("ut-handoff", relative_root + "/ut-handoff.md"),
        )
        legacy = replace(self.state, ticket=ticket, artifacts=artifacts)
        grill = os.path.join(old_root, "grill.md")
        spec = os.path.join(old_root, "spec.md")
        story = os.path.join(old_root, "story.md")
        self.write(grill, "# Legacy Grill\n\nGQ-001 已确认。\n")
        self.write(spec, "# Legacy Spec\n\nGQ-001 -> AC-001\n")
        self.write(story, "# Legacy Story\n\nCP1 implements AC-001.\n")
        self.write(os.path.join(old_root, "survey.md"), "# Survey\n\n事实。\n")
        self.write(
            os.path.join(old_root, "grill-prep.md"),
            "# Grill preparation\n\n" + "\n\n".join(
                section + "\n\n结论：已检查。"
                for section in (
                    "## 1 状态机完备性", "## 2 边界值", "## 3 并发时序",
                    "## 4 失败路径与残留清理", "## 5 数据一致性",
                    "## 6 存量升级兼容", "## 7 规格性能", "## 8 可观测",
                    "## 9 结论汇总",
                )) + "\n",
        )

        convergence = prepare_grill_request(
            self.root, legacy, AdvanceRequest("grill-converged"))
        self.assertEqual(
            self.digest(grill),
            json.loads(convergence.decision_value)["grill_sha256"],
        )
        converged = advance_flow(legacy, convergence).state
        converged = replace(
            converged,
            capabilities=(CapabilityAttempt(
                "grill", "grill:spec:-", "lean-workflow-v1", "returned"),),
        )
        critic = prepare_grill_request(
            self.root, converged, AdvanceRequest("grill-clear"))
        reviewed = advance_flow(converged, critic).state
        self.assertEqual("", validate_spec_confirmation(self.root, reviewed))

        story_state = replace(
            reviewed,
            phase=Phase.STORY,
            capabilities=(CapabilityAttempt(
                "story", "story:story:-", "lean-workflow-v1", "returned"),),
        )
        design = prepare_phase_request(
            self.root,
            story_state,
            AdvanceRequest("reviewer-clear", decision_value="设计检视通过。"),
        )
        self.assertEqual(
            self.digest(story), json.loads(design.decision_value)["story_sha256"])


if __name__ == "__main__":
    unittest.main()
