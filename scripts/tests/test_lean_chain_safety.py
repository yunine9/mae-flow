#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pure Hook safety contracts while a Chain workflow owns the anchor."""

import os
import sys
import tempfile
import unittest


SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.guard.chain_safety import decide_chain_pretool  # noqa: E402
from mae_flow_core.orchestration import ChainState  # noqa: E402


class LeanChainSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = self.temporary.name
        self.document = ".mae-flow-work/REQ/chain.md"
        self.state = ChainState(
            ticket="REQ", request="cross repository", requirement_source="r.md",
            anchor_root=self.root, document_path=self.document,
        )

    def decide(self, tool, tool_input):
        return decide_chain_pretool(self.root, self.state, tool, tool_input)

    def test_only_the_exact_chain_document_accepts_direct_writes(self):
        for tool, path in (
                ("Write", self.document),
                ("Edit", os.path.join(self.root, *self.document.split("/"))),
                ("MultiEdit", self.document)):
            with self.subTest(tool=tool):
                self.assertTrue(self.decide(tool, {"file_path": path}).allow)

        for path in ("src/service.py", "docs/other.md", "../sibling/code.py"):
            with self.subTest(path=path):
                decision = self.decide("Write", {"file_path": path})
                self.assertFalse(decision.allow)
                self.assertEqual("chain_write_scope", decision.rule)

    def test_bash_read_only_inspection_and_exact_document_write_are_allowed(self):
        read = self.decide("Bash", {"command": "rg Contract src"})
        document = self.decide(
            "Bash", {"command": "printf '# Chain' > %s" % self.document})

        self.assertTrue(read.allow)
        self.assertTrue(document.allow)

    def test_delete_and_git_effects_are_blocked(self):
        cases = (
            "rm -rf build",
            "rm %s" % self.document,
            "git add src/a.py",
            "git commit -m update",
            "git push origin main",
            "git reset --hard HEAD~1",
            "git checkout -- src/a.py",
        )
        for command in cases:
            with self.subTest(command=command):
                decision = self.decide("Bash", {"command": command})
                self.assertFalse(decision.allow)


if __name__ == "__main__":
    unittest.main()
