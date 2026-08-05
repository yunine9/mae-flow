#!/usr/bin/env python3
"""Story-centered prompts and retained coding roles."""

import os
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as stream:
        return stream.read()


class Spec2CodePromptResourceTests(unittest.TestCase):
    def test_checkpoint_runtime_and_cp_agent_are_removed(self):
        removed = (
            "flow/steps/build_pace.md",
            "flow/steps/tw_pace.md",
            "flow/steps/rf_pace.md",
            "agents/cp-implementer-agent.md",
            "scripts/mae_flow_core/cli_commands/checkpoint_commands.py",
            "scripts/mae_flow_core/cli_commands/checkpoint_facts.py",
            "scripts/mae_flow_core/cli_commands/checkpoint_plan.py",
            "scripts/mae_flow_core/delivery/checkpoints.py",
            "scripts/mae_flow_core/application/delivery/checkpoints.py",
            "scripts/mae_flow_core/application/delivery/checkpoint_status.py",
            "scripts/mae_flow_core/application/delivery/checkpoint_recovery.py",
            "scripts/mae_flow_core/application/delivery/checkpoint_quality.py",
            "scripts/mae_flow_core/application/delivery/checkpoint_decisions.py",
            "scripts/mae_flow_core/application/delivery/checkpoint_ready_recovery.py",
            "scripts/mae_flow_core/application/delivery/checkpoint_final.py",
        )
        self.assertEqual([], [
            path for path in removed
            if os.path.exists(os.path.join(ROOT, path))
        ])

    def test_comment_standard_is_single_versioned_source(self):
        text = read("runtime/standards/comment-standard-v1.md")
        self.assertIn("新增业务注释统一使用简体中文", text)
        self.assertIn("TODO(<问题单>)", text)
        self.assertIn("单行不超过 120 列", text)
        self.assertIn("逐行翻译代码", text)

    def test_story_and_implementation_companion_replace_heavy_plans(self):
        text = read("agents/story-generator-agent.md")
        self.assertIn("测试设计", text)
        self.assertIn("implementation.md", text)
        self.assertIn("不生成额外的编码前计划过程件", text)
        self.assertFalse(os.path.exists(os.path.join(
            ROOT, "agents", "test-design-agent.md")))
        self.assertFalse(os.path.exists(os.path.join(
            ROOT, "agents", "cp-task-analyst-agent.md")))

    def test_craft_reviewer_is_read_only_and_bounded(self):
        text = read("agents/craft-reviewer-agent.md")
        self.assertIn("每轮最多五条", text)
        self.assertIn("禁止修改源码", text)
        for field in ("位置", "依据", "证据", "实际影响", "最小改法"):
            self.assertIn(field, text)
        self.assertNotIn("TASK_CARD_SHA256", text)

    def test_main_agent_implements_without_implementation_subagent(self):
        self.assertFalse(os.path.exists(os.path.join(
            ROOT, "agents", "implementer-agent.md")))
        build = read("flow/steps/build.md")
        self.assertIn("主 Agent", build)
        self.assertIn("不要派实现子 Agent", build)

    def test_ut_generator_retains_behavior_driven_execution(self):
        text = read("agents/ut-generator-agent.md")
        self.assertIn("禁止重新发明测试场景", text)

    def test_build_prompt_is_one_whole_change_with_optional_precheck(self):
        build = read("flow/steps/build.md")
        self.assertIn("spec.md", build)
        self.assertIn("story.md", build)
        self.assertIn("agent-task compile", build)
        self.assertNotIn("CP", build)
        review = read("flow/steps/build_agent_review.md")
        self.assertIn("role-task code-review", review)
        self.assertIn("不代替用户人工检视", review)

    def test_live_operator_docs_have_no_checkpoint_or_story_commit_protocol(self):
        operator_docs = "\n".join(read(path) for path in (
            "README.md", "MAINTAINERS.md", "FIELD-TEST.md",
            "commands/mae-flow.md", "skills/mae-flow/SKILL.md",
        ))
        for retired in (
                "Staged", "Continuous", "development_review",
                "development_checkpoints", "CP 编号", "每个 CP",
                "CP1", "CP2", "STORY入库",
                "tasks 全部完成", "实现 tasks"):
            with self.subTest(retired=retired):
                self.assertNotIn(retired, operator_docs)

        command = read("commands/mae-flow.md")
        self.assertNotIn("docs/story/STORY-", command)
        self.assertNotIn("用户选择入库", command)
        self.assertNotIn("由你决定是否入库", read("README.md"))
        self.assertNotIn("只给 ASKUSER 令牌", read("MAINTAINERS.md"))


if __name__ == "__main__":
    unittest.main()
