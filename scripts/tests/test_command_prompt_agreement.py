#!/usr/bin/env python3
"""Every runnable command shown to an Agent agrees with the real parser."""

import glob
import os
import re
import shlex
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.cli_parser import parse_args  # noqa: E402
from mae_flow_core.workflow.command_catalog import (  # noqa: E402
    catalog_ids,
    render_command,
)


CONTEXT = {
    "file": "src/a.cpp", "message": "feat: A", "target": "main",
    "message_id": "msg-1", "scope": "本次修改",
}


def resource_commands():
    patterns = [
        "flow/steps/*.md", "agents/*.md", "runtime/guidance/*.md",
        "skills/mae-flow/**/*.md",
    ]
    for pattern in patterns:
        for path in glob.glob(os.path.join(ROOT, pattern), recursive=True):
            with open(path, encoding="utf-8") as stream:
                content = stream.read()
            for command in re.findall(
                    r'`python (?:"\{MAEFLOW_PATH\}"|\{MAEFLOW_PATH\}) ([^`]+)`',
                    content):
                command = re.sub(r"\s*\[[^]]+\]", "", command)
                command = re.sub(
                    r"<[^>]+>|\{[^}]+\}|CPn|第N批", "VALUE", command)
                yield os.path.relpath(path, ROOT), command


class CommandPromptAgreementTests(unittest.TestCase):
    def test_every_catalog_command_is_built_then_parsed(self):
        for command_id in catalog_ids():
            with self.subTest(command=command_id):
                argv = render_command(command_id, CONTEXT)
                self.assertEqual(argv[0], parse_args(argv).cmd)

    def test_every_runnable_operational_resource_command_parses(self):
        commands = list(resource_commands())
        self.assertGreater(len(commands), 30)
        for resource, command in commands:
            with self.subTest(resource=resource, command=command):
                try:
                    parse_args(shlex.split(command))
                except SystemExit as exc:
                    self.fail("不可执行命令(%s): %s (exit %s)" % (
                        resource, command, exc.code))

    def test_retired_lean_advance_commands_are_never_emitted(self):
        for resource, command in resource_commands():
            with self.subTest(resource=resource):
                self.assertNotRegex(
                    command, r"^(?:advance|decision)\s+(?:capability\.|grill-)")


if __name__ == "__main__":
    unittest.main()
