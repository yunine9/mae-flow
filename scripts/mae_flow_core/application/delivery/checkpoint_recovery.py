"""Checkpoint commit, push, and recovery orchestration."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

from mae_flow_core.delivery.models import DeliveryEffect, DeliveryResult
from mae_flow_core.application.delivery.checkpoint_ready_recovery import (
    activate_next_checkpoint,
)


@dataclass(frozen=True)
class CheckpointRecoveryPorts:
    head: Callable[[], str]
    current_snapshot: Callable[[object], object]
    upstream: Callable[[], object]
    source_fresh: Callable[[str], object]
    merge_base: Callable[[str, str], str]
    commit_paths: Callable[[str], object]
    commit_count: Callable[[str], str]
    dirty_paths: Callable[[], object]
    commit_tagged: Callable[[], object]
    commit_commands: Callable[[object], object]
    ack_cursor: Callable[[], object]
    now: Callable[[], str]
    rework_target: Callable[[], str]
    reopen_spec_archive: Callable[[object], object]


def _result(effects=(), stdout=(), stderr=(), exit_code=0):
    return DeliveryResult(
        effects=tuple(effects),
        stdout=tuple(stdout),
        stderr=tuple(stderr),
        exit_code=exit_code,
    )


def _failure(message, effects=()):
    return _result(
        effects=effects, stderr=(message,), exit_code=2)


def _set_review(review):
    return DeliveryEffect("set_development_review", review)


def _current_item(review):
    items = review.get("checkpoints") or []
    index = int(review.get("current_index", 0) or 0)
    return items[index] if 0 <= index < len(items) else None


def reviewed_worktree_fresh(item, head, snapshot):
    receipt = item.get("receipt") or {}
    if head != str(receipt.get("base", "")):
        return False, "HEAD 已变化"
    if dict(snapshot) != (receipt.get("snapshot") or {}):
        return False, "未提交 diff 已变化"
    return True, ""


def _commit_head_error(item, head, ports):
    base = str((item.get("receipt") or {}).get("base", ""))
    if head == base:
        add, commit = ports.commit_commands(item)
        return (
            "用户已确认，但检视代码尚未提交。依次执行:\n"
            "  %s\n  %s" % (add, commit))
    return ""


def _path_set_error(expected, actual):
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    details = []
    if missing:
        details.append("漏掉 " + "、".join(missing[:8]))
    if extra:
        details.append("夹带 " + "、".join(extra[:8]))
    return "提交文件集合不等于检视收据：" + "；".join(details)


def _commit_error(item, head, ports):
    receipt = item.get("receipt") or {}
    base = str(receipt.get("base", ""))
    if head == base:
        return _commit_head_error(item, head, ports)
    if ports.merge_base(base, head) != base:
        return (
            "提交历史已改写，旧检视收据失效；"
            "禁止自动 reset/rebase")
    expected = set((receipt.get("snapshot") or {}).keys())
    snapshot = dict(ports.current_snapshot(item))
    if snapshot != (receipt.get("snapshot") or {}):
        return (
            "提交后的代码不等于用户检视快照；拒绝继续。"
            "保留现场并展示差异，不要自动 amend/reset")
    actual = set(ports.commit_paths(base))
    if actual != expected:
        return _path_set_error(expected, actual)
    count = ports.commit_count(base)
    if count != "1":
        return (
            "每个检视检查点必须对应 1 个精确提交，当前产生 %s 个"
            % (count if count else "不可核实"))
    dirty = sorted(expected.intersection(ports.dirty_paths()))
    if dirty:
        return "用户已检视文件仍有未提交变化: " + "、".join(
            dirty[:8])
    ok, why = ports.commit_tagged()
    if not ok:
        return "检视后提交格式不合规:" + why
    return ""


def _accept_checkpoint(
        review, item, current, head, now, pushed_message):
    item["status"] = "accepted"
    item["accepted_head"] = head
    item["accepted_at"] = now
    item["closed_at"] = now
    review["last_reviewed_head"] = head
    review["current_index"] = int(
        review.get("current_index", 0)) + 1
    next_item = _current_item(review)
    activate_next_checkpoint(review, next_item, head)
    suffix = (
        "进入 " + next_item["id"]
        if next_item else "全部计划检查点已完成")
    history = DeliveryEffect("append_history", {
        "step": current,
        "result": "checkpoint:accept:" + item["id"],
        "note": "我已认真检视并完成自验证，继续",
        "at": now,
    })
    return _result(
        effects=(_set_review(review), history),
        stdout=(pushed_message % (item["id"], suffix),),
    )


def _complete_continuous(review, item, head, now):
    review["mode"] = "continuous"
    item["status"] = "completed"
    item["completed_head"] = head
    item["closed_at"] = now
    review["current_index"] = int(
        review.get("current_index", 0)) + 1
    next_item = _current_item(review)
    activate_next_checkpoint(review, next_item, head)
    message = (
        "已切换为一次完成模式；当前内部提交将在质量链后"
        "与剩余代码统一检视。"
        + (
            "进入 " + next_item["id"]
            if next_item else "全部检查点已完成"
        )
    )
    return _result(
        effects=(_set_review(review),),
        stdout=(message,),
    )


def _refresh_commit_pending(review, item, current, ports):
    head = ports.head()
    error = _commit_error(item, head, ports)
    base = str((item.get("receipt") or {}).get("base", ""))
    if error and head == base:
        return _result(stdout=("[mae-flow] " + error,))
    if error:
        item["status"] = "commit_recovery"
        item["verification_error"] = error
        item.setdefault("receipt", {})[
            "ack_cursor"] = ports.ack_cursor()
        return _result(
            effects=(_set_review(review),),
            stdout=(
                "[mae-flow] 提交核验失败，已禁止 push，现场保持不变："
                + error,
                "把失败原因和真实 git diff 展示给用户，"
                "让用户选择「需要调整代码」；随后执行 checkpoint "
                "decide revise。",
            ),
        )
    now = ports.now()
    item["head"] = head
    item["committed_at"] = now
    if item.pop("after_commit_continuous", False):
        return _complete_continuous(review, item, head, now)
    ref, remote_head, local_head = ports.upstream()
    if ref and remote_head == local_head == head:
        return _accept_checkpoint(
            review, item, current, head, now,
            "%s 的检视快照、精确提交和已存在的远端 push "
            "均已核对。%s")
    item["status"] = "push_pending"
    return _result(
        effects=(_set_review(review),),
        stdout=(
            "检视确认后的精确提交已核对。现在执行 "
            "git push -u origin HEAD；成功后再执行 checkpoint status。",
        ),
    )


def _refresh_reset_pending(review, item, ports):
    base = str((item.get("receipt") or {}).get("base", ""))
    if ports.head() != base:
        return _failure(
            "恢复尚未完成；执行 git reset --mixed %s，"
            "它只撤销未推送的错误检查点提交并保留工作区内容。"
            % base)
    item["status"] = "coding"
    item["attempt"] = int(item.get("attempt", 1)) + 1
    for key in (
            "receipt", "head", "compile_head",
            "compile_task_sha256", "verification_error"):
        item.pop(key, None)
    return _result(
        effects=(
            _set_review(review),
            DeliveryEffect("invalidate_quality", {}),
        ),
        stdout=(
            "[mae-flow] 错误提交已安全拆回工作区，检查点返回 coding；"
            "调整代码后重新生成编译任务和检视收据。",
        ),
    )


def _push_error(item, ports):
    receipt = item.get("receipt") or {}
    head = str(item.get("head", ""))
    if ports.head() != head:
        return "检视后待推送 HEAD 已变化；旧收据不能背书新提交"
    if dict(ports.current_snapshot(item)) != (
            receipt.get("snapshot") or {}):
        return "待推送代码不再等于用户检视快照；拒绝继续"
    ref, remote_head, local_head = ports.upstream()
    if not ref:
        return "当前分支没有上游；执行 git push -u origin HEAD"
    if remote_head != local_head or local_head != head:
        return (
            "本地与上游不一致（本地 %s，%s=%s）。执行普通 git push；"
            "远端领先时禁止自动 rebase/force-push，先展示分叉。"
            % (
                local_head[:10],
                ref,
                remote_head[:10] if remote_head else "未知",
            ))
    return ""


def _refresh_push_pending(review, item, current, ports):
    error = _push_error(item, ports)
    if error:
        return _failure(error)
    return _accept_checkpoint(
        review, item, current, str(item.get("head", "")),
        ports.now(), "%s 已确认、精确提交并推送。%s")


def _refresh_legacy_staged(review, item, ports):
    fresh, why = ports.source_fresh(
        str(item.get("compile_head", "")))
    if not fresh:
        item["status"] = "coding"
        item.pop("receipt", None)
        return _failure(
            "编译后" + why + "；已回到当前批次，重新提交并编译",
            (_set_review(review),))
    head = ports.head()
    item["head"] = head
    ref, remote_head, local_head = ports.upstream()
    if not ref:
        return _failure(
            "当前分支没有上游；执行 git push -u origin HEAD",
            (_set_review(review),))
    if remote_head != local_head:
        return _failure(
            "本地与上游不一致（本地 %s，%s=%s）。执行普通 git push；"
            "若远端领先，禁止自动 rebase/force-push，先展示分叉。"
            % (
                local_head[:10], ref,
                remote_head[:10] if remote_head else "未知",
            ),
            (_set_review(review),))
    item["status"] = "review_pending"
    item["receipt"] = {
        "base": item.get("fixed_base", ""),
        "head": local_head,
        "remote_ref": ref,
        "remote_head": remote_head,
        "ack_cursor": ports.ack_cursor(),
        "at": ports.now(),
    }
    return _result(effects=(
        _set_review(review),
        DeliveryEffect("show_checkpoint_review", {}),
    ))


def refresh_checkpoint(review, current, ports):
    """Refresh one intermediate checkpoint from external repository facts."""
    updated = deepcopy(review)
    item = _current_item(updated)
    if not item:
        return _failure("当前没有可刷新的检查点。")
    status = item.get("status")
    if updated.get("review_before_commit"):
        handlers = {
            "commit_pending": _refresh_commit_pending,
            "reset_pending": _refresh_reset_pending,
            "push_pending": _refresh_push_pending,
        }
        handler = handlers.get(status)
        if handler is None:
            return _result(effects=(
                DeliveryEffect("show_checkpoint_review", {}),))
        if status == "reset_pending":
            return handler(updated, item, ports)
        return handler(updated, item, current, ports)
    if updated.get("mode") == "staged" and status == "push_pending":
        return _refresh_legacy_staged(updated, item, ports)
    return _result(effects=(
        DeliveryEffect("show_checkpoint_review", {}),))


def _activate_final_rework(state, context, ports):
    updated = deepcopy(state)
    review = updated.get("development_review") or {}
    final = review.get("final_review") or {}
    target = ports.rework_target()
    if not target:
        workflow = (
            (updated.get("choices") or {}).get(
                "workflow", ""))
        return _failure(
            "无法确定返工编码入口，workflow="
            + (workflow or "未设置"))
    reopened, why = ports.reopen_spec_archive(updated)
    if not reopened:
        return _failure(
            "最终检视返工无法回退规格验证阶段:" + why)
    reviewed_head = context.get("reviewed_head", "")
    if reviewed_head:
        review["last_reviewed_head"] = reviewed_head
    review.pop("final_review", None)
    review["final_rework"] = {
        "status": "coding",
        "base": final.get("base", ""),
        "rejected_head": final.get("head", ""),
        "at": ports.now(),
    }
    updated["current"] = target
    updated.setdefault("step_heads", {})[target] = (
        context.get("step_base") or ports.head())
    for key in (
            "unlock", "risk_acceptances",
            "agent_tasks", "quality"):
        updated.pop(key, None)
    updated.setdefault("history", []).append({
        "step": "delivery_review",
        "result": "checkpoint:rework-final",
        "note": context.get("note", ""),
        "at": ports.now(),
    })
    if reviewed_head:
        message = (
            "[mae-flow] 用户检视后的精确提交已核对；"
            "为防止未验证代码直达 push，已回到 %s "
            "重新执行编译和完整质量链。" % target)
    elif context.get("show_current"):
        message = (
            "[mae-flow] 用户要求调整最终代码，已回到 %s。"
            "修复提交后必须重新走编译和质量链；"
            "已检视基点不前移，最终会展示完整修复组合。"
            % target)
    else:
        message = (
            "[mae-flow] 错误提交已拆回工作区并保留文件内容；"
            "已回到 %s，调整后重新编译、检查和检视。"
            % target)
    effects = [
            DeliveryEffect("drop_quality_tokens", {}),
            DeliveryEffect("set_state", updated),
    ]
    if context.get("show_current"):
        effects.append(DeliveryEffect("print_current", {}))
    return _result(
        effects=tuple(effects),
        stdout=(message,),
    )


def activate_final_rework(state, context, ports):
    """Atomically construct the complete final-review rework state."""
    return _activate_final_rework(state, context or {}, ports)


def _final_commit(state, review, final, ports):
    head = ports.head()
    error = _commit_error(final, head, ports)
    base = str((final.get("receipt") or {}).get("base", ""))
    if error and head == base:
        return _result(stdout=("[mae-flow] " + error,))
    if error:
        final["status"] = "commit_recovery"
        final["verification_error"] = error
        final["ack_cursor"] = ports.ack_cursor()
        return _result(
            effects=(_set_review(review),),
            stdout=(
                "[mae-flow] 最终增量提交核验失败，已禁止 push，"
                "现场保持不变：" + error,
                "展示真实差异，让用户选择「需要调整代码」后执行 "
                "checkpoint decide revise。",
            ),
        )
    final["head"] = head
    final["status"] = "accepted"
    final["accepted_at"] = ports.now()
    if final.get("requires_quality_rerun"):
        updated = deepcopy(state)
        updated["development_review"] = review
        return _activate_final_rework(
            updated, {
                "note": "用户检视后的最终工作区提交已核对，"
                "重新执行完整质量链",
                "reviewed_head": head,
                "step_base": base,
            }, ports)
    review["last_reviewed_head"] = head
    return _result(
        effects=(_set_review(review),),
        stdout=(
            "[mae-flow] 最终检视提交已核对；"
            "执行 done 进入规格定稿/最终 push。",
        ),
    )


def _final_reset(state, review, final, ports):
    base = str((final.get("receipt") or {}).get("base", ""))
    if ports.head() != base:
        return _failure(
            "恢复尚未完成；执行 git reset --mixed %s。"
            "该命令保留工作区内容。" % base)
    updated = deepcopy(state)
    updated["development_review"] = review
    return _activate_final_rework(
        updated, {
            "note": "错误的最终增量提交已拆回工作区，"
            "重新执行完整质量链",
        }, ports)


def _migrate_final(review, final, ports):
    head = str(final.get("head") or ports.head())
    if ports.head() != head:
        return _failure(
            "旧版最终 push 状态的 HEAD 已变化，不能自动迁移旧收据；"
            "先展示历史差异让用户决定。")
    ref, remote_head, _local_head = ports.upstream()
    final["status"] = "review_pending"
    final["head"] = head
    final["remote_ref"] = ref if remote_head == head else ""
    final["remote_head"] = remote_head if remote_head == head else ""
    final["ack_cursor"] = ports.ack_cursor()
    return _result(
        effects=(
            _set_review(review),
            DeliveryEffect("show_final_review", {}),
        ),
        stdout=(
            "[mae-flow] 旧版最终状态已迁移为“本地先检视”；"
            "不再要求先 push。",
        ),
    )


def refresh_final_review(state, ports):
    """Refresh final review recovery without mutating caller state."""
    updated_state = deepcopy(state)
    updated = updated_state.get("development_review") or {}
    final = updated.get("final_review") or {}
    status = final.get("status")
    if status == "commit_pending":
        return _final_commit(
            updated_state, updated, final, ports)
    if status == "reset_pending":
        return _final_reset(
            updated_state, updated, final, ports)
    if status == "push_pending":
        return _migrate_final(updated, final, ports)
    return _result(effects=(
        DeliveryEffect("show_final_review", {}),))
