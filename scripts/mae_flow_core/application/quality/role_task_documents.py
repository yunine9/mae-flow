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


CODE_REVIEW_AXES = ("standards", "spec")

_AXIS_BRIEFS = {
    "standards": (
        "视角:工程质量(standards)。只看代码本身写得好不好,不判断需求做得对不对——"
        "需求符合性由另一张卡的独立 Agent 负责,两者互不参考。",
        "本卡故意不提供 Spec 与 Story:一个 Agent 同时盯业务正确性和工程质量时,"
        "注意力会全部流向业务,低级工程问题就漏了。",
        "逐条检查:命名是否继承邻居;是否重造了仓内已有抽象;错误处理是否与本模块惯例一致;"
        "函数是否按概念拆分;有没有投机的灵活性;相似分支是否对称;失效旧代码是否删净;"
        "资源在每条离开路径上是否收口。基准见 "
        ".mae-flow-work/plugin-resources/standards/code-taste-v1.md。",
        "两类必查(按正确性报告):① 改动触碰的每个共享符号,独立 grep 全仓核对引用是否全部适配,"
        "重点查 XML 映射、配置、SQL、反射字符串这些编译器看不见的文件;"
        "② 与既有函数高度相似的新函数,其中复制来的副作用语句"
        "(clear/reset/init/register/truncate)在新的调用时序里是否应该再次发生。",
    ),
    "spec": (
        "视角:需求符合性(spec)。只判断代码有没有把需求做对做全,不报代码风格与工程质量问题——"
        "那由另一张卡的独立 Agent 负责,两者互不参考。",
        "三类结论:① 需求要求了但增量里缺失或只做了一半;② 增量里有需求没要求的行为"
        "(擅自扩大范围);③ 看起来实现了、但实现方式与需求不符。",
        "每条必须引用 Spec 或 Story 里的原句作为依据;引不出原句的不要报。",
        "Grill 已拍板的决策同样是需求,与 Spec 条目同等效力。",
    ),
}


def _append_code_review_contract(document, context, axis):
    _append_context(document, context.context_paths)
    document.extend((
        "模式:CODE，只读；这是用户人工检视前的一次可选 Agent 预检。",
        "只检查本需求完整未提交增量与直接集成边界；禁止修改任何文件。",
    ))
    document.extend(_AXIS_BRIEFS[axis])
    document.extend((
        "实际增量:",
        context.diff or "（缺失；返回 NEEDS_INPUT）",
        "工具已经在管的不报:编译告警、格式、行数与圈复杂度由 lightcheck 与 CodeCheck 守下限,"
        "重复报占名额。",
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
        if stage not in CODE_REVIEW_AXES:
            raise ValueError("code-review 必须指定视角: " + str(stage))
        _append_code_review_contract(document, context, stage)
    elif role in ("story-generate", "story-review"):
        _append_story_contract(document, role, context)
    elif role == "grill-critic":
        _append_grill_contract(document, stage, context)
    else:
        raise ValueError("未知角色: " + str(role))
    document.append("返回内容可以使用任意自然语言格式；不返回令牌、摘要或固定状态行。")
    return document
