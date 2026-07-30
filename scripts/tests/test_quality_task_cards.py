#!/usr/bin/env python3
"""Tests for pure quality task-card contracts."""

import hashlib
import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.quality.task_cards import (  # noqa: E402
    TaskCardDocument,
    task_allowed,
    task_record,
)


class QualityTaskCardTests(unittest.TestCase):
    def test_allowed_steps_are_case_insensitive_by_kind(self):
        self.assertTrue(task_allowed("compile", "build"))
        self.assertTrue(task_allowed("UT", "rf_verify"))
        self.assertFalse(task_allowed("CODECHECK", "build"))

    def test_document_preserves_lines_and_legacy_digest_contract(self):
        document = TaskCardDocument(["# card", "line"])
        document.extend(["tail"])
        body = "# card\nline\ntail\n"
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        self.assertEqual(body, document.body())
        self.assertEqual(digest, document.digest())
        self.assertEqual(
            body + "TASK_CARD_SHA256: " + digest + "\n",
            document.sealed_body(),
        )

    def test_task_record_detaches_mutable_inputs(self):
        files = ["src/main.cpp"]
        roots = ["src"]
        worktree_snapshot = {"generated/build.properties": "before"}
        record = task_record(
            step="build",
            path="/tmp/card.md",
            digest="abc",
            head="deadbeef",
            scope="core",
            checkpoint="CP-1",
            precommit_review=True,
            initial_compile_net=2,
            source_snapshot={"src/main.cpp": "hash"},
            worktree_snapshot=worktree_snapshot,
            worktree_snapshot_valid=True,
            allowed_files=files,
            task_files=files,
            execution_roots=roots,
            lightcheck={"status": "CLEAN"},
            ut_targets={},
            unchanged_initial_dirty=["src/old.cpp"],
            at="2026-07-29 10:00:00",
            issuance_id="issuance-123",
        )
        files.append("src/later.cpp")
        roots.append(".")
        worktree_snapshot["generated/build.properties"] = "after"
        self.assertEqual(["src/main.cpp"], record["task_files"])
        self.assertEqual(["src"], record["execution_roots"])
        self.assertEqual(
            {"generated/build.properties": "before"},
            record["worktree_snapshot"],
        )
        self.assertTrue(record["worktree_snapshot_valid"])
        self.assertEqual("abc", record["sha256"])
        self.assertEqual("issuance-123", record["issuance_id"])


if __name__ == "__main__":
    unittest.main()
