#!/usr/bin/env python3
"""Spec2Code 本地过程件纯契约回归。"""

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from mae_flow_core.quality.spec2code_artifacts import (  # noqa: E402
    artifact_path,
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


def review(findings=1, status="已解决", disposition="修改"):
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
    return "# CP1 CODE Review\n\n" + "\n".join(blocks)


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
        errors = validate_blueprint(
            BLUEPRINT.replace("- 可观察结果：返回新对象。\n", ""))
        self.assertTrue(any("可观察结果" in error for error in errors))

    def test_validates_roadmap_and_exact_deferrals(self):
        self.assertEqual((), validate_roadmap(ROADMAP))
        errors = validate_roadmap(
            ROADMAP.replace(
                "查询 → CP2 / Task CP2-T1。",
                "后续处理。",
            )
        )
        self.assertTrue(any("具体 CP/Task" in error for error in errors))

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
        self.assertEqual((), validate_review(review(), "code", "CP1"))
        errors = validate_review(review(findings=6), "code", "CP1")
        self.assertTrue(any("最多五条" in error for error in errors))
        self.assertTrue(review_requires_rework(review(status="待处理")))
        self.assertFalse(
            review_requires_rework(
                review(status="已拒绝", disposition="拒绝/暂缓")
            )
        )


if __name__ == "__main__":
    unittest.main()
