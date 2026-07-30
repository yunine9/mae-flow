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

    def test_ut_generator_executes_blueprint_instead_of_redesigning_it(self):
        text = read("agents/ut-generator-agent.md")
        self.assertIn("BLUEPRINT_SHA256:", text)
        self.assertIn("BLUEPRINT_MAPPING:", text)
        self.assertIn("禁止重新发明测试场景", text)

    def test_build_prompts_use_registered_plan_and_role_loops(self):
        blueprint = read("flow/steps/test_blueprint.md")
        self.assertIn(
            "quality-artifact present blueprint",
            blueprint,
        )
        planning = read("flow/steps/build_plan.md")
        roadmap_register = planning.index(
            "quality-artifact register roadmap")
        analyst = planning.index("role-task task-analysis")
        plan_register = planning.index("quality-artifact register plan")
        reviewer = planning.index("role-task craft-plan")
        self.assertLess(roadmap_register, analyst)
        self.assertLess(analyst, plan_register)
        self.assertLess(plan_register, reviewer)
        self.assertIn("quality-artifact present plan", planning)
        pace = read("flow/steps/build_pace.md")
        self.assertIn("--roadmap", pace)
        self.assertIn("--plan", pace)
        build = read("flow/steps/build.md")
        self.assertIn("role-task cp-implement", build)
        self.assertIn("role-task craft-code", build)
        self.assertIn("checkpoint craft-reviewed", build)
        self.assertIn("Comment Standard v1", build)


if __name__ == "__main__":
    unittest.main()
