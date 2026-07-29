#!/usr/bin/env python3
"""CLI assembly regression for one-shot Gate permits."""

import importlib.util
import json
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


def load_cli():
    path = os.path.join(SCRIPTS, "mae-flow.py")
    spec = importlib.util.spec_from_file_location(
        "mae_flow_guard_permit_integration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PermitIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mf = load_cli()

    def test_valid_format_permit_is_not_replayed_before_branch_check(self):
        command = "git commit -m bad"
        state = {
            "current": "build",
            "config": {
                "单号": "REQ-1",
                "分支名": "feature/req",
                "基线分支": "main",
            },
            "history": [],
        }
        flow = {"steps": {"build": {
            "allow_source_edit": True,
            "allow_specs_write": False,
        }}}
        permit_id = self.mf._gate_block_id(
            "bash-commit-format", command)
        permits = {permit_id: {
            "rule": "bash-commit-format",
            "step": "build",
            "head": "HEAD123",
            "used": False,
        }}
        args = types.SimpleNamespace(what="bash", arg=command)
        with tempfile.TemporaryDirectory() as temporary:
            previous = os.getcwd()
            os.chdir(temporary)
            try:
                with open(
                    self.mf.GATE_PERMITS_PATH,
                    "w",
                    encoding="utf-8",
                ) as stream:
                    json.dump(permits, stream)
                with (
                    mock.patch.object(
                        self.mf, "sh",
                        side_effect=lambda value: (
                            "feature/req"
                            if "branch --show-current" in value
                            else "HEAD123")),
                    mock.patch.object(
                        self.mf, "save_state", return_value=None),
                    mock.patch.object(
                        self.mf, "_checkpoint_locked_item",
                        return_value={}),
                    mock.patch.object(
                        self.mf, "_checkpoint_review_locked",
                        return_value=False),
                    mock.patch.object(
                        self.mf, "_gate_commit_candidates",
                        return_value=None),
                    mock.patch.object(
                        self.mf, "_gate_bash_writes",
                        side_effect=SystemExit(0)),
                ):
                    with self.assertRaises(SystemExit) as raised:
                        self.mf.cmd_gate(flow, state, args)
                self.assertEqual(0, raised.exception.code)
                with open(
                    self.mf.GATE_PERMITS_PATH,
                    encoding="utf-8",
                ) as stream:
                    consumed = json.load(stream)
                self.assertTrue(consumed[permit_id]["used"])
                self.assertFalse(
                    os.path.exists(self.mf.GATE_STRIKES_PATH))
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
