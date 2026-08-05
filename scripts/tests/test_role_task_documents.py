#!/usr/bin/env python3
"""Spec2Code 角色化任务卡渲染回归。"""

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from mae_flow_core.application.quality.role_task_documents import (  # noqa: E402
    ArtifactRef,
    RoleTaskContext,
    build_role_task_document,
)


ARTIFACTS = {
    "blueprint": ArtifactRef(
        "/repo/.mae-flow-work/test-blueprint-REQ-1.md",
        "a" * 64,
    ),
    "roadmap": ArtifactRef(
        "/repo/.mae-flow-work/roadmap-REQ-1.md",
        "b" * 64,
    ),
    "plan": ArtifactRef(
        "/repo/.mae-flow-work/plan-REQ-1.md",
        "c" * 64,
    ),
}


def build(role, artifacts=ARTIFACTS):
    return build_role_task_document(
        role=role,
        project_root="/repo",
        ticket="REQ-1",
        checkpoint="CP1",
        context=RoleTaskContext(
            artifacts=artifacts,
            files=("src/service.py",),
            context_paths=(
                "/repo/docs/requirement.md",
                "/repo/.mae-flow-work/survey-REQ-1.md",
            ),
            diff="""文件清单:
- src/service.py
补丁:
diff --git a/src/service.py b/src/service.py
""",
            review_output=(
                "/repo/.mae-flow-work/reviews/REQ-1/CP1-code.md"),
            review_target_sha256="d" * 64,
            write_output="/repo/.mae-flow-work/plan-REQ-1.md",
            companion_output="/repo/.mae-flow-work/REQ-1/implementation.md",
        ),
    ).body()


class RoleTaskDocumentTests(unittest.TestCase):
    def test_each_role_has_scoped_inputs_and_output_contract(self):
        roles = (
            "test-design", "task-analysis", "craft-plan", "cp-implement",
            "craft-code", "story-generate", "story-review", "grill-critic",
        )
        for role in roles:
            with self.subTest(role=role):
                body = build(role)
                self.assertIn("任意自然语言格式", body)
                self.assertNotIn("_RESULT:", body)
                self.assertNotIn("TASK_CARD_SHA256", body)
                self.assertNotIn("聊天记录", body)

    def test_story_roles_receive_local_spec_grill_story_and_domain_context(self):
        context = RoleTaskContext(
            artifacts={},
            context_paths=(
                "/repo/.mae-flow-work/REQ-1/spec.md",
                "/repo/.mae-flow-work/REQ-1/grill.md",
                "/repo/.mae-flow-work/REQ-1/story.md",
                "/repo/.mae-flow-work/REQ-1/implementation.md",
                "/repo/docs/specs/radio.md",
                "/repo/.mae-flow-work/plugin-resources/assets/STORY-TEMPLATE.md",
                "/repo/.mae-flow-work/plugin-resources/assets/IMPLEMENTATION-TEMPLATE.md",
            ),
            write_output="/repo/.mae-flow-work/REQ-1/story.md",
            companion_output="/repo/.mae-flow-work/REQ-1/implementation.md",
        )
        generated = build_role_task_document(
            role="story-generate", project_root="/repo", ticket="REQ-1",
            checkpoint="", context=context).body()
        reviewed = build_role_task_document(
            role="story-review", project_root="/repo", ticket="REQ-1",
            checkpoint="", context=context).body()
        self.assertIn("仅允许写入", generated)
        self.assertIn("/repo/.mae-flow-work/REQ-1/story.md", generated)
        self.assertIn("/repo/.mae-flow-work/REQ-1/implementation.md", generated)
        self.assertIn("只读", reviewed)
        self.assertIn("只执行一次", reviewed)

    def test_grill_critic_is_read_only_and_stage_is_explicit(self):
        body = build_role_task_document(
            role="grill-critic", project_root="/repo", ticket="REQ-1",
            checkpoint="prep",
            context=RoleTaskContext(
                artifacts={},
                context_paths=(
                    "/repo/.mae-flow-work/grill-prep-REQ-1.md",
                    "/repo/.mae-flow-work/REQ-1/grill.md",
                ),
            ),
        ).body()
        self.assertIn("质询检查阶段: prep", body)
        self.assertIn("只读", body)
        self.assertIn("禁止修改任何文件", body)

    def test_implementer_receives_comment_standard_and_allowed_files(self):
        body = build("cp-implement")
        self.assertIn("runtime/standards/comment-standard-v1.md", body)
        self.assertIn("允许修改:\n- src/service.py", body)
        self.assertIn("注释计划", body)
        self.assertIn("当前职责和非目标", body)
        self.assertIn("禁止编写或修改 UT", body)
        self.assertIn("verify_ut", body)

    def test_code_reviewer_receives_diff_but_no_write_permission(self):
        body = build("craft-code")
        self.assertIn("diff --git a/src/service.py", body)
        self.assertNotIn("REVIEW_TARGET_SHA256", body)
        self.assertNotIn("TASK_CARD_SHA256", body)
        self.assertIn("返回文字格式不作为门禁", body)
        self.assertIn("- 处置：待用户裁决", body)
        self.assertIn("- 状态：待裁决", body)
        self.assertIn("## Finding F1", body)
        self.assertIn("只读", body)
        self.assertNotIn("允许修改:", body)

    def test_test_designer_reads_requirement_and_survey_not_future_blueprint(self):
        artifacts = {
            kind: ref for kind, ref in ARTIFACTS.items()
            if kind != "blueprint"
        }
        body = build("test-design", artifacts)
        self.assertIn("/repo/docs/requirement.md", body)
        self.assertIn("/repo/.mae-flow-work/survey-REQ-1.md", body)
        self.assertNotIn("- blueprint:", body)

    def test_task_analyst_writes_plan_before_plan_reviewer_reads_it(self):
        artifacts = {
            kind: ref for kind, ref in ARTIFACTS.items()
            if kind != "plan"
        }
        body = build("task-analysis", artifacts)
        self.assertIn("唯一允许写入的过程件", body)
        self.assertIn("/repo/.mae-flow-work/plan-REQ-1.md", body)
        self.assertNotIn("- plan: （未登记）", body)
        self.assertIn("蓝图场景只用于追踪", body)
        self.assertIn("不得生成测试文件 Task", body)

    def test_unknown_role_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "未知角色"):
            build("unknown")


if __name__ == "__main__":
    unittest.main()
