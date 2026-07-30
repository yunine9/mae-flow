#!/usr/bin/env python3
"""Spec2Code 本地过程件纯契约回归。"""

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from mae_flow_core.quality.spec2code_artifacts import (  # noqa: E402
    artifact_path,
    blueprint_scenario_ids,
    checkpoint_review_context,
    roadmap_checkpoints,
    review_requires_rework,
    validate_blueprint,
    validate_plan,
    validate_review,
    validate_roadmap,
)


BLUEPRINT = """# UT 行为蓝图

## Scenario: SC-1
- 规格来源：Requirement A / Scenario A
- 测试目的：验证创建行为。
- 输入与前置状态：对象不存在。
- 执行动作：提交创建请求。
- 可观察结果：返回新对象。
- 必须不存在的副作用：不修改其他对象。
- 分类：正常。
- 建议测试层级：单元测试。
- 允许替代的依赖：时钟。
- 必须使用真实组件的依赖：值对象。
- 禁止依赖的实现细节：private 字段。
"""

ROADMAP = """# 全局 CP 路线图

## CP1: 创建核心对象
- 业务目标：创建对象。
- 完成合同：公开接口可创建。
- 明确非目标：不做查询。
- Scenario 归属：SC-1。
- 主要模块职责：service 编排。
- 状态所有权：repository。
- 前序接口：无。
- 后续接口：CP2 使用 create。
- 延后事项及具体落点：查询 → CP2 / Task CP2-T1。
- 关键风险：并发写。
"""

PLAN = """# 实现计划

## Task CP1-T1
- 所属 CP：CP1。
- 目标：增加创建入口。
- 创建/修改文件：src/service.py。
- 目标类、函数或接口：Service.create。
- 精确函数签名：create(request) -> Result。
- 输入、输出与错误语义：非法输入返回 Invalid。
- 主要控制流约束：先校验再持久化。
- 状态所有权：Repository。
- 必须复用：Validator。
- 禁止事项：不新增缓存。
- 注释计划：NONE：命名可完整表达。
- 对应 UT 蓝图场景：SC-1。
- 完成后的定向检查：调用现有编译入口。
"""


TASK_CARD_SHA = "e" * 64
REVIEW_TARGET_SHA = "f" * 64


def review(
        findings=1,
        status="已解决",
        disposition="修改",
        mode="CODE",
        checkpoint="CP1",
        task_card_sha=TASK_CARD_SHA,
        target_sha=REVIEW_TARGET_SHA,
        result="FINDINGS",
):
    blocks = []
    for index in range(findings):
        blocks.append(
            """## Finding F%d
- 位置：src/service.py:10。
- 依据：Task CP1-T1。
- 证据：重复调用同一校验器。
- 实际影响：错误语义不一致。
- 最小改法：复用 Validator。
- 处置：%s
- 状态：%s
""" % (index + 1, disposition, status)
        )
    return """# %s %s Review

- CRAFT_REVIEW_RESULT: %s
- Reviewer 模式: %s
- 检查点: %s
- TASK_CARD_SHA256: %s
- REVIEW_TARGET_SHA256: %s

%s""" % (
        checkpoint,
        mode,
        result,
        mode,
        checkpoint,
        task_card_sha,
        target_sha,
        "\n".join(blocks),
    )


class Spec2CodeArtifactTests(unittest.TestCase):
    def test_builds_only_local_safe_paths(self):
        self.assertEqual(
            ".mae-flow-work/test-blueprint-REQ-1.md",
            artifact_path("blueprint", "REQ-1"),
        )
        self.assertEqual(
            ".mae-flow-work/reviews/REQ-1/CP2-code.md",
            artifact_path("review", "REQ-1", "CP2", mode="code"),
        )
        for ticket in ("", "../REQ-1", "REQ/1"):
            with self.subTest(ticket=ticket):
                with self.assertRaises(ValueError):
                    artifact_path("blueprint", ticket)

    def test_validates_blueprint_required_behavior_fields(self):
        self.assertEqual((), validate_blueprint(BLUEPRINT))
        self.assertEqual(("SC-1",), blueprint_scenario_ids(BLUEPRINT))
        errors = validate_blueprint(
            BLUEPRINT.replace("- 可观察结果：返回新对象。\n", ""))
        self.assertTrue(any("可观察结果" in error for error in errors))
        duplicate = (
            BLUEPRINT
            + "\n"
            + BLUEPRINT[BLUEPRINT.index("## Scenario: SC-1"):]
        )
        errors = validate_blueprint(duplicate)
        self.assertTrue(any("重复" in error for error in errors))

    def test_validates_roadmap_and_exact_deferrals(self):
        self.assertEqual((), validate_roadmap(ROADMAP))
        self.assertEqual(
            (("CP1", "创建核心对象"),),
            roadmap_checkpoints(ROADMAP),
        )
        errors = validate_roadmap(
            ROADMAP.replace(
                "查询 → CP2 / Task CP2-T1。",
                "后续处理。",
            )
        )
        self.assertTrue(any("具体 CP/Task" in error for error in errors))

    def test_checkpoint_context_renders_global_and_local_views(self):
        lines = checkpoint_review_context(
            ROADMAP,
            PLAN,
            "CP1",
            "base..HEAD",
        )
        body = "\n".join(lines)
        for heading in (
            "整体交付地图",
            "当前 CP 完成合同",
            "当前 CP 非目标",
            "延后事项 → 后续 CP/Task",
            "Scenario → CP → Task → 状态",
            "对后续暴露的接口",
            "实际代码 diff",
        ):
            self.assertIn(heading, body)

    def test_validates_plan_and_comment_plan(self):
        self.assertEqual((), validate_plan(PLAN, "CP1"))
        errors = validate_plan(
            PLAN.replace(
                "NONE：命名可完整表达。",
                "适当补充注释。",
            ),
            "CP1",
        )
        self.assertTrue(any("注释计划" in error for error in errors))

    def test_review_has_five_item_limit_and_disposition(self):
        self.assertEqual(
            (),
            validate_review(
                review(),
                "code",
                "CP1",
                TASK_CARD_SHA,
                REVIEW_TARGET_SHA,
            ),
        )
        errors = validate_review(
            review(findings=6),
            "code",
            "CP1",
            TASK_CARD_SHA,
            REVIEW_TARGET_SHA,
        )
        self.assertTrue(any("最多五条" in error for error in errors))
        self.assertTrue(review_requires_rework(review(status="待处理")))
        self.assertFalse(
            review_requires_rework(
                review(status="已拒绝", disposition="拒绝/暂缓")
            )
        )

    def test_review_requires_bound_envelope_and_explicit_clean(self):
        errors = validate_review(
            "",
            "code",
            "CP1",
            TASK_CARD_SHA,
            REVIEW_TARGET_SHA,
        )
        self.assertTrue(any("CRAFT_REVIEW_RESULT" in error for error in errors))
        self.assertEqual(
            (),
            validate_review(
                review(findings=0, result="CLEAN"),
                "code",
                "CP1",
                TASK_CARD_SHA,
                REVIEW_TARGET_SHA,
            ),
        )
        mismatched = validate_review(
            review(task_card_sha="0" * 64),
            "code",
            "CP1",
            TASK_CARD_SHA,
            REVIEW_TARGET_SHA,
        )
        self.assertTrue(any("TASK_CARD_SHA256" in error for error in mismatched))
        contradictory = validate_review(
            review(findings=0, result="FINDINGS"),
            "code",
            "CP1",
            TASK_CARD_SHA,
            REVIEW_TARGET_SHA,
        )
        self.assertTrue(any("至少一条" in error for error in contradictory))


if __name__ == "__main__":
    unittest.main()
