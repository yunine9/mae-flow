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

    def test_code_taste_baseline_exists_and_has_consumers(self):
        """标准文件必须有生产消费者——comment-standard 曾无人引用地躺了一个月。"""
        taste = read("runtime/standards/code-taste-v1.md")
        for marker in ("顺应优先于自包含", "按概念拆", "投机的灵活性",
                       "目标状态", "不是门禁", "改动收口", "最小改动面",
                       "每条离开路径", "依赖方向", "编译通过 ≠ 适配完整",
                       "复用靠调用，不靠粘贴", "副作用会随复制翻倍"):
            self.assertIn(marker, taste)
        # 完整性收口必须三处闭环:写码纪律、基准、reviewer 独立核对
        self.assertIn("改动收口", read("flow/steps/build.md"))
        self.assertIn(
            "独立 grep", read("agents/craft-reviewer-agent.md"))
        self.assertIn(
            "非编译文件", read("agents/craft-reviewer-agent.md"))
        self.assertIn(
            "副作用随复制翻倍", read("agents/craft-reviewer-agent.md"))
        build = read("flow/steps/build.md")
        self.assertIn("standards/code-taste-v1.md", build)
        self.assertIn("comment-standard-v1.md", build)
        self.assertIn("四项自查", build)
        reviewer = read("agents/craft-reviewer-agent.md")
        self.assertIn("code-taste-v1.md", reviewer)
        self.assertIn("品味问题与正确性问题同级", reviewer)
        construction = read("runtime/guidance/construction.md")
        self.assertIn("code-taste-v1.md", construction)
        # 物化清单里必须有,否则项目本地路径是死链接
        runtime_source = read("scripts/mae_flow_core/cli_runtime.py")
        self.assertIn("standards/code-taste-v1.md", runtime_source)
        self.assertIn("standards/comment-standard-v1.md", runtime_source)

    def test_build_chunk_discipline_is_in_context_only(self):
        """分块是同一上下文内的纪律,不得回退成流程批次(那是 CP 被退掉的原因)。"""
        build = read("flow/steps/build.md")
        self.assertIn("分块纪律", build)
        self.assertIn("implementation.md", build)
        self.assertIn("不编译、不 done、不询问用户", build)
        self.assertIn("跨块漂移", build)
        # 反回退:仍然是一步、一次编译、无实现子 Agent、无批次文档
        self.assertIn("一次完成需求涉及的全部生产代码", build)
        self.assertIn("不要拆开发批次", build)
        # 子 Agent 边界:设计不外包;只读侦察与机械扇出是仅有的两类合法用法,
        # 且扇出产出不免检——放宽永远不得放宽到"实现整体外包"。
        self.assertIn("设计承载的代码不外包", build)
        self.assertIn("只读侦察", build)
        self.assertIn("机械扇出", build)
        self.assertIn("不免检", build)
        self.assertIn("已亲写第一个完整样例", build)
        # 工单携带上下文而不是指向上下文——子 Agent 重建上下文正是 CP 被退掉的主因
        self.assertIn("自包含", build)
        self.assertIn("不要读 spec/story/领域文档", build)

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
        self.assertIn("设计承载的代码不外包", build)

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

    def test_compile_risk_recovery_has_no_retired_cp_or_commit_first_hint(self):
        text = read("scripts/mae_flow_core/cli_commands/done_status.py")
        self.assertNotIn("分段编译风险确认", text)
        self.assertNotIn("精确提交当前修复，再执行 done", text)
        self.assertIn("重新执行 agent-task compile", text)

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
