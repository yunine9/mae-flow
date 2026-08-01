#!/usr/bin/env python3
"""Tests for pure Gate request parsing."""

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.guard.intent import (  # noqa: E402
    BranchCommand,
    hits_path,
    parse_intent,
    recursive_delete_targets,
)
from mae_flow_core.foundation.git_intent import (  # noqa: E402
    git_commit_intent,
    git_commit_intents,
)


class GuardIntentTests(unittest.TestCase):
    def test_parse_normalizes_slashes_and_tokenizes_bash_paths(self):
        intent = parse_intent(
            "bash",
            r'sed -i "x" src\main.cpp && git status',
        )
        self.assertEqual(
            'sed -i "x" src/main.cpp && git status',
            intent.subject,
        )
        self.assertEqual(
            ("sed", "-i", "x", "src/main.cpp", "git", "status"),
            intent.tokens,
        )
        self.assertTrue(hits_path(intent, r"(^|/)src/"))

    def test_edit_intent_keeps_no_command_tokens(self):
        intent = parse_intent("edit", r"src\main.cpp")
        self.assertEqual("src/main.cpp", intent.subject)
        self.assertEqual((), intent.tokens)

    def test_branch_command_distinguishes_creation_and_recovery(self):
        self.assertEqual(
            BranchCommand("feature/x", True),
            parse_intent(
                "bash", "git switch -c feature/x").branch,
        )
        self.assertEqual(
            BranchCommand("", False),
            parse_intent(
                "bash", "git checkout HEAD -- src/main.cpp").branch,
        )
        self.assertEqual(
            BranchCommand("main", False),
            parse_intent("bash", "git switch main").branch,
        )

    def test_recursive_delete_targets_only_inspects_delete_segment(self):
        self.assertEqual(
            (),
            recursive_delete_targets(parse_intent(
                "bash",
                "rm -rf build && cmake -S . -B build",
            )),
        )
        self.assertEqual(
            (".",),
            recursive_delete_targets(parse_intent(
                "bash",
                "git status && rm -rf .",
            )),
        )
        self.assertEqual(
            ("C:/",),
            recursive_delete_targets(parse_intent(
                "bash",
                "rd /s C:\\",
            )),
        )

    def test_commit_intents_preserve_every_invocation_in_shell_order(self):
        command = (
            "git commit -am first && "
            "git commit --include src/a.py -m second && "
            "git commit -m third"
        )

        intents = git_commit_intents(command)

        self.assertEqual(
            [
                {"pathspecs": [], "all": True, "include": False},
                {
                    "pathspecs": ["src/a.py"],
                    "all": False,
                    "include": True,
                },
                {"pathspecs": [], "all": False, "include": False},
            ],
            intents,
        )
        self.assertEqual(intents[-1], git_commit_intent(command))


if __name__ == "__main__":
    unittest.main()
