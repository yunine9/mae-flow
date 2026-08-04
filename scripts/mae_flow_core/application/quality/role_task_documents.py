"""Render role-specific Spec2Code task cards from frozen artifact refs."""

from dataclasses import dataclass
from typing import Mapping

from mae_flow_core.quality.task_cards import TaskCardDocument


@dataclass(frozen=True)
class ArtifactRef:
    path: str
    sha256: str


@dataclass(frozen=True)
class RoleTaskContext:
    artifacts: Mapping[str, ArtifactRef]
    files: tuple = ()
    context_paths: tuple = ()
    diff: str = ""
    review_output: str = ""
    review_target_sha256: str = ""
    write_output: str = ""


_MARKERS = {
    "test-design": "TEST_DESIGN_RESULT:",
    "task-analysis": "TASK_ANALYSIS_RESULT:",
    "craft-plan": "CRAFT_REVIEW_RESULT:",
    "cp-implement": "CP_IMPLEMENT_RESULT:",
    "craft-code": "CRAFT_REVIEW_RESULT:",
}

_INPUTS = {
    "test-design": ("blueprint",),
    "task-analysis": ("blueprint", "roadmap", "plan"),
    "craft-plan": ("blueprint", "roadmap", "plan"),
    "cp-implement": ("blueprint", "roadmap", "plan"),
    "craft-code": ("roadmap", "plan"),
}
_OPTIONAL_INPUTS = {
    "test-design": {"blueprint"},
    "task-analysis": {"plan"},
}


def _append_artifacts(document, role, artifacts):
    document.append("允许读取的过程件（路径与摘要必须同时匹配）:")
    for kind in _INPUTS[role]:
        ref = artifacts.get(kind)
        if ref is None:
            if kind in _OPTIONAL_INPUTS.get(role, set()):
                continue
            document.append("- %s: （未登记）" % kind)
        else:
            document.append(
                "- %s: %s | SHA256 %s"
                % (kind, ref.path, ref.sha256)
            )


def _append_context_paths(document, paths):
    document.append("允许读取的业务上下文:")
    document.extend("- " + path for path in paths)
    if not paths:
        document.append("- （缺失；返回 NEEDS_INPUT，不得靠猜测补全）")


def _append_review_contract(document, context, user_decision=False):
    document.extend([
        "Review 记录必须写入: "
        + (context.review_output or "（缺失；返回 NEEDS_INPUT）"),
        "Review 记录写明结论、检查点和真实 Finding；返回文字格式不作为门禁。",
        "零条 Finding 时直接说明未发现真实问题。",
        "FINDINGS 使用以下完整模板:",
        "## Finding F1",
        "- 位置：<文件:行或符号>",
        "- 依据：<计划/规格/工程原则>",
        "- 证据：<当前 diff 中可复核事实>",
        "- 实际影响：<正确性、维护性或集成影响>",
        "- 最小改法：<最小修正方向>",
    ])
    if user_decision:
        document.extend([
            "- 处置：待用户裁决",
            "- 状态：待裁决",
            "CODE Reviewer 只写客观事实，"
            "不得替用户决定处置或宣称关闭。",
        ])
    else:
        document.extend([
            "- 处置：修改|验证后修改|人工裁决|拒绝/暂缓",
            "- 状态：待处理|已解决|已拒绝",
        ])


def _append_role_contract(document, role, context):
    if role == "test-design":
        document.extend([
            "职责:只生成或修订 UT 行为蓝图；不写测试或业务源码。",
            "禁止确定测试文件、Fixture、Mock API、类名、函数名或 private 调用。",
            "唯一允许写入的过程件: "
            + (context.write_output or "（缺失；返回 NEEDS_INPUT）"),
        ])
    elif role == "task-analysis":
        document.extend([
            "职责:只展开当前 CP 的细粒度 Task；不写业务源码。",
            "每个 Task 必须包含目标文件、符号/签名、状态所有权、复用、"
            "禁止事项、注释计划和蓝图场景。",
            "对应 UT 蓝图场景只用于追踪生产实现覆盖的行为；"
            "不得生成测试文件 Task，不得把 Fixture、Fake/Mock、测试用例"
            "或 UT 执行写进当前 CP 计划。测试技术落位统一由 verify_ut 完成。",
            "唯一允许写入的过程件: "
            + (context.write_output or "（缺失；返回 NEEDS_INPUT）"),
            "只更新当前 CP Task；不得修改已确认路线图或其他 CP 合同。",
        ])
    elif role == "craft-plan":
        document.extend([
            "模式: PLAN，只读。",
            "职责:检查落点、职责、状态所有权、复用、Scenario、接口和注释计划。",
            "每轮最多五条；每条包含位置、依据、证据、实际影响和最小改法。",
        ])
        _append_review_contract(document, context)
    elif role == "cp-implement":
        document.extend([
            "Comment Standard v1: runtime/standards/comment-standard-v1.md",
            "当前职责和非目标、状态所有权、复用、错误/兼容语义、"
            "注释计划、UT 蓝图场景、前序接口和后续接口均以已确认 Task 为准。",
            "禁止编写或修改 UT、测试 Fixture、Fake/Mock；"
            "蓝图 Scenario 只用于核对生产实现，测试统一留给 verify_ut。",
            "允许修改:",
        ])
        document.extend("- " + path for path in context.files)
        if not context.files:
            document.append("- （无；返回 NEEDS_INPUT，不得自行扩大范围）")
    elif role == "craft-code":
        document.extend([
            "模式: CODE，只读；禁止修改源码、测试、计划或状态。",
            "实际 diff:",
            context.diff or "（缺失；返回 NEEDS_INPUT）",
            "只检查当前 CP diff 与直接集成边界，每轮最多五条。",
        ])
        _append_review_contract(document, context, user_decision=True)


def build_role_task_document(
        *,
        role,
        project_root,
        ticket,
        checkpoint,
        context: RoleTaskContext,
):
    if role not in _MARKERS:
        raise ValueError("未知角色: " + str(role))
    document = TaskCardDocument([
        "# Mae-Flow Spec2Code ROLE TASK",
        "本文件由 Harness 生成；不得读取任务卡未列出的上下文。",
        "项目根: " + project_root,
        "单号: " + ticket,
        "开发检查点: " + (checkpoint or "无"),
        "角色: " + role,
    ])
    _append_artifacts(document, role, context.artifacts)
    _append_context_paths(document, context.context_paths)
    _append_role_contract(document, role, context)
    document.extend([
        "不得读取任务卡未列出的其他上下文；缺失时返回 NEEDS_INPUT。",
        "最终报告可以使用任意自然语言格式。",
    ])
    return document
