"""Recovery for checkpoints committed by older bypassable runtimes."""

from mae_flow_core.delivery.models import DeliveryEffect, DeliveryResult


def _failure(message):
    return DeliveryResult(
        effects=(), stdout=(), stderr=(message,), exit_code=2)


def ready_recovered_precommit(
        review, item, base, head, agent_tasks, ports):
    dirty = tuple(ports.dirty_paths())
    if dirty:
        return _failure(
            "旧版本绕过检查点后已有提交，但当前仍有未提交交付文件: "
            + "、".join(dirty[:8])
            + "。先归因处理，再重新编译并 ready。")
    if not ports.has_commit(base, head):
        return _failure(
            "旧版本恢复标记存在，但固定基点后没有可检视提交。")
    ok, why = ports.commit_tagged()
    if not ok:
        return _failure("旧版本恢复提交格式不合规:" + why)
    source_files = tuple(ports.source_files(base, head))
    task = (agent_tasks or {}).get("COMPILE", {})
    if source_files:
        if task.get("checkpoint") != item["id"]:
            return _failure(
                "恢复后的编译任务没有绑定当前检查点 %s；"
                "重新执行 agent-task compile --checkpoint %s。"
                % (item["id"], item["id"]))
        ok, why = ports.agent_evidence()
        if not ok:
            return _failure("恢复后的检查点编译证据不足:" + why)
    snapshot = dict(ports.delivery_snapshot(base))
    item.update({
        "compile_head": head,
        "compile_task_sha256": (
            task.get("sha256", "") if source_files else ""),
        "compile_skipped_no_source": not source_files,
        "compile_source_sha256": ports.snapshot_sha256(snapshot),
        "head": head,
        "receipt": {
            "base": base,
            "head": head,
            "snapshot": snapshot,
            "snapshot_sha256": ports.snapshot_sha256(snapshot),
            "precommitted_recovery": True,
            "ack_cursor": ports.ack_cursor(),
            "at": ports.now(),
        },
        "status": "review_pending",
        "compiled_at": ports.now(),
    })
    return DeliveryResult(
        effects=(
            DeliveryEffect("set_development_review", review),
            DeliveryEffect("show_checkpoint_review", item),
        ),
        stdout=(
            "[mae-flow] 检测到旧版本已绕过 CP 并产生本地提交；"
            "已保留现场并恢复为本地用户检视，禁止 amend 或提前 push。",
        ),
        stderr=(),
        exit_code=0,
    )
