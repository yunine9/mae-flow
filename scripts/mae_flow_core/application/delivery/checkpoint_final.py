"""Creation of the final delivery review receipt."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

from mae_flow_core.delivery.models import DeliveryEffect, DeliveryResult


LOCKED_STATUSES = {
    "review_pending",
    "commit_pending",
    "commit_recovery",
    "reset_pending",
    "push_pending",
}


@dataclass(frozen=True)
class FinalReviewPorts:
    final_delta: Callable[[], object]
    head: Callable[[], str]
    final_snapshot: Callable[[str], object]
    snapshot_sha256: Callable[[object], str]
    upstream: Callable[[], object]
    ack_cursor: Callable[[], object]
    now: Callable[[], str]


def _result(effects=(), stdout=(), stderr=(), exit_code=0):
    return DeliveryResult(
        effects=tuple(effects),
        stdout=tuple(stdout),
        stderr=tuple(stderr),
        exit_code=exit_code,
    )


def prepare_final_review(current, review, moonlight, ports):
    """Prepare or redisplay the final review without mutating caller state."""
    if current != "delivery_review":
        return _result(
            stderr=(
                "checkpoint final 只允许在最终代码增量检视步骤执行；"
                "中间批次使用 checkpoint ready/status。",
            ),
            exit_code=2,
        )
    if not review or moonlight:
        return _result(stdout=(
            "[mae-flow] 当前无需检查点式最终检视；"
            "直接按 current 执行 done。",
        ))
    updated = deepcopy(review)
    active = updated.get("final_review")
    if (
            isinstance(active, dict)
            and active.get("status") in LOCKED_STATUSES):
        effects = []
        if active.get("status") == "push_pending":
            effects.append(DeliveryEffect(
                "migrate_legacy_final", {}))
        effects.append(DeliveryEffect("show_final_review", {}))
        return _result(effects=effects)

    changed, error = ports.final_delta()
    if error:
        return _result(
            stderr=("最终检视基点无法核实:" + error,),
            exit_code=2,
        )
    if not changed:
        return _result(stdout=(
            "[mae-flow] 最后已检视代码版本之后没有源码/测试/构建变化；"
            "无需重复确认，直接执行 done。",
        ))
    base = str(
        updated.get("last_reviewed_head")
        or updated.get("delivery_base")
        or "")
    head = ports.head()
    worktree_snapshot = dict(ports.final_snapshot(head))
    receipt = {}
    if worktree_snapshot:
        receipt = {
            "base": head,
            "snapshot": worktree_snapshot,
            "snapshot_sha256": ports.snapshot_sha256(
                worktree_snapshot),
            "scope": "final",
        }
    ref, remote_head, _local_head = ports.upstream()
    remote_ref = ref if remote_head == head else ""
    updated["final_review"] = {
        "status": "review_pending",
        "base": base,
        "head": head,
        "title": "最终检视增量",
        "remote_ref": remote_ref,
        "remote_head": remote_head if remote_ref else "",
        "changed": changed,
        "receipt": receipt,
        "requires_commit": bool(worktree_snapshot),
        "requires_quality_rerun": bool(worktree_snapshot),
        "ack_cursor": ports.ack_cursor(),
        "at": ports.now(),
    }
    return _result(effects=(
        DeliveryEffect("set_development_review", updated),
        DeliveryEffect("show_final_review", {}),
    ))
