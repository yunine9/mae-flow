#!/usr/bin/env python3
"""Story-centered prompts and retained coding roles."""

import os
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as stream:
        return stream.read()


class Spec2CodePromptResourceTests(unittest.TestCase):
    def test_comment_standard_is_single_versioned_source(self):
        text = read("runtime/standards/comment-standard-v1.md")
        self.assertIn("新增业务注释统一使用简体中文", text)
        self.assertIn("TODO(<问题单>)", text)
        self.assertIn("单行不超过 120 列", text)
        self.assertIn("逐行翻译代码", text)

    def test_story_absorbs_test_design_and_light_cp_boundaries(self):
        text = read("agents/story-generator-agent.md")
        self.assertIn("测试设计", text)
        self.assertIn("CP", text)
        self.assertIn("不生成 Roadmap", text)
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

    def test_cp_implementer_stops_at_checkpoint_boundary(self):
        text = read("agents/cp-implementer-agent.md")
        self.assertIn("只允许修改任务卡", text)
        self.assertIn("NEEDS_INPUT", text)

    def test_ut_generator_retains_behavior_driven_execution(self):
        text = read("agents/ut-generator-agent.md")
        self.assertIn("禁止重新发明测试场景", text)

    def test_build_prompts_use_story_cp_and_existing_checkpoint_runtime(self):
        pace = read("flow/steps/build_pace.md")
        self.assertIn("checkpoint plan --item", pace)
        self.assertNotIn("--roadmap", pace)
        build = read("flow/steps/build.md")
        self.assertIn("role-task cp-implement", build)
        self.assertIn("Staged", build)
        self.assertIn("Continuous", build)
        self.assertNotIn("role-task task-analysis", build)
        self.assertNotIn("role-task craft-plan", build)


if __name__ == "__main__":
    unittest.main()
