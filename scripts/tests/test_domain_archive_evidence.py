#!/usr/bin/env python3
"""Workflow Evidence for the one durable archive boundary."""

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.workflow.evidence_rules import (  # noqa: E402
    WorkflowEvidenceRules,
)


class DomainArchiveEvidenceTests(unittest.TestCase):
    def test_applied_change_or_confirmed_unchanged_passes(self):
        rules = WorkflowEvidenceRules(None)
        changed = rules.domain_archive_complete({}, {
            "domain_archive": {
                "status": "applied", "result": "changes",
                "applied_paths": ["docs/specs/radio.md"],
            },
        })
        unchanged = rules.domain_archive_complete({}, {
            "domain_archive": {
                "status": "applied", "result": "unchanged",
                "applied_paths": [],
            },
        })
        self.assertTrue(changed.passed)
        self.assertTrue(unchanged.passed)

    def test_draft_and_invalid_paths_fail_with_one_recovery_command(self):
        rules = WorkflowEvidenceRules(None)
        draft = rules.domain_archive_complete({}, {
            "domain_archive": {"status": "draft"},
        })
        invalid = rules.domain_archive_complete({}, {
            "domain_archive": {
                "status": "applied", "result": "changes",
                "applied_paths": ["docs/review/REVIEW-1.md"],
            },
        })
        self.assertFalse(draft.passed)
        self.assertIn("domain-archive status", draft.reason)
        self.assertFalse(invalid.passed)


if __name__ == "__main__":
    unittest.main()
