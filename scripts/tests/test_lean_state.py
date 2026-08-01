#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fixture-level contract for the lean workflow serialized state."""

import json
import os
import unittest


FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "lean_state_v3.json")


class LeanStateContractTests(unittest.TestCase):
    def test_fixture_keeps_recovery_facts_without_evidence_police_fields(self):
        with open(FIXTURE, encoding="utf-8") as stream:
            raw = json.load(stream)
        self.assertEqual("lean-v1", raw["engine"])
        self.assertEqual("startup", raw["phase"])
        self.assertEqual("REQ-7", raw["ticket"])
        forbidden = {"tokens", "agent_tasks", "receipts", "evidence", "step_heads"}
        self.assertFalse(forbidden.intersection(raw))


if __name__ == "__main__":
    unittest.main()
