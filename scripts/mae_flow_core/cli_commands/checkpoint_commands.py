"""CLI responsibilities extracted from the historical entrypoint."""

from .shared import (
    CheckpointDecisionPorts, CheckpointQualityPorts, FinalReviewPorts,
    activate_final_rework, decide_checkpoint, decide_checkpoint_plan,
    decide_craft_review,
    hashlib, inspect_checkpoint_status, os, prepare_checkpoint_plan,
    prepare_final_review, read_text, record_craft_review, re,
    refresh_checkpoint, refresh_final_review, thaw_delivery_payload, time,
)
from .wiring import api

def cmd_checkpoint_status(st):
    data = api._development_review(st)
    result = inspect_checkpoint_status(data)
    for line in result.stdout:
        print(line)
    for effect in result.effects:
        if effect.kind == "refresh_final_review":
            refreshed = refresh_final_review(
                st, api._checkpoint_recovery_ports(st))
            api._apply_checkpoint_refresh(st, refreshed)
            return
        if effect.kind == "refresh_checkpoint":
            refreshed = refresh_checkpoint(
                data, st.get("current"),
                api._checkpoint_recovery_ports(st))
            api._apply_checkpoint_refresh(st, refreshed)
            return
        raise RuntimeError(
            "unsupported checkpoint status effect: " + effect.kind)

def cmd_checkpoint_final(st):
    result = prepare_final_review(
        current=st.get("current"),
        review=api._development_review(st),
        moonlight=api._moonlight(st),
        ports=FinalReviewPorts(
            final_delta=lambda: api._final_review_delta(st),
            head=lambda: api.sh("git rev-parse --verify HEAD"),
            final_snapshot=lambda head: api._final_delivery_snapshot(
                st, head),
            snapshot_sha256=api._snapshot_sha256,
            upstream=api._upstream_snapshot,
            ack_cursor=api._ack_message_cursor,
            now=lambda: time.strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    if result.exit_code:
        api.die(result.stderr[0], result.exit_code)
    show_final = False
    migrated = False
    save = False
    for effect in result.effects:
        if effect.kind == "set_development_review":
            st["development_review"] = thaw_delivery_payload(effect.payload)
            save = True
        elif effect.kind == "migrate_legacy_final":
            migration = refresh_final_review(
                st, api._checkpoint_recovery_ports(st))
            api._apply_checkpoint_refresh(st, migration)
            migrated = True
        elif effect.kind == "show_final_review":
            show_final = not migrated
        else:
            raise RuntimeError(
                "unsupported final review effect: " + effect.kind)
    if save:
        api.save_state(st)
    if show_final:
        data = api._development_review(st)
        api._show_final_review_receipt(
            st, data, (data or {}).get("final_review") or {})
    for line in result.stdout:
        print(line)

def _checkpoint_ack(st, expected, receipt):
    cursor = set((receipt or {}).get("ack_cursor") or [])
    fresh = [
        item for item in api._current_ack_messages(st)
        if api._ack_message_signature(item) not in cursor
    ]
    normalized = re.sub(r"\s+", "", expected)
    if any(
            normalized in api._ack_candidates(item.get("text", ""))
            for item in fresh):
        api._ack_failure(st, success=True)
        return True, ""
    why = (
        "没有捕获到本次检视收据呈现之后的新用户选择。"
        "同一编码步骤内上一批的“继续”不能复用到当前批次；"
        "请展示当前收据并重新取得一次选项回答")
    count = api._ack_failure(st, why)
    return False, why + api._ack_retry_guidance(count)


def _local_process_path(path):
    return os.path.normpath(
        os.path.relpath(os.path.realpath(path), os.path.realpath(os.getcwd()))
    ).replace("\\", "/")


def _role_task_sha(st, role, checkpoint):
    record = (st.get("role_tasks") or {}).get(role) or {}
    if record.get("checkpoint") != checkpoint:
        return ""
    expected_target = (
        str(
            ((st.get("spec2code") or {}).get("plan") or {}).get(
                "sha256", "")
            or "")
        if role == "craft-plan"
        else str(
            (api._checkpoint_current(st) or {}).get(
                "compile_source_sha256", "")
            or "")
    )
    if record.get("review_target_sha256") != expected_target:
        return ""
    return str(record.get("sha256", "") or "")


def _checkpoint_quality_ports(st):
    return CheckpointQualityPorts(
        is_file=os.path.isfile,
        read_text=lambda path: read_text(path, encoding="utf-8"),
        normalize_path=_local_process_path,
        digest=lambda text: hashlib.sha256(
            text.encode("utf-8")).hexdigest(),
        ack_cursor=api._ack_message_cursor,
        verify_ack=lambda receipt, expected: _checkpoint_ack(
            st, expected, receipt),
        role_task_sha=lambda role, checkpoint: _role_task_sha(
            st, role, checkpoint),
        registered_artifact_sha=lambda kind: str(
            ((st.get("spec2code") or {}).get(kind) or {}).get(
                "sha256", "")
            or ""),
        now=lambda: time.strftime("%Y-%m-%d %H:%M:%S"),
        is_test_path=lambda path: api._is_test_file(path, st),
    )


def _apply_checkpoint_quality_result(st, result):
    if result.exit_code:
        api.die(result.stderr[0], result.exit_code)
    show_review = False
    changed = False
    for effect in result.effects:
        payload = thaw_delivery_payload(effect.payload)
        if effect.kind == "set_development_review":
            st["development_review"] = payload
            changed = True
        elif effect.kind == "append_history":
            st.setdefault("history", []).append(payload)
            changed = True
        elif effect.kind == "invalidate_quality":
            _invalidate_quality_for_rework(st)
            changed = True
        elif effect.kind == "show_checkpoint_review":
            show_review = True
        else:
            raise RuntimeError(
                "unsupported checkpoint quality effect: " + effect.kind)
    if changed:
        api.save_state(st)
    for line in result.stdout:
        print(line)
    if show_review:
        data = api._development_review(st)
        api._show_checkpoint_review(st, data, api._checkpoint_current(st))


def cmd_checkpoint_prepare(st, args):
    ticket = str((st.get("config") or {}).get("单号", "") or "")
    result = prepare_checkpoint_plan(
        api._development_review(st),
        args.checkpoint_id,
        args.plan,
        args.review,
        ticket,
        _checkpoint_quality_ports(st),
        moonlight=api._moonlight(st),
    )
    _apply_checkpoint_quality_result(st, result)


def cmd_checkpoint_plan_decide(st, args):
    result = decide_checkpoint_plan(
        api._development_review(st),
        args.choice,
        _checkpoint_quality_ports(st),
    )
    _apply_checkpoint_quality_result(st, result)


def _current_craft_source_sha(st):
    item = api._checkpoint_current(st) or {}
    receipt = item.get("receipt") or {}
    if receipt.get("snapshot_sha256"):
        current = api._checkpoint_worktree_snapshot(st, api.FLOW)
        return api._snapshot_sha256(current)
    base = str(item.get("fixed_base", "") or "")
    head = api.sh("git rev-parse --verify HEAD")
    return hashlib.sha256(
        (base + "\0" + head).encode("utf-8")
    ).hexdigest()


def cmd_checkpoint_craft_reviewed(st, args):
    ticket = str((st.get("config") or {}).get("单号", "") or "")
    result = record_craft_review(
        api._development_review(st),
        args.checkpoint_id,
        args.review,
        ticket,
        _current_craft_source_sha(st),
        _checkpoint_quality_ports(st),
        moonlight=api._moonlight(st),
    )
    _apply_checkpoint_quality_result(st, result)


def cmd_checkpoint_craft_decide(st, args):
    ticket = str((st.get("config") or {}).get("单号", "") or "")
    result = decide_craft_review(
        api._development_review(st),
        args.checkpoint_id,
        args.review,
        ticket,
        _current_craft_source_sha(st),
        _checkpoint_quality_ports(st),
    )
    _apply_checkpoint_quality_result(st, result)

def _invalidate_quality_for_rework(st):
    st.pop("unlock", None)
    st.pop("risk_acceptances", None)
    st.pop("agent_tasks", None)
    st.pop("quality", None)
    for kind in ("COMPILE", "CODECHECK", "UT"):
        api._drop_agent_token(kind)

def cmd_checkpoint_decide(flow, st, args):
    result = decide_checkpoint(
        review=api._development_review(st),
        current=st.get("current"),
        moonlight=api._moonlight(st),
        choice=args.choice,
        config=st.get("config", {}) or {},
        ports=CheckpointDecisionPorts(
            verify_ack=lambda receipt, expected: _checkpoint_ack(
                st, expected, receipt),
            head=lambda: api.sh("git rev-parse --verify HEAD"),
            upstream=api._upstream_snapshot,
            worktree_fresh=lambda item: api._reviewed_worktree_fresh(
                st, item),
            final_snapshot=lambda head: api._final_delivery_snapshot(
                st, head),
            source_fresh=lambda head: api._checkpoint_source_fresh(
                head, st),
            upstream_contains=api._upstream_contains_reset_commit,
            now=lambda: time.strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    if result.exit_code:
        api.die(result.stderr[0], result.exit_code)
    show_final = False
    changed = False
    for effect in result.effects:
        if effect.kind == "set_development_review":
            st["development_review"] = thaw_delivery_payload(effect.payload)
            changed = True
        elif effect.kind == "invalidate_quality":
            _invalidate_quality_for_rework(st)
            changed = True
        elif effect.kind == "append_history":
            st.setdefault("history", []).append(
                thaw_delivery_payload(effect.payload))
            changed = True
        elif effect.kind == "show_final_review":
            show_final = True
        elif effect.kind == "activate_final_rework":
            payload = thaw_delivery_payload(effect.payload)
            rework = activate_final_rework(
                st, payload, api._checkpoint_recovery_ports(st))
            api._apply_checkpoint_refresh(st, rework)
            return
        else:
            raise RuntimeError(
                "unsupported checkpoint decision effect: " + effect.kind)
    if changed:
        api.save_state(st)
    if show_final:
        data = api._development_review(st)
        api._show_final_review_receipt(
            st, data, (data or {}).get("final_review") or {})
    for line in result.stdout:
        print(line)

def cmd_checkpoint(flow, st, args):
    action = args.checkpoint_action
    if action == "plan":
        return api.cmd_checkpoint_plan(st, args)
    if action == "status":
        return cmd_checkpoint_status(st)
    if action == "ready":
        return api.cmd_checkpoint_ready(flow, st, args)
    if action == "prepare":
        return cmd_checkpoint_prepare(st, args)
    if action == "plan-decide":
        return cmd_checkpoint_plan_decide(st, args)
    if action == "craft-reviewed":
        return cmd_checkpoint_craft_reviewed(st, args)
    if action == "craft-decide":
        return cmd_checkpoint_craft_decide(st, args)
    if action == "final":
        return cmd_checkpoint_final(st)
    if action == "decide":
        return cmd_checkpoint_decide(flow, st, args)
    api.die("未知 checkpoint 动作: " + str(action), 2)
