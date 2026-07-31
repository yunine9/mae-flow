"""User decisions for checkpoint and final delivery reviews."""

import shlex
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

from mae_flow_core.delivery.models import DeliveryEffect, DeliveryResult


CONTINUE_ACK = "我已认真检视并完成自验证，继续"
REVISE_ACK = "需要调整代码"
CONTINUOUS_ACK = "当前批次先不确认，剩余代码一次完成后统一检视"
ACKS = {
    "continue": CONTINUE_ACK,
    "revise": REVISE_ACK,
    "continuous": CONTINUOUS_ACK,
}


@dataclass(frozen=True)
class CheckpointDecisionPorts:
    verify_ack: Callable[[object, str], object]
    head: Callable[[], str]
    upstream: Callable[[], object]
    worktree_fresh: Callable[[object], object]
    final_snapshot: Callable[[str], object]
    source_fresh: Callable[[str], object]
    upstream_contains: Callable[[str, str], str]
    now: Callable[[], str]


def _failure(message):
    return DeliveryResult(
        effects=(), stdout=(), stderr=(message,), exit_code=2)


def _success(effects=(), stdout=()):
    return DeliveryResult(
        effects=tuple(effects),
        stdout=tuple(stdout),
        stderr=(),
        exit_code=0,
    )


def _set_review(review):
    return DeliveryEffect("set_development_review", review)


def _history(current, result, note, now):
    return DeliveryEffect("append_history", {
        "step": current,
        "result": result,
        "note": note,
        "at": now,
    })


def _current_item(review):
    items = review.get("checkpoints") or []
    index = int(review.get("current_index", 0) or 0)
    return items[index] if 0 <= index < len(items) else None


def commit_commands(item, config):
    paths = list(((item.get("receipt") or {}).get("snapshot") or {}).keys())
    add = "git add -- " + " ".join(shlex.quote(path) for path in paths)
    message = "[%s][%s]%s" % (
        config.get("单号", ""),
        config.get("单号类型", ""),
        item.get("title", "检查点代码"),
    )
    return add, "git commit -m " + shlex.quote(message)


def decide_checkpoint(
        review, current, moonlight, choice, ports, config=None):
    """Resolve one checkpoint decision without mutating caller state."""
    if not review or moonlight:
        return _failure("当前没有等待用户裁决的普通模式检查点。")
    expected = ACKS[choice]
    ack = expected
    now = ports.now()
    updated = deepcopy(review)
    final = updated.get("final_review") or {}
    if current == "delivery_review":
        final_result = _decide_delivery_review(
            updated, final, choice, ack, expected, now, ports)
        if final_result is not None:
            return final_result
    return _decide_intermediate(
        updated, current, choice, ack, expected,
        now, ports, config or {})


def _decide_delivery_review(
        review, final, choice, ack, expected, now, ports):
    if final.get("status") == "review_pending":
        return _decide_final_review(
            review, final, choice, ack, expected, now, ports)
    if final.get("status") == "commit_recovery":
        return _decide_final_recovery(
            review, final, choice, ack, ports)
    return None


def _decide_intermediate(
        updated, current, choice, ack, expected,
        now, ports, config):
    item = _current_item(updated)
    if item and item.get("status") == "commit_recovery":
        return _decide_checkpoint_recovery(
            updated, item, choice, ack, ports)
    if not item or item.get("status") != "review_pending":
        return _failure(
            "当前没有处于 review_pending 的中间检查点；"
            "执行 checkpoint status 查看。")
    ok, why = ports.verify_ack(item.get("receipt") or {}, expected)
    if not ok:
        return _failure("检查点用户裁决验真失败:" + why)
    if choice == "revise":
        return _revise_checkpoint(
            updated, item, current, ack, now)
    if updated.get("review_before_commit"):
        return _confirm_worktree(
            updated, item, current, choice, ack, now, config, ports)
    if choice == "continuous":
        return _switch_continuous(
            updated, item, current, ack, now, ports)
    return _accept_legacy_checkpoint(
        updated, item, current, ack, now, ports)


def _decide_final_review(
        review, final, choice, ack, expected, now, ports):
    ok, why = ports.verify_ack(final, expected)
    if not ok:
        return _failure("检查点用户裁决验真失败:" + why)
    if choice == "continuous":
        return _failure("最终检视已经是统一收尾，不能再切换为连续模式。")
    if choice == "revise":
        return _success(
            effects=(DeliveryEffect("activate_final_rework", {
                "note": ack,
                "show_current": True,
            }),),
        )
    receipt_head = final.get("head", "")
    if ports.head() != receipt_head:
        return _failure(
            "最终检视期间 HEAD 已变化，旧确认不能背书新版本；"
            "先选择调整并重新验证。")
    if final.get("remote_ref"):
        ref, remote_head, local_head = ports.upstream()
        if ref != final.get("remote_ref") or remote_head != local_head:
            return _failure(
                "远端检查点在检视期间发生变化，拒绝确认旧远端收据。")
    if final.get("requires_commit"):
        fresh, why = ports.worktree_fresh(final)
        if not fresh:
            return _failure("最终检视收据已失效:" + why)
        final["status"] = "commit_pending"
        final["confirmed_at"] = now
        return _success(effects=(
            _set_review(review),
            _history(
                "delivery_review",
                "checkpoint:confirmed-final-worktree",
                ack,
                now,
            ),
            DeliveryEffect("show_final_review", {}),
        ))
    dirty = dict(ports.final_snapshot(receipt_head))
    if dirty:
        return _failure(
            "最终检视收据已失效:检视期间又出现交付代码变化："
            + "、".join(list(dirty)[:8]))
    review["last_reviewed_head"] = receipt_head
    final["status"] = "accepted"
    final["accepted_at"] = now
    review.pop("final_rework", None)
    return _success(
        effects=(
            _set_review(review),
            _history(
                "delivery_review",
                "checkpoint:accept-final",
                ack,
                now,
            ),
        ),
        stdout=(
            "[mae-flow] 最终代码增量已确认。"
            "执行 done 进入规格定稿/最终 push。",
        ),
    )


def _decide_final_recovery(review, final, choice, ack, ports):
    if choice != "revise":
        return _failure(
            "错误的最终增量提交不能直接放行；"
            "只能选择「需要调整代码」。")
    ok, why = ports.verify_ack(final, REVISE_ACK)
    if not ok:
        return _failure("最终提交恢复裁决验真失败:" + why)
    base = str((final.get("receipt") or {}).get("base", ""))
    head = ports.head()
    pushed_ref = ports.upstream_contains(base, head)
    if pushed_ref:
        return _failure(
            "待拆回的最终增量提交已经存在于上游 %s，"
            "不能自动改写远端历史。请让用户决定追加纠正提交、"
            "另开分支或由管理员处理；禁止 force-push。" % pushed_ref)
    final["status"] = "reset_pending"
    final["recovery_ack"] = ack
    return _success(
        effects=(_set_review(review),),
        stdout=(
            "[mae-flow] 用户已选择调整。执行：",
            "  git reset --mixed " + base,
            "完成后执行 checkpoint status；文件内容会保留并回到完整质量链。",
        ),
    )


def _decide_checkpoint_recovery(
        review, item, choice, ack, ports):
    if choice != "revise":
        return _failure(
            "错误提交不能用“继续”放行；只能让用户选择"
            "「需要调整代码」后安全拆回工作区。")
    ok, why = ports.verify_ack(item.get("receipt") or {}, REVISE_ACK)
    if not ok:
        return _failure("检查点恢复裁决验真失败:" + why)
    base = str((item.get("receipt") or {}).get("base", ""))
    head = ports.head()
    pushed_ref = ports.upstream_contains(base, head)
    if pushed_ref:
        return _failure(
            "错误提交已经存在于上游 %s，不能自动改写远端历史。"
            "请让用户决定追加纠正提交、另开分支或由仓库管理员处理；"
            "当前继续冻结，禁止 force-push。" % pushed_ref)
    item["status"] = "reset_pending"
    item["recovery_ack"] = ack
    return _success(
        effects=(_set_review(review),),
        stdout=(
            "[mae-flow] 用户已选择调整。执行：",
            "  git reset --mixed " + base,
            "该命令只撤销尚未推送的错误检查点提交，"
            "文件内容保留在工作区；完成后执行 checkpoint status 返回 coding。",
        ),
    )


def _revise_checkpoint(review, item, current, ack, now):
    item["status"] = "coding"
    item["attempt"] = int(item.get("attempt", 1)) + 1
    for key in ("receipt", "head", "compile_head", "compile_task_sha256"):
        item.pop(key, None)
    return _success(
        effects=(
            _set_review(review),
            DeliveryEffect("invalidate_quality", {}),
            _history(
                current,
                "checkpoint:revise:" + item["id"],
                ack,
                now,
            ),
        ),
        stdout=(
            "[mae-flow] %s 返回修改；固定基点仍为 %s，"
            "修复后会重新展示整批组合差异。"
            % (item["id"], str(item.get("fixed_base", ""))[:10]),
        ),
    )


def _confirm_worktree(
        review, item, current, choice, ack, now, config, ports):
    fresh, why = ports.worktree_fresh(item)
    if not fresh:
        return _failure(
            "检查点收据已失效:" + why
            + "；旧确认不能背书另一份未提交 diff。")
    item["status"] = "commit_pending"
    item["confirmed_at"] = now
    item["after_commit_continuous"] = choice == "continuous"
    add, commit = commit_commands(item, config)
    output = []
    if choice == "continuous":
        output.append(
            "[mae-flow] 用户选择后续统一检视；当前工作区快照已冻结，"
            "先形成可追踪的内部检查点提交，之后不 push、不再停顿。")
    else:
        output.append(
            "[mae-flow] 用户已确认未提交 diff。"
            "现在只提交刚才检视过的精确文件：")
    output.extend(("  " + add, "  " + commit))
    output.append(
        "提交成功后执行 checkpoint status；"
        "系统会逐文件核对提交内容与检视快照，"
        + (
            "然后进入连续开发。"
            if choice == "continuous"
            else "相等后才允许小步 push。"
        ))
    return _success(
        effects=(
            _set_review(review),
            _history(
                current,
                "checkpoint:confirmed-worktree:" + item["id"],
                ack,
                now,
            ),
        ),
        stdout=output,
    )


def _switch_continuous(
        review, item, current, ack, now, ports):
    fresh, why = ports.source_fresh(item.get("compile_head", ""))
    if not fresh:
        return _failure(
            "切换一次完成模式前，当前批编译收据已失效:"
            + why + "。先选择调整并重新编译。")
    completed_head = ports.head()
    review["mode"] = "continuous"
    item["status"] = "completed"
    item["completed_head"] = completed_head
    item["closed_at"] = now
    item.pop("receipt", None)
    review["current_index"] = int(review.get("current_index", 0)) + 1
    next_item = _current_item(review)
    if next_item:
        next_item["fixed_base"] = completed_head
    suffix = (
        "进入 " + next_item["id"] + "，"
        if next_item else "全部检查点已完成，"
    )
    return _success(
        effects=(
            _set_review(review),
            _history(
                current,
                "checkpoint:switch-continuous",
                ack,
                now,
            ),
        ),
        stdout=(
            "[mae-flow] 已切换为一次完成模式。"
            "当前批的有效编译结果已保留，但不会冒充用户已检视；"
            + suffix
            + "质量链结束后从上一个已确认 HEAD 统一检视。",
        ),
    )


def _accept_legacy_checkpoint(
        review, item, current, ack, now, ports):
    receipt = item.get("receipt") or {}
    receipt_head = receipt.get("head", "")
    if ports.head() != receipt_head:
        return _failure(
            "检视期间 HEAD 已变化；旧远端收据失效，"
            "选择调整后重新编译、push、检视。")
    fresh, why = ports.source_fresh(receipt_head)
    if not fresh:
        return _failure("检查点收据已失效:" + why)
    ref, remote_head, local_head = ports.upstream()
    if (ref != receipt.get("remote_ref")
            or remote_head != receipt_head
            or local_head != receipt_head):
        return _failure(
            "检视期间本地或远端分支发生变化；拒绝确认旧收据。")
    item["status"] = "accepted"
    item["accepted_head"] = receipt_head
    item["accepted_at"] = now
    review["last_reviewed_head"] = receipt_head
    review["current_index"] = int(review.get("current_index", 0)) + 1
    next_item = _current_item(review)
    if next_item:
        next_item["fixed_base"] = receipt_head
    return _success(
        effects=(
            _set_review(review),
            _history(
                current,
                "checkpoint:accept:" + item["id"],
                ack,
                now,
            ),
        ),
        stdout=(
            "[mae-flow] %s 已确认并冻结远端收据。%s"
            % (
                item["id"],
                "进入 " + next_item["id"]
                if next_item else "全部计划检查点已完成",
            ),
        ),
    )
