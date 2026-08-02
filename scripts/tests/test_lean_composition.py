#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cross-module composition contract for migrated lean workflow recovery."""

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


class LeanCompositionTests(unittest.TestCase):
    def test_representative_families_compose_through_recovery_boundaries(self):
        cases = (
            (
                "full", "grill", DeliveryPath.FULL, Phase.SPEC,
                ("grill-clear", "spec-confirmed"), Phase.STORY,
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
                    if event == "grill-clear":
                        advanced = record_flow_attempt(
                            advanced,
                            flow_attempt_context(advanced, "grill"),
                            "returned",
                        )
                    advanced = advance_flow(
                        advanced, AdvanceRequest(event)).state

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
                result = advance_flow(recovered, AdvanceRequest(event))

                self.assertEqual(DeliveryPath.FOCUSED, recovered.path)
                self.assertEqual(phase, recovered.phase)
                self.assertEqual(target, result.state.phase)
                self.assertFalse(result.needs_user)
                self.assertNotIn("does not change", result.reason.lower())


if __name__ == "__main__":
    unittest.main()
