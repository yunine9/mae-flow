"""Pure Gate decisions for repository edit requests."""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class GateDecision:
    kind: str
    rule: str = ""
    message: str = ""

    def __iter__(self):
        return iter((self.kind, self.rule, self.message))


@dataclass(frozen=True)
class EditGateContext:
    path: str
    match_path: str
    step: str
    step_title: str
    inside_plugin: bool
    specs_truth: str
    allow_specs_write: bool
    is_source: bool
    checkpoint_locked: bool
    checkpoint_label: str
    allow_source_edit: bool
    tests_only_patterns: tuple
    source_unlocked: bool


def _absolute(message):
    return GateDecision("absolute", message=message)


def _block(rule, message):
    return GateDecision("block", rule=rule, message=message)


def _protected_file_decision(context):
    path = context.path
    if path.lower().endswith((".comet.yaml", ".openspec.yaml")):
        return _absolute(
            "禁止手动编辑 comet/openspec 状态文件(.comet.yaml/.openspec.yaml),"
            "它们由 comet-state 维护(黑名单#4)。")
    if re.search(
            r"\.mae-flow\.json(?:\.[\w-]+)*$"
            r"|\.mae-flow-history\.jsonl$|\.mae-flow-need-reload$"
            r"|(^|/)\.mae-flow-work/moonlight-report\.md$",
            path, re.I):
        return _absolute(
            "流程状态/令牌/历史账本/待重启标记/月光宝盒报告由 mae-flow 与 hook "
            "维护,禁止直接编辑或删除。待重启标记只能靠**重启会话**清除"
            "(SessionStart 自动删),不许手动绕过——绕过 = skill 没加载就往下走。")
    if re.search(r"(^|/)\.mae-flow-defaults\.json$", path, re.I):
        return _absolute(
            "流程运行期间禁止修改 .mae-flow-defaults.json:它决定源码/测试路径的"
            "判定口径,改它等于改门禁规则。团队预设请在流程外走正常评审提交。")
    if (
        re.search(r"(^|/)\.env(\.[\w.-]+)?$", path, re.I)
        and not re.search(
            r"\.env\.(example|sample|template|dist|defaults)$",
            path, re.I)
    ):
        return _absolute(
            ".env 类密钥文件禁止写入(凭据保护);确需修改请用户手动操作。")
    return None


def _repository_edit_decision(context):
    path = context.path
    match_path = context.match_path
    if (
        context.step == "config_confirm"
        and re.search(r"(^|/)docs/req/", match_path, re.I)
    ):
        return _block(
            "edit-docs-req",
            "配置确认阶段禁止 Agent 直接写 docs/req（Windows shell/编辑工具编码"
            "不可作为需求真相源）。用户口述先执行 mae-flow messages，再用 "
            "requirement-record --message-id；已有文本用 requirement-record --source。",
        )
    if context.inside_plugin:
        return _absolute(
            "禁止修改插件自身(flow/steps/hooks/scripts):流程规则不是交付改动的对象。")
    if (
        re.search(context.specs_truth, match_path, re.I)
        and not context.allow_specs_write
    ):
        return _block(
            "edit-specs",
            "openspec/specs/ 为真相源,当前步骤 %s 禁止写入(黑名单#3)。"
            % (context.step or "未初始化"),
        )
    return None


def _source_edit_decision(context):
    match_path = context.match_path
    if not context.is_source:
        return None
    if context.checkpoint_locked:
        return _block(
            "edit-checkpoint-review",
            "检查点 %s 的检视快照已经冻结，Agent 不能继续改源码。"
            "用户选择“需要调整代码”后执行 checkpoint decide revise，"
            "状态回到 coding 才能修改。"
            % (context.checkpoint_label or "最终检视"),
        )
    if not context.allow_source_edit:
        return _block(
            "edit-source",
            "当前步骤 %s(%s)禁止修改源码;先 mae-flow current 查看该做什么。"
            % (context.step, context.step_title),
        )
    if (
        context.tests_only_patterns
        and not context.source_unlocked
        and not any(
            re.search(pattern, match_path, re.I)
            for pattern in context.tests_only_patterns)
    ):
        return _block(
            "edit-tests-only",
            "当前步骤 %s 仅允许写测试路径(当前生效规则: %s)。"
            "UT 暴露的疑似源码缺陷不是死路:自查确认后带报告呈用户裁决,"
            "用户判定确为代码缺陷时执行 mae-flow unlock source "
            "--reason <裁决结论> --ack \"用户原话\" 解锁本步修复;"
            "禁止未经用户裁决自行改源码。"
            % (context.step, "|".join(context.tests_only_patterns)),
        )
    return None


def decide_edit(context):
    """Return the first historical Edit Gate decision in rule order."""
    for evaluator in (
        _protected_file_decision,
        _repository_edit_decision,
        _source_edit_decision,
    ):
        decision = evaluator(context)
        if decision is not None:
            return decision
    return GateDecision("allow")
