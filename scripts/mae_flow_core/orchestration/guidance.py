"""Minimal phase guidance for recovering a lean workflow."""

import os
import posixpath

from .capabilities import (
    capability_record_command, flow_attempt_context, flow_retry_options)
from .behavior_baseline import domain_actions, selected_domains
from .checkpoints import (
    checkpoint_context,
    checkpoint_facts,
    next_checkpoint_context,
)
from .models import CommitPace, DeliveryPath, FlowState, Phase
from .moonlight_policy import moonlight_authorization_view


_PHASE_ROOT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "flow", "phases"))
_PLUGIN_RESOURCES = (
    ".mae-flow-work/plugin-resources/guidance/grill.md",
    ".mae-flow-work/plugin-resources/assets/GRILL-PREP-TEMPLATE.md",
    ".mae-flow-work/plugin-resources/assets/STORY-TEMPLATE.md",
    ".mae-flow-work/plugin-resources/assets/CHAIN-TEMPLATE.md",
    ".mae-flow-work/plugin-resources/assets/BEHAVIOR-TEMPLATE.md",
    ".mae-flow-work/plugin-resources/assets/REVIEW-TEMPLATE.md",
)

_PHASE_LABELS = {
    "startup": "启动确认（Intake）",
    "spec": "需求澄清（Spec）",
    "story": "详细设计（Design）",
    "construction": "编码实现（Construction）",
    "quality": "质量验证（Quality）",
    "delivery": "交付确认（Delivery）",
}
_PATH_LABELS = {
    "full": "完整流程（Full）",
    "focused": "聚焦流程（Focused）",
}
_PACE_LABELS = {
    "continuous": "最终一次提交（Continuous）",
    "staged": "按批次提交（Staged）",
}
_STATUS_LABELS = {
    "active": "进行中",
    "complete": "已完成",
    "exited": "已退出",
}
_ARTIFACT_LABELS = {
    "request": "需求说明",
    "spec": "需求规格",
    "grill": "质询记录",
    "story": "详细设计",
    "ut-handoff": "UT 交接",
    "chain": "跨仓方案",
}
_ACTION_LABELS = {
    "new": "新增",
    "updated": "更新",
    "unchanged": "不变",
}
_OUTCOME_LABELS = {
    "returned": "已正常返回",
    "failed-to-start": "启动失败",
    "timed-out": "已超时",
    "not-observed": "未观察到返回",
}
_PHASE_CAPABILITIES = {
    Phase.SPEC: (("Grill Critic", "grill"),),
    Phase.STORY: (("Story 生成", "story"), ("设计检视", "reviewer")),
    Phase.CONSTRUCTION: (("代码检视", "reviewer"), ("构建", "build")),
    Phase.QUALITY: (
        ("CodeCheck", "codecheck"),
        ("正式 UT", "ut"),
        ("条件触发的集成边界检视", "reviewer"),
        ("失效后经用户确认的补充构建", "build"),
    ),
}
_CAPABILITY_OUTCOMES = (
    "returned", "failed-to-start", "timed-out", "not-observed")


def phase_label(value):
    key = value.value if isinstance(value, Phase) else str(value)
    return _PHASE_LABELS.get(key, key)


def path_label(value):
    key = value.value if isinstance(value, DeliveryPath) else str(value)
    return _PATH_LABELS.get(key, key)


def status_label(value):
    return _STATUS_LABELS.get(str(value), str(value))


def artifact_label(value):
    return _ARTIFACT_LABELS.get(str(value), str(value))


def outcome_label(value):
    return _OUTCOME_LABELS.get(str(value), str(value))


def reason_label(reason, recovery="当前流程恢复信息。", updated="流程状态已更新。"):
    if not reason:
        return ""
    if any("\u4e00" <= char <= "\u9fff" for char in reason):
        return reason
    return recovery if "recovery context" in reason.casefold() else updated


def render_capability_commands(state):
    """Render exact fact commands for capabilities planned in this phase."""
    capabilities = _PHASE_CAPABILITIES.get(state.phase, ())
    if (
            state.path == DeliveryPath.FOCUSED
            and state.phase in {Phase.SPEC, Phase.STORY}):
        capabilities = ()
    if not capabilities:
        return ""
    lines = ["能力事实记录命令（真实调用结束后只执行匹配结果的一条）:"]
    for label, kind in capabilities:
        lines.append("%s（能力 key: %s）:" % (label, kind))
        lines.extend(
            capability_record_command(kind, outcome)
            for outcome in _CAPABILITY_OUTCOMES)
    if state.phase == Phase.SPEC:
        lines.extend((
            "Grill Critic 正常返回并记录后，继续执行:",
            'python ".mae-flow-work/bin/mae-flow.py" advance grill-clear',
        ))
    return "\n".join(lines)


def _moonlight_reason_label(reason):
    if not reason:
        return "无"
    exact = {
        "Moonlight is disabled.": "月光宝盒未启用",
        "Unresolved workflow risk requires a safe stop.": "仍有未解决风险",
        "No exact delivery manifest is available yet.": "尚未形成精确交付清单",
        "The current exact manifest is preauthorized.": "当前精确清单已预授权",
    }
    if reason in exact:
        return exact[reason]
    prefixes = (
        ("The exact delivery manifest is unavailable: ", "精确交付清单不可用："),
        ("Unowned dirty files prevent automatic commit and push: ",
         "存在未确认归属的已有改动："),
        ("The manifest includes files outside exact Moonlight preauthorization, "
         "including any conditional document not explicitly named: ",
         "交付清单包含未明确授权的文件："),
    )
    for source, target in prefixes:
        if reason.startswith(source):
            return target + reason[len(source):]
    return "权限尚未满足安全条件"


def _items(title, values):
    if not values:
        return "%s: 无" % title
    return "%s:\n%s" % (
        title,
        "\n".join("- %s" % value for value in values),
    )


def _latest_decision(state, key):
    return next((
        value for existing, value in reversed(state.decisions)
        if existing == key), "")


def render_guidance(state):
    """Render one phase document with only useful recovery context."""
    if not isinstance(state, FlowState):
        raise TypeError("state must be a FlowState")

    if (
            state.path == DeliveryPath.FOCUSED
            and state.phase in {Phase.SPEC, Phase.STORY}):
        phase_guidance = "\n".join((
            "## 聚焦流程恢复说明",
            "这是旧状态遗留的完整流程专属阶段，不补做完整流程的质询、详细设计"
            "或设计检视。",
            "若工作仍是已定位的局部修改，按当前恢复说明直接进入 "
            "编码实现；若发现真实的跨模块、兼容性、数据、安全、接口、"
            "共享状态或并发风险，执行 `advance upgrade-to-full --decision "
            "\"<自然语言依据>\"` 进入完整流程。",
            "恢复选择只看语义风险，不看文件数或行数。",
        ))
    else:
        phase_path = os.path.join(_PHASE_ROOT, "%s.md" % state.phase.value)
        with open(phase_path, encoding="utf-8") as stream:
            phase_guidance = stream.read().strip()

    artifacts = tuple(
        "%s: %s" % (_ARTIFACT_LABELS.get(kind, kind), path)
        for kind, path in state.artifacts)
    grill_path = next((
        path for kind, path in state.artifacts if kind == "grill"), "")
    grill_work = ()
    if grill_path:
        directory = posixpath.dirname(grill_path)
        grill_work = (
            posixpath.join(directory, "survey.md"),
            posixpath.join(directory, "grill-prep.md"),
        )
    config = state.startup_config
    defaults_warning = _latest_decision(state, "startup.defaults_warning")
    startup_title = (
        "已确认的启动配置"
        if _latest_decision(state, "startup.confirmation")
        else "待确认的启动配置")
    startup = (
        "工号: %s" % (config.worker or "未配置"),
        "单号类型: %s" % (config.ticket_type or "未配置"),
        "需求来源: %s" % (config.requirement_source or "未配置"),
        "基线分支: %s" % (config.base_branch or "未配置"),
        "工作分支: %s" % (config.working_branch or "未配置"),
        "构建方式: %s" % (config.build_method or "未配置"),
        "UT 生成方式: %s" % (config.ut_method or "未配置"),
        "UT 运行入口: %s" % (config.ut_command or "未配置"),
        "质量组合: %s" % (
            _latest_decision(state, "startup.quality_plan")
            or "未配置"),
    ) + (("仓库预设提示: %s" % defaults_warning,)
         if defaults_warning else ())
    domains = selected_domains(state)
    actions = tuple(
        "%s: %s%s" % (
            item.path, _ACTION_LABELS.get(item.action, item.action),
            " — " + item.summary if item.summary else "")
        for item in domain_actions(state))
    checkpoints = tuple(
        "%s: 简报=%s | 结果=%s | 检视=%s | UT=%s" % (
            item.name, item.brief or "无", item.result or "无",
            item.review or "无", item.ut_intent or "无")
        for item in checkpoint_facts(state))
    context = (
        "工单: %s\n"
        "交付路径: %s\n"
        "当前阶段: %s\n"
        "当前开发批次: %s\n"
        "%s\n"
        "%s\n"
        "%s\n"
        "%s\n"
        "%s\n"
        "%s\n"
        "%s\n"
        "%s"
    ) % (
        state.ticket,
        path_label(state.path),
        phase_label(state.phase),
        state.current_cp or "无",
        _items(startup_title, startup),
        _items("流程产物", artifacts),
        _items("插件本地资源", _PLUGIN_RESOURCES),
        _items("质询准备文件", grill_work),
        _items("相关业务领域", domains),
        _items("行为基线处理", actions),
        _items("开发批次上下文", checkpoints),
        _items("未解决风险", state.risks),
    )
    capability_commands = render_capability_commands(state)
    suffix = "\n\n" + capability_commands if capability_commands else ""
    return "%s\n\n%s%s\n" % (context, phase_guidance, suffix)


def render_capability_facts(state):
    """Render opaque attempts and the current retry authorization cursor."""
    if not state.capabilities:
        return ""
    lines = ["能力尝试（只记录返回事实，不解释工具输出）:"]
    lines.extend(
        "- %s | %s | %s" % (
            attempt.kind,
            _OUTCOME_LABELS.get(attempt.outcome, attempt.outcome),
            attempt.summary or "无摘要")
        for attempt in state.capabilities)
    lines.append("能力重试授权:")
    seen = set()
    for attempt in state.capabilities:
        if attempt.kind in seen:
            continue
        seen.add(attempt.kind)
        try:
            option = flow_retry_options(state, attempt.kind)
            context = flow_attempt_context(state, attempt.kind)
        except (TypeError, ValueError):
            label = "状态未知；不要猜测或自动重试"
        else:
            current_attempted = any(
                item.kind == context.kind.value
                and item.source_revision == context.source_revision
                and item.environment_revision == context.environment_revision
                for item in state.capabilities)
            if option.allowed and current_attempted:
                label = "已授权一次重试（尚未消费）"
            elif option.allowed:
                label = "当前新语义 slot 尚未调用；仅按阶段计划调用"
            else:
                label = "再次调用前需要用户决定"
        lines.append("- %s: %s" % (attempt.kind, label))
    return "\n".join(lines) + "\n"


def _delivery_message_lines(state, decisions):
    if state.commit_pace == CommitPace.CONTINUOUS:
        return ("提交说明: %s" % decisions.get(
            "delivery.commit_message", "尚未选择"),)

    prefix = "delivery.cp."
    suffix = ".message"
    messages = tuple(
        (key[len(prefix):-len(suffix)], value)
        for key, value in state.decisions
        if key.startswith(prefix) and key.endswith(suffix)
    )
    if not messages:
        return ("提交说明（按 CP 顺序）: 尚未选择",)
    return ("提交说明（按 CP 顺序）:",) + tuple(
        "- %s: %s" % item for item in messages)


def _delivery_user_card(state):
    decisions = {key: value for key, value in state.decisions}
    moonlight = moonlight_authorization_view(state)
    lines = ["需要用户介入: 交付（精确文件、提交说明和是否推送）"]
    conformance = decisions.get("quality.final_conformance", "未记录")
    lines.append("最终 Spec/Story/代码对照: " + conformance)
    if decisions.get("quality.integration.required"):
        lines.append("集成边界走读: " + decisions.get(
            "quality.integration.review", "尚未完成"))
    actions = domain_actions(state)
    if actions:
        lines.append("领域行为基线:")
        lines.extend("- %s: %s%s" % (
            item.path, _ACTION_LABELS.get(item.action, item.action),
            " — " + item.summary if item.summary else "")
            for item in actions)
    if state.delivery_files:
        lines.append("精确文件:")
        lines.extend("- %s" % path for path in state.delivery_files)
    else:
        lines.append("精确文件: 无")
    lines.extend(_delivery_message_lines(state, decisions))
    lines.extend((
        "月光宝盒请求权限: 提交=%s，推送=%s" % (
            "允许" if moonlight.requested.allow_commit else "不允许",
            "允许" if moonlight.requested.allow_push else "不允许",
        ),
        "月光宝盒当前权限: 提交=%s，推送=%s" % (
            "允许" if moonlight.effective.allow_commit else "不允许",
            "允许" if moonlight.effective.allow_push else "不允许",
        ),
        "月光宝盒阻断原因: %s" % (
            _moonlight_reason_label(moonlight.block_reason)),
    ))
    return "\n".join(lines)


def render_user_card(state):
    """Return the one high-value user intervention for the current cursor.

    Moonlight suppresses routine phase confirmations only.  Delivery stays
    visible here; the dedicated policy alone may authorize its exact effects.
    """
    if not isinstance(state, FlowState):
        raise TypeError("state must be a FlowState")
    if state.status != "active":
        return ""
    decisions = {key: value for key, value in state.decisions}
    moonlight = decisions.get("moonlight.enabled") == "true"
    confirmed = set(decisions)
    if state.phase == Phase.STARTUP:
        if moonlight:
            return ""
        config = state.startup_config
        defaults_warning = _latest_decision(
            state, "startup.defaults_warning")
        lines = (
            "需要用户介入: 启动确认（完整配置一次确认）",
            "完整启动配置:",
            "- 工号: %s" % (config.worker or "未配置"),
            "- 单号: %s" % state.ticket,
            "- 单号类型: %s" % (config.ticket_type or "未配置"),
            "- 需求来源: %s" % (config.requirement_source or "未配置"),
            "- 交付路径: %s" % path_label(state.path),
            "- 提交节奏: %s" % _PACE_LABELS.get(
                state.commit_pace.value, state.commit_pace.value),
            "- 基线分支: %s" % (config.base_branch or "未配置"),
            "- 工作分支: %s" % (config.working_branch or "未配置"),
            "- Build: %s" % (config.build_method or "未配置"),
            "- UT 生成: %s" % (config.ut_method or "未配置"),
            "- UT 运行入口: %s" % (config.ut_command or "未配置"),
            "- 需求摘要: %s" % (
                decisions.get("request.summary", "未配置")),
            "- 质量组合: %s" % (
                decisions.get("startup.quality_plan", "未配置")),
        ) + (("- 预设读取提示: %s" % defaults_warning,)
             if defaults_warning else ()) + (
            "请直接用自然语言确认或修改以上任意项。",)
        return "\n".join(lines)
    if state.path == DeliveryPath.FOCUSED:
        if state.phase == Phase.DELIVERY and "delivery.confirmation" not in confirmed:
            return _delivery_user_card(state)
        return ""
    if state.phase == Phase.SPEC:
        return "" if moonlight else (
            "需要用户介入: 需求澄清（可观察行为和范围）")
    if state.phase == Phase.STORY:
        return "" if moonlight else (
            "需要用户介入: 详细设计（实现边界、方案和可测性）")
    if (
            state.phase == Phase.CONSTRUCTION
            and decisions.get("construction.cp.%s.ready" % (
                state.current_cp or "CP1")) == "true"
            and "construction.cp.%s.confirmation" % (
                state.current_cp or "CP1") not in confirmed):
        if moonlight:
            return ""
        checkpoint = state.current_cp or "CP1"
        current = checkpoint_context(state, checkpoint)
        following = next_checkpoint_context(state, checkpoint)
        lines = [
            "需要用户介入: 开发批次（本批结果与下一批设计）",
            "- 当前 CP: %s" % checkpoint,
            "- 原简报: %s" % (current.brief or "未记录"),
            "- 实际结果: %s" % (current.result or "未记录"),
            "- 代码检视: %s" % (current.review or "未记录"),
            "- 累计 UT 增量: %s" % (current.ut_intent or "未记录"),
        ]
        plan_prefix = "delivery.cp.%s." % checkpoint
        planned_files = tuple(
            value for key, value in state.decisions
            if key == plan_prefix + "file")
        planned_message = _latest_decision(
            state, plan_prefix + "message")
        if planned_files:
            lines.append("本批精确提交计划:")
            lines.extend("- %s" % path for path in planned_files)
            lines.append("- 提交说明: %s" % (
                planned_message or "未记录"))
        if following is not None:
            lines.append("- 下一 CP: %s — %s" % (
                following.name, following.brief or "未记录"))
        lines.append(
            "请直接用自然语言确认，或说明需要调整的代码/后续设计；"
            "调整完成并重新检视前不会提交。")
        return "\n".join(lines)
    if (
            state.phase == Phase.DELIVERY
            and "delivery.confirmation" not in confirmed):
        return _delivery_user_card(state)
    return ""
