"""CLI responsibilities extracted from the historical entrypoint."""

from .shared import (
    CONFIG_CONFIRM_ACK, EXIT_PATH, HISTORY_PATH, hashlib, json, os, re, read_lines,
    read_text, review_status_count, review_statuses, sys, tempfile, time,
    workflow_advancement, write_text,
)
from .wiring import api
from mae_flow_core.orchestration.work_package import ensure_work_package

def _gitignore():
    gi = ".gitignore"
    # .mae-flow.json* 含 .tmp 原子写中间件与 .last 交付备份;历史账本单列(pattern 不覆盖)
    lines = [".mae-flow.json*", EXIT_PATH, HISTORY_PATH, ".mae-flow-work/"]
    # errors=replace:用户仓的 .gitignore 可能是 GBK 注释,严格解码会让 init 直接
    # 崩 traceback(且报错看不出和 .gitignore 有关);替换字符只影响去重判断,无害。
    txt = (read_text(gi, errors="replace")
           if os.path.exists(gi) else "")
    existing = {
        line.strip() for line in txt.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    add = [line for line in lines if line not in existing]
    if add:
        body = ("\n" if txt and not txt.endswith("\n") else "") + "\n".join(add) + "\n"
        write_text(gi, body, mode="a")
    _gitattributes()

def _gitattributes():
    """openspec/ 锁 LF:comet 的 bash 侧读 .comet.yaml 不剥 \\r,Windows autocrlf
    检出会让 comet 读到 "pass\\r" 全线报 Invalid,而 mae-flow 侧证据解析对 \\r 免疫
    ——症状是「done 说证据满足、comet 命令全报错」的双状态机分裂。"""
    ga = ".gitattributes"
    line = "openspec/** text eol=lf"
    try:
        txt = (read_text(ga, errors="replace")
               if os.path.exists(ga) else "")
        existing = {
            item.strip() for item in txt.splitlines()
            if item.strip() and not item.lstrip().startswith("#")
        }
        if line in existing:
            return
        body = (("\n" if txt and not txt.endswith("\n") else "") + "# mae-flow: comet 状态文件必须 LF(CRLF 检出会造成阶段状态读取分裂)\n"
                + line + "\n")
        write_text(ga, body, newline="\n", mode="a")
    except OSError as exc:
        print("[mae-flow] ⚠ 无法写 .gitattributes(%s);Windows autocrlf 环境请手动加入: %s"
              % (exc, line), file=sys.stderr)

def _friction_from_log(st):
    """从 hook 日志统计本单起始时间之后的摩擦(gate 拦截/契约打回/hook 异常)。
    日志不可读返回空 dict(账本/报告按缺项处理,不阻塞)。"""
    gate = bounce = anom = 0
    try:
        log_path = os.path.join(tempfile.gettempdir(), "mae-flow-hook.log")
        for line in read_lines(log_path, errors="replace"):
            if line[:19] >= st.get("started", ""):
                if "end pretooluse rc=2" in line:
                    gate += 1
                elif "end subagentstop rc=2" in line:
                    bounce += 1
                elif "WATCHDOG" in line or "EXC" in line:
                    anom += 1
    except OSError:
        return {}
    return {"gate拦截": gate, "契约打回": bounce, "hook异常": anom}

def _append_history(st, outcome="completed"):
    """终态备份前把本单摘要追加进历史账本(团队度量/推广数据)。
    失败不阻塞开新单,但必须可见(stderr)。"""
    try:
        hist = st.get("history", [])
        ended = hist[-1]["at"] if hist else st.get("started", "")

        def ts(s):
            return time.mktime(time.strptime(s, "%Y-%m-%d %H:%M:%S"))

        rec = {"单号": st.get("config", {}).get("单号", "?"),
               "workflow": st.get("choices", {}).get("workflow", "?"),
               "结果": outcome,
               "开始": st.get("started", ""), "结束": ended,
               "耗时秒": int(max(0, ts(ended) - ts(st.get("started", ended)))),
               "goto次数": sum(1 for h in hist if str(h.get("result", "")).startswith("goto:")),
               "skip次数": sum(1 for h in hist if h.get("result") == "skipped"),
               "风险放行次数": sum(1 for h in hist if str(h.get("result", "")).startswith("accept-risk:"))}
        rec.update(_friction_from_log(st))
        with open(HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[mae-flow] 历史账本写入失败(不影响流程): {e}", file=sys.stderr)

def advance(flow, st, sid, step, tag, note=""):
    # review 的增量边界由 harness 在进入裁决前冻结，后面任何模型都不能拿当前 HEAD 偷换基点。
    if sid == "branch_create" and st.get("choices", {}).get("workflow") == "review":
        base = api.sh("git rev-parse --verify HEAD")
        if not base:
            api.die("无法记录评审意见处理基点 HEAD,拒绝进入本轮修改。", 2)
        st["review_base_head"] = base
    # 兼容旧版已经停在 rf_verify 的在途单：按 history 自动恢复返工前 HEAD。
    if sid == "rf_verify" and st.get("choices", {}).get("workflow") == "review":
        _, err = api._ensure_review_base(st)
        if err:
            api.die(err, 2)
    if sid == "rf_triage":
        review_doc = os.path.join(ensure_work_package(
            os.getcwd(), st.get("config", {}).get("单号", "")).root,
            "review.md")
        try:
            review_text = read_text(review_doc, errors="replace")
        except OSError as exc:
            api.die("无法冻结评审裁决快照:" + str(exc), 2)
        st["review_triage_statuses"] = review_statuses(review_text)
        st["review_triage_transfer_count"] = review_status_count(
            review_text, "转规格轮次(已确认)")
    st.pop("unlock", None)   # 源码解锁仅限本步实例,推进即失效
    st.pop("risk_acceptances", None)   # 风险放行同样只属于当前步骤实例
    st["history"].append({"step": sid, "result": tag, "note": note, "at": time.strftime("%Y-%m-%d %H:%M:%S")})
    try:
        for event in workflow_advancement.transition_events(
                flow, st, sid, step):
            if event.kind == "audit":
                st["history"].append({
                    "step": event.step,
                    "result": event.result,
                    "note": event.note,
                    "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                })
            else:
                nxt = event.step
    except workflow_advancement.TransitionResolutionError as exc:
        api.die(f"月光旁路步骤 {exc.step_id} 缺少可解析的 moonlight_choice/next，拒绝卡死流程。", 2)
    if api._moonlight(st) and sid == "push":
        api._moonlight_resolve_kind(st, "push")
        ml = api._moonlight_data(st)
        ml["pushed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        ml["pushed_head"] = api.sh("git rev-parse --verify HEAD")
    st["current"] = nxt
    if nxt:
        st.setdefault("step_heads", {})[nxt] = api.sh("git rev-parse --verify HEAD")
    api.save_state(st)
    if api._moonlight(st) and nxt == "moonlight_review":
        api._write_moonlight_report(flow, st)
    print(f"[mae-flow] {sid} {tag} → 进入 {nxt}\n")
    api.print_current(flow, st)

def _validated_pending_config(step, st, set_values):
    """Build and fully validate a candidate without touching confirmed config."""
    sid = st["current"]
    # 配置先在内存候选副本里完成全部校验；任何一步失败都不污染已确认状态。
    # 旧实现遇到需求路径不存在会先 save_state，导致下一轮继续携带半套/乱码配置。
    pending_config = dict(st.get("config", {}) or {})
    allowed_sets = api._allowed_set_keys(step)
    for kv in set_values or []:
        if "=" not in kv:
            api.die(f"--set 需为 k=v 形式: {kv}")
        k, v = kv.split("=", 1)
        if k not in allowed_sets:
            api.die(f"当前步骤 {sid} 不允许写配置项「{k}」。已确认配置不能在后续步骤偷偷改写；"
                "确需调整请经用户确认 goto config_confirm 后修改。", 2)
        bad = api._validate_config_value(k, v)
        if bad:
            api.die(f"{k}「{v}」不合法:{bad}。", 2)
        pending_config[k] = v
    if pending_config.get("单号") and not pending_config.get("单号类型"):
        pending_config["单号类型"] = "feat" if pending_config["单号"].startswith("REQ") else "fix"
    # 需求文档:单号与需求完全解耦(单号只管 git 命名,需求只管做什么),内容对不对只有用户能判定,
    # 机器只拦"路径是假的"这一种硬错;"拿对文档"靠 config_confirm 的单独确认(展示摘录给用户核实)
    new_keys = [kv.split("=", 1)[0] for kv in (set_values or []) if "=" in kv]
    doc = pending_config.get("需求文档", "")
    if "需求文档" in new_keys and not os.path.exists(doc):
        api.die(f"需求文档「{doc}」不存在——路径必须真实可读。"
            "用户口述/粘贴的需求须先原文照录落盘(如 docs/req/REQ-<单号>.md)并经用户确认,再以该路径 --set。", 2)
    if doc and ("需求文档" in new_keys or sid == "config_confirm"):
        ok, why = api._validate_requirement_document(doc)
        if not ok:
            api.die(f"需求文档「{doc}」未通过严格文本校验:{why}。"
                "不要让用户重复说“我确认”，确认无法修复坏文件；"
                "用户口述用 messages + requirement-record --message-id，"
                "已有 GBK/UTF-16 文本用 requirement-record --source 规范化。", 2)
    if step.get("require_sets"):
        missing = [k for k in step["require_sets"] if not pending_config.get(k)]
        if missing:
            remedy = ("用 --set 补齐；月光模式禁止询问用户，只能从本轮需求原话、仓库预设、"
                      "当前分支和代码事实中保守取得，不能编造"
                      if api._moonlight(st) else "用 --set 补齐;缺失项应询问用户")
            api.die("配置缺失,禁止推进: " + "、".join(missing) + "(" + remedy + ")", 2)
        if "基线分支" in step["require_sets"]:
            derived_branch = "{基线分支}_{工号}_{单号}".format(**pending_config)
            bad = api._validate_config_value("分支名", derived_branch)
            if bad:
                api.die("脚本按基线分支、工号和单号生成的分支名「%s」不合法:%s。"
                    "请修正组成字段后重新确认，不能带着非法 ref 进入后续步骤。"
                    % (derived_branch, bad), 2)
            supplied_branch = pending_config.get("分支名", "")
            if supplied_branch and supplied_branch != derived_branch:
                api.die(
                    "分支名无需 Agent 拼接，脚本按基线分支、工号和单号确定生成。"
                    "收到的分支名「%s」与应为的「%s」不一致；删除该 --set 后重试。"
                    % (supplied_branch, derived_branch), 2)
            pending_config["分支名"] = derived_branch
    return pending_config

def _config_review_excerpt(path):
    try:
        text = read_text(path)
    except OSError:
        return ""
    lines = [re.sub(r"\s+", " ", line).strip()
             for line in text.splitlines() if line.strip()]
    return " / ".join(lines[:3])[:300]

def _print_config_review(review, step):
    pending = review.get("config") or {}
    print("[mae-flow] 完整配置确认单（收据 %s，指纹 %s）" % (
        review.get("id", "?"), str(review.get("sha256", ""))[:12]))
    for key in step.get("require_sets", []):
        print("  %s: %s" % (key, pending.get(key, "")))
    print("  分支名: %s" % pending.get("分支名", ""))
    excerpt = _config_review_excerpt(pending.get("需求文档", ""))
    if excerpt:
        print("  需求内容摘录: " + excerpt)

def cmd_config_review(flow, st, args):
    if st.get("current") != "config_confirm":
        api.die("config-review 只用于配置确认阶段。其他步骤的已确认配置不能偷偷改写。", 2)
    if api._moonlight(st):
        api.die("月光宝盒不询问用户，不需要 config-review；按 current 指令保守补齐配置后直接 done。", 2)
    step = flow["steps"]["config_confirm"]
    pending = _validated_pending_config(step, st, args.set or [])
    requirement_sha = api._requirement_sha256(pending.get("需求文档", ""))
    digest = api._config_sha256(pending, requirement_sha)
    review_id = hashlib.sha256(
        (digest + "\0" + str(time.time_ns())).encode("utf-8")).hexdigest()[:16]
    st["config_review"] = {
        "step": "config_confirm",
        "id": review_id,
        "sha256": digest,
        "config": pending,
        "requirement_sha256": requirement_sha,
        "head": api.sh("git rev-parse --verify HEAD"),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    api.save_state(st)
    api._ack_failure(st, success=True)

    _print_config_review(st["config_review"], step)
    print("\n现在只做一次最终确认。用 AskUserQuestion 原样询问：")
    print("  上述完整配置是否正确？")
    print("选项：")
    print("  - " + CONFIG_CONFIRM_ACK)
    print("  - 需要修改")
    print("不要把前面多个单项回答拼成 ack，也不要再次调用 config-review。")
    print("用户选择确认后执行：")
    print('python "%s" done' % os.path.abspath(sys.argv[0]))
    print("若 AskUserQuestion 的选择结果未被宿主回传，让用户直接发送同一句普通消息后重试；"
          "无需退出或重新初始化。")
