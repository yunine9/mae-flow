#!/usr/bin/env python3
"""Story is the sole reviewed pre-code design artifact."""

import json
import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.workflow.transitions import workflow_chain  # noqa: E402


def read(relative):
    with open(os.path.join(ROOT, relative), encoding="utf-8") as stream:
        return stream.read()


class StoryContractTests(unittest.TestCase):
    def test_full_path_uses_grill_local_spec_story_and_pace_directly(self):
        flow = json.loads(read("flow/flow.json"))
        chain = workflow_chain(flow, "full")
        ordered = ["grill", "open", "story", "build_pace", "build"]
        self.assertEqual(ordered, [step for step in chain if step in ordered])
        for removed in (
                "grill_ask", "design", "test_blueprint",
                "story_ask", "build_plan"):
            self.assertNotIn(removed, chain)
        self.assertEqual("story", flow["steps"]["open"]["next"])
        self.assertEqual("build_pace", flow["steps"]["story"]["next"])

    def test_story_template_has_approved_semantic_sections(self):
        template = read("skills/mae-flow/assets/STORY-TEMPLATE.md")
        sections = (
            "业务目标与范围",
            "Grill 决策与未决项",
            "可观察行为与验收条件",
            "性能规格",
            "对外及跨组件接口设计",
            "关键函数与方法修改详述",
            "数据与兼容性",
            "测试设计",
            "CP 划分与轻量实施说明",
            "风险、回滚与领域文档影响",
        )
        positions = [template.index(section) for section in sections]
        self.assertEqual(sorted(positions), positions)
        self.assertIn("仅填写容量、时延、吞吐、并发或资源上限", template)
        self.assertIn("REST、CORBA", template)

    def test_story_generator_requires_exact_local_inputs(self):
        generator = read("agents/story-generator-agent.md")
        for required in (
                "spec.md", "grill.md", "docs/specs/index.md",
                "STORY-TEMPLATE.md", "代码路径"):
            self.assertIn(required, generator)
        self.assertNotIn("openspec/changes", generator)
        self.assertNotIn("STORY_RESULT:", generator)
        self.assertIn(".mae-flow-work/<单号>/story.md", generator)

    def test_story_reviewer_runs_once_without_digest_reentry(self):
        flow = json.loads(read("flow/flow.json"))
        evidence = flow["steps"]["story"]["evidence"]
        self.assertIn("REVIEWER", [
            item.get("agent") for item in evidence
            if item.get("type") == "agent_ran"])
        reviewer = read("agents/craft-reviewer-agent.md")
        self.assertIn("Story 设计检视", reviewer)
        self.assertIn("只执行一次", reviewer)
        for forbidden in (
                "TASK_CARD_SHA256", "审查目标 SHA256",
                "CRAFT_REVIEW_RESULT:", "文件变化后重新检视"):
            self.assertNotIn(forbidden, reviewer)

    def test_only_seven_approved_agents_remain(self):
        expected = {
            "grill-critic-agent.md",
            "story-generator-agent.md",
            "craft-reviewer-agent.md",
            "cp-implementer-agent.md",
            "compile-agent.md",
            "codecheck-fix-agent.md",
            "ut-generator-agent.md",
        }
        actual = {
            name for name in os.listdir(os.path.join(ROOT, "agents"))
            if name.endswith("-agent.md")
        }
        self.assertEqual(expected, actual)

    def test_pace_is_user_selected_and_cp_stops_are_deterministic(self):
        pace = read("flow/steps/build_pace.md")
        build = read("flow/steps/build.md")
        self.assertIn("用户选择是唯一依据", pace)
        self.assertIn("Staged：每个 CP", build)
        self.assertIn("Continuous：所有 CP", build)
        self.assertNotIn("roadmap-", pace)
        self.assertNotIn("plan-", pace)
        self.assertNotIn("role-task task-analysis", build)
        self.assertNotIn("role-task craft-plan", build)


if __name__ == "__main__":
    unittest.main()
