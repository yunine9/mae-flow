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
from mae_flow_core.foundation import git_intent  # noqa: E402
from mae_flow_core.foundation.git_intent import (  # noqa: E402
    git_delivery_intents,
    git_commit_intent,
    git_commit_intents,
)


class GuardIntentTests(unittest.TestCase):
    def test_delivery_execution_predicate_follows_real_wrapper_positions(self):
        executes_delivery = getattr(
            git_intent, "executes_git_commit_or_push", lambda command: False)
        commands = (
            "git push origin HEAD",
            "env FOO=1 command git push origin HEAD",
            "sudo -u root git commit -m update",
            "bash --noprofile -O extglob -c 'git push origin HEAD'",
            "powershell.exe -NoProfile -Command git commit -m update",
            "cmd.exe /d /s /c git push origin HEAD",
            "bash -c \"sh -c 'git commit -m update'\"",
            "cmd /c cmd /c cmd /c cmd /c cmd /c cmd /c git push",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(executes_delivery(command))

    def test_delivery_execution_predicate_rejects_inspection_and_bad_arity(self):
        executes_delivery = getattr(
            git_intent, "executes_git_commit_or_push", lambda command: False)
        commands = (
            "echo git push origin HEAD",
            "command -v git push",
            "sudo -u git push",
            "env printf -S 'git push'",
            "bash --not-a-shell-option -c 'git push'",
            "bash -c git push",
            "powershell.exe -Bogus -Command git push",
            "cmd.exe /bogus /c git push",
            "python -c \"print('git push')\"",
            "cmd /c cmd /c cmd /c cmd /c cmd /c cmd /c cmd /c git push",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertFalse(executes_delivery(command))

    def test_delivery_execution_predicate_respects_sudo_mode_semantics(self):
        executes_delivery = getattr(
            git_intent, "executes_git_commit_or_push", lambda command: False)
        cases = (
            ("sudo -B -E -k -u root git push origin HEAD", True),
            ("sudo --preserve-env --host=build --user=root git commit -m x", True),
            ("sudo -i git push origin HEAD", True),
            ("sudo --shell git commit -m update", True),
            ("sudo -e git push", False),
            ("sudo --edit git commit -m update", False),
            ("sudo -V git push", False),
            ("sudo --version git push", False),
            ("sudo -v git push", False),
            ("sudo --validate git commit -m update", False),
            ("sudo -l git push", False),
            ("sudo --list git commit -m update", False),
            ("sudo -K git push", False),
            ("sudo --remove-timestamp git commit -m update", False),
            ("sudo --help git push", False),
            ("sudo --user git push", False),
        )
        for command, expected in cases:
            with self.subTest(command=command):
                self.assertIs(expected, executes_delivery(command))

    def test_delivery_execution_predicate_uses_launcher_specific_shell_options(self):
        executes_delivery = getattr(
            git_intent, "executes_git_commit_or_push", lambda command: False)
        cases = {
            "sh": (
                ("sh -eu -o errexit -c 'git push origin HEAD'", True),
                ("sh -o -c 'git push origin HEAD'", False),
                ("sh --help -c 'git push origin HEAD'", False),
            ),
            "bash": (
                ("bash --noprofile -O extglob -c 'git commit -m update'", True),
                ("bash -o errexit -c 'git push origin HEAD'", True),
                ("bash -l -c 'git push origin HEAD'", True),
                ("bash -O -c 'git push origin HEAD'", False),
                ("bash -oerrexit -c 'git push origin HEAD'", False),
                ("bash --init-command ready -c 'git push origin HEAD'", False),
            ),
            "zsh": (
                ("zsh -o SH_WORD_SPLIT -c 'git push origin HEAD'", True),
                ("zsh -oSH_WORD_SPLIT -c 'git push origin HEAD'", True),
                ("zsh -l -c 'git commit -m update'", True),
                ("zsh -o -c 'git push origin HEAD'", False),
                ("zsh --noprofile -c 'git push origin HEAD'", False),
            ),
            "fish": (
                ("fish -C 'echo ready' -c 'git push origin HEAD'", True),
                ("fish --init-command='echo ready' --command='git commit -m update'", True),
                ("fish -C 'git push origin HEAD' -c 'echo ready'", True),
                ("fish --init-command='git commit -m x' --command='echo ready'", True),
                ("fish -c 'git push origin HEAD' arg0", True),
                ("fish -C -c 'git push origin HEAD'", False),
                ("fish -O extglob -c 'git push origin HEAD'", False),
                ("fish --version -c 'git push origin HEAD'", False),
                ("fish -c 'echo ready' arg0 -c 'git push origin HEAD'", False),
            ),
        }
        for launcher, launcher_cases in cases.items():
            for command, expected in launcher_cases:
                with self.subTest(launcher=launcher, command=command):
                    self.assertIs(expected, executes_delivery(command))

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

    def test_delivery_intents_preserve_ordinary_and_opaque_source_order(self):
        command = (
            "git commit -a -m first && "
            "git add --pathspec-from-file=paths.txt && "
            "git add src/a.py && "
            "git commit -m second && "
            "git push origin main"
        )

        intents = git_delivery_intents(command)

        self.assertEqual(
            [
                ("commit", False, (), True, False),
                ("add", True, (), False, False),
                ("add", False, ("src/a.py",), False, False),
                ("commit", False, (), False, False),
                ("push", False, (), False, False),
            ],
            [
                (
                    intent.operation,
                    intent.opaque_pathspec,
                    intent.pathspecs,
                    intent.all,
                    intent.include,
                )
                for intent in intents
            ],
        )


if __name__ == "__main__":
    unittest.main()
