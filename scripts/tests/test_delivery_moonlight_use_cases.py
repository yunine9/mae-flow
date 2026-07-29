#!/usr/bin/env python3
"""Moonlight delivery application use-case tests."""

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.application.delivery.moonlight import (  # noqa: E402
    activate_moonlight,
    disable_moonlight,
    finalize_moonlight,
    record_blocker,
    record_deferred_quality,
    record_push_failure,
    repair_moonlight,
    unlock_moonlight_source,
)
from mae_flow_core.delivery.models import thaw  # noqa: E402


class MoonlightUseCaseTests(unittest.TestCase):
    def state(self, current="verify_ut"):
        return {
            "current": current,
            "choices": {"workflow": "tweak"},
            "config": {"CHANGE_NAME": "change"},
            "moonlight": {
                "enabled": True,
                "cycle": 1,
                "issues": [],
            },
            "history": [],
        }

    def updated(self, result):
        return thaw(result.effects[0].payload)

    def test_blocker_and_push_failure_create_durable_issue(self):
        state = self.state("build")
        result = record_blocker(
            state, can_block=True,
            reason="external service credentials are unavailable",
            head="head", dirty_paths=("src/main.py",), now="now")
        updated = self.updated(result)
        self.assertEqual("ML-001", updated["moonlight"]["hard_blocked"]["issue"])
        self.assertEqual("write_report", result.effects[1].kind)

        state = self.state("push")
        result = record_push_failure(
            state,
            reason="authentication failed after two retries",
            head="head",
            now="now",
        )
        updated = self.updated(result)
        self.assertEqual("push", updated["moonlight"]["issues"][0]["kind"])
        self.assertEqual("push", updated["current"])

    def test_defer_supersedes_same_kind_and_requests_advance(self):
        state = self.state("verify_ut")
        state["moonlight"]["issues"] = [{
            "id": "ML-001",
            "kind": "ut",
            "reason": "old failure",
        }]
        result = record_deferred_quality(
            state,
            kind="ut",
            reason="two tests still fail after scoped repair",
            rejection="agent diagnostic",
            head="head",
            now="now",
        )
        updated = self.updated(result)
        self.assertEqual(
            "superseded",
            updated["moonlight"]["issues"][0]["resolved_as"])
        self.assertEqual("advance_deferred", result.effects[-1].kind)

    def test_unlock_and_repair_blocker_preserve_current_step(self):
        state = self.state()
        result = unlock_moonlight_source(
            state,
            tests_only=True,
            reason="failing case proves source contract mismatch",
            now="now",
        )
        self.assertEqual("source", self.updated(result)["unlock"]["scope"])

        state["moonlight"]["hard_blocked"] = {
            "issue": "ML-001",
        }
        state["moonlight"]["issues"] = [{
            "id": "ML-001",
            "kind": "blocker",
        }]
        result = repair_moonlight(
            state, repair_target="tw_change", head="head", now="later")
        updated = self.updated(result)
        self.assertEqual("verify_ut", updated["current"])
        self.assertEqual(2, updated["moonlight"]["cycle"])

    def test_finalize_disables_moonlight_and_targets_archive(self):
        state = self.state("moonlight_review")
        result = finalize_moonlight(
            state,
            ack="",
            ack_verified=(True, ""),
            head="head",
            now="now",
        )
        updated = self.updated(result)
        self.assertFalse(updated["moonlight"]["enabled"])
        self.assertEqual("archive_confirm", updated["current"])
        self.assertEqual("print_current", result.effects[-1].kind)

    def test_activation_defers_archive_and_off_requires_authorization(self):
        state = self.state("archive_confirm")
        state["moonlight"]["enabled"] = False
        state["config_review"] = {"stale": True}
        result = activate_moonlight(
            state,
            ack="please run overnight",
            request="please run overnight",
            activated_at="now",
            history_at="later",
            head="head",
            active_change_exists=False,
        )
        updated = self.updated(result)
        self.assertTrue(updated["moonlight"]["enabled"])
        self.assertEqual("push", updated["current"])
        self.assertNotIn("config_review", updated)

        result = disable_moonlight(
            updated, ack="", ack_verified=(False, ""), now="off")
        self.assertEqual(2, result.exit_code)
        result = disable_moonlight(
            updated,
            ack="关闭月光宝盒",
            ack_verified=(True, ""),
            now="off",
        )
        self.assertFalse(self.updated(result)["moonlight"]["enabled"])


if __name__ == "__main__":
    unittest.main()
