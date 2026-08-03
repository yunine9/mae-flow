#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cross-module composition contract for migrated lean workflow recovery."""

import json
import os
import sys
import unittest


SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.orchestration import (  # noqa: E402
    AdvanceRequest,
    DeliveryPath,
    Phase,
    advance_flow,
    decode_flow_state,
    encode_flow_state,
    flow_attempt_context,
    migrate_legacy_flow,
    record_flow_attempt,
)
from mae_flow_core.orchestration.guidance import render_guidance  # noqa: E402


def legacy(current, workflow):
    return {
        "schema_version": 2,
        "current": current,
        "config": {"单号": "REQ-COMPOSE"},
        "choices": {"workflow": workflow},
        "history": [],
    }


def satisfy_new_completion_facts(state, event):
    if event == "construction-complete":
        return record_flow_attempt(
            state,
            flow_attempt_context(state, "build"),
            "returned",
            "opaque migrated CP build return",
        )
    if event == "quality-complete":
        return advance_flow(state, AdvanceRequest(
            "final-conformance", "",
            "迁移后的最终实现与已确认范围一致。",
        )).state
    return state


class LeanCompositionTests(unittest.TestCase):
    def test_representative_families_compose_through_recovery_boundaries(self):
        cases = (
            (
                "full", "grill", DeliveryPath.FULL, Phase.SPEC,
                ("grill-question", "grill-answer", "grill-converged",
                 "grill-clear", "spec-confirmed"), Phase.STORY,
            ),
            (
                "hotfix", "hf_open", DeliveryPath.FOCUSED, Phase.SPEC,
                ("spec-confirmed",), Phase.CONSTRUCTION,
            ),
            (
                "tweak", "tw_change", DeliveryPath.FOCUSED,
                Phase.CONSTRUCTION, ("construction-complete",), Phase.QUALITY,
            ),
            (
                "review", "rf_ut", DeliveryPath.FOCUSED, Phase.QUALITY,
                ("quality-complete",), Phase.DELIVERY,
            ),
        )
        for workflow, current, path, phase, events, target in cases:
            with self.subTest(workflow=workflow, current=current):
                migrated = migrate_legacy_flow(legacy(current, workflow)).state
                recovered = decode_flow_state(encode_flow_state(migrated))
                guidance = render_guidance(recovered)
                advanced = recovered
                for event in events:
                    key = ""
                    value = "用户确认迁移后的语义恢复步骤。"
                    if event == "grill-question":
                        key = "GQ-001"
                        value = json.dumps({
                            "parent": "",
                            "evidence": "迁移状态缺少 SUL 边界。",
                            "impact": "行为无法形成可测 Spec。",
                            "recommendation": "沿用确认的兼容边界。",
                        }, sort_keys=True, separators=(",", ":"))
                    elif event == "grill-answer":
                        key = "GQ-001"
                    elif event == "grill-converged":
                        value = json.dumps({
                            "answer_count": 1,
                            "grill_sha256": "a" * 64,
                        }, sort_keys=True, separators=(",", ":"))
                    if event == "grill-clear":
                        advanced = record_flow_attempt(
                            advanced,
                            flow_attempt_context(advanced, "grill"),
                            "returned",
                        )
                        value = json.dumps({
                            "grill_sha256": "a" * 64,
                            "input_coverage": "complete",
                            "spec_sha256": "b" * 64,
                        }, sort_keys=True, separators=(",", ":"))
                    advanced = satisfy_new_completion_facts(advanced, event)
                    advanced = advance_flow(
                        advanced, AdvanceRequest(
                            event, key, value),
                    ).state

                self.assertEqual(path, recovered.path)
                self.assertEqual(phase, recovered.phase)
                self.assertIn("Ticket: REQ-COMPOSE", guidance)
                self.assertIn("Path: %s" % path.value, guidance)
                self.assertIn("Phase: %s" % phase.value, guidance)
                self.assertEqual(target, advanced.phase)

    def test_every_focused_migration_phase_has_a_safe_semantic_next_event(self):
        cases = (
            ("config_confirm", Phase.STARTUP, "startup-confirmed", Phase.CONSTRUCTION),
            ("hf_open", Phase.SPEC, "spec-confirmed", Phase.CONSTRUCTION),
            ("design", Phase.STORY, "story-confirmed", Phase.CONSTRUCTION),
            (
                "tw_change", Phase.CONSTRUCTION,
                "construction-complete", Phase.QUALITY,
            ),
            ("rf_ut", Phase.QUALITY, "quality-complete", Phase.DELIVERY),
            ("push", Phase.DELIVERY, "delivery-confirmed", Phase.DELIVERY),
        )
        for current, phase, event, target in cases:
            with self.subTest(current=current, phase=phase):
                migrated = migrate_legacy_flow(
                    legacy(current, "review")).state
                recovered = decode_flow_state(encode_flow_state(migrated))
                recovered = satisfy_new_completion_facts(recovered, event)
                result = advance_flow(
                    recovered,
                    AdvanceRequest(
                        event, "", "用户确认迁移后的语义恢复步骤。"),
                )

                self.assertEqual(DeliveryPath.FOCUSED, recovered.path)
                self.assertEqual(phase, recovered.phase)
                self.assertEqual(target, result.state.phase)
                self.assertFalse(result.needs_user)
                self.assertNotIn("does not change", result.reason.lower())


if __name__ == "__main__":
    unittest.main()
