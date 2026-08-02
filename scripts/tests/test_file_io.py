#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for managed runtime file I/O."""

import gc
import json
import os
import subprocess
import sys
import tempfile
import unittest
import warnings


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.file_io import (  # noqa: E402
    load_json,
    read_bytes,
    read_lines,
    read_text,
    write_text,
)


class ManagedFileIOTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.text_path = os.path.join(self.temporary.name, "text.txt")
        self.json_path = os.path.join(self.temporary.name, "data.json")
        with open(self.json_path, "w", encoding="utf-8") as stream:
            json.dump({"值": 1}, stream, ensure_ascii=False)

    def test_read_write_and_json_helpers_close_their_streams(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ResourceWarning)
            write_text(self.text_path, "一\n", newline="\n")
            write_text(self.text_path, "二\n", newline="\n", mode="a")
            self.assertEqual("一\n二\n", read_text(self.text_path))
            self.assertEqual(["一\n", "二\n"], read_lines(self.text_path))
            self.assertEqual(
                "一\n二\n".encode("utf-8"),
                read_bytes(self.text_path),
            )
            self.assertEqual({"值": 1}, load_json(self.json_path))
            gc.collect()
        self.assertEqual(
            [],
            [
                item
                for item in caught
                if issubclass(item.category, ResourceWarning)
            ],
        )

    def test_lean_runtime_emits_no_resource_warnings(self):
        cases = (
            "scripts.tests.test_lean_migration_cli.LeanMigrationCliTests."
            "test_existing_schema_v3_current_is_read_only",
            "scripts.tests.test_lean_hook_adapter.LeanHookAdapterTests."
            "test_git_reservation_and_post_facts_complete_the_exact_receipt",
            "scripts.tests.test_delivery_manifest.DeliveryAuthorizationTests."
            "test_authorization_returns_new_state_with_exact_delivery_files",
        )
        result = subprocess.run(
            [
                sys.executable,
                "-W",
                "always::ResourceWarning",
                "-m",
                "unittest",
                *cases,
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
        )
        output = result.stdout + result.stderr
        self.assertEqual(0, result.returncode, output)
        self.assertNotIn("ResourceWarning", output)


if __name__ == "__main__":
    unittest.main()
