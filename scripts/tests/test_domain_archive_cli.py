#!/usr/bin/env python3
"""CLI contract for the local domain archive."""

import argparse
import os
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.cli_parser import parse_args  # noqa: E402
from mae_flow_core.cli_commands import domain_archive  # noqa: E402


class DomainArchiveCliTests(unittest.TestCase):
    def test_parser_accepts_all_copyable_archive_commands(self):
        commands = (
            ["domain-archive", "prepare", "--domain", "radio", "--keyword", "SUL"],
            ["domain-archive", "prepare", "--unchanged"],
            ["domain-archive", "show"],
            ["domain-archive", "status"],
            ["domain-archive", "apply", "--message-id", "msg-1"],
        )
        for argv in commands:
            with self.subTest(argv=argv):
                self.assertEqual("domain-archive", parse_args(argv).cmd)

    def test_unchanged_can_be_confirmed_and_applied(self):
        state = {
            "current": "domain_archive",
            "config": {"单号": "REQ-1"},
        }
        saved = []
        fake_api = types.SimpleNamespace(
            save_state=lambda value: saved.append(value),
            sh=lambda _command: "",
            _authorization_message=mock.Mock(return_value=(
                True, "确认无需更新领域文档",
                {"message_id": "msg-1", "answer_sha256": "a"}, "")),
            die=lambda message, code=1: (_ for _ in ()).throw(
                RuntimeError("%s:%s" % (code, message))),
        )
        with tempfile.TemporaryDirectory() as root, mock.patch.object(
                domain_archive, "api", fake_api), mock.patch.object(
                domain_archive.os, "getcwd", return_value=root):
            prepared = domain_archive.cmd_domain_archive(
                state, argparse.Namespace(
                    domain_archive_action="prepare", unchanged=True,
                    domain=None, keyword=[]))
            applied = domain_archive.cmd_domain_archive(
                saved[-1], argparse.Namespace(
                    domain_archive_action="apply", message_id="msg-1"))
        self.assertEqual("prepared", prepared["status"])
        self.assertEqual("applied", applied["status"])
        self.assertEqual([], applied["applied_paths"])


if __name__ == "__main__":
    unittest.main()
