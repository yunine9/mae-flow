#!/usr/bin/env python3
"""Behavioral contract between capability prompts and the production CLI."""

import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core import cli_parser  # noqa: E402
from mae_flow_core.orchestration import capabilities  # noqa: E402
from mae_flow_core.orchestration import (  # noqa: E402
    CommitPace,
    DeliveryPath,
    FlowState,
)


ENTRYPOINT = os.path.join(SCRIPTS, "mae-flow.py")
CORRECTION = (
    'advance capability-returned --key grill '
    '--decision "<简短不透明摘要>"'
)


class CapabilityCommandRenderingTests(unittest.TestCase):
    def test_every_rendered_kind_and_outcome_parses_as_the_real_advance_api(self):
        render = getattr(capabilities, "capability_record_command", None)
        self.assertIsNotNone(render, "缺少统一能力命令渲染器")
        for kind in (
                "build", "ut", "codecheck", "reviewer", "grill", "story"):
            for outcome in (
                    "returned", "failed-to-start", "timed-out", "not-observed"):
                with self.subTest(kind=kind, outcome=outcome):
                    command = render(kind, outcome, "不透明同步返回")
                    arguments = shlex.split(command)[2:]
                    parsed = cli_parser.parse_args(arguments)
                    self.assertEqual("advance", parsed.cmd)
                    self.assertEqual("capability-" + outcome, parsed.event)
                    self.assertEqual(kind, parsed.key)
                    self.assertEqual("不透明同步返回", parsed.decision)


class CapabilityErrorRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = self.temporary.name
        state = FlowState.new(
            "REQ-CAPABILITY-ERROR",
            DeliveryPath.FULL,
            CommitPace.CONTINUOUS,
        )
        with open(os.path.join(self.root, ".mae-flow.json"),
                  "w", encoding="utf-8") as stream:
            json.dump(state.to_dict(), stream, ensure_ascii=False)

    def tearDown(self):
        self.temporary.cleanup()

    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, ENTRYPOINT, *arguments],
            cwd=self.root,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
            check=False,
        )

    def test_capability_alias_errors_print_the_exact_correction(self):
        attempts = (
            ("advance", "grill-critic-attempt"),
            ("advance", "capability.grill-critic"),
            ("advance", "capability-attempt", "--key", "grill"),
            ("advance", "capability.grill-critic", "--note", "done"),
        )
        for arguments in attempts:
            with self.subTest(arguments=arguments):
                result = self.run_cli(*arguments)
                output = result.stdout + result.stderr
                self.assertEqual(2, result.returncode, output)
                self.assertIn(CORRECTION, output)
                self.assertIn(
                    "build、ut、codecheck、reviewer、grill、story", output)


if __name__ == "__main__":
    unittest.main()
