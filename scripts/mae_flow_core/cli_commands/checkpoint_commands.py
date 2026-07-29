"""CLI responsibilities extracted from the historical entrypoint."""

from .shared import (
    CheckpointDecisionPorts, FinalReviewPorts, activate_final_rework,
    decide_checkpoint, inspect_checkpoint_status, prepare_final_review, re,
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

def _checkpoint_ack(st, ack, expected, receipt):
    if ack != expected:
        return False, "选择原文必须精确为「%s」，不能用近义词代答" % expected
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
        ack=args.ack,
        config=st.get("config", {}) or {},
        ports=CheckpointDecisionPorts(
            verify_ack=lambda receipt, expected: _checkpoint_ack(
                st, args.ack, expected, receipt),
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
    if action == "final":
        return cmd_checkpoint_final(st)
    if action == "decide":
        return cmd_checkpoint_decide(flow, st, args)
    api.die("未知 checkpoint 动作: " + str(action), 2)
