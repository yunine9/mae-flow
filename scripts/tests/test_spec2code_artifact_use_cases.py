#!/usr/bin/env python3
"""Spec2Code 过程件登记纯用例回归。"""

import hashlib
import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from mae_flow_core.application.quality.spec2code_artifacts import (  # noqa: E402
    ArtifactPorts,
    confirm_artifacts,
    register_artifact,
)
from mae_flow_core.delivery.models import thaw  # noqa: E402
from test_spec2code_artifacts import BLUEPRINT  # noqa: E402


class Spec2CodeArtifactUseCaseTests(unittest.TestCase):
    def call(self, text=BLUEPRINT, path=None, exists=True):
        path = path or ".mae-flow-work/test-blueprint-REQ-1.md"
        ports = ArtifactPorts(
            is_file=lambda _path: exists,
            read_text=lambda _path: text,
            normalize_path=lambda value: value.replace("\\", "/"),
            now=lambda: "2026-07-30 12:00:00",
        )
        return register_artifact(
            {},
            "blueprint",
            path,
            "REQ-1",
            ports,
        )

    def test_rejects_missing_wrong_path_and_invalid_content(self):
        missing = self.call(exists=False)
        self.assertEqual(2, missing.exit_code)
        self.assertIn("不存在", missing.stderr[0])

        wrong = self.call(path=".mae-flow-work/other.md")
        self.assertIn("规范路径", wrong.stderr[0])

        invalid = self.call(text="# UT 行为蓝图\n")
        self.assertIn("结构校验失败", invalid.stderr[0])

    def test_registers_path_digest_and_revision(self):
        result = self.call()
        self.assertEqual(0, result.exit_code)
        self.assertEqual("set_spec2code", result.effects[0].kind)
        process = thaw(result.effects[0].payload)
        record = process["blueprint"]
        self.assertEqual(
            ".mae-flow-work/test-blueprint-REQ-1.md",
            record["path"],
        )
        self.assertEqual(
            hashlib.sha256(BLUEPRINT.encode("utf-8")).hexdigest(),
            record["sha256"],
        )
        self.assertEqual(1, record["revision"])
        self.assertEqual(0, record["confirmed_revision"])

        again = register_artifact(
            process,
            "blueprint",
            record["path"],
            "REQ-1",
            ArtifactPorts(
                is_file=lambda _path: True,
                read_text=lambda _path: BLUEPRINT + "\n",
                normalize_path=lambda value: value,
                now=lambda: "2026-07-30 12:01:00",
            ),
        )
        self.assertEqual(
            2,
            thaw(again.effects[0].payload)["blueprint"]["revision"],
        )

    def test_confirmation_binds_current_revision_digest_actor_and_time(self):
        registered = thaw(self.call().effects[0].payload)

        result = confirm_artifacts(
            registered,
            ("blueprint",),
            "user",
            "2026-07-30 12:02:00",
        )

        self.assertEqual(0, result.exit_code)
        confirmed = thaw(result.effects[0].payload)["blueprint"]
        self.assertEqual(confirmed["revision"], confirmed["confirmed_revision"])
        self.assertEqual(confirmed["sha256"], confirmed["confirmed_sha256"])
        self.assertEqual("user", confirmed["confirmed_by"])
        self.assertEqual(
            "2026-07-30 12:02:00",
            confirmed["confirmed_at"],
        )

    def test_reregistering_an_artifact_invalidates_its_confirmation(self):
        registered = thaw(self.call().effects[0].payload)
        confirmed = thaw(confirm_artifacts(
            registered,
            ("blueprint",),
            "user",
            "2026-07-30 12:02:00",
        ).effects[0].payload)

        result = register_artifact(
            confirmed,
            "blueprint",
            ".mae-flow-work/test-blueprint-REQ-1.md",
            "REQ-1",
            ArtifactPorts(
                is_file=lambda _path: True,
                read_text=lambda _path: BLUEPRINT + "\n",
                normalize_path=lambda value: value,
                now=lambda: "2026-07-30 12:03:00",
            ),
        )

        record = thaw(result.effects[0].payload)["blueprint"]
        self.assertEqual(2, record["revision"])
        self.assertEqual(0, record["confirmed_revision"])
        self.assertNotIn("confirmed_sha256", record)
        self.assertNotIn("confirmed_by", record)
        self.assertNotIn("confirmed_at", record)

    def test_confirmation_rejects_missing_artifacts_atomically(self):
        registered = thaw(self.call().effects[0].payload)
        result = confirm_artifacts(
            registered,
            ("blueprint", "plan"),
            "moonlight",
            "2026-07-30 12:04:00",
        )

        self.assertEqual(2, result.exit_code)
        self.assertIn("plan", result.stderr[0])
        self.assertEqual((), result.effects)


if __name__ == "__main__":
    unittest.main()
