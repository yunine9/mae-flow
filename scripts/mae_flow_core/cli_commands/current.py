"""CLI responsibilities extracted from the historical entrypoint."""

from mae_flow_core.quality.spec2code_recovery import (
    recovery_guidance,
)
from mae_flow_core.delivery.checkpoints import misplaced_checkpoint_step

from .shared import (
    CapabilityError, DEFAULTS_PATH, HERE, MOONLIGHT_QUALITY_STEPS, STEPS_DIR, json,
    load_json, os, re, read_text, render_pack, subst, sys, time, workflow_transitions,
)
from .wiring import api

def perms_line(step):
    allow, forbid = [], []
    (allow if step.get("allow_source_edit") else forbid).append("修改源码")
    (allow if step.get("allow_specs_write") else forbid).append("写 openspec/specs/ 真相源")
    return "允许: " + ("、".join(allow) or "仅本步指令内动作") + ";禁止: " + "、".join(forbid + ["编辑 .comet.yaml"])

def _spec_data(st):
    """本单的交付登记(阶段与产物指针)。

    v3:阶段状态收归 .mae-flow.json 单一裁决源——此前它活在 comet 的 .comet.yaml 里,
    形成第二状态机:phase 掉队、僵尸 change、Bash 直写伪造、CRLF 双脑分裂全部源于此。
    现在与流程状态同文件、同一把锁、同一份 gate 保护,不需要哨兵对账。"""
    return st.setdefault("spec", {})

def _spec_phase(st):
    return str(_spec_data(st).get("phase", "") or "")

def _active_change_count():
    """在建区活跃 change 计数(排除 archive/ 与已归档)。>1 = 有历史残留未归档。"""
    n = 0
    try:
        for d in os.listdir(os.path.join("openspec", "changes")):
            full = os.path.join("openspec", "changes", d)
            if os.path.isdir(full) and d != "archive":
                n += 1
    except OSError:
        pass
    return n

def _sentinel_lines(sid, st):
    """在建区残留诊断。阶段错位这一整类随 v3 消失(阶段与流程同源,不可能不一致)。"""
    out = []
    n = _active_change_count()
    if n > 1:
        out.append(f"⚠ 在建区有 {n} 个 change 目录(应只有当前单一个)。当前单为 "
                   f"{(st.get('config', {}) or {}).get('CHANGE_NAME', '?')},其余是历史残留——"
                   "做完没定稿的补定稿,废弃的经用户确认移除,以免规格产物混淆。")
    return out

def _next_from_step(step, st, choice_override=""):
    """解析步骤去向；月光旁路可显式指定其保守分支而不伪造用户选择。"""
    return workflow_transitions.next_step(step, st, choice_override)

def _resolved_next(flow, st, sid):
    """按当前 choices 解析某历史步骤的去向，供旧状态恢复入口 HEAD。"""
    return workflow_transitions.resolved_next(flow, st, sid)

def _ensure_step_entry_head(flow, st, sid):
    """为旧版在途 tests_only 步骤恢复入口 HEAD。

    新版 advance 会直接记录精确 HEAD。旧状态只能从“上一阶段进入当前步骤”的历史时间反推，
    使用该时间之前最后一个 commit；时间同秒时最多多包含一笔旧改动，只会多验，不会漏验。
    绝不以当前 HEAD 兜底，因为当前 HEAD 可能已经包含 UT 阶段偷偷修改的源码。
    """
    old = (st.get("step_heads", {}) or {}).get(sid, "")
    if old and api.argv_out(["git", "cat-file", "-t", old]) == "commit":
        return old, ""
    entered_at = ""
    for h in reversed(st.get("history", [])):
        result = str(h.get("result", ""))
        if result == "goto:" + sid or _resolved_next(flow, st, h.get("step", "")) == sid:
            entered_at = h.get("at", "")
            break
    if not entered_at:
        return "", f"历史中找不到进入 {sid} 的转换记录"
    base = api.argv_out(["git", "rev-list", "-1", "--before=" + entered_at, "HEAD"])
    if not base or api.argv_out(["git", "cat-file", "-t", base]) != "commit":
        return "", f"无法按进入时间 {entered_at} 解析安全基点"
    st.setdefault("step_heads", {})[sid] = base
    st.setdefault("migrations", []).append({
        "type": "recover-step-head", "step": sid, "head": base,
        "from_history_at": entered_at, "at": time.strftime("%Y-%m-%d %H:%M:%S")})
    api.save_state(st)
    return base, ""

def _with_lightcheck_prompt(sid, text):
    if sid not in (
            "build", "rf_fix", "tw_change", "verify_ponytail",
            "verify_ut", "rf_ut", "tw_ut"):
        return text
    prompt = (
        "\n\n──── 轻量编码预防（建议层，不新增门禁） ────\n"
        "写每个函数时主动控制：正式入参≤5（Python self/cls 不计）、"
        "有效代码行≤50（空行/纯注释/仅括号分隔行不计）、控制结构最大嵌套深度≤5、"
        "本次新增/修改代码行≤120字符。长行禁止机械切字符串：优先仓库 formatter 配置，"
        "否则参考同文件附近同类参数列表/条件/链式调用的换行方式。\n"
        "提交 Hook 会自动执行轻量检查，无需主动调用或向用户展示 CLEAN 结果；"
        "只修 Hook 提示中高置信且属于本次范围的建议，最多修复并复查两轮。"
        "工具异常、超时、解析不确定或仅为基线旧债时直接留痕继续，"
        "不得扩大需求、不得让用户确认、不得把它当正式 CodeCheck。"
    )
    return text + prompt

def _step_md_text(sid, st):
    """步骤指令文本:模板路径与已确认配置全部替换后返回(无该 md 返回 None)。
    占位符替换 = 把"需要模型去拿"的信息直接喂到嘴边(弱模型会跳过"去拿"的动作);
    未确认的配置键保持 {原样},不误伤。"""
    md = os.path.join(STEPS_DIR, sid + ".md")
    if not os.path.exists(md):
        return None
    txt = read_text(md).rstrip()
    for ph, name in (("{STORY_TEMPLATE_PATH}", "STORY-TEMPLATE.md"),
                     ("{GRILL_PREP_TEMPLATE_PATH}", "GRILL-PREP-TEMPLATE.md"),
                     ("{REVIEW_TEMPLATE_PATH}", "REVIEW-TEMPLATE.md")):
        txt = txt.replace(ph, os.path.abspath(
            os.path.join(HERE, "..", "skills", "mae-flow", "assets", name)))
    txt = txt.replace("{MAEFLOW_PATH}", os.path.abspath(sys.argv[0]))
    for pack in re.findall(r"\{\{CAPABILITY_PACK:([a-z0-9-]+)\}\}", txt):
        marker = "{{CAPABILITY_PACK:%s}}" % pack
        try:
            txt = txt.replace(marker, render_pack(pack))
        except CapabilityError as exc:
            api.die("插件内嵌能力包损坏，当前步骤不能可靠执行: %s。"
                "请升级/重装 Mae-Flow；流程状态尚未推进。" % exc, 2)
    return subst(_with_lightcheck_prompt(sid, txt), st)

def _review_receipt_lines(st, step):
    """生成编译后人工检视收据；只展示机器解析出的本轮精确 Git 范围。"""
    evidence = next(
        (item for item in step.get("evidence", [])
         if item.get("type") == "review_snapshot"), {})
    base_step = evidence.get("base_step", "")
    base = (st.get("step_heads", {}) or {}).get(base_step, "")
    head = api.sh("git rev-parse --verify HEAD")
    if (not base or not head
            or api.argv_out(["git", "cat-file", "-t", base]) != "commit"):
        return ["❌ 无法生成本轮检视收据：缺少可信 Git 基点；done 会安全拒绝。"]
    commits = api.argv_out([
        "git", "-c", "core.quotepath=false", "log", "--format=%h %s",
        base + ".." + head,
    ]).splitlines()
    files = api.argv_out([
        "git", "-c", "core.quotepath=false", "diff", "--name-status",
        base, head,
    ]).splitlines()
    stat = api.argv_out([
        "git", "-c", "core.quotepath=false", "diff", "--shortstat",
        base, head,
    ])
    lines = [
        "🔎 本轮代码检视收据（确认只对这一版有效）",
        f"  范围: {base[:10]}..{head[:10]}（入口步骤 {base_step} → 编译通过）",
        "  提交:",
    ]
    lines += ["    " + item for item in commits[:30]] or ["    （本轮没有新提交）"]
    if len(commits) > 30:
        lines.append(f"    …另有 {len(commits) - 30} 个提交")
    lines.append("  文件:")
    lines += ["    " + item for item in files[:80]] or ["    （本轮没有文件差异）"]
    if len(files) > 80:
        lines.append(f"    …另有 {len(files) - 80} 个文件")
    if stat:
        lines.append("  统计: " + stat)
    lines.append(f"  完整差异命令: git diff {base} {head}")
    return lines

def _defaults():
    """读仓库预设 .mae-flow-defaults.json。解析失败必须可见(fail-open 但可观测,不静默吞)。"""
    if not os.path.exists(DEFAULTS_PATH):
        return None, ""
    try:
        # utf-8-sig:Windows 编辑器手写的 JSON 常带 BOM,对无 BOM 文件无害
        return load_json(DEFAULTS_PATH, encoding="utf-8-sig"), ""
    except Exception as e:
        return None, f"⚠ {DEFAULTS_PATH} 解析失败,已忽略(修复该 JSON 或删除): {e}"

def print_current(flow, st):
    recovery_step = misplaced_checkpoint_step(st)
    if recovery_step:
        previous = st.get("current", "")
        item = api._checkpoint_current(st)
        if item:
            item["legacy_forced_goto_recovered"] = True
        st["current"] = recovery_step
        st.setdefault("history", []).append({
            "step": previous,
            "result": "checkpoint:auto-recover:" + recovery_step,
            "note": "旧版本曾绕过未闭环 CP，自动恢复到所属编码步骤",
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        api.save_state(st)
        print(
            "[mae-flow] 检测到旧版本把未闭环检查点跳到了 %s；"
            "已保留全部文件和提交，自动恢复到 %s。"
            % (previous, recovery_step)
        )
    sid = st["current"]
    step = flow["steps"][sid]
    print(f"═══ 当前步骤: {sid} — {step['title']} ═══")
    if api._moonlight(st):
        ml = api._moonlight_data(st)
        print(f"🌙 月光宝盒运行中（第 {ml.get('cycle', 1)} 轮）：禁止询问用户；"
              "能从需求、代码和仓库规则判断的直接采用保守结论并留痕。")
        print("目标：尽力完成并推送当前分支。质量问题先真实修复；有限尝试后仍失败则登记遗留并继续，"
              "禁止伪装通过、删除测试、缩小测试范围或自动豁免。")
        print("覆盖规则：下方普通步骤文字里的“询问用户 / AskUserQuestion / 等用户拍板”在本模式下一律不执行。"
              "分析和配置从用户原话、仓库预设、当前分支及代码事实中保守推断；"
              "质量裁决拿不准时不得替用户选择豁免，走本步的 moonlight defer。")
        request = str(ml.get("request", "")).strip()
        if request:
            preview = request[:800] + ("…" if len(request) > 800 else "")
            print("──── 月光宝盒启动需求（已持久化，断点恢复以此为准） ────")
            print(preview)
        unresolved = api._moonlight_unresolved(st)
        if unresolved:
            print("──── 当前遗留（修复轮必须优先处理） ────")
            print(api._moonlight_issue_context(st))
    print(perms_line(step))
    for _w in _sentinel_lines(sid, st):
        print(_w)
    if st.get("spec2code") and sid in {
            "test_blueprint", "build_plan", "build", "verify_ut"}:
        print("\n".join(recovery_guidance(
            st,
            is_file=os.path.isfile,
            read_text=lambda path: read_text(
                path, encoding="utf-8"),
        )))
    checkpoint_state = api._development_review(st)
    if checkpoint_state and checkpoint_state.get("status") == "active":
        mode_label = ("分阶段先检视、后提交并 push"
                      if checkpoint_state.get("mode") == "staged"
                      else "一次完成、最终统一检视")
        print("🧭 开发节奏: " + mode_label)
        current_checkpoint = api._checkpoint_current(st)
        if sid == api._checkpoint_expected_code_step(st) and current_checkpoint:
            print("   当前检查点: %s [%s] %s" % (
                current_checkpoint.get("id"),
                current_checkpoint.get("status"),
                current_checkpoint.get("title")))
            if current_checkpoint.get("status") == "push_pending":
                if api._review_before_commit(checkpoint_state):
                    print("   用户检视过的精确提交待推送；普通 push 后执行 checkpoint status 验真。")
                else:
                    print("   编译已通过；完成普通 push 后执行 checkpoint status 冻结远端检视收据。")
            elif current_checkpoint.get("status") == "commit_pending":
                base = str((current_checkpoint.get("receipt") or {}).get(
                    "base", ""))
                if api.sh("git rev-parse --verify HEAD") == base:
                    add, commit = api._checkpoint_commit_command(
                        st, current_checkpoint)
                    print("   用户已确认未提交 diff；现在精确提交后执行 checkpoint status：")
                    print("     " + add)
                    print("     " + commit)
                else:
                    print("   检查点提交已产生但尚未核验；禁止再次 commit/push，"
                          "直接执行 checkpoint status。")
            elif current_checkpoint.get("status") == "commit_recovery":
                print("   提交核验失败且 push 已冻结："
                      + str(current_checkpoint.get("verification_error", "")))
                print("   展示现场后让用户选择「需要调整代码」，再执行 checkpoint decide revise。")
            elif current_checkpoint.get("status") == "reset_pending":
                base = str((current_checkpoint.get("receipt") or {}).get(
                    "base", ""))
                print("   用户已授权拆回错误提交；执行 git reset --mixed %s，"
                      "然后 checkpoint status。" % base)
            elif current_checkpoint.get("status") in {
                    "planned", "plan_review_pending",
                    "craft_pending", "craft_decision_pending",
                    "review_pending"}:
                api._show_checkpoint_review(
                    st, checkpoint_state, current_checkpoint)
        elif (sid == api._checkpoint_expected_code_step(st)
              and (checkpoint_state.get("final_rework") or {}).get("status")
              == "coding"):
            print("   当前是最终检视返工，不新增或重开原 CP。按本步骤提交修改并走正常编译/质量链，"
                  "不要再执行 checkpoint ready；回到 delivery_review 后会重新展示完整增量。")
        if sid == "delivery_review":
            final = api._final_review_active(checkpoint_state)
            if final:
                api._show_final_review_receipt(st, checkpoint_state, final)
            else:
                changed, review_err = api._final_review_delta(st)
                if review_err:
                    print("❌ 最终检视基点异常: " + review_err)
                elif changed:
                    print("🔎 质量链后仍有未检视代码增量: "
                          + "、".join(changed[:8]))
                    print("   执行 checkpoint final 生成最终收据；"
                          "不能直接进入不可逆规格定稿。")
                else:
                    print("✅ 当前最终代码已被既有检查点/最终收据完整覆盖，无需重复确认。")
    if any(e.get("type") == "review_snapshot"
           for e in step.get("evidence", [])):
        print("\n".join(_review_receipt_lines(st, step)))
    ul = st.get("unlock") or {}
    if ul.get("step") == sid:
        print(f"🔓 本步源码修改已解锁(用户裁决: {ul.get('reason', '')};推进后自动失效)")
    for kind, rec in sorted((st.get("risk_acceptances", {}) or {}).items()):
        if rec.get("step") != sid:
            continue
        valid, why = api._risk_acceptance(kind, st)
        if valid:
            print(f"⚠ 用户已承担 {kind} 令牌缺失风险，本步按放行继续；其他证据仍会检查。")
        else:
            print(f"⚠ {kind} 风险放行已失效: {why}；需要重新取证或重新让用户确认。")
    if step.get("tests_only"):
        if not (st.get("step_heads", {}) or {}).get(sid):
            head, why = _ensure_step_entry_head(flow, st, sid)
            if head:
                print(f"♻ 已从旧版流程历史恢复本步入口 HEAD: {head[:9]}（只会扩大重验范围，不会漏验）")
            else:
                print("❌ 旧版 UT 入口 HEAD 无法自动恢复: " + why + "；done 将安全拒绝，禁止拿当前 HEAD 补位")
        tp = api._test_patterns(st)
        if tp:
            print("🛡 UT 写入边界:使用仓库配置的测试路径硬拦非测试源码: " + " | ".join(tp))
        else:
            print("⚠ UT 写入边界:仓库未配置「测试路径」，当前使用内置保守规则硬拦非测试源码。"
                  "若本仓测试目录不符合 tests/、test/、src/test/、*_test.*、*Test.java，"
                  "请先在 .mae-flow-defaults.json 配置「测试路径」，禁止用 unlock 把长期目录差异当单次源码缺陷处理。")
    if step.get("clear_hint"):
        print("💡 会话卫生:本步开始前若会话已较长,建议 /clear 后说「继续」——状态在磁盘,进度不丢,防长上下文行为漂移。")
    if sid == "config_confirm" and not api._moonlight(st):
        print("⚠ 本步先收集配置值，再由 config-review 生成完整确认单。"
              "只有确认单后的最终回答能推进；基线分支、单号等局部回答不能代替整单确认。")
    elif step.get("user_ack") and not api._moonlight(st):
        print("⚠ 本步有真实用户决策:用 AskUserQuestion 呈现固定选项，用户点选后同轮直接 done。"
              "按钮结果由 harness 自动读取，不要再要求用户手动输入“确认××”；"
              "只有宿主确实不回传按钮结果时才退回一次纯文本选择。")
    elif step.get("user_ack") and api._moonlight(st):
        print("🌙 本步原本需要用户确认，现由月光宝盒启动授权代替；禁止调用 AskUserQuestion。"
              "按最保守且不扩大需求的选项继续，并把决定写入阶段产物。")
    if step.get("terminal"):
        print("流程已完成。")
        txt = _step_md_text(sid, st)
        if txt:
            print(txt)
        return
    txt = _step_md_text(sid, st)
    if txt is not None:
        print("──── 执行指令 ────")
        print(txt)
    if api._moonlight(st) and sid in MOONLIGHT_QUALITY_STEPS:
        print("──── 尽力而为出口 ────")
        print("先真实执行本步并尝试修复；确认继续尝试只会重复消耗后，提交当前有效改动，然后执行：")
        print(f"python \"{os.path.abspath(sys.argv[0])}\" moonlight defer "
              "--reason \"<遗留现象、已尝试修复、当前风险>\"")
        print("该命令会把问题写入晨间报告并继续下一阶段，不会把失败伪装成通过。")
    if api._moonlight(st) and step.get("tests_only"):
        print("UT 若经自查后明确指向被测源码缺陷，不需要等用户：先执行")
        print(f"python \"{os.path.abspath(sys.argv[0])}\" moonlight unlock-source "
              "--reason \"<失败用例、规格依据、自查结论>\"")
        print("再修源码并提交；done 会自动回流编译、CodeCheck 和 UT。")
    if api._moonlight(st) and sid == "push":
        print("push 若因认证、网络或冲突在有限重试后仍失败，禁止询问或谎报成功；执行：")
        print(f"python \"{os.path.abspath(sys.argv[0])}\" moonlight push-failed "
              "--reason \"<错误原文和已尝试处理>\"")
        print("状态会停在 push，早晨修好远端问题后直接重新 push + done。")
    if api._moonlight(st) and api._moonlight_can_block(sid):
        print("若不是质量失败，而是需求材料、权限或外部依赖客观缺失，继续执行已无意义，执行：")
        print(f"python \"{os.path.abspath(sys.argv[0])}\" moonlight blocked "
              "--reason \"<缺失条件、已尝试确认、为什么无法继续>\"")
        print("它会生成晨间报告并允许本轮正常停止，不会让 Stop Hook 无限打回。")
    if sid == "moonlight_review":
        return
    if step.get("require_sets"):
        dft, warn = _defaults()
        if warn:
            print(warn)
        show = {k: v for k, v in (dft or {}).items() if k in step["require_sets"]}
        if show:
            suffix = ("月光模式下须结合用户原话与仓库事实自行核验后 --set，不得询问或编造"
                      if api._moonlight(st) else
                      "候选值;缺项时只询问取值，最后随完整配置确认单一次确认")
            print(f"──── 仓库预设({DEFAULTS_PATH},{suffix}) ────")
            for k, v in show.items():
                print(f"  {k} = {v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)}")
    print("──── 完成后执行 ────")
    if sid == "config_confirm" and not api._moonlight(st):
        review = st.get("config_review") or {}
        if review.get("sha256"):
            api._print_config_review(review, step)
            print("展示上述确认单后只问一次最终确认；不要再拼接前面的单项回答。")
            print('python "%s" done' % os.path.abspath(sys.argv[0]))
        else:
            sets = " --set ".join(
                key + "=<值>" for key in step.get("require_sets", []))
            print('python "%s" config-review --set %s' % (
                os.path.abspath(sys.argv[0]), sets))
            print("该命令会一次性校验并展示完整配置；用户最终确认后再执行它输出的简短 done 命令。")
        return
    extra = ""
    if step.get("choice_key"):
        extra += f" --choice <{'|'.join(step['choices'])}>"
    if step.get("require_sets"):
        missing_sets = [
            k for k in step["require_sets"]
            if not (st.get("config", {}) or {}).get(k)
        ]
        if missing_sets:
            extra += " --set " + " --set ".join(k + "=<值>" for k in missing_sets)
    # python(非 python3:Windows 无此命令);abspath(非 relpath:跨盘符 relpath 抛 ValueError)
    print(f"python \"{os.path.abspath(sys.argv[0])}\" done{extra}")
    if step.get("skippable"):
        print(f"(可跳过: ... skip --reason \"<理由>\")")
