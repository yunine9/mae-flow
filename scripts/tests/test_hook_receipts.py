#!/usr/bin/env python3
"""Tests for Hook quality receipt creation and reuse."""

import hashlib
import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.application.hooks.receipts import (  # noqa: E402
    ReceiptContext,
    plan_compile_run_receipt,
    plan_codecheck_build_receipt,
    plan_codecheck_fullcheck_receipt,
    plan_ut_generator_receipt,
    plan_ut_run_receipt,
    reusable_compile_run_receipt,
    reusable_codecheck_build_receipt,
    reusable_codecheck_fullcheck_receipt,
    reusable_ut_receipt,
)


HEAD = "a" * 40
TASK = {"step": "tw_ut", "sha256": "task-digest", "head": HEAD}


class HookReceiptTests(unittest.TestCase):
    def test_compile_receipt_binds_opaque_run_without_storing_raw_result(self):
        task = {
            "step": "build",
            "sha256": "compile-task",
            "issuance_id": "issue-1",
            "checkpoint": "CP1",
            "precommit_review": True,
        }
        receipt = plan_compile_run_receipt(
            task,
            ReceiptContext(
                "2026-07-31 20:00:00",
                HEAD,
                {"src/a.cpp": "fingerprint"},
            ),
            "build-fix",
            "OK",
            "internal maven and g++ output",
        )

        self.assertEqual("issue-1", receipt["task_issuance_id"])
        self.assertEqual("CP1", receipt["checkpoint"])
        self.assertEqual("build-fix", receipt["build"])
        self.assertEqual("OK", receipt["status"])
        self.assertEqual(
            {"src/a.cpp": "fingerprint"},
            receipt["source_snapshot"],
        )
        self.assertEqual(
            hashlib.sha256(
                b"internal maven and g++ output").hexdigest(),
            receipt["result_sha256"],
        )
        self.assertNotIn("internal maven and g++ output", repr(receipt))

    def test_compile_reuse_requires_same_issuance_route_status_and_snapshot(self):
        task = {
            "step": "build",
            "sha256": "compile-task",
            "issuance_id": "issue-1",
            "checkpoint": "CP1",
            "precommit_review": True,
        }
        snapshot = {"src/a.cpp": "one"}
        receipt = plan_compile_run_receipt(
            task,
            ReceiptContext("now", HEAD, snapshot),
            "build-fix",
            "OK",
            "opaque",
        )

        self.assertEqual(
            receipt,
            reusable_compile_run_receipt(
                receipt,
                task,
                "build-fix",
                "OK",
                source_snapshot=snapshot,
            ),
        )
        self.assertIsNone(reusable_compile_run_receipt(
            receipt,
            dict(task, issuance_id="issue-2"),
            "build-fix",
            "OK",
            source_snapshot=snapshot,
        ))
        self.assertIsNone(reusable_compile_run_receipt(
            receipt,
            task,
            "another-build",
            "OK",
            source_snapshot=snapshot,
        ))
        self.assertIsNone(reusable_compile_run_receipt(
            receipt,
            task,
            "build-fix",
            "BLOCKED",
            source_snapshot=snapshot,
        ))
        self.assertIsNone(reusable_compile_run_receipt(
            receipt,
            task,
            "build-fix",
            "OK",
            source_snapshot={"src/a.cpp": "two"},
        ))

    def test_build_receipt_binds_task_head_and_configuration(self):
        receipt = plan_codecheck_build_receipt(
            TASK,
            ReceiptContext("2026-07-30 10:00:00", HEAD),
            "python build.py",
        )
        self.assertEqual({
            "at": "2026-07-30 10:00:00",
            "step": "tw_ut",
            "task_sha256": "task-digest",
            "head": HEAD,
            "build": "python build.py",
        }, receipt)

    def test_standalone_receipts_bind_source_snapshot(self):
        task = dict(TASK, standalone=True)
        context = ReceiptContext(
            "2026-07-30 10:00:00",
            HEAD,
            {"src/main.py": "fingerprint"},
        )
        build = plan_codecheck_build_receipt(
            task, context, "python build.py")
        generator = plan_ut_generator_receipt(
            task, context, "manual")
        self.assertEqual(
            {"src/main.py": "fingerprint"},
            build["source_snapshot"],
        )
        self.assertEqual(
            {"src/main.py": "fingerprint"},
            generator["source_snapshot"],
        )

    def test_fullcheck_receipt_distinguishes_counts_from_unknown_output(self):
        context = ReceiptContext("2026-07-30 10:00:00", HEAD)
        counted = plan_codecheck_fullcheck_receipt(
            TASK, context, 2, [2, 1],
            {"count": 3, "stock_excluded": 0},
            expected_raw=3,
            result_hashes=["one", "two"],
        )
        self.assertTrue(counted["machine_counts_complete"])
        self.assertEqual(3, counted["raw_total"])

        unknown = plan_codecheck_fullcheck_receipt(
            TASK, context, 2, [],
            {"count": 3, "stock_excluded": 0},
            result_hashes=["one", "two"],
        )
        self.assertFalse(unknown["machine_counts_complete"])
        self.assertEqual([], unknown["raw_counts"])
        self.assertEqual(0, unknown["raw_total"])

    def test_ut_run_receipt_binds_reported_counts_and_result_hash(self):
        receipt = plan_ut_run_receipt(
            TASK,
            ReceiptContext("2026-07-30 10:00:00", HEAD),
            "python -m unittest",
            {"total": 7, "passed": 7, "failed": 0},
            "Ran 7 tests\nOK",
        )
        self.assertEqual(
            {"total": 7, "passed": 7, "failed": 0},
            receipt["reported_counts"],
        )
        self.assertEqual(
            hashlib.sha256(
                b"Ran 7 tests\nOK").hexdigest(),
            receipt["result_sha256"],
        )

    def test_ut_reuse_requires_same_task_config_and_fresh_source(self):
        receipt = plan_ut_generator_receipt(
            TASK,
            ReceiptContext("2026-07-30 10:00:00", HEAD),
            "manual",
        )
        self.assertEqual(
            receipt,
            reusable_ut_receipt(
                receipt, TASK, expected=" manual ",
                changed_paths=(), source_error=""),
        )
        self.assertIsNone(reusable_ut_receipt(
            receipt, TASK, expected="autout",
            changed_paths=(), source_error=""))
        self.assertIsNone(reusable_ut_receipt(
            receipt, TASK, expected="manual",
            changed_paths=("src/main.py",), source_error=""))

    def test_standalone_reuse_requires_the_same_source_snapshot(self):
        task = dict(TASK, standalone=True)
        receipt = plan_ut_generator_receipt(
            task,
            ReceiptContext(
                "2026-07-30 10:00:00", HEAD, {"src/a.py": "one"}),
            "manual",
        )
        self.assertEqual(
            receipt,
            reusable_ut_receipt(
                receipt,
                task,
                expected="manual",
                standalone_snapshot={"src/a.py": "one"},
            ),
        )
        self.assertIsNone(reusable_ut_receipt(
            receipt,
            task,
            expected="manual",
            standalone_snapshot={"src/a.py": "two"},
        ))

    def test_codecheck_reuse_rejects_stale_or_incoherent_receipts(self):
        context = ReceiptContext("2026-07-30 10:00:00", HEAD)
        build = plan_codecheck_build_receipt(
            TASK, context, "python build.py")
        self.assertEqual(
            build,
            reusable_codecheck_build_receipt(
                build, TASK, "python build.py"),
        )
        self.assertIsNone(reusable_codecheck_build_receipt(
            build, TASK, "other build"))

        fullcheck = plan_codecheck_fullcheck_receipt(
            TASK, context, 2, [2, 1],
            {"count": 3, "stock_excluded": 0},
        )
        self.assertEqual(
            fullcheck,
            reusable_codecheck_fullcheck_receipt(
                fullcheck,
                TASK,
                2,
                {"count": 3, "stock_excluded": 0},
            ),
        )
        incoherent = dict(fullcheck, raw_total=99)
        self.assertIsNone(reusable_codecheck_fullcheck_receipt(
            incoherent,
            TASK,
            2,
            {"count": 3, "stock_excluded": 0},
        ))


if __name__ == "__main__":
    unittest.main()
