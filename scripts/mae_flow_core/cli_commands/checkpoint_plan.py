"""CLI responsibilities extracted from the historical entrypoint."""

from .shared import (
    CHECKPOINT_CODE_STEPS, CHECKPOINT_CONTINUE_ACK, CHECKPOINT_CONTINUOUS_ACK,
    CHECKPOINT_LOCKED_STATUSES, CHECKPOINT_REVISE_ACK, CheckpointPlanPorts,
    CheckpointReadyPorts, CheckpointRecoveryPorts, checkpoint_commit_commands,
    checkpoint_review_context, hashlib, os, plan_checkpoint, read_text,
    ready_checkpoint,
    reviewed_worktree_fresh, thaw_delivery_payload, time,
)
from .wiring import api

def _activate_checkpoint_plan(st, mode):
    data = api._development_review(st)
    head = api.sh("git rev-parse --verify HEAD")
    data.update({
        "status": "active",
        "mode": mode,
        "delivery_base": head,
        "last_reviewed_head": head,
        "current_index": 0,
        "configured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    no_code = bool(data.get("no_code_plan"))
    version = int(data.get("version", 1) or 1)
    for index, item in enumerate(data.get("checkpoints") or []):
        for key in ("head", "compile_head", "compile_task_sha256",
                    "receipt", "accepted_head", "completed_head"):
            item.pop(key, None)
        item["status"] = (
            ("accepted" if mode == "staged" else "completed")
            if no_code
            else ("coding" if version == 1 or index == 0 else "planned"))
        item["attempt"] = 1
        item["fixed_base"] = head if index == 0 else ""
        if no_code:
            item["completed_head"] = head
            if mode == "staged":
                item["accepted_head"] = head
    if no_code:
        data["current_index"] = len(data.get("checkpoints") or [])

def _registered_process_artifacts(st, supplied_paths):
    records = st.get("spec2code") or {}
    result = {}
    for kind in ("roadmap", "plan"):
        supplied = str(
            supplied_paths.get(kind)
            or (records.get(kind) or {}).get("path")
            or "")
        if not supplied:
            api.die(
                "新 full 流程缺少已登记的 %s；先完成 build_plan。"
                % kind,
                2,
            )
        record = records.get(kind) or {}
        normalized = os.path.normpath(
            os.path.relpath(
                os.path.realpath(supplied),
                os.path.realpath(os.getcwd()),
            )
        ).replace("\\", "/")
        if normalized != record.get("path"):
            api.die(
                "%s 未登记或路径不匹配；先执行 quality-artifact register。"
                % kind,
                2,
            )
        text = read_text(supplied, encoding="utf-8")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest != record.get("sha256"):
            api.die(
                "%s 登记后内容已变化；重新校验并登记。" % kind,
                2,
            )
        result[kind] = {
            "path": normalized,
            "sha256": digest,
            "text": text,
        }
    return result

def _checkpoint_plan_result(
        st, raw_items, supplied_paths, moonlight=None):
    return plan_checkpoint(
        current=st.get("current"),
        workflow=(st.get("choices", {}) or {}).get("workflow"),
        moonlight=(
            api._moonlight(st)
            if moonlight is None else moonlight),
        raw_items=raw_items,
        code_reviewer=(
            (st.get("choices") or {}).get("code_reviewer")
            or "enabled"
        ),
        ports=CheckpointPlanPorts(
            dirty_paths=lambda: api._blocking_dirty_source_paths(st, api.FLOW),
            task_structure=lambda: api._task_structure_fingerprint(st),
            head=lambda: api.sh("git rev-parse --verify HEAD"),
            ack_cursor=api._ack_message_cursor,
            now=lambda: time.strftime("%Y-%m-%d %H:%M:%S"),
            process_artifacts=lambda: _registered_process_artifacts(
                st, supplied_paths),
            is_test_path=lambda path: api._is_test_file(path, st),
        ),
    )

def _apply_checkpoint_plan_result(st, result):
    if result.exit_code:
        api.die(result.stderr[0], result.exit_code)
    for effect in result.effects:
        if effect.kind != "set_development_review":
            raise RuntimeError(
                "unsupported checkpoint plan effect: " + effect.kind)
        st["development_review"] = thaw_delivery_payload(effect.payload)
    api.save_state(st)
    for line in result.stdout:
        print(line)

def cmd_checkpoint_plan(st, args):
    supplied = {
        "roadmap": getattr(args, "roadmap", ""),
        "plan": getattr(args, "plan", ""),
    }
    raw_items = getattr(args, "item", ()) or ()
    new_full = (
        (st.get("choices") or {}).get("workflow") == "full"
        and (st.get("spec2code") or {}).get("version") == 1
    )
    if new_full and raw_items:
        api.die(
            "新 full 流程不得使用兼容参数 --item 降级；"
            "必须使用已登记的 --roadmap 与 --plan。",
            2,
        )
    if not raw_items and (
            not supplied["roadmap"] or not supplied["plan"]):
        api.die(
            "新 full 流程须传 --roadmap 与 --plan；"
            "旧流程可继续使用 --item。",
            2,
        )
    _apply_checkpoint_plan_result(
        st,
        _checkpoint_plan_result(
            st, raw_items, supplied),
    )


def _prepare_moonlight_checkpoint_plan(st):
    """Freeze CP artifacts while bypassing only the human pace choice."""
    original = st.get("current")
    st["current"] = "build_pace"
    try:
        result = _checkpoint_plan_result(
            st, (), {}, moonlight=False)
    finally:
        st["current"] = original
    _apply_checkpoint_plan_result(st, result)
    _activate_checkpoint_plan(st, "continuous")
    st.setdefault("history", []).append({
        "step": "build_pace",
        "result": "moonlight:checkpoint-continuous",
        "note": "保留 Task 分析和 PLAN/CODE Reviewer，仅旁路人工节奏确认",
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    api.save_state(st)

def _checkpoint_plan_drift(st):
    data = api._development_review(st) or {}
    current_sha, _ = api._task_structure_fingerprint(st)
    planned = str(data.get("task_structure_sha256", ""))
    return bool(planned and current_sha != planned)

def _checkpoint_source_fresh(head, st):
    changed, err = api._source_changed_since(head, st)
    if err:
        return False, "代码基点无法核实:" + err
    if changed:
        return False, "代码发生变化:" + "、".join(changed[:8])
    return True, ""

def _print_checkpoint_decisions(final=False):
    print("\n展示完整 diff、关键风险和自验证方式后，用 AskUserQuestion 提供：")
    print("  - " + CHECKPOINT_CONTINUE_ACK)
    print("  - " + CHECKPOINT_REVISE_ACK)
    if not final:
        print("  - " + CHECKPOINT_CONTINUOUS_ACK)
    print("点选后执行 checkpoint decide continue|revise"
          + ("" if final else "|continuous")
          + "；命令会自动读取本次检视后的新回答。")

def cmd_checkpoint_ready(flow, st, args):
    result = ready_checkpoint(
        review=api._development_review(st),
        current=st.get("current"),
        workflow=(st.get("choices", {}) or {}).get("workflow"),
        moonlight=api._moonlight(st),
        checkpoint_id=args.checkpoint_id,
        agent_tasks=st.get("agent_tasks", {}) or {},
        ports=CheckpointReadyPorts(
            head=lambda: api.sh("git rev-parse --verify HEAD"),
            object_type=lambda value: api.argv_out([
                "git", "cat-file", "-t", value]),
            merge_base=lambda base, head: api.argv_out([
                "git", "merge-base", base, head]),
            worktree_snapshot=lambda: api._checkpoint_worktree_snapshot(
                st, flow),
            is_source_path=lambda path: api._is_source_path(
                path, st, flow),
            agent_evidence=lambda: api.ev_agent_ran(
                {"agent": "COMPILE", "statuses": ["OK"]}, st),
            snapshot_sha256=api._snapshot_sha256,
            ack_cursor=api._ack_message_cursor,
            now=lambda: time.strftime("%Y-%m-%d %H:%M:%S"),
            task_structure_drift=lambda: _checkpoint_plan_drift(st),
            dirty_paths=lambda: api._blocking_dirty_source_paths(st, flow),
            has_commit=lambda base, head: bool(api.argv_out([
                "git", "log", "-1", "--format=%H", base + ".." + head])),
            commit_tagged=lambda: api.ev_commit_tagged({}, st),
            source_files=lambda base, head: [
                path for path in api.argv_out([
                    "git", "-c", "core.quotepath=false",
                    "diff", "--name-only", base, head,
                ]).splitlines()
                if path and api._is_source_path(path, st, flow)
            ],
            delivery_snapshot=lambda base:
                api._checkpoint_delivery_snapshot(st, base, flow),
        ),
    )
    if result.exit_code:
        api.die(result.stderr[0], result.exit_code)
    render_items = []
    show_review = False
    for effect in result.effects:
        if effect.kind == "set_development_review":
            st["development_review"] = thaw_delivery_payload(effect.payload)
        elif effect.kind == "render_worktree_review":
            render_items.append(thaw_delivery_payload(effect.payload))
        elif effect.kind == "show_checkpoint_review":
            show_review = True
        else:
            raise RuntimeError(
                "unsupported checkpoint ready effect: " + effect.kind)
    api.save_state(st)
    for item in render_items:
        print("\n".join(api._checkpoint_worktree_review_lines(item)))
    if show_review:
        api._show_checkpoint_review(
            st, api._development_review(st), api._checkpoint_current(st))
    for line in result.stdout:
        print(line)

def _reviewed_snapshot_current(st, item):
    receipt = item.get("receipt") or {}
    base = str(receipt.get("base", ""))
    if receipt.get("scope") == "final":
        return api._final_delivery_snapshot(st, base)
    return api._checkpoint_delivery_snapshot(st, base)

def _reviewed_worktree_fresh(st, item):
    return reviewed_worktree_fresh(
        item,
        api.sh("git rev-parse --verify HEAD"),
        _reviewed_snapshot_current(st, item),
    )

def _checkpoint_commit_command(st, item):
    return checkpoint_commit_commands(
        item, st.get("config", {}) or {})

def _show_pending_checkpoint_review(st, data, item):
    if data.get("version") == 2:
        try:
            roadmap = read_text(data.get("roadmap_path"), encoding="utf-8")
            plan = read_text(data.get("plan_path"), encoding="utf-8")
            receipt = item.get("receipt") or {}
            diff = (
                "HEAD（当前未提交快照）"
                if receipt.get("snapshot")
                else "%s..%s" % (
                    receipt.get("base", ""),
                    receipt.get("head", ""),
                )
            )
            print("\n".join(checkpoint_review_context(
                roadmap, plan, item.get("id", ""), diff)))
        except (OSError, UnicodeDecodeError) as exc:
            api.die("CP 检视上下文无法读取:" + str(exc), 2)
    if api._review_before_commit(data):
        fresh, why = _reviewed_worktree_fresh(st, item)
        if not fresh:
            api.die("检查点收据已失效:" + why
                + "；选择调整后重新编译并生成收据。", 2)
        print("\n".join(api._checkpoint_worktree_review_lines(item)))
    else:
        receipt = item.get("receipt") or {}
        print("\n".join(api._checkpoint_review_lines(
            receipt.get("base", ""), receipt.get("head", ""),
            "%s 用户代码检视" % item.get("id"),
            receipt.get("remote_ref", ""))))
    if item.get("task_structure_drift"):
        print("⚠ 实现清单结构在开发中发生变化，请重点核对新增/删除任务是否仍符合确认范围。")
    _print_checkpoint_decisions(final=False)

def _show_coding_checkpoint(data, item):
    if data.get("mode") == "staged" and api._review_before_commit(data):
        print("当前正在编码 %s；保持代码未提交，绑定本批 compile-agent 通过后执行 "
              "checkpoint ready %s。" % (item["id"], item["id"]))
        return
    print("当前正在编码 %s；完成提交和绑定本批的 compile-agent 后执行 checkpoint ready %s。"
          % (item["id"], item["id"]))

def _show_checkpoint_review(st, data, item):
    if item.get("status") == "review_pending":
        _show_pending_checkpoint_review(st, data, item)
    elif item.get("status") == "coding":
        _show_coding_checkpoint(data, item)
    elif item.get("status") == "planned":
        print(
            "%s 等待即时展开细粒度 Task；生成 task-analysis 与 craft-plan "
            "角色卡，完成后执行 checkpoint prepare。"
            % item.get("id", "当前 CP"))
    elif item.get("status") == "plan_review_pending":
        print(
            "%s 计划等待用户检视；选择后执行 checkpoint plan-decide。"
            % item.get("id", "当前 CP"))
    elif item.get("status") == "craft_pending":
        print(
            "%s 首次编译已完成，等待新鲜 Craft Reviewer CODE 走读；"
            "登记后才能展示用户 CP 检视卡。"
            % item.get("id", "当前 CP"))
    elif item.get("status") == "craft_decision_pending":
        print(
            "%s CODE Findings 已登记，等待用户裁决；"
            "主 Agent 不得自行宣称关闭。用户确认处置后执行 "
            "checkpoint craft-decide；即使源码已提前按确认项修改，"
            "该命令也会保留现场并安全恢复到 coding。"
            % item.get("id", "当前 CP"))

def _final_drifted_checkpoints(data):
    return [
        item.get("id", "?") for item in data.get("checkpoints") or []
        if item.get("task_structure_drift")
    ]

def _show_final_review_mode(data):
    mode = data.get("mode")
    if mode == "continuous":
        print("  模式说明:中途策略是不 push；确认最终整体代码后才进入正式 push。")
    elif mode == "staged":
        print("  模式说明:最终质量增量确认后才进入正式 push；"
              "若已被外部工具提前推送会明确告警。")

def _show_final_review_context(data):
    drifted = _final_drifted_checkpoints(data)
    if drifted:
        print("⚠ 开发期间实现/评审任务结构曾偏离编码前方案（%s）；"
              "请额外核对新增、删除或重排的任务仍符合需求边界。"
              % "、".join(drifted))
    _show_final_review_mode(data)

def _show_final_pending_review(data, final):
    base = str(final.get("base", ""))
    head = str(final.get("head", ""))
    if base != head:
        print("\n".join(api._checkpoint_review_lines(
            base, head, "最终未检视代码增量",
            final.get("remote_ref", ""))))
    receipt = final.get("receipt") or {}
    if receipt.get("snapshot"):
        print("\n".join(api._checkpoint_worktree_review_lines({
            "id": "最终增量", "receipt": receipt,
        })))
    if final.get("remote_ref"):
        print("⚠ 当前本地 HEAD 已经存在于上游；仍须完成检视，"
              "但不要再次 push 或改写远端历史。")
    _show_final_review_context(data)
    _print_checkpoint_decisions(final=True)

def _show_final_pending_commit(st, final):
    add, commit = _checkpoint_commit_command(st, final)
    print("最终未提交增量已经用户确认；只允许提交该检视快照：")
    print("  " + add)
    print("  " + commit)
    print("提交后执行 checkpoint status 核验；核验通过后会回流完整质量链。")

def _show_final_commit_recovery(final):
    print("最终增量提交核验失败，push 已冻结："
          + str(final.get("verification_error", "未知原因")))
    print("展示真实差异并让用户选择「需要调整代码」，"
          "再执行 checkpoint decide revise。")

def _show_final_reset_pending(final):
    base = str(((final.get("receipt") or {}).get("base", "")))
    print("用户已授权拆回错误的最终增量提交；执行 git reset --mixed "
          + base + "，随后 checkpoint status。")

def _show_legacy_final_push_pending():
    print("检测到旧版“先 push、后最终检视”的在途状态；执行 checkpoint status "
          "会原地迁移为本地先检视，不需要先 push。")

def _show_final_review_receipt(st, data, final):
    handlers = {
        "review_pending": lambda: _show_final_pending_review(data, final),
        "commit_pending": lambda: _show_final_pending_commit(st, final),
        "commit_recovery": lambda: _show_final_commit_recovery(final),
        "reset_pending": lambda: _show_final_reset_pending(final),
        "push_pending": _show_legacy_final_push_pending,
    }
    handler = handlers.get(final.get("status"))
    if handler:
        handler()

def _final_review_active(data):
    final = (data or {}).get("final_review")
    if not isinstance(final, dict):
        return None
    return final if final.get("status") in CHECKPOINT_LOCKED_STATUSES else None

def _checkpoint_recovery_ports(st):
    return CheckpointRecoveryPorts(
        head=lambda: api.sh("git rev-parse --verify HEAD"),
        current_snapshot=lambda item: _reviewed_snapshot_current(
            st, item),
        upstream=api._upstream_snapshot,
        source_fresh=lambda head: _checkpoint_source_fresh(
            head, st),
        merge_base=lambda base, head: api.argv_out([
            "git", "merge-base", base, head]),
        commit_paths=lambda base: tuple(api.argv_out([
            "git", "-c", "core.quotepath=false", "diff",
            "--name-only", "--no-renames", base, "HEAD",
        ]).splitlines()),
        commit_count=lambda base: api.argv_out([
            "git", "rev-list", "--count", base + "..HEAD"]),
        dirty_paths=lambda: tuple(api._dirty_paths()),
        commit_tagged=lambda: api.ev_commit_tagged({}, st),
        commit_commands=lambda item: _checkpoint_commit_command(
            st, item),
        ack_cursor=api._ack_message_cursor,
        now=lambda: time.strftime("%Y-%m-%d %H:%M:%S"),
        rework_target=lambda: CHECKPOINT_CODE_STEPS.get(
            (st.get("choices", {}) or {}).get(
                "workflow", ""),
            "",
        ),
        reopen_spec_archive=lambda state: api._reopen_spec_archive(
            state),
    )

def _apply_checkpoint_refresh(st, result):
    show_checkpoint = False
    show_final = False
    show_current = False
    changed = False
    for effect in result.effects:
        payload = thaw_delivery_payload(effect.payload)
        if effect.kind == "set_development_review":
            st["development_review"] = payload
            changed = True
        elif effect.kind == "invalidate_quality":
            api._invalidate_quality_for_rework(st)
            changed = True
        elif effect.kind == "append_history":
            st.setdefault("history", []).append(payload)
            changed = True
        elif effect.kind == "show_checkpoint_review":
            show_checkpoint = True
        elif effect.kind == "show_final_review":
            show_final = True
        elif effect.kind == "drop_quality_tokens":
            for kind in ("COMPILE", "CODECHECK", "UT"):
                api._drop_agent_token(kind)
        elif effect.kind == "set_state":
            st.clear()
            st.update(payload)
            changed = True
        elif effect.kind == "print_current":
            show_current = True
        else:
            raise RuntimeError(
                "unsupported checkpoint refresh effect: " + effect.kind)
    if changed:
        api.save_state(st)
    for line in result.stdout:
        print(line)
    if show_checkpoint:
        data = api._development_review(st)
        _show_checkpoint_review(st, data, api._checkpoint_current(st))
    if show_final:
        data = api._development_review(st)
        _show_final_review_receipt(
            st, data, (data or {}).get("final_review") or {})
    if show_current:
        api.print_current(api.FLOW, st)
    if result.exit_code:
        api.die(result.stderr[0], result.exit_code)
