"""Minimal phase guidance for recovering a lean workflow."""

import os

from .capabilities import flow_attempt_context, flow_retry_options
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


def _items(title, values):
    if not values:
        return "%s: none" % title
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
            "## Focused 恢复路径",
            "这是由旧流程迁移留下的 Full 专属阶段，不补做 Full 的 Grill、Story "
            "或 Design Reviewer 仪式。",
            "若工作仍是已定位的局部修改，按当前恢复说明直接进入 "
            "Construction；若发现真实的跨模块、兼容性、数据、安全、接口、"
            "共享状态或并发风险，执行 `advance upgrade-to-full --decision "
            "\"<自然语言依据>\"` 进入 Full。",
            "恢复选择只看语义风险，不看文件数或行数。",
        ))
    else:
        phase_path = os.path.join(_PHASE_ROOT, "%s.md" % state.phase.value)
        with open(phase_path, encoding="utf-8") as stream:
            phase_guidance = stream.read().strip()

    artifacts = tuple(
        "%s: %s" % (kind, path) for kind, path in state.artifacts)
    config = state.startup_config
    defaults_warning = _latest_decision(state, "startup.defaults_warning")
    startup_title = (
        "Confirmed startup configuration"
        if _latest_decision(state, "startup.confirmation")
        else "Proposed startup configuration")
    startup = (
        "worker: %s" % (config.worker or "not configured"),
        "ticket type: %s" % (config.ticket_type or "not configured"),
        "requirement source: %s" % (
            config.requirement_source or "not configured"),
        "base branch: %s" % (config.base_branch or "not configured"),
        "working branch: %s" % (
            config.working_branch or "not configured"),
        "Build: %s" % (config.build_method or "not configured"),
        "UT generation: %s" % (config.ut_method or "not configured"),
        "UT run entry: %s" % (config.ut_command or "not configured"),
        "Quality plan: %s" % (
            _latest_decision(state, "startup.quality_plan")
            or "not configured"),
    ) + (("repository defaults warning: %s" % defaults_warning,)
         if defaults_warning else ())
    domains = selected_domains(state)
    actions = tuple(
        "%s: %s%s" % (
            item.path, item.action,
            " — " + item.summary if item.summary else "")
        for item in domain_actions(state))
    checkpoints = tuple(
        "%s: brief=%s | result=%s | review=%s | UT=%s" % (
            item.name, item.brief or "none", item.result or "none",
            item.review or "none", item.ut_intent or "none")
        for item in checkpoint_facts(state))
    context = (
        "Ticket: %s\n"
        "Path: %s\n"
        "Phase: %s\n"
        "CP: %s\n"
        "%s\n"
        "%s\n"
        "%s\n"
        "%s\n"
        "%s\n"
        "%s"
    ) % (
        state.ticket,
        state.path.value,
        state.phase.value,
        state.current_cp or "none",
        _items(startup_title, startup),
        _items("Artifacts", artifacts),
        _items("Selected behavior domains", domains),
        _items("Behavior reconciliation", actions),
        _items("Checkpoint context", checkpoints),
        _items("Unresolved risks", state.risks),
    )
    return "%s\n\n%s\n" % (context, phase_guidance)


def render_capability_facts(state):
    """Render opaque attempts and the current retry authorization cursor."""
    if not state.capabilities:
        return ""
    lines = ["能力尝试（只记录返回事实，不解释工具输出）:"]
    lines.extend(
        "- %s | %s | %s" % (
            attempt.kind, attempt.outcome, attempt.summary or "无摘要")
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
            item.path, item.action,
            " — " + item.summary if item.summary else "")
            for item in actions)
    if state.delivery_files:
        lines.append("精确文件:")
        lines.extend("- %s" % path for path in state.delivery_files)
    else:
        lines.append("精确文件: none")
    lines.extend(_delivery_message_lines(state, decisions))
    lines.extend((
        "Moonlight requested: allow_commit=%s, allow_push=%s" % (
            str(moonlight.requested.allow_commit).lower(),
            str(moonlight.requested.allow_push).lower(),
        ),
        "Moonlight effective: allow_commit=%s, allow_push=%s" % (
            str(moonlight.effective.allow_commit).lower(),
            str(moonlight.effective.allow_push).lower(),
        ),
        "Moonlight block reason: %s" % (
            moonlight.block_reason or "none"),
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
            "需要用户介入: Intake（启动选择、完整配置一次确认）",
            "完整启动配置:",
            "- 工号: %s" % (config.worker or "未配置"),
            "- 单号: %s" % state.ticket,
            "- 单号类型: %s" % (config.ticket_type or "未配置"),
            "- 需求来源: %s" % (config.requirement_source or "未配置"),
            "- 交付路径: %s" % state.path.value,
            "- 提交节奏: %s" % state.commit_pace.value,
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
            "需要用户介入: Spec（可观察行为和范围）")
    if state.phase == Phase.STORY:
        return "" if moonlight else (
            "需要用户介入: Design（Story 实现边界、设计和可测性）")
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
            "需要用户介入: CP（本批实际结果与下一批设计）",
            "- 当前 CP: %s" % checkpoint,
            "- 原简报: %s" % (current.brief or "未记录"),
            "- 实际结果: %s" % (current.result or "未记录"),
            "- Reviewer: %s" % (current.review or "未记录"),
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
