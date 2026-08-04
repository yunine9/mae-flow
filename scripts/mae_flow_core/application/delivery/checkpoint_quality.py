"""Plan-review and craft-review use cases for development checkpoints."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

from mae_flow_core.delivery.models import DeliveryEffect, DeliveryResult
from mae_flow_core.quality.spec2code_artifacts import (
    artifact_path,
    review_facts_sha256,
    review_has_findings,
    review_requires_human_decision,
    review_requires_rework,
    validate_plan,
    validate_review,
)


PLAN_CONTINUE_ACK = "当前 CP 编码计划已确认，继续"
PLAN_REVISE_ACK = "需要调整当前 CP 编码计划"
CRAFT_DECISION_ACK = "确认上述 Finding 处置"


@dataclass(frozen=True)
class CheckpointQualityPorts:
    is_file: Callable[[str], bool]
    read_text: Callable[[str], str]
    normalize_path: Callable[[str], str]
    digest: Callable[[str], str]
    ack_cursor: Callable[[], object]
    verify_ack: Callable[[object, str], object]
    role_task_sha: Callable[[str, str], str]
    registered_artifact_sha: Callable[[str], str]
    now: Callable[[], str]
    is_test_path: Callable[[str], bool] = lambda _path: False
    role_returned: Callable[[str, str], bool] = lambda _role, _checkpoint: False


def _failure(message):
    return DeliveryResult(
        effects=(), stdout=(), stderr=(message,), exit_code=2)


def _success(review, stdout, extra=()):
    return DeliveryResult(
        effects=(
            DeliveryEffect("set_development_review", review),
            *tuple(extra),
        ),
        stdout=tuple(stdout),
        stderr=(),
        exit_code=0,
    )


def _current(review, checkpoint):
    if not isinstance(review, dict) or review.get("version") not in (2, 3):
        return None
    items = review.get("checkpoints") or []
    index = int(review.get("current_index", 0) or 0)
    item = items[index] if 0 <= index < len(items) else None
    return item if item and item.get("id") == checkpoint else None


def _read_expected(path, expected, ports):
    normalized = ports.normalize_path(path)
    if normalized != expected:
        return None, "过程件必须使用规范路径 %s，收到 %s" % (
            expected, normalized)
    if not ports.is_file(path):
        return None, "过程件不存在: " + normalized
    try:
        return ports.read_text(path), ""
    except (OSError, UnicodeDecodeError) as exc:
        return None, "过程件读取失败: %s" % exc


def prepare_checkpoint_plan(
        review, checkpoint, plan_path, review_path, ticket, ports,
        moonlight=False):
    updated = deepcopy(review)
    item = _current(updated, checkpoint)
    if not item or item.get("status") != "planned":
        return _failure(
            "当前检查点不是等待计划展开的 %s。" % checkpoint)
    plan_text, why = _read_expected(
        plan_path, artifact_path("plan", ticket), ports)
    if why:
        return _failure(why)
    errors = validate_plan(
        plan_text,
        checkpoint,
        is_test_path=ports.is_test_path,
    )
    if errors:
        return _failure("当前 CP 计划结构校验失败: " + "；".join(errors))
    plan_sha256 = ports.digest(plan_text)
    if ports.registered_artifact_sha("plan") != plan_sha256:
        return _failure(
            "当前 CP 计划与已登记 plan 摘要不一致；"
            "重新登记 plan 并重新签发 PLAN Reviewer 任务卡。")
    review_text, why = _read_expected(
        review_path,
        artifact_path("review", ticket, checkpoint, "plan"),
        ports,
    )
    if why:
        return _failure(why)
    errors = validate_review(
        review_text,
        "plan",
        checkpoint,
        ports.role_task_sha("craft-plan", checkpoint),
        plan_sha256,
    )
    if errors:
        return _failure("PLAN Reviewer 记录校验失败: " + "；".join(errors))
    if moonlight and review_requires_human_decision(review_text):
        return _failure(
            "PLAN Reviewer 存在“人工裁决”项，月光宝盒不得代替用户拍板；"
            "执行 moonlight blocked --reason "
            '"<CP、Finding、候选方案和当前风险>"，保留现场到早晨处理。')
    if review_requires_rework(review_text):
        return _failure(
            "PLAN Reviewer 仍有待处理意见；先由主 Agent 核实并修订计划。")
    item["status"] = "plan_review_pending"
    item["plan_attempt"] = int(item.get("plan_attempt", 0) or 0) + 1
    item["plan_receipt"] = {
        "plan_path": ports.normalize_path(plan_path),
        "plan_sha256": ports.digest(plan_text),
        "review_path": ports.normalize_path(review_path),
        "review_sha256": ports.digest(review_text),
        "ack_cursor": ports.ack_cursor(),
        "at": ports.now(),
    }
    if updated.get("mode") == "continuous":
        item["status"] = "coding"
        item["plan_confirmed_at"] = ports.now()
        return _success(
            updated,
            (
                "[mae-flow] %s 细粒度计划与 PLAN 走读已冻结；"
                "连续模式按已选节奏直接进入编码。" % checkpoint,
            ),
        )
    return _success(
        updated,
        (
            "[mae-flow] %s 细粒度计划与 PLAN 走读已冻结，等待用户检视。"
            % checkpoint,
            "选项：%s / %s" % (PLAN_CONTINUE_ACK, PLAN_REVISE_ACK),
        ),
    )


def _plan_receipt_fresh(receipt, ports):
    for prefix in ("plan", "review"):
        path = str(receipt.get(prefix + "_path", "") or "")
        expected = str(receipt.get(prefix + "_sha256", "") or "")
        if not path or not expected or not ports.is_file(path):
            return False
        try:
            text = ports.read_text(path)
        except (OSError, UnicodeDecodeError):
            return False
        if ports.digest(text) != expected:
            return False
    return True


def decide_checkpoint_plan(review, choice, ports):
    updated = deepcopy(review)
    items = updated.get("checkpoints") or []
    index = int(updated.get("current_index", 0) or 0)
    item = items[index] if 0 <= index < len(items) else None
    if not item or item.get("status") != "plan_review_pending":
        return _failure("当前没有等待用户确认的 CP 编码计划。")
    expected = {
        "continue": PLAN_CONTINUE_ACK,
        "revise": PLAN_REVISE_ACK,
    }.get(choice)
    if expected is None:
        return _failure("计划裁决只能是 continue 或 revise。")
    receipt = item.get("plan_receipt") or {}
    if not _plan_receipt_fresh(receipt, ports):
        item["status"] = "planned"
        item.pop("plan_receipt", None)
        return _success(
            updated,
            (
                "[mae-flow] 已展示的 CP 计划或 PLAN Review 发生变化；"
                "旧确认收据已失效，必须重新登记、走读并展示。",
            ),
        )
    ok, why = ports.verify_ack(receipt, expected)
    if not ok:
        return _failure("CP 计划用户裁决验真失败:" + why)
    if choice == "continue":
        item["status"] = "coding"
        item["plan_confirmed_at"] = ports.now()
        message = "[mae-flow] %s 编码计划已确认，进入编码。" % item["id"]
    else:
        item["status"] = "planned"
        item.pop("plan_receipt", None)
        message = "[mae-flow] %s 返回计划修改；修订后重新走读和展示差异。" % item["id"]
    return _success(
        updated,
        (message,),
        extra=(DeliveryEffect("append_history", {
            "result": "checkpoint:plan-%s:%s" % (choice, item["id"]),
            "note": expected,
            "at": ports.now(),
        }),),
    )


def _validated_craft_text(
        review_path, ticket, checkpoint,
        target_sha256, ports, moonlight):
    text, why = _read_expected(
        review_path,
        artifact_path("review", ticket, checkpoint, "code"),
        ports,
    )
    if why:
        return "", why
    errors = validate_review(
        text,
        "code",
        checkpoint,
        ports.role_task_sha("craft-code", checkpoint),
        target_sha256,
    )
    if errors:
        return "", "CODE Reviewer 记录校验失败: " + "；".join(errors)
    if moonlight and review_requires_human_decision(text):
        return "", (
            "CODE Reviewer 存在“人工裁决”项，月光宝盒不得代替用户拍板；"
            "执行 moonlight blocked --reason "
            '"<CP、Finding、候选方案和当前风险>"，保留现场到早晨处理。')
    return text, ""


def _complete_continuous_craft(updated, item):
    item["status"] = "completed"
    item["completed_head"] = item.get("head", "")
    item["closed_at"] = item.get("reviewed_at", "")
    updated["current_index"] = int(
        updated.get("current_index", 0) or 0) + 1
    items = updated.get("checkpoints") or []
    index = updated["current_index"]
    if index < len(items):
        next_item = items[index]
        next_item["status"] = (
            "coding" if updated.get("version") == 3 else "planned")
        next_item["fixed_base"] = item.get("head", "")
    return _success(
        updated,
        (
            "[mae-flow] %s CODE 走读已闭环；连续模式进入下一 CP 计划。"
            % item.get("id", "当前 CP"),
        ),
    )


def record_craft_review(
        review, checkpoint, review_path, ticket,
        current_source_sha256, ports, moonlight=False):
    updated = deepcopy(review)
    item = _current(updated, checkpoint)
    if not item or item.get("status") != "craft_pending":
        if item and item.get("status") == "coding":
            return _failure(
                "%s 正在修复代码，旧 CODE Review 不能重复登记。"
                "修复并编译后先执行 checkpoint ready %s；"
                "已完成本 CP 的独立走读时，编译收据会直接进入用户检视，"
                "不会自动启动第二轮 Reviewer。"
                % (checkpoint, checkpoint))
        return _failure(
            "当前检查点不是等待 CODE 走读的 %s；"
            "先执行 checkpoint status 查看下一条精确指令。"
            % checkpoint)
    if item.get("compile_source_sha256") != current_source_sha256:
        return _failure(
            "源码摘要与首次编译收据不一致；重新编译后派新鲜 CODE Reviewer。")
    if updated.get("version") == 3:
        if not ports.role_returned("REVIEWER", checkpoint):
            return _failure(
                "当前检查点的 craft-reviewer-agent 尚未正常返回；"
                "先执行 role-task craft-code --checkpoint %s，"
                "按任务卡完成一次检视。" % checkpoint)
        item["craft_review_performed"] = True
        item["reviewed_at"] = ports.now()
        if updated.get("mode") == "continuous":
            return _complete_continuous_craft(updated, item)
        item["status"] = "review_pending"
        receipt = item.get("receipt")
        if isinstance(receipt, dict):
            receipt["ack_cursor"] = ports.ack_cursor()
        return _success(
            updated,
            ("[mae-flow] %s CODE 走读已返回；现在展示 CP 检视卡给用户。"
             % checkpoint,),
            extra=(DeliveryEffect("show_checkpoint_review", {}),),
        )
    text, why = _validated_craft_text(
        review_path,
        ticket,
        checkpoint,
        current_source_sha256,
        ports,
        moonlight,
    )
    if why:
        return _failure(why)
    item["craft_review"] = {
        "path": ports.normalize_path(review_path),
        "sha256": ports.digest(text),
        "facts_sha256": review_facts_sha256(text),
        "source_sha256": current_source_sha256,
        "ack_cursor": ports.ack_cursor(),
        "at": ports.now(),
    }
    item["craft_review_performed"] = True
    item["reviewed_at"] = ports.now()
    if review_has_findings(text):
        item["status"] = "craft_decision_pending"
        return _success(
            updated,
            (
                "[mae-flow] %s CODE Reviewer 提交了 Findings；"
                "已登记客观事实，尚未接受、关闭或交回修改。" % checkpoint,
                "主 Agent 逐条提出处置建议并展示给用户；只允许修改 Review "
                "文件中的“处置/状态”。用户选择“%s”后执行 "
                "checkpoint craft-decide %s --review \"%s\"。"
                % (CRAFT_DECISION_ACK, checkpoint, review_path),
            ),
        )
    if updated.get("mode") == "continuous":
        return _complete_continuous_craft(
            updated, item)
    item["status"] = "review_pending"
    receipt = item.get("receipt")
    if isinstance(receipt, dict):
        receipt["ack_cursor"] = ports.ack_cursor()
    return _success(
        updated,
        (
            "[mae-flow] %s CODE 走读已闭环；现在展示 CP 检视卡给用户。"
            % checkpoint,
        ),
        extra=(DeliveryEffect("show_checkpoint_review", {}),),
    )


def decide_craft_review(
        review, checkpoint, review_path, ticket,
        current_source_sha256, ports):
    """Apply user-confirmed Finding dispositions without changing facts."""
    updated = deepcopy(review)
    item = _current(updated, checkpoint)
    if not item or item.get("status") != "craft_decision_pending":
        return _failure(
            "当前没有等待用户裁决的 %s CODE Findings。"
            % checkpoint)
    receipt = item.get("craft_review") or {}
    reviewed_source_sha256 = str(
        receipt.get("source_sha256")
        or item.get("compile_source_sha256")
        or ""
    )
    text, why = _validated_craft_text(
        review_path,
        ticket,
        checkpoint,
        reviewed_source_sha256,
        ports,
        moonlight=False,
    )
    if why:
        return _failure(why)
    if ports.normalize_path(review_path) != receipt.get("path"):
        return _failure("Finding 裁决必须使用已展示的 Review 文件。")
    if review_facts_sha256(text) != receipt.get("facts_sha256"):
        return _failure(
            "Finding 的位置/依据/证据/影响/最小改法已变化；"
            "旧用户裁决收据失效，必须重新登记并展示。")
    if review_requires_human_decision(text):
        return _failure(
            "仍有 Finding 处于“待用户裁决/待裁决/人工裁决”；"
            "先逐条填写修改、验证后修改或拒绝/暂缓及对应状态，"
            "再展示给用户确认。")
    ok, why = ports.verify_ack(receipt, CRAFT_DECISION_ACK)
    if not ok:
        return _failure("CODE Finding 用户裁决验真失败:" + why)
    item["craft_review"].update({
        "sha256": ports.digest(text),
        "decided_at": ports.now(),
    })
    source_changed = current_source_sha256 != reviewed_source_sha256
    if review_requires_rework(text) or source_changed:
        return _resume_coding_after_craft_decision(
            updated, item, checkpoint, source_changed,
        )
    if updated.get("mode") == "continuous":
        return _complete_continuous_craft(updated, item)
    item["status"] = "review_pending"
    cp_receipt = item.get("receipt")
    if isinstance(cp_receipt, dict):
        cp_receipt["ack_cursor"] = ports.ack_cursor()
    return _success(
        updated,
        (
            "[mae-flow] %s Findings 已按用户裁决闭环；"
            "现在展示 CP 检视卡给用户。" % checkpoint,
        ),
        extra=(DeliveryEffect("show_checkpoint_review", {}),),
    )


def _resume_coding_after_craft_decision(
        updated, item, checkpoint, source_changed):
    item["status"] = "coding"
    item["craft_attempt"] = int(item.get("craft_attempt", 0) or 0) + 1
    item["craft_review_performed"] = True
    if source_changed:
        messages = (
            "[mae-flow] %s 用户已确认 Finding 处置；"
            "检测到源码已提前修改，已安全恢复到 coding。"
            % checkpoint,
            "旧编译证据已失效；保留当前修改并重新编译，随后执行 "
            "checkpoint ready %s 进入用户 CP 检视，"
            "不会自动启动第二轮 CODE Reviewer。" % checkpoint,
        )
    else:
        messages = (
            "[mae-flow] %s 用户已接受待处理 Finding，"
            "交回同一 CP Implementer 仅修改接受项。" % checkpoint,
            "修改后重新编译并执行 checkpoint ready %s；"
            "本 CP 已完成独立走读，将直接进入用户检视。"
            % checkpoint,
        )
    return _success(
        updated,
        messages,
        extra=(DeliveryEffect("invalidate_quality", {}),),
    )
