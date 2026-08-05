#!/usr/bin/env python3
"""Thin Story-centered role task card contracts."""

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from mae_flow_core.application.quality.role_task_documents import (  # noqa: E402
    RoleTaskContext,
    build_role_task_document,
)


def build(role, *, stage="", context=None):
    return build_role_task_document(
        role=role,
        project_root="/repo",
        ticket="REQ-1",
        stage=stage,
        context=context or RoleTaskContext(
            context_paths=(
                "/repo/.mae-flow-work/REQ-1/spec.md",
                "/repo/.mae-flow-work/REQ-1/story.md",
            ),
            diff="diff --git a/src/service.py b/src/service.py\n",
            write_output="/repo/.mae-flow-work/REQ-1/story.md",
            companion_output="/repo/.mae-flow-work/REQ-1/implementation.md",
        ),
    ).body()


class RoleTaskDocumentTests(unittest.TestCase):
    def test_only_active_roles_render(self):
        for role in (
                "code-review", "story-generate", "story-review",
                "grill-critic"):
            with self.subTest(role=role):
                body = build(role, stage="prep")
                self.assertIn("任意自然语言格式", body)
                self.assertNotIn("_RESULT:", body)
                self.assertNotIn("TASK_CARD_SHA256", body)
                self.assertIn("不回放聊天记录", body)
        for retired in (
                "implement", "cp-implement", "test-design",
                "task-analysis", "craft-plan"):
            with self.subTest(role=retired):
                with self.assertRaisesRegex(ValueError, "未知角色"):
                    build(retired)

    def test_code_reviewer_gets_exact_inputs_and_is_read_only(self):
        body = build("code-review")
        self.assertIn("spec.md", body)
        self.assertIn("story.md", body)
        self.assertIn("diff --git", body)
        self.assertIn("用户人工检视前", body)
        self.assertIn("只读", body)
        self.assertIn("最多五条", body)
        self.assertIn("CLEAR", body)

    def test_story_roles_use_local_outputs_once(self):
        generated = build("story-generate")
        reviewed = build("story-review")
        self.assertIn("仅允许写入", generated)
        self.assertIn("implementation.md", generated)
        self.assertIn("不得拆开发批次", generated)
        self.assertIn("只执行一次", reviewed)
        self.assertIn("禁止修改任何文件", reviewed)

    def test_grill_critic_stage_is_explicit_and_read_only(self):
        body = build("grill-critic", stage="final")
        self.assertIn("质询检查阶段: final", body)
        self.assertIn("只读", body)
        self.assertIn("禁止修改任何文件", body)


if __name__ == "__main__":
    unittest.main()
