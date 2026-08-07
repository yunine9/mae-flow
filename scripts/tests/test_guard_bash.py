#!/usr/bin/env python3
"""Pure general Bash/Git Gate policy tests."""

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.guard.bash import (  # noqa: E402
    BashGateContext,
    decide_commit_branch,
    decide_post_commit,
    decide_pre_commit,
)


class BashGatePolicyTests(unittest.TestCase):
    def context(self, **overrides):
        values = {
            "command": "git status",
            "has_internal_state_path": False,
            "branch_name": "",
            "branch_creating": False,
            "step": "build",
            "wanted_branch": "feature/req",
            "base_branch": "main",
            "ticket": "REQ-1",
            "commit_message_present": False,
            "commit_message": "",
            "current_branch": "",
            "add_paths": (),
            "recursive_delete_targets": (),
            "state_active": True,
        }
        values.update(overrides)
        return BashGateContext(**values)

    def test_pre_commit_preserves_absolute_and_permit_classes(self):
        internal = decide_pre_commit(self.context(
            has_internal_state_path=True))
        self.assertEqual("absolute", internal.kind)
        # 分支命名约定已退役(错了可改名);切分支本身不再被拦。
        self.assertEqual(
            "allow",
            decide_pre_commit(self.context(branch_name="wrong")).kind)
        wide = decide_pre_commit(self.context(command="git add -A"))
        self.assertEqual("absolute", wide.kind)

    def test_commit_format_and_branch_are_checked_before_ownership(self):
        fmt = decide_pre_commit(self.context(
            command="git commit -m bad",
            commit_message_present=True,
            commit_message="bad"))
        self.assertEqual(("block", "bash-commit-format"),
                         (fmt.kind, fmt.rule))
        branch = decide_commit_branch(self.context(
            command="git commit -m '[REQ-1][fix]ok'",
            commit_message_present=True,
            commit_message="[REQ-1][fix]ok",
            current_branch="wrong"))
        self.assertEqual(("block", "bash-commit-branch"),
                         (branch.kind, branch.rule))

    def test_post_commit_blocks_force_push_and_destructive_actions(self):
        force = decide_post_commit(self.context(
            command="git push --force"))
        self.assertEqual("absolute", force.kind)
        leased_force = decide_post_commit(self.context(
            command="sh -c 'git push --force-with-lease origin HEAD'"))
        self.assertEqual("absolute", leased_force.kind)
        wipe = decide_post_commit(self.context(
            command="git reset --hard"))
        self.assertEqual(("block", "bash-wipe-worktree"),
                         (wipe.kind, wipe.rule))
        recursive = decide_post_commit(self.context(
            command="rm -rf .",
            recursive_delete_targets=(".",)))
        self.assertEqual("absolute", recursive.kind)


if __name__ == "__main__":
    unittest.main()
