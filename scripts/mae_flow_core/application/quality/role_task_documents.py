"""Render compact role task cards for the Story-centered workflow."""

from dataclasses import dataclass

from mae_flow_core.quality.task_cards import TaskCardDocument


@dataclass(frozen=True)
class RoleTaskContext:
    context_paths: tuple = ()
    diff: str = ""
    write_output: str = ""
    companion_output: str = ""
    review_output: str = ""
    feedback: str = ""


def _append_context(document, paths):
    document.append("权威输入（按顺序读取；无需扫描其他过程文档）:")
    document.extend("- " + path for path in paths)
    if not paths:
        document.append("- （缺失；返回 NEEDS_INPUT，不得靠全仓探索补流程输入）")


def _append_code_review_contract(document, context):
    _append_context(document, context.context_paths)
    document.extend((
        "模式:CODE，只读；这是用户人工检视前的一次可选 Agent 预检。",
        "只检查本需求完整未提交增量与直接集成边界；禁止修改任何文件。",
        "实际增量:",
        context.diff or "（缺失；返回 NEEDS_INPUT）",
        "只报告真实问题，每轮最多五条；每条包含位置、依据、证据、实际影响和最小改法。",
        "没有问题时直接说明 CLEAR。返回自然语言格式不作为门禁。",
    ))


def _append_story_contract(document, role, context):
    _append_context(document, context.context_paths)
    if role == "story-generate":
        document.extend((
            "职责:根据本地 Grill、Spec、相关领域文档、两个模板和真实代码生成 Story 与实施附录。",
            "仅允许写入:",
            "- Story: " + (context.write_output or "（缺失；返回 NEEDS_INPUT）"),
            "- 实施附录: " + (
                context.companion_output or "（缺失；返回 NEEDS_INPUT）"),
            "Story 严格保持模板结构；实施附录记录 Grill 影响、关键函数详述和领域归档影响。",
            "不得拆开发批次，也不得生成额外的编码前计划过程件。",
        ))
    else:
        document.extend((
            "模式:DESIGN，只读；联合检查 Story 与实施附录，只执行一次。",
            "禁止修改任何文件；只报告真实问题，没有问题时直接说明 CLEAR。",
        ))


def _append_grill_contract(document, stage, context):
    _append_context(document, context.context_paths)
    document.extend((
        "质询检查阶段: " + (stage or "（缺失）"),
        "模式:CRITIC，只读；禁止修改任何文件。",
        "检查遗漏、冲突、错误假设和不可验收表述；只报告真实问题。",
    ))


def build_role_task_document(
        *, role, project_root, ticket, context, stage=""):
    document = TaskCardDocument(list((
        "# Mae-Flow ROLE TASK",
        "本文件由 Harness 生成；只执行本卡，不回放聊天记录。",
        "项目根: " + project_root,
        "单号: " + ticket,
        "角色: " + role,
    )))
    if role == "code-review":
        _append_code_review_contract(document, context)
    elif role in ("story-generate", "story-review"):
        _append_story_contract(document, role, context)
    elif role == "grill-critic":
        _append_grill_contract(document, stage, context)
    else:
        raise ValueError("未知角色: " + str(role))
    document.append("返回内容可以使用任意自然语言格式；不返回令牌、摘要或固定状态行。")
    return document
