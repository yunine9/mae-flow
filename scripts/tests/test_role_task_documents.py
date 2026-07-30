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


def build(role):
    return build_role_task_document(
        role=role,
        project_root="/repo",
        ticket="REQ-1",
        checkpoint="CP1",
        context=RoleTaskContext(
            artifacts=ARTIFACTS,
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
        ),
    ).body()


class RoleTaskDocumentTests(unittest.TestCase):
    def test_each_role_has_scoped_inputs_and_output_contract(self):
        expected = {
            "test-design": "TEST_DESIGN_RESULT:",
            "task-analysis": "TASK_ANALYSIS_RESULT:",
            "craft-plan": "CRAFT_REVIEW_RESULT:",
            "cp-implement": "CP_IMPLEMENT_RESULT:",
            "craft-code": "CRAFT_REVIEW_RESULT:",
        }
        for role, marker in expected.items():
            with self.subTest(role=role):
                body = build(role)
                self.assertIn(marker, body)
                self.assertIn("TASK_CARD_SHA256", body)
                self.assertNotIn("聊天记录", body)

    def test_implementer_receives_comment_standard_and_allowed_files(self):
        body = build("cp-implement")
        self.assertIn("runtime/standards/comment-standard-v1.md", body)
        self.assertIn("允许修改:\n- src/service.py", body)
        self.assertIn("注释计划", body)
        self.assertIn("当前职责和非目标", body)

    def test_code_reviewer_receives_diff_but_no_write_permission(self):
        body = build("craft-code")
        self.assertIn("diff --git a/src/service.py", body)
        self.assertIn("REVIEW_TARGET_SHA256: " + "d" * 64, body)
        self.assertIn("TASK_CARD_SHA256", body)
        self.assertIn("CRAFT_REVIEW_RESULT: CLEAN|FINDINGS", body)
        self.assertIn("只读", body)
        self.assertNotIn("允许修改:", body)

    def test_test_designer_reads_requirement_and_survey_not_future_blueprint(self):
        body = build("test-design")
        self.assertIn("/repo/docs/requirement.md", body)
        self.assertIn("/repo/.mae-flow-work/survey-REQ-1.md", body)
        self.assertNotIn("- blueprint:", body)

    def test_unknown_role_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "未知角色"):
            build("unknown")


if __name__ == "__main__":
    unittest.main()
