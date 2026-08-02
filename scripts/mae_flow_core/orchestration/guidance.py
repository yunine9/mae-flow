"""Minimal phase guidance for recovering a lean workflow."""

import os

from .models import CommitPace, DeliveryPath, FlowState, Phase


_PHASE_ROOT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "flow", "phases"))


def _items(title, values):
    if not values:
        return "%s: none" % title
    return "%s:\n%s" % (
        title,
        "\n".join("- %s" % value for value in values),
    )


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
    context = (
        "Ticket: %s\n"
        "Path: %s\n"
        "Phase: %s\n"
        "CP: %s\n"
        "%s\n"
        "%s"
    ) % (
        state.ticket,
        state.path.value,
        state.phase.value,
        state.current_cp or "none",
        _items("Artifacts", artifacts),
        _items("Unresolved risks", state.risks),
    )
    return "%s\n\n%s\n" % (context, phase_guidance)


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
    lines = ["需要用户介入: 交付（精确文件、提交说明和是否推送）"]
    if state.delivery_files:
        lines.append("精确文件:")
        lines.extend("- %s" % path for path in state.delivery_files)
    else:
        lines.append("精确文件: none")
    lines.extend(_delivery_message_lines(state, decisions))
    lines.append(
        "Moonlight 权限: allow_commit=%s, allow_push=%s" % (
            decisions.get("moonlight.allow_commit", "false"),
            decisions.get("moonlight.allow_push", "false"),
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
        return "" if moonlight else (
            "需要用户介入: 启动选择（路径、范围和提交节奏）")
    if state.path == DeliveryPath.FOCUSED:
        if state.phase == Phase.DELIVERY and "delivery.confirmation" not in confirmed:
            return _delivery_user_card(state)
        return ""
    if state.phase == Phase.SPEC:
        return "" if moonlight else (
            "需要用户介入: Spec（可观察行为和范围）")
    if state.phase == Phase.STORY:
        return "" if moonlight else (
            "需要用户介入: Story（实现边界、设计和可测性）")
    if (
            state.phase == Phase.CONSTRUCTION
            and "construction.cp.%s.confirmation" % (
                state.current_cp or "CP1") not in confirmed):
        return "" if moonlight else (
            "需要用户介入: CP（本批结果和后续节奏）")
    if (
            state.phase == Phase.DELIVERY
            and "delivery.confirmation" not in confirmed):
        return _delivery_user_card(state)
    return ""
