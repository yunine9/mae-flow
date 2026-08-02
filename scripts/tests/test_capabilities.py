#!/usr/bin/env python3
"""Migration-only integrity checks for retained capability reference sources."""

import json
import os
import subprocess
import sys
import unittest


SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROOT = os.path.abspath(os.path.join(SCRIPTS, ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.capability_codecheck import _tree_sha256  # noqa: E402
from mae_flow_core.capability_packs import render_pack  # noqa: E402
from mae_flow_core.capability_shared import (  # noqa: E402
    CAPABILITY_PACKS,
    MANIFEST_PATH,
    VENDOR_ROOT,
)


class ReferenceCapabilitySourceTests(unittest.TestCase):
    def manifest(self):
        with open(MANIFEST_PATH, encoding="utf-8") as stream:
            return json.load(stream)

    def test_vendored_sources_match_pinned_integrity_manifest(self):
        manifest = self.manifest()
        self.assertEqual(1, manifest["schema"])
        self.assertEqual(
            {"comet", "openspec", "superpowers", "ponytail", "lizard"},
            set(manifest["components"]),
        )
        for name, metadata in sorted(manifest["components"].items()):
            with self.subTest(component=name):
                root = os.path.join(VENDOR_ROOT, name)
                self.assertTrue(os.path.isdir(root), root)
                self.assertEqual(metadata["sha256"], _tree_sha256(root))
                license_path = os.path.join(ROOT, metadata["license"])
                self.assertTrue(os.path.isfile(license_path), license_path)

    def test_reference_prompt_pack_sources_remain_readable(self):
        self.assertTrue(CAPABILITY_PACKS)
        for pack, entries in sorted(CAPABILITY_PACKS.items()):
            with self.subTest(pack=pack):
                self.assertTrue(entries)
                rendered = render_pack(pack)
                self.assertIn("内嵌能力", rendered)
                for entry in entries:
                    relative = entry[1]
                    self.assertTrue(os.path.isfile(os.path.join(
                        VENDOR_ROOT, *relative.split("/"))))

    def test_reference_manifest_declares_native_runtime_cutover(self):
        runtime = self.manifest()["runtime_guidance"]
        self.assertFalse(runtime["loads_vendor_prompt_text"])
        self.assertEqual(
            "scripts/mae_flow_core/orchestration/native_guidance.py",
            runtime["loader"],
        )
        self.assertEqual(
            "runtime/guidance/capability-preservation.json",
            runtime["preservation"],
        )

    def test_production_cli_rejects_retired_capability_lifecycle(self):
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "mae-flow.py"),
             "capability", "status"],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("invalid choice", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
