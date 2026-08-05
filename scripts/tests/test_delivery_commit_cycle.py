#!/usr/bin/env python3
"""Delivery cannot reach push with an uncommitted confirmed manifest."""

import os
import sys
import types
import unittest


SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.delivery.evidence import DeliveryEvidenceRules  # noqa: E402


def rules(committed=(), dirty=(), message="[REQ-1][feat]archive domain truth"):
    def argv(arguments):
        if arguments[:3] == ["git", "cat-file", "-t"]:
            return "commit"
        if arguments[:3] == ["git", "log", "--format=%H"]:
            return "new-head"
        if arguments[:3] == ["git", "diff", "--name-only"]:
            return "\n".join(committed)
        return ""

    return DeliveryEvidenceRules(types.SimpleNamespace(
        argv_output=argv,
        shell_output=lambda command: message if "pretty=%s" in command else "",
        dirty_paths=lambda: list(dirty),
    ))


class DeliveryCommitCycleTests(unittest.TestCase):
    def state(self):
        return {
            "current": "delivery_review",
            "config": {"单号": "REQ-1"},
            "step_heads": {"delivery_review": "base-head"},
            "delivery_manifest": {
                "files": ["docs/specs/radio.md"],
                "confirmed": True,
            },
        }

    def test_confirmed_manifest_must_be_committed_and_clean(self):
        missing = rules().delivery_manifest_committed({}, self.state())
        dirty = rules(
            committed=("docs/specs/radio.md",),
            dirty=("docs/specs/radio.md",),
        ).delivery_manifest_committed({}, self.state())
        clean = rules(
            committed=("docs/specs/radio.md",),
        ).delivery_manifest_committed({}, self.state())
        self.assertFalse(missing.passed)
        self.assertFalse(dirty.passed)
        self.assertTrue(clean.passed)

    def test_unconfirmed_manifest_never_authorizes_delivery_commit(self):
        state = self.state()
        state["delivery_manifest"]["confirmed"] = False
        result = rules(
            committed=("docs/specs/radio.md",),
        ).delivery_manifest_committed({}, state)
        self.assertFalse(result.passed)
        self.assertIn("未确认", result.reason)

    def test_quality_review_requires_every_reviewed_path_committed_and_clean(self):
        state = {
            "current": "quality_commit",
            "config": {"单号": "REQ-1"},
            "step_heads": {"quality_commit": "base-head"},
            "quality_review": {
                "changed_files": ["src/a.cpp", "tests/a_test.cpp"],
            },
        }
        missing = rules(
            committed=("src/a.cpp",),
        ).quality_review_committed({}, state)
        dirty = rules(
            committed=("src/a.cpp", "tests/a_test.cpp"),
            dirty=("tests/a_test.cpp",),
        ).quality_review_committed({}, state)
        clean = rules(
            committed=("src/a.cpp", "tests/a_test.cpp"),
        ).quality_review_committed({}, state)
        extra = rules(
            committed=("src/a.cpp", "tests/a_test.cpp", "src/extra.cpp"),
        ).quality_review_committed({}, state)
        self.assertFalse(missing.passed)
        self.assertFalse(dirty.passed)
        self.assertFalse(extra.passed)
        self.assertTrue(clean.passed)


if __name__ == "__main__":
    unittest.main()
