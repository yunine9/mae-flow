#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the behavior-preserving differential harness."""

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TESTS = os.path.join(ROOT, "scripts", "tests")
if TESTS not in sys.path:
    sys.path.insert(0, TESTS)

from differential.normalize import normalize_text, normalize_value  # noqa: E402
from differential.snapshot import Snapshot  # noqa: E402


class DifferentialNormalizationTests(unittest.TestCase):
    def test_normalize_text_replaces_only_explicit_dynamic_values(self):
        replacements = {
            "/tmp/mf-123": "<TMP>",
            "2026-07-29 12:34:56": "<TIME>",
            "receipt-abcd": "<RECEIPT>",
        }
        actual = normalize_text(
            "path=/tmp/mf-123 at=2026-07-29 12:34:56 "
            "id=receipt-abcd semantic=2026-07-29",
            replacements,
        )
        self.assertEqual(
            "path=<TMP> at=<TIME> id=<RECEIPT> semantic=2026-07-29",
            actual,
        )

    def test_normalize_value_preserves_types_and_unknown_fields(self):
        source = {
            "path": "/tmp/mf-123/state.json",
            "nested": [{"at": "2026-07-29 12:34:56", "count": 2}],
            "unknown": {"keep": True},
        }
        actual = normalize_value(
            source,
            {
                "/tmp/mf-123": "<TMP>",
                "2026-07-29 12:34:56": "<TIME>",
            },
        )
        self.assertEqual(
            {
                "path": "<TMP>/state.json",
                "nested": [{"at": "<TIME>", "count": 2}],
                "unknown": {"keep": True},
            },
            actual,
        )

    def test_snapshot_round_trip_is_lossless(self):
        snapshot = Snapshot(
            stdout="out",
            stderr="err",
            returncode=2,
            files={"a.txt": {"sha256": "abc", "size": 3}},
            state={"flow": {"current": "build", "unknown": 7}},
            git={"branch": "main", "head": "deadbeef", "status": ""},
        )
        self.assertEqual(snapshot, Snapshot.from_dict(snapshot.to_dict()))


if __name__ == "__main__":
    unittest.main()
