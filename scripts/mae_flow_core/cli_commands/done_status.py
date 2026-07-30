"""CLI responsibilities extracted from the historical entrypoint."""

from .shared import (
    PACE_STEPS, WORKFLOW_LABELS, json, os, sys, time, workflow_completion,
    workflow_transitions,
)
from .wiring import api

def _done_handle_legacy_pace(flow, st, sid, step):
    if (sid in PACE_STEPS and not api._development_checkpoints_enabled(st)
            and not api._development_review(st)):
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        target = api._next_from_step(step, st, "continuous")
        st.setdefault("history", []).append({
            "step": sid, "result": "legacy:skipped-development-pace",
            "note": "旧版在途状态恢复升级前路径", "at": now})
        st["current"] = target
        st.setdefault("step_heads", {})[target] = api.sh(
            "git rev-parse --verify HEAD")
        api.save_state(st)
        print("[mae-flow] 检测到升级前在途状态；本单不追加开发节奏确认，"
              "已按原流程进入 %s。\n" % target)
        api.print_current(flow, st)
        return True
    return False

def _done_pending_config(step, st, args, sid):
    review = st.get("config_review") if sid == "config_confirm" else None
    if sid != "config_confirm" or api._moonlight(st):
        return api._validated_pending_config(step, st, args.set or [])
    if not isinstance(review, dict) or not review.get("sha256"):
        api.die(
            "尚未生成完整配置确认单。先按 current 输出执行 config-review --set ...；"
            "脚本会校验并展示全部配置，再让用户只做一次最终确认。"
            "不要直接拿基线分支、单号等局部回答调用 done。", 2)
    if args.set:
        pending_config = api._validated_pending_config(step, st, args.set)
        current_requirement_sha = api._requirement_sha256(
            pending_config.get("需求文档", ""))
        if api._config_sha256(
                pending_config, current_requirement_sha) != review.get("sha256"):
            api.die(
                "done 携带的配置与用户看到的确认单不一致。禁止确认 A、提交 B；"
                "请用新配置重新执行 config-review。", 2)
    else:
        review_state = dict(st)
        review_state["config"] = dict(review.get("config") or {})
        pending_config = api._validated_pending_config(step, review_state, [])
        current_requirement_sha = api._requirement_sha256(
            pending_config.get("需求文档", ""))
        if api._config_sha256(
                pending_config,
                current_requirement_sha) != review.get("sha256"):
            api.die("配置或需求文档在呈现后发生变化，旧确认单已自动失效。"
                "重新执行 config-review 即可恢复，无需退出流程。", 2)
    ok, why = api._config_ack_verified(
        st, args.ack or "", review.get("sha256"), review.get("id", ""))
    if not ok:
        api.die(why, 2)
    return pending_config

def _done_validate_choice_and_ack(step, st, args, sid):
    error = workflow_completion.choice_error(step, args.choice)
    if error:
        api.die(error, 2)
    if (sid == "config_confirm" or not step.get("user_ack")
            or api._moonlight(st)):
        return
    if step.get("choice_key"):
        pace_state = api._development_review(st) if sid in PACE_STEPS else None
        ok, why = api._choice_verified(
            step, st, args.choice,
            (pace_state or {}).get("ack_cursor")
            if pace_state else None)
    elif step.get("confirmation_answers"):
        ok, why = api._implicit_ack_verified(step, st)
    elif args.ack:
        ok, why = api._ack_verified(st, args.ack)
    else:
        ok, why = api._implicit_ack_verified(step, st)
    if not ok:
        api.die(why, 2)

def _done_commit_inputs(step, st, args, sid, pending_config):
    for key, value in workflow_completion.choice_config(step, args.choice).items():
        bad = api._validate_config_value(key, value)
        if bad:
            api.die(f"流程定义为选择 {args.choice} 配置的 {key}「{value}」不合法:{bad}。"
                "请维护人修正 flow.json，拒绝写入半套状态。", 2)
        pending_config[key] = value
    st["config"] = pending_config
    if sid == "config_confirm":
        st.pop("config_review", None)
        st.pop("branch_resolution", None)
    if step.get("choice_key"):
        st["choices"][step["choice_key"]] = args.choice

def _done_guard_branch(st, sid):
    if sid == "story":
        api._canonicalize_story_output(
            st.get("config", {}).get("单号", ""), st)
    want = st.get("config", {}).get("分支名", "")
    if sid not in ("config_confirm", "workflow_select", "branch_create") and want:
        cur = api.sh("git branch --show-current")
        if cur != want:
            _done_save_die(
                st, f"当前分支 {cur or '未知'} != 本单约定分支 {want}。先切回正确分支，禁止在别的分支推进。")

def _done_save_die(st, message):
    api.save_state(st)
    api.die(message, 2)

def _done_transition_to_recheck(flow, st, sid, target, changed, note, message,
                                clear_unlock=False):
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    st["history"].append({"step": sid, "result": "source-recheck:" + target,
                          "note": note + "、".join(changed[:10]), "at": now})
    st["current"] = target
    st.setdefault("step_heads", {})[target] = api.sh("git rev-parse --verify HEAD")
    if clear_unlock:
        st.pop("unlock", None)
    for kind in ("COMPILE", "CODECHECK", "UT"):
        (st.get("agent_tasks", {}) or {}).pop(kind, None)
    (st.get("quality", {}) or {}).pop("codecheck_scan", None)
    (st.get("quality", {}) or {}).pop("codecheck_verify", None)
    api.save_state(st)
    print(message)
    api.print_current(flow, st)
    return True

def _done_source_change(flow, st, sid, step):
    source_next = step.get("source_change_next")
    if not source_next:
        return False
    _, migrate_err = api._ensure_step_entry_head(flow, st, sid)
    if migrate_err:
        _done_save_die(
            st, "无法恢复步骤入口 HEAD:" + migrate_err + "。拒绝猜测源码是否变化。")
    changed, why = api._source_changed_since(
        (st.get("step_heads", {}) or {}).get(sid, ""), st)
    if why:
        _done_save_die(st, "无法核对本步源码变化:" + why)
    if not changed:
        return False
    dirty = [x for x in changed if x.endswith("(未提交)")]
    if dirty:
        _done_save_die(st, "本步改过源码，但仍有未提交改动: " + "、".join(dirty[:5])
                       + "。先按单号格式精确提交，再 done；否则下一步任务卡看不到这些文件。")
    ok, commit_why = api.ev_commit_tagged_after_entry({}, st)
    if not ok:
        _done_save_die(st, "源码变化尚未形成可追踪的本步提交:" + commit_why)
    return _done_transition_to_recheck(
        flow, st, sid, source_next, changed, "本步修改源码:",
        f"[mae-flow] {sid} 修改了源码，自动进入 {source_next} 重新编译；主会话不要自行编译。\n")

def _done_source_recheck(flow, st, sid, step):
    recheck = step.get("source_change_recheck")
    if not recheck:
        return False
    _, migrate_err = api._ensure_step_entry_head(flow, st, sid)
    if migrate_err:
        _done_save_die(st, "无法恢复 UT 步骤入口 HEAD:" + migrate_err
                       + "。为避免漏掉编译/CodeCheck，拒绝向后推进；请交维护人核对历史。")
    changed, why = api._business_source_changed_since_step(st, sid)
    if why:
        _done_save_die(st, "无法核对 UT 步骤内是否修改过被测源码:" + why
                       + "。为避免漏掉编译/CodeCheck，拒绝向后推进；请交维护人恢复步骤入口基点。")
    if not changed:
        return False
    ul = st.get("unlock") or {}
    if ul.get("scope") != "source" or ul.get("step") != sid:
        _done_save_die(st, "UT 步骤内检测到未经 unlock source 用户裁决的被测源码变更: "
                       + "、".join(changed[:5]) + ("…" if len(changed) > 5 else "")
                       + "。这是越权修改，不能靠补跑验证洗白；先呈报变更和 UT 自查结论，由用户裁决后再处理。")
    dirty = [x for x in changed if x.endswith("(未提交)")]
    if dirty:
        _done_save_die(st, "用户虽已解锁源码修复，但这些源码仍未提交: "
                       + "、".join(dirty[:5])
                       + "。先按单号格式精确提交，再 done；否则回流任务卡无法覆盖真实改动。")
    ok, commit_why = api.ev_commit_tagged_after_entry({}, st)
    if not ok:
        _done_save_die(st, "UT 暴露的源码修复尚未形成可追踪提交:" + commit_why)
    return _done_transition_to_recheck(
        flow, st, sid, recheck, changed, "UT 裁决后修改被测源码:",
        f"[mae-flow] UT 阶段经用户裁决修改了被测源码，自动回流到 {recheck}。"
        "必须重新经过编译、CodeCheck 与 UT；禁止直接推送。\n", clear_unlock=True)

def _done_require_evidence(step, st, args, sid):
    fails = api.check_evidence(step, st)
    if not fails:
        api._evidence_failure_count(sid, success=True)
        return
    api.save_state(st)
    count = api._evidence_failure_count(sid)
    target = (api._next_from_step(step, st, args.choice or "")
              if count >= 2 and not api._moonlight(st) else "")
    api.die(workflow_completion.evidence_error(
        fails, count, api._moonlight(st), target,
        os.path.abspath(sys.argv[0])), 2)

def _done_adjust_checkpoint(flow, st, sid):
    st.pop("development_review", None)
    st.get("choices", {}).pop("development_pace", None)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    st.setdefault("history", []).append({
        "step": sid, "result": "checkpoint-plan:adjust",
        "note": "用户要求调整检查点划分", "at": now})
    st.setdefault("step_heads", {})[sid] = api.sh("git rev-parse --verify HEAD")
    api.save_state(st)
    print("[mae-flow] 用户选择调整检查点；旧方案已失效，代码仍未解锁。"
          "结合用户意见重新执行 checkpoint plan --item ...。")
    api.print_current(flow, st)

def _done_finalize(flow, st, args, sid, step):
    for event in workflow_completion.completion_events(
            sid, step, st, args.choice, args.ack or ""):
        if event.kind == "adjust_checkpoint":
            _done_adjust_checkpoint(flow, st, sid)
            return
        if event.kind == "activate_checkpoint":
            api._activate_checkpoint_plan(st, event.value)
        elif event.kind == "prepare_moonlight_checkpoint":
            api._prepare_moonlight_checkpoint_plan(st)
        elif event.kind == "resolve_moonlight":
            api._moonlight_resolve_kind(st, event.value)
        elif event.kind == "localize_story":
            api._localize_story(event.value)
        elif event.kind == "advance":
            api.advance(flow, st, sid, step, "done", event.note)

def cmd_done(flow, st, args):
    sid = st["current"]
    step = flow["steps"][sid]
    if step.get("terminal"):
        api.die("流程已在终态。")
    if _done_handle_legacy_pace(flow, st, sid, step):
        return
    if sid == "moonlight_review":
        api.die("月光宝盒已推送并等待早晨处理。请执行 moonlight report、moonlight repair 或 moonlight finalize，"
            "不能用 done 跳过报告闭环。", 2)
    args.choice = workflow_completion.resolve_choice(step, st, args.choice)
    pending_config = _done_pending_config(step, st, args, sid)
    _done_validate_choice_and_ack(step, st, args, sid)
    _done_commit_inputs(step, st, args, sid, pending_config)
    _done_guard_branch(st, sid)
    if (_done_source_change(flow, st, sid, step)
            or _done_source_recheck(flow, st, sid, step)):
        return
    _done_require_evidence(step, st, args, sid)
    _done_finalize(flow, st, args, sid, step)

def cmd_skip(flow, st, args):
    sid = st["current"]
    step = flow["steps"][sid]
    if not step.get("skippable"):
        api.die(f"步骤 {sid} 不可跳过。", 2)
    if not args.reason:
        api.die("skip 必须 --reason 说明理由(留痕)。", 2)
    if step.get("skip_requires_ack"):
        api.die("本步不能由 Agent 自行 skip；请走当前步骤的用户确认分支。", 2)
    api.advance(flow, st, sid, step, "skipped", args.reason)

def _step_agent_kinds(step):
    kinds = set()
    for spec in step.get("evidence", []):
        typ = spec.get("type")
        if typ == "review_codecheck":
            kinds.add("CODECHECK")
            kinds.add("CODECHECK_TOOL")
        elif typ in ("agent_ran", "agent_or_no_source", "review_agent_or_no_code") and spec.get("agent"):
            kinds.add(str(spec["agent"]).upper())
    return kinds

def cmd_accept_risk(flow, st, args):
    """用户有意识地只放行当前步骤某个 Agent 令牌；不跳过同一步的其他机器证据。"""
    sid = st["current"]
    step = flow["steps"][sid]
    kind = args.agent.upper()
    required = _step_agent_kinds(step)
    # TIER_SCOPE 不是 Agent 令牌:它放行的是本步的档位范围硬校验(升级阈值),
    # 仅在挂了 tier_scope 证据的步骤可用。
    if kind == "TIER_SCOPE":
        if not any(e.get("type") == "tier_scope"
                   for e in step.get("evidence", [])):
            api.die(f"当前步骤 {sid} 没有档位范围校验,不需要 tier_scope 放行。", 2)
    elif kind not in required:
        api.die(f"当前步骤 {sid} 不需要 {kind} 令牌，不能预先或跨步骤放行。"
            + ("本步可放行: " + "、".join(sorted(required)) if required else "本步没有可风险放行的 Agent 令牌。"), 2)
    if not args.reason:
        api.die("accept-risk 必须 --reason 写清具体风险，不能只写『继续』。", 2)
    if not args.ack:
        api.die("accept-risk 必须携带用户明确承担风险的原话:--ack \"用户原话\"。", 2)
    ok, why = api._ack_verified(st, args.ack, exact=True)
    if not ok:
        api.die("accept-risk 授权验真失败:" + why, 2)
    dirty = api._blocking_dirty_source_paths(st, flow)
    if dirty:
        api.die("风险确认必须绑定稳定代码版本，但仍有未提交源码/测试/构建文件: " + "、".join(dirty[:8])
            + "。先按本单规范提交，再向用户展示风险并重新确认。", 2)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    inherited_dirty = api._unchanged_initial_dirty_source_paths(st, flow)
    task = (st.get("agent_tasks", {}) or {}).get(kind, {})
    rec = {"step": sid, "head": api.sh("git rev-parse --verify HEAD"), "at": now,
           "task_sha256": task.get("sha256", ""), "reason": args.reason, "ack": args.ack,
           "unchanged_initial_dirty": inherited_dirty}
    st.setdefault("risk_acceptances", {})[kind] = rec
    st.setdefault("history", []).append(
        {"step": sid, "result": "accept-risk:" + kind, "note": args.reason, "at": now})
    api.save_state(st)
    print(f"[mae-flow] 用户已确认承担 {kind} 令牌缺失风险；仅放行当前步骤 {sid}、当前代码版本。")
    print("风险: " + args.reason)
    if inherited_dirty:
        print("审计:以下流程启动前已脏文件指纹未变，不算本单变化: "
              + "、".join(inherited_dirty[:8]))
    print("其他机器证据不会跳过；源码/测试变化、任务卡变化或进入下一步后，本次放行自动失效。现在重新执行 done。")

def _workflow_chain(flow, wf):
    """按交付方式线性展开步骤链(可选询问步取"做"分支展示完整形态)。"""
    return workflow_transitions.workflow_chain(flow, wf)

def cmd_steps(flow, st, args):
    """工作流全景:每条交付方式背后的完整步骤链、每步卡什么、哪些环节可裁。

    透明化诉求:用户选档/裁剪前先看得见全貌;质量门禁步骤不在可裁白名单。"""
    current = st.get("current") if st else None
    active_wf = (st.get("choices", {}) or {}).get("workflow") if st else None
    ask_labels = {"grill_ask": "需求质询", "grill": "需求质询",
                  "story_ask": "STORY", "story": "STORY"}
    for wf in ("full", "hotfix", "tweak", "review"):
        marker = "(本单)" if wf == active_wf else ""
        print("\n═══ %s(%s)%s ═══" % (WORKFLOW_LABELS[wf], wf, marker))
        for sid in _workflow_chain(flow, wf):
            step = flow["steps"][sid]
            tags = []
            if sid in ("grill_ask", "story_ask"):
                tags.append("可选环节:%s(流程内询问决定)" % ask_labels[sid])
            elif sid in ("grill", "story"):
                tags.append("随「%s」询问可选" % ask_labels[sid])
            if step.get("user_ack"):
                tags.append("用户确认")
            evidence = sorted({e.get("type", "?")
                               for e in step.get("evidence", [])})
            here = "▶" if (wf == active_wf and sid == current) else " "
            print(" %s %-28s %s%s" % (
                here, sid + " " + step.get("title", ""),
                ("[" + "、".join(tags) + "] ") if tags else "",
                ("证据:" + ",".join(evidence)) if evidence else "(无硬证据)"))
    print("\n可选环节(需求质询/STORY)由流程内询问逐单决定;其余步骤为流程完整性"
          "的一部分,不提供配置级裁剪。")

def cmd_status(flow, st, args):
    sid = st["current"]
    step = flow["steps"][sid]
    if args.inject:
        cfg = st.get("config", {})
        parts = []
        if cfg.get("单号"):
            parts.append(f"单号 {cfg['单号']},commit 格式 [{cfg['单号']}][{cfg.get('单号类型', 'feat|fix')}]描述")
        if cfg.get("分支名"):
            parts.append("分支 " + cfg["分支名"])
        if cfg.get("CHANGE_NAME"):
            parts.append("change " + cfg["CHANGE_NAME"])
        if api._moonlight(st):
            parts.append("月光宝盒=无人值守;禁止向用户提问;质量失败尽力修复后用 moonlight defer 留痕继续")
        ctx = (";" + ";".join(parts)) if parts else ""
        me = os.path.abspath(sys.argv[0])
        print(f"[mae-flow 状态] 当前步骤: {sid}({step['title']}){ctx};{api.perms_line(step)}。"
              f"执行 python \"{me}\" current 获取指令(勿搜索脚本位置,以此路径为准),"
              f"禁止做当前步骤之外的流程动作。"
              f"(用户与流程无关的问答/阅读/分析不受此限,照常回应;但无关的源码改动应引导用户开 worktree,勿混入交付分支)")
        return
    print(json.dumps(st, ensure_ascii=False, indent=2))
