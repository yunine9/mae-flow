"""Checkpoint status query routing."""

from mae_flow_core.delivery.models import DeliveryEffect, DeliveryResult


LOCKED_STATUSES = {
    "craft_decision_pending",
    "review_pending",
    "commit_pending",
    "commit_recovery",
    "reset_pending",
    "push_pending",
}


def _result(stdout, effects=()):
    return DeliveryResult(
        effects=tuple(effects),
        stdout=tuple(stdout),
        stderr=(),
        exit_code=0,
    )


def inspect_checkpoint_status(review):
    """Describe a checkpoint plan and request the relevant refresh."""
    if not review:
        return _result((
            "[mae-flow] 当前是旧版在途流程，没有检查点子状态；"
            "继续按 current 的既有步骤执行。",
        ))
    output = [
        "[mae-flow] 开发节奏: %s；计划状态: %s"
        % (
            review.get("mode", "待确认"),
            review.get("status", "未知"),
        )
    ]
    items = review.get("checkpoints") or []
    output.extend(
        "  %s [%s] %s"
        % (item.get("id"), item.get("status"), item.get("title"))
        for item in items
    )
    index = int(review.get("current_index", 0) or 0)
    item = items[index] if 0 <= index < len(items) else None
    if item:
        return _result(
            output,
            (DeliveryEffect("refresh_checkpoint", {"index": index}),),
        )
    final = review.get("final_review")
    if (
            isinstance(final, dict)
            and final.get("status") in LOCKED_STATUSES):
        return _result(
            output,
            (DeliveryEffect("refresh_final_review", {}),),
        )
    output.append("全部计划检查点已闭环；继续当前主流程。")
    return _result(output)
