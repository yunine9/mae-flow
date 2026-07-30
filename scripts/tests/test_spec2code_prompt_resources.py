#!/usr/bin/env python3
"""Spec2Code 固定 Prompt 与注释规范资源回归。"""

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

    def test_test_design_agent_only_designs_behavior(self):
        text = read("agents/test-design-agent.md")
        self.assertIn("TEST_DESIGN_RESULT:", text)
        self.assertIn("禁止写测试代码", text)
        self.assertIn("禁止确定测试文件", text)

    def test_task_analyst_requires_exact_code_landing(self):
        text = read("agents/cp-task-analyst-agent.md")
        self.assertIn("TASK_ANALYSIS_RESULT:", text)
        self.assertIn("目标类、函数或接口", text)
        self.assertIn("注释计划", text)

    def test_craft_reviewer_is_read_only_and_bounded(self):
        text = read("agents/craft-reviewer-agent.md")
        self.assertIn("CRAFT_REVIEW_RESULT:", text)
        self.assertIn("每轮最多五条", text)
        self.assertIn("禁止修改源码", text)
        for field in ("位置", "依据", "证据", "实际影响", "最小改法"):
            self.assertIn(field, text)

    def test_cp_implementer_stops_at_checkpoint_boundary(self):
        text = read("agents/cp-implementer-agent.md")
        self.assertIn("CP_IMPLEMENT_RESULT:", text)
        self.assertIn("只允许修改任务卡", text)
        self.assertIn("NEEDS_INPUT", text)


if __name__ == "__main__":
    unittest.main()
