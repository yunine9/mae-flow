#!/usr/bin/env python3
"""quality-artifact CLI 路由与状态适配回归。"""

import os
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from io import StringIO


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from mae_flow_core.cli_parser import parse_args  # noqa: E402
from mae_flow_core.cli_commands import quality_artifacts  # noqa: E402
from mae_flow_core.cli_commands.wiring import api  # noqa: E402
from test_spec2code_artifacts import BLUEPRINT  # noqa: E402


class QualityArtifactCliTests(unittest.TestCase):
    def test_parser_accepts_register_and_show(self):
        args = parse_args([
            "quality-artifact",
            "register",
            "blueprint",
            ".mae-flow-work/test-blueprint-REQ-1.md",
        ])
        self.assertEqual("register", args.quality_action)
        self.assertEqual("blueprint", args.kind)
        self.assertEqual(
            "show",
            parse_args(["quality-artifact", "show"]).quality_action,
        )
        presented = parse_args([
            "quality-artifact", "present", "blueprint",
        ])
        self.assertEqual("present", presented.quality_action)
        self.assertEqual("blueprint", presented.kind)

    def test_register_saves_spec2code_state(self):
        original_save = getattr(api, "save_state", None)
        saved = []
        try:
            api.save_state = lambda state: saved.append(dict(state))
            with tempfile.TemporaryDirectory() as root:
                work = os.path.join(root, ".mae-flow-work")
                os.makedirs(work)
                path = os.path.join(work, "test-blueprint-REQ-1.md")
                with open(path, "w", encoding="utf-8") as stream:
                    stream.write(BLUEPRINT)
                old = os.getcwd()
                os.chdir(root)
                try:
                    args = types.SimpleNamespace(
                        quality_action="register",
                        kind="blueprint",
                        path=path,
                    )
                    output = StringIO()
                    with redirect_stdout(output):
                        quality_artifacts.cmd_quality_artifact(
                            {},
                            {"config": {"单号": "REQ-1"}},
                            args,
                        )
                finally:
                    os.chdir(old)
            self.assertEqual(1, len(saved))
            self.assertIn("本地过程件，不入库", output.getvalue())
            self.assertIn("blueprint", saved[0]["spec2code"])
        finally:
            if original_save is not None:
                api.save_state = original_save


if __name__ == "__main__":
    unittest.main()
