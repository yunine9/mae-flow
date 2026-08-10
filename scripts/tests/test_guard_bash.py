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


class HeredocCommitMessageTests(unittest.TestCase):
    """多行提交信息走 heredoc 是通用写法,不该被当成不合规。

    实战:模型写了 `git commit -m "$(cat <<'EOF' … EOF)"`,格式完全正确,
    却被 bash-commit-format 拦下——因为拿到的是 `$(cat <<'EOF'\\n…` 整串。
    与编译证据那次同源:拿 shell 原文去比对语义值,迟早误伤。
    """

    def test_heredoc_body_is_what_gets_checked(self):
        from mae_flow_core.foundation import git_intent
        command = (
            'git commit -m "$(cat <<\'EOF\'\n'
            "[REQ2026080901][feat]新增短信通知渠道与失败重试机制\n"
            "\n正文若干\nEOF\n)\"")
        present, message = git_intent.git_commit_message(command)
        self.assertTrue(present)
        self.assertTrue(message.startswith("[REQ2026080901][feat]"))
        self.assertIn("正文若干", message)

    def test_plain_message_is_untouched(self):
        from mae_flow_core.foundation import git_intent
        for command, expected in (
                ('git commit -m "[REQ-1][fix]单行"', "[REQ-1][fix]单行"),
                ('git commit --message="[REQ-1][feat]等号形式"',
                 "[REQ-1][feat]等号形式"),
                ('git commit -m"[REQ-1][feat]紧贴形式"',
                 "[REQ-1][feat]紧贴形式")):
            self.assertEqual((True, expected),
                             git_intent.git_commit_message(command))


class CommitBeforeBranchExistsTests(unittest.TestCase):
    """分支名定下来之后,不许把本单提交落在基线分支上。

    实战(无人值守):跑到 workflow_select(第 3 步)时,模型把整个需求写完、提交、
    推送——三个提交全落在基线分支 sim_liaoxiang_base 上,branch_create 压根没跑过。
    没人拦是因为提交分支检查对启动阶段的四个步骤显式开了天窗,而"build 之前
    不许写源码"这件事门禁从来不执行(allow_source_edit 没有任何判据读它)。
    提交这一关是最后的拦阻点,不能也开天窗。
    """

    def _context(self, step, current, wanted):
        from mae_flow_core.guard.bash import BashGateContext
        return BashGateContext(
            command='git commit -m "[REQ-1][feat]x"',
            has_internal_state_path=False, branch_name="",
            branch_creating=False, step=step, wanted_branch=wanted,
            base_branch="master", ticket="REQ-1",
            commit_message_present=True,
            commit_message="[REQ-1][feat]x",
            current_branch=current, add_paths=(),
            recursive_delete_targets=(), state_active=True)

    def test_startup_steps_no_longer_get_a_free_pass(self):
        from mae_flow_core.guard.bash import decide_commit_branch
        for step in ("config_confirm", "workflow_select",
                     "code_reviewer_ask", "branch_create"):
            decision = decide_commit_branch(
                self._context(step, "master", "master_liao_REQ-1"))
            self.assertEqual("block", decision.kind,
                             "%s 上提交到基线分支必须拦" % step)
            self.assertIn("别把本单提交落在基线分支上", decision.message)

    def test_no_branch_name_yet_still_allowed(self):
        """分支名还没定(配置确认前)本来就没法比对,照旧放行。"""
        from mae_flow_core.guard.bash import decide_commit_branch
        self.assertEqual("allow", decide_commit_branch(
            self._context("config_confirm", "master", "")).kind)

    def test_on_the_agreed_branch_is_allowed(self):
        from mae_flow_core.guard.bash import decide_commit_branch
        self.assertEqual("allow", decide_commit_branch(
            self._context("build_commit", "master_liao_REQ-1",
                          "master_liao_REQ-1")).kind)
