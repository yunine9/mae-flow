"""Checkpoint delivery use cases.

This module owns request validation and result construction.  Entrypoints
provide external facts through narrow, lazy ports and apply returned effects.
"""

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

from mae_flow_core.delivery.models import DeliveryEffect, DeliveryResult
from mae_flow_core.workflow.advancement import PACE_STEPS


@dataclass(frozen=True)
class CheckpointPlanPorts:
    dirty_paths: Callable[[], object]
    task_structure: Callable[[], object]
    head: Callable[[], str]
    ack_cursor: Callable[[], object]
    now: Callable[[], str]


@dataclass(frozen=True)
class CheckpointReadyPorts:
    head: Callable[[], str]
    object_type: Callable[[str], str]
    merge_base: Callable[[str, str], str]
    worktree_snapshot: Callable[[], object]
    is_source_path: Callable[[str], bool]
    agent_evidence: Callable[[], object]
    snapshot_sha256: Callable[[object], str]
    ack_cursor: Callable[[], object]
    now: Callable[[], str]
    task_structure_drift: Callable[[], bool]
    dirty_paths: Callable[[], object]
    has_commit: Callable[[str, str], bool]
    commit_tagged: Callable[[], object]
    source_files: Callable[[str, str], object]


def _failure(message):
    return DeliveryResult(
        effects=(),
        stdout=(),
        stderr=(message,),
        exit_code=2,
    )


def plan_checkpoint(
        current, workflow, moonlight, raw_items, ports):
    """Validate and create a checkpoint plan without mutating state."""
    if current not in PACE_STEPS:
        return _failure(
            "checkpoint plan 只允许在开发节奏确认步骤执行；"
            "先按 current 完成方案/范围分析。")
    if moonlight:
        return _failure(
            "月光宝盒不需要人工开发节奏方案；状态机会自动旁路本步骤。")
    items = [
        re.sub(r"\s+", " ", str(item or "")).strip()
        for item in (raw_items or ())
    ]
    if not 1 <= len(items) <= 6 or any(
            len(item) < 2 for item in items):
        return _failure(
            "检查点必须给出 1-6 个非空 --item；"
            "小改可 1 个，常规任务建议 2-4 个。")
    if len(set(items)) != len(items):
        return _failure(
            "检查点标题/范围不能重复；请写出各批次可区分的业务边界。")

    dirty = tuple(ports.dirty_paths())
    if dirty:
        return _failure(
            "开发节奏必须在写第一行代码前确认；当前已有本轮未提交源码: "
            + "、".join(dirty[:8])
            + "。先归因并处理，再重新生成方案。")

    task_sha, task_lines = ports.task_structure()
    head = ports.head()
    checkpoints = [
        {
            "id": "CP%d" % (index + 1),
            "title": title,
            "status": "planned",
        }
        for index, title in enumerate(items)
    ]
    plan_body = json.dumps({
        "head": head,
        "task_sha256": task_sha,
        "items": [
            {"id": item["id"], "title": item["title"]}
            for item in checkpoints
        ],
    }, ensure_ascii=False, sort_keys=True)
    review = {
        "version": 1,
        "review_before_commit": True,
        "status": "plan_pending",
        "plan_step": current,
        "plan_head": head,
        "plan_sha256": hashlib.sha256(
            plan_body.encode("utf-8")).hexdigest(),
        "task_structure_sha256": task_sha,
        "task_count": len(task_lines),
        "ack_cursor": ports.ack_cursor(),
        "no_code_plan": workflow == "review" and not task_lines,
        "checkpoints": checkpoints,
        "created_at": ports.now(),
    }
    output = [
        "[mae-flow] 开发检查点方案（确认前尚未开始写码）",
        "  代码基点: " + head[:10],
        "  实现/评审任务数: %d（勾选状态和备注不计入结构指纹）"
        % len(task_lines),
    ]
    output.extend(
        "  %s — %s" % (item["id"], item["title"])
        for item in checkpoints
    )
    output.extend((
        "\n用 AskUserQuestion 提供三个固定选项：",
        "  - 按检查点分阶段开发、检视确认后提交并推送",
        "  - 一次完成全部代码，最终统一检视",
        "  - 调整检查点划分",
        "用户点选后执行 done --choice staged|continuous|adjust；"
        "月光宝盒不会进入此确认。",
    ))
    return DeliveryResult(
        effects=(DeliveryEffect(
            "set_development_review", review),),
        stdout=tuple(output),
        stderr=(),
        exit_code=0,
    )


def _review_decision_lines():
    return (
        "\n展示完整 diff、关键风险和自验证方式后，用 AskUserQuestion 提供：",
        "  - 我已认真检视并完成自验证，继续",
        "  - 需要调整代码",
        "  - 当前批次先不确认，剩余代码一次完成后统一检视",
        "点选后执行 checkpoint decide continue|revise|continuous "
        '--ack "用户选择原文"。',
    )


def _review_effect(review):
    return DeliveryEffect("set_development_review", review)


def ready_checkpoint(
        review, current, workflow, moonlight, checkpoint_id,
        agent_tasks, ports):
    """Close compilation for the current checkpoint."""
    failure, index = _ready_request_failure(
        review, current, workflow, moonlight, checkpoint_id)
    if failure:
        return failure
    updated = deepcopy(review)
    item = updated.get("checkpoints", [])[index]
    base = str(item.get("fixed_base") or updated.get("delivery_base") or "")
    head = ports.head()
    history_failure = _ready_history_failure(base, head, ports)
    if history_failure:
        return history_failure
    mode = updated.get("mode")
    if mode == "staged" and bool(updated.get("review_before_commit")):
        return _ready_precommit(
            updated, item, base, head, agent_tasks, ports)
    return _ready_committed(
        updated, item, base, head, mode, agent_tasks, ports)


def _ready_request_failure(
        review, current, workflow, moonlight, checkpoint_id):
    if not review or review.get("status") != "active":
        return _failure(
            "当前没有已确认的开发检查点方案；"
            "旧版在途流程继续按原有 review 节点执行。"), -1
    if moonlight:
        return _failure(
            "月光宝盒不执行人工检查点；继续按当前质量链无人值守推进。"), -1
    expected_step = {
        "full": "build",
        "hotfix": "build",
        "tweak": "tw_change",
        "review": "rf_fix",
    }.get(workflow, "")
    if current != expected_step:
        return _failure(
            "checkpoint ready 只允许在本工作流编码步骤 %s 执行；当前为 %s。"
            % (expected_step or "(未知)", current)), -1
    items = review.get("checkpoints") or []
    index = int(review.get("current_index", 0) or 0)
    item = items[index] if 0 <= index < len(items) else None
    if not item or item.get("id") != checkpoint_id:
        return _failure(
            "当前应处理 %s，不是 %s。先执行 checkpoint status 查看计划。"
            % ((item or {}).get("id", "无剩余检查点"), checkpoint_id)), -1
    if item.get("status") not in ("coding",):
        return _failure(
            "%s 当前状态为 %s，不能重复 ready；"
            "执行 checkpoint status 查看下一步。"
            % (item["id"], item.get("status", "未知"))), -1
    return None, index


def _ready_history_failure(base, head, ports):
    if (not base or ports.object_type(base) != "commit"
            or ports.merge_base(base, head) != base):
        return _failure(
            "检查点固定基点不在当前历史上，可能发生 rebase/reset；"
            "不能用改写后的历史冒充原检查点。")
    return None


def _ready_precommit(review, item, base, head, agent_tasks, ports):
    if head != base:
        return _failure(
            "%s 使用“先检视、后提交”，但固定基点之后已经产生提交。"
            "旧提交不能冒充 IDE 未提交 diff；保留现场并让用户决定如何归因，"
            "不要 amend/reset 自动改写历史。" % item["id"])
    snapshot = dict(ports.worktree_snapshot())
    if not snapshot:
        return _failure(
            "%s 没有本轮未提交交付差异；空批次应调整或合并，"
            "不要制造空检视。" % item["id"])
    source_paths = [
        path for path in snapshot if ports.is_source_path(path)
    ]
    task = (agent_tasks or {}).get("COMPILE", {})
    if source_paths:
        if (task.get("checkpoint") != item["id"]
                or not task.get("precommit_review")):
            return _failure(
                "最后一次编译任务没有绑定当前未提交检查点 %s。"
                "先执行 agent-task compile --checkpoint %s "
                '--scope "<本批模块/任务>"，再启动 compile-agent。'
                % (item["id"], item["id"]))
        ok, why = ports.agent_evidence()
        if not ok:
            return _failure("检查点编译证据不足:" + why)
    snapshot = dict(ports.worktree_snapshot())
    receipt = {
        "base": head,
        "snapshot": snapshot,
        "snapshot_sha256": ports.snapshot_sha256(snapshot),
        "ack_cursor": ports.ack_cursor(),
        "at": ports.now(),
    }
    item.update({
        "compile_head": head,
        "compile_task_sha256": (
            task.get("sha256", "") if source_paths else ""),
        "compile_skipped_no_source": not source_paths,
        "head": head,
        "receipt": receipt,
        "status": "review_pending",
        "task_structure_drift": ports.task_structure_drift(),
        "closed_at": ports.now(),
    })
    stdout = []
    if item.get("task_structure_drift"):
        stdout.append(
            "⚠ 实现清单结构在开发中发生变化，"
            "请重点核对新增/删除任务是否仍符合确认范围。")
    stdout.extend(_review_decision_lines())
    return DeliveryResult(
        effects=(
            _review_effect(review),
            DeliveryEffect("render_worktree_review", item),
        ),
        stdout=tuple(stdout),
        stderr=(),
        exit_code=0,
    )


def _ready_committed(
        review, item, base, head, mode, agent_tasks, ports):
    dirty = tuple(ports.dirty_paths())
    if dirty:
        return _failure(
            "检查点编译收尾前仍有未提交源码/测试/构建文件: "
            + "、".join(dirty[:8])
            + "。只精确提交本批应入库文件后重试。")
    if not ports.has_commit(base, head):
        return _failure(
            "%s 自固定基点后没有新提交；"
            "空批次应调整/合并检查点，不制造空检视。" % item["id"])
    ok, why = ports.commit_tagged()
    if not ok:
        return _failure("检查点最新提交格式不合规:" + why)
    source_files = tuple(ports.source_files(base, head))
    task = (agent_tasks or {}).get("COMPILE", {})
    if source_files:
        if task.get("checkpoint") != item["id"]:
            return _failure(
                "最后一次编译任务没有绑定当前检查点 %s。"
                "先执行 agent-task compile --checkpoint %s "
                '--scope "<本批模块/任务>"，再启动 compile-agent。'
                % (item["id"], item["id"]))
        ok, why = ports.agent_evidence()
        if not ok:
            return _failure("检查点编译证据不足:" + why)
    item.update({
        "compile_head": head,
        "compile_task_sha256": (
            task.get("sha256", "") if source_files else ""),
        "compile_skipped_no_source": not source_files,
        "head": head,
        "task_structure_drift": ports.task_structure_drift(),
        "closed_at": ports.now(),
    })
    stdout = []
    if mode == "continuous":
        item["status"] = "completed"
        item["completed_head"] = head
        review["current_index"] = int(
            review.get("current_index", 0)) + 1
        next_index = review["current_index"]
        next_item = (
            review.get("checkpoints", [])[next_index]
            if next_index < len(review.get("checkpoints", []))
            else None
        )
        if next_item:
            next_item["fixed_base"] = head
        stdout.append(
            "[mae-flow] %s 已编译并记录范围 %s..%s；"
            "连续模式不 push、不等待，直接进入%s。"
            % (
                item["id"], base[:10], head[:10],
                (" " + next_item["id"])
                if next_item else "编码收尾",
            ))
        if item.get("task_structure_drift"):
            stdout.append(
                "⚠ 实现清单结构较确认时有变化，最终检视会显式标注；"
                "若业务边界发生实质变化，应主动呈用户调整计划。")
    else:
        item["status"] = "push_pending"
        stdout.extend((
            "[mae-flow] %s 编译通过，已冻结候选范围 %s..%s。现在小步推送："
            % (item["id"], base[:10], head[:10]),
            "  git push -u origin HEAD",
            "推送成功后执行 checkpoint status；"
            "系统会核对真实上游 HEAD 后才开始检视。",
        ))
    return DeliveryResult(
        effects=(_review_effect(review),),
        stdout=tuple(stdout),
        stderr=(),
        exit_code=0,
    )
