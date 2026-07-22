#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dispatch.py — 跨平台 hook 分发器(Windows 优先,零 POSIX 依赖)。

用法(hooks.json 中,shell form——公司 codeagent 实测**不支持** exec form 的 args 数组:
只执行 command 本体,payload 落进 python 的 stdin 被当脚本解析,JSON 的 false 炸 NameError,2026-07-20 实战):
  python "${CODEAGENT3_PLUGIN_ROOT}/hooks/dispatch.py" <事件>
事件:pretooluse | userprompt | sessionstart | subagentstop | posttooluse
(Windows 上 hook 经 Git Bash 执行,${VAR} 可展开;路径带引号防空格)
输入:stdin 的 hook JSON。exit 2 = 拦截/打回(stderr 回传模型);其余一律 0(fail-open)。

防卡死设计(hook 在每条消息上同步执行,任何阻塞都会冻住整个会话):
  - 看门狗:进程存活超过 WATCHDOG_SECS 秒无条件 os._exit(0) 放行;
  - stdin 读取放在守护线程里,STDIN_SECS 秒拿不到 EOF 按空输入处理
    (防 harness 不关闭 stdin 导致 read() 永久阻塞);
  - 调 mae-flow 的子进程带超时;
  - 每次调用在 %TEMP%/mae-flow-hook.log 记 start/end 与耗时,
    只有 start 没有 end = 该次挂起被看门狗击杀,可据此定位。
"""
import glob, hashlib, json, os, re, subprocess, sys, tempfile, threading, time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
MAEFLOW = os.path.join(HERE, "..", "scripts", "mae-flow.py")
STATE = ".mae-flow.json"
EXIT_STATE = ".mae-flow.json.exited"
REJECTION_STATE = STATE + ".agent-rejections"
EVIDENCE_STATE = STATE + ".agent-evidence"
LOG = os.path.join(tempfile.gettempdir(), "mae-flow-hook.log")
WATCHDOG_SECS = 12
STDIN_SECS = 3
SUBPROC_SECS = 8
_T0 = time.time()


def _log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%s pid=%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), os.getpid(), msg))
    except Exception:
        pass


def _arm_watchdog():
    def _kill():
        _log("WATCHDOG timeout(%ss) — force exit 0(fail-open)" % WATCHDOG_SECS)
        os._exit(0)
    t = threading.Timer(WATCHDOG_SECS, _kill)
    t.daemon = True
    t.start()


def maeflow(*args):
    """以当前解释器调 mae-flow,stderr 透传,返回退出码。超时视为放行。"""
    try:
        r = subprocess.run([sys.executable, MAEFLOW, *args],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=SUBPROC_SECS)
    except subprocess.TimeoutExpired:
        _log("maeflow %s TIMEOUT" % (args,))
        return 0
    if r.stdout:
        print(r.stdout, end="")
    if r.stderr:
        print(r.stderr, end="", file=sys.stderr)
    return r.returncode


def read_input():
    """守护线程读 stdin。payload 惯例是单行 JSON,用 readline(见换行即返回)而非 read()(等 EOF):
    公司 harness 写完 payload 后关闭管道晚/不关,read() 等 EOF 会在 3s 兜底处误判超时、把已到的数据丢掉
    (2026-07-20 实战定位:exec form 时代 python 把 stdin 当脚本能读到完整 JSON,证明数据在管道里,只是 EOF 迟)。
    readline 解析失败(罕见多行 payload)再补读到 EOF;3s 仍拿不到按空输入,只兜底不阻塞。"""
    box = {}

    def _r():
        try:
            buf = sys.stdin.readline()
            try:
                box["d"] = json.loads(buf or "{}")
                box["n"] = len(buf)
                return
            except Exception:
                pass
            buf += sys.stdin.read()
            box["d"] = json.loads(buf or "{}")
            box["n"] = len(buf)
        except Exception:
            box["d"] = {}
            box["n"] = -1

    th = threading.Thread(target=_r, daemon=True)
    th.start()
    th.join(STDIN_SECS)
    if "d" not in box:
        _log("stdin read timeout(%ss) — 按空输入处理" % STDIN_SECS)
        return {}
    if not box["d"]:
        _log("stdin empty/unparsed(n=%s) — 按空输入处理" % box.get("n"))
    return box["d"]


def _chdir_root(d):
    """hook 进程的 cwd 是 codeagent 启动目录,未必是项目根。
    以 hook JSON 的 cwd 为基准向上找 .mae-flow.json 或退出标记并 chdir;
    找不到则退回 JSON cwd(init 之前属正常)。mae-flow 自身还会再定位一次,双保险。"""
    base = d.get("cwd") or os.getcwd()
    probe = os.path.abspath(base)
    while True:
        if (os.path.exists(os.path.join(probe, STATE))
                or os.path.exists(os.path.join(probe, EXIT_STATE))):
            if probe != os.getcwd():
                _log("chdir 项目根: " + probe)
            os.chdir(probe)
            return
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    try:
        os.chdir(base)
    except Exception:
        pass


def ev_pretooluse(d):
    tool = d.get("tool_name", "")
    ti = d.get("tool_input") or {}
    if tool in ("Edit", "Write", "MultiEdit"):
        p = ti.get("file_path", "") or ""
        if p:
            sys.exit(maeflow("gate", "edit", p))
    elif tool == "Bash":
        c = ti.get("command", "") or ""
        if c:
            sys.exit(maeflow("gate", "bash", c))
    sys.exit(0)


def ev_inject(d, session_start=False):
    if session_start:
        # 重启会话 = skill 已重新加载:清"待重启"标记(迁移后真空期的唯一合法出口)
        try:
            if os.path.exists(".mae-flow-need-reload"):
                os.remove(".mae-flow-need-reload")
                _log("cleared need-reload(会话重启,skill 已加载)")
        except Exception as e:
            _log("clear need-reload EXC: %s" % e)
    else:
        # 用户消息原文进 ack 验真存储。payload 无 prompt 字段时确认步骤会明确拒绝并要求用户
        # 再发一条普通消息，不再降级成模型自行填写 ack。
        _capture_usermsg(d.get("prompt") or "")
    me = os.path.abspath(MAEFLOW)
    readme = os.path.abspath(os.path.join(HERE, "..", "README.md"))
    if os.path.exists(STATE):
        maeflow("status", "--inject")
        if session_start:
            print(f"[mae-flow] 存在进行中的交付流程。续跑先执行 python \"{me}\" current 获取当前步骤指令。"
                  f"用户问 mae-flow 用法/流程类问题时,先读 \"{readme}\" 再按其内容作答,禁止凭记忆即兴。")
    elif session_start and (os.path.isdir("openspec") or os.path.isdir(".comet")):
        # 交付项目 + 无在途单:给新用户一行发现入口(仅会话启动时,不打扰后续消息)
        print(f"[mae-flow] 本项目适用 mae-flow 交付流程:开新单直接说「交付 <单号> + SE 文档」"
              f"或敲 /mae-flow;新手指南敲 /mae-flow help。(流程脚本: python \"{me}\";"
              f"用户问用法/流程类问题时,先读 \"{readme}\" 再作答,禁止凭记忆即兴)")
    sys.exit(0)


AUTOPSY = os.path.join(tempfile.gettempdir(), "mae-flow-agent-autopsy.log")
ERR_PAT = re.compile(r"(command not found|is not recognized|No such file|not found|不可用|不存在|无法|失败|"
                     r"denied|Exception|Traceback|timeout|超时|error[: ])", re.I)


def _autopsy(tp, asst):
    """子 agent 非正常收尾的尸检:留档 + 提炼一行死因线索(嵌进打回消息喂给主 agent)。
    治"agent 奇奇怪怪自行退出没人知道为什么"——静默失效是最大的敌人。写档失败不影响主流程。"""
    turns = len(asst)
    tails = [a.strip().replace("\n", " ")[-160:] for a in asst[-2:] if a.strip()]
    errs = []
    try:
        full = "\n".join(asst[-8:])
        for m in ERR_PAT.finditer(full):
            s = full[max(0, m.start() - 40):m.end() + 60].replace("\n", " ")
            if s not in errs:
                errs.append(s)
            if len(errs) >= 3:
                break
    except Exception:
        pass
    clue = "约 %s 轮" % turns
    if errs:
        clue += ";检出报错特征: " + " | ".join(e[:90] for e in errs[:2])
    if tails:
        clue += ";临终输出: …" + tails[-1][:120]
    try:
        with open(AUTOPSY, "a", encoding="utf-8") as f:
            f.write("%s %s\n  turns=%s\n  tails=%s\n  errs=%s\n" % (
                time.strftime("%Y-%m-%d %H:%M:%S"), os.path.basename(tp) or "?", turns, tails, errs))
    except Exception:
        pass
    return clue


def ev_subagentstop(d):
    # retry=打回后的重答收尾:此路径禁止再次 exit 2(防死循环),但验证通过仍须发令牌
    # (历史 bug:曾在此处无条件放行,导致"打回→改正→再收尾"的自愈终点拿不到令牌)
    retry = bool(d.get("stop_hook_active"))
    # 定位 agent 自己的 transcript:payload 的 transcript_path 可能指向主会话文件
    # (历史 bug:一直解析主会话尾巴,agent 的合法标记永远"看不见")。
    # 优先用 payload 中带 agent 字样的路径字段;否则取 <主transcript同名目录>/subagents/ 下最新的 agent 文件。
    tp = ""
    for k, v in d.items():
        if isinstance(v, str) and "transcript" in k.lower() and "agent" in k.lower():
            tp = v
            break
    main_tp = d.get("transcript_path", "")
    if not tp:
        stem = os.path.splitext(main_tp)[0]
        cand = glob.glob(os.path.join(stem, "subagents", "agent-*.jsonl"))
        tp = max(cand, key=os.path.getmtime) if cand else main_tp
    _log("subagentstop transcript: " + (os.path.basename(tp) or "?"))
    try:
        lines = [json.loads(x) for x in open(tp, encoding="utf-8") if x.strip()]
    except Exception:
        sys.exit(0)

    def texts(role):
        out = []
        for e in lines:
            if e.get("type") == role or (e.get("message", {}) or {}).get("role") == role:
                c = (e.get("message", {}) or {}).get("content", e.get("content", ""))
                if isinstance(c, list):
                    out.append("".join(b.get("text", "") for b in c if isinstance(b, dict)))
                elif isinstance(c, str):
                    out.append(c)
        return out

    users, asst = texts("user"), texts("assistant")
    tool_calls, by_id = [], {}
    for e in lines:
        c = (e.get("message", {}) or {}).get("content", e.get("content", ""))
        if not isinstance(c, list):
            continue
        for b in c:
            if isinstance(b, dict) and b.get("type") in ("tool_use", "tool_call"):
                call = {"id": b.get("id", ""), "name": b.get("name", ""),
                        "input": b.get("input", {}), "result_seen": False,
                        "is_error": False, "result": ""}
                tool_calls.append(call)
                if call["id"]:
                    by_id[call["id"]] = call
            if isinstance(b, dict) and b.get("type") in ("tool_result", "tool_response"):
                call = by_id.get(b.get("tool_use_id") or b.get("tool_call_id") or b.get("id"))
                if call:
                    content = b.get("content", "")
                    if isinstance(content, list):
                        content = "\n".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in content)
                    call["result_seen"] = True
                    call["is_error"] = bool(b.get("is_error") or b.get("isError"))
                    call["result"] = str(content)
    prompt = users[0] if users else ""
    last = (asst[-1] if asst else "").strip()
    # 标记本身即身份证明。优先第一行；兼容模型在前面多写一句话/代码围栏的情况，
    # 只要最终回复中恰好有一个契约标记就继续验完整契约。格式小毛病不值得重跑重活。
    first_line = last.splitlines()[0] if last else ""
    matches = list(re.finditer(
        r"^\s*(ENV|UT|CODECHECK|STORY|GRILL|COMPILE)_RESULT:\s*(\S+)", last, re.M))
    m = re.match(r"^(ENV|UT|CODECHECK|STORY|GRILL|COMPILE)_RESULT:\s*(\S+)", first_line)
    if len(matches) > 1:
        kinds = {x.group(1) + "/" + x.group(2) for x in matches}
        _record_rejection("SUBAGENT", "最终回复包含多个结果标记，无法判断真实结果: " + "、".join(sorted(kinds)))
        m = None
    elif not m and len(matches) == 1:
        m = matches[0]
        _log("subagentstop: 契约标记不在第一行,兼容接受并继续验完整契约")
    # 凡以唯一合法契约标记收尾的 agent,直接验契约+发令牌,
    # 不依赖启动 prompt 的措辞(主模型派发时未必写 agent 文件名——已实际踩过)
    if m:
        if m.group(1) == "CODECHECK":
            _codecheck_contract(m.group(2), last, tool_calls, soft=retry)
        if m.group(1) == "UT":
            _ut_contract(m.group(2), last, tool_calls, soft=retry)
        if m.group(1) == "COMPILE":
            _compile_contract(m.group(2), last, tool_calls, soft=retry)
        _record_agent_token(m.group(1), m.group(2))
        sys.exit(0)
    if retry:
        _autopsy(tp, asst)   # 留档(不进 stderr:此路径 exit 0,别被 harness 当 hook error 展示)
        _record_rejection("SUBAGENT", "重答后仍未找到唯一的 XXX_RESULT 结果标记。")
        _log("subagentstop: 重答后仍无契约标记,放行防死循环(不发令牌,done 会拦;尸检已留档)")
        sys.exit(0)
    # 无标记:判定是否我方契约 agent——扫 transcript 头部(含 agent 系统提示,必带 agent 名/契约字样),
    # 不依赖任务 prompt 措辞(主模型派"定稿"类子任务时不会写 agent 名——已实际踩过)
    try:
        head = open(tp, encoding="utf-8", errors="replace").read(16000)
    except OSError:
        head = prompt
    if not re.search(r"_RESULT:|env-setup-agent|ut-generator-agent|codecheck-fix-agent|story-generator-agent|compile-agent", head):
        _log("subagentstop: 无契约标记且 transcript 头部未见契约 agent 特征,跳过")
        sys.exit(0)
    clue = _autopsy(tp, asst)
    print("[mae-flow] 子 agent 契约违规:最终回复必须以 XXX_RESULT: <状态> 开头(第一行)。"
          "请按你的定义文件顶部「最终回复格式」重新输出完整结果;不确定时用失败/待确认类状态,禁止省略标记。\n"
          "尸检线索(" + clue + ")——若死因是工具不可用/持续报错,按契约「带着情报死」条款以 FAIL/BLOCKED 收尾并写明详情;"
          "主 agent 重启新实例时必须把此线索转告它。",
          file=sys.stderr)
    sys.exit(2)


def _git_head():
    """当前 HEAD sha(令牌新鲜度绑定用)。拿不到返回空串=该令牌不做新鲜度校验(fail-open)。"""
    try:
        r = subprocess.run("git rev-parse --verify HEAD", shell=True, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _record_agent_token(kind, status=""):
    """子 agent 合法收尾的硬令牌:仅由本 hook(harness 调用)写入,是模型无法伪造的证据源——
    令牌文件在 gate 黑名单中(Edit/Bash 双拦),手动调 dispatch.py 也被 gate 拦截。
    mae-flow 的 agent_ran 证据据此判定"本步期间该 agent 真实跑过"。
    令牌同时绑定签发时 HEAD(新鲜度):签发后源码再变,证据即过期(mae-flow 侧校验)。"""
    try:
        p = ".mae-flow.json.tokens"
        d = {}
        if os.path.exists(p):
            d = json.loads(open(p, encoding="utf-8").read() or "{}")
        head = _git_head()
        step = ""
        try:
            step = json.load(open(STATE, encoding="utf-8")).get("current", "")
        except Exception:
            pass
        d[kind] = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "head": head,
                   "status": status, "step": step}
        tmp = p + ".tmp"
        open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False))
        os.replace(tmp, p)
        _clear_rejection(kind)
        _log("agent token: %s/%s @%s" % (kind, status or "-", head[:9] or "no-git"))
    except Exception as e:
        _log("token EXC: %s" % e)


def _text_of(v):
    """tool_response 可能是 str/dict/list,统一转文本(供 ack 验真存储)。"""
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v, ensure_ascii=False) if v else ""
    except Exception:
        return ""


def _capture_usermsg(text):
    """harness 捕获的用户真实输入(UserPromptSubmit 的 prompt / AskUserQuestion 的应答),
    供 done --ack 三级验真。仅在有在途流程时记录(不污染未用 mae-flow 的仓库);
    保留最近 10 条、单条截断 2000 字;写失败留日志不阻塞。
    存储文件在 gate 黑名单前缀内(.mae-flow.json.usermsg),模型不可改写。"""
    try:
        text = (text or "").strip()
        if not text or not os.path.exists(STATE):
            return
        p = STATE + ".usermsg"
        try:
            msgs = json.loads(open(p, encoding="utf-8").read() or "[]")
        except Exception:
            msgs = []
        step = ""
        try:
            step = json.load(open(STATE, encoding="utf-8")).get("current", "")
        except Exception:
            pass
        msgs.append({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "step": step, "text": text[:2000]})
        msgs = msgs[-10:]
        tmp = p + ".tmp"
        open(tmp, "w", encoding="utf-8").write(json.dumps(msgs, ensure_ascii=False))
        os.replace(tmp, p)
    except Exception as e:
        _log("usermsg EXC: %s" % e)


def _capture_direct_prompt(text):
    """直接模式也只为“用户明确重新启用”保留最近原话；不恢复任何旧流程令牌。"""
    try:
        text = (text or "").strip()
        if not text or not os.path.isfile(EXIT_STATE):
            return
        rec = json.load(open(EXIT_STATE, encoding="utf-8"))
        msgs = rec.get("direct_messages", []) or []
        msgs.append({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "text": text[:2000]})
        rec["direct_messages"] = msgs[-10:]
        tmp = EXIT_STATE + ".tmp"
        open(tmp, "w", encoding="utf-8").write(json.dumps(rec, ensure_ascii=False, indent=2))
        os.replace(tmp, EXIT_STATE)
    except Exception as e:
        _log("direct prompt EXC: %s" % e)


def _maybe_utrun(d):
    """UT 运行命令被真实调起 → UTRUN 事件令牌。当前仅观测(doctor 可见);
    升级为 verify_ut 硬证据前,须公司机确认子 agent 的 Bash 也触发 PostToolUse。"""
    try:
        cmd = re.sub(r"\s+", " ", ((d.get("tool_input") or {}).get("command", "") or ""))
        ut = ""
        if os.path.exists(STATE):
            ut = (json.load(open(STATE, encoding="utf-8")).get("config", {}) or {}).get("UT运行命令", "")
        ut = re.sub(r"\s+", " ", ut or "").strip()
        if ut and ut in cmd:
            _record_agent_token("UTRUN", "EXECUTED")
    except Exception as e:
        _log("utrun EXC: %s" % e)


def _atomic_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _record_rejection(label, msg):
    """把真实拒签原因留给 done/doctor；Hook stderr 被宿主吞掉时也不能让主模型猜。"""
    try:
        data = json.load(open(REJECTION_STATE, encoding="utf-8")) if os.path.exists(REJECTION_STATE) else {}
        try:
            st = json.load(open(STATE, encoding="utf-8"))
        except Exception:
            st = {}
        task = (st.get("agent_tasks", {}) or {}).get(label, {})
        data[label] = {
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "step": st.get("current", ""),
            "head": _git_head(),
            "task_sha256": task.get("sha256", ""),
            "reason": msg,
        }
        _atomic_json(REJECTION_STATE, data)
        _log(label + " 拒签: " + msg)
    except Exception as e:
        _log("rejection EXC: " + str(e))


def _clear_rejection(label):
    try:
        if not os.path.exists(REJECTION_STATE):
            return
        data = json.load(open(REJECTION_STATE, encoding="utf-8"))
        if label in data or "SUBAGENT" in data:
            data.pop(label, None)
            data.pop("SUBAGENT", None)
            _atomic_json(REJECTION_STATE, data)
    except Exception as e:
        _log("clear rejection EXC: " + str(e))


def _contract_bail(label, msg, soft):
    _record_rejection(label, msg)
    if soft:
        _log(label + " 重答仍违规: " + msg)
        sys.exit(0)
    print("[mae-flow] " + label + " 契约违规:" + msg
          + " 请按 agent 定义的 Return format 重新真实收尾。", file=sys.stderr)
    sys.exit(2)


def _task_card_contract(kind, report, soft=False):
    """报告必须回传 harness 任务卡指纹；缺配置时不再允许子 agent 边猜边做。"""
    try:
        st = json.load(open(STATE, encoding="utf-8"))
        task = (st.get("agent_tasks", {}) or {}).get(kind, {})
    except Exception:
        st, task = {}, {}
    if not task:
        _contract_bail(kind, "未生成 harness 任务卡。主 agent 必须先执行 mae-flow agent-task。", soft)
    if task.get("step") != st.get("current"):
        _contract_bail(kind, "任务卡属于旧步骤,禁止拿旧配置执行当前任务。", soft)
    m = re.search(r"^TASK_CARD_SHA256:\s*([0-9a-f]{64})\s*$", report, re.M | re.I)
    if not m or m.group(1).lower() != task.get("sha256", "").lower():
        _contract_bail(kind, "最终报告缺少当前任务卡的 TASK_CARD_SHA256,说明启动信息不完整。", soft)
    try:
        txt = open(task["path"], encoding="utf-8").read()
        body = txt.rsplit("TASK_CARD_SHA256:", 1)[0]
        actual = hashlib.sha256(body.encode("utf-8")).hexdigest()
    except Exception as e:
        _contract_bail(kind, "任务卡不可读:" + str(e), soft)
    if actual != task.get("sha256"):
        _contract_bail(kind, "任务卡内容被修改过,必须重新执行 agent-task 生成。", soft)
    head = task.get("head", "")
    if not re.fullmatch(r"[0-9a-f]{7,64}", head or ""):
        _contract_bail(kind, "任务卡缺少可验证的基点 HEAD。", soft)
    base = _git_out(f"git merge-base {head} HEAD").strip()
    if base != head and head != _git_head():
        _contract_bail(kind, "任务卡基点已不在当前提交历史中(amend/rebase/切分支)，请重新生成任务卡。", soft)
    return task


def _state_config():
    try:
        return (json.load(open(STATE, encoding="utf-8")).get("config", {}) or {})
    except Exception:
        return {}


def _field(report, name):
    m = re.search(r"^\s*" + re.escape(name) + r":\s*(.+?)\s*$", report, re.M)
    return m.group(1).strip() if m else ""


_REPORT_FIELDS = (
    "TASK_CARD_SHA256", "GENERATOR_USED", "EXECUTED_UT", "EXECUTED_BUILD", "EXECUTED_COMMAND",
    "TESTS_TOTAL", "TESTS_PASSED", "TESTS_FAILED", "AC_COVERAGE", "PENDING_QUESTIONS",
    "KNOWN_FAILURES", "SUSPECTED_BUGS", "FOUND", "FIXED", "REMAINING_COUNT",
)


def _flex_field(report, name):
    """弱模型常把机器字段挤在一行或加 Markdown bullet；按下一个已知字段切开而非卡排版。"""
    fields = "|".join(re.escape(x) for x in _REPORT_FIELDS)
    m = re.search(
        r"(?:^|(?<=[\s,;]))(?:[-*]\s*)?" + re.escape(name)
        + r"\s*:\s*(.*?)(?=(?:\s+|,\s*)(?:[-*]\s*)?(?:" + fields + r")\s*:|\Z)",
        report, re.I | re.S)
    return m.group(1).strip(" \t\r\n`") if m else None


def _number_field(report, name):
    value = _flex_field(report, name)
    m = re.match(r"(\d+)\b", value or "")
    return int(m.group(1)) if m else None


def _same_config(actual, expected):
    def n(s):
        return re.sub(r"\s+", "", (s or "")).lower()
    return bool(n(actual)) and bool(n(expected)) and n(expected) in n(actual)


def _required_skill(config_value):
    v = (config_value or "").lower()
    if "java-autout" in v:
        return "java-autout"
    if "autout" in v:
        return "autout"
    if "build-fix" in v:
        return "build-fix"
    return ""


def _codecheck_build_call(tool_calls, build_cfg):
    """返回当前 transcript 中与配置一致且未明确失败的编译调用。"""
    need = _required_skill(build_cfg)
    call = _skill_call(tool_calls, need) if need else _bash_call(tool_calls, build_cfg)
    return call if call and not _call_failed(call) else None


def _record_codecheck_build_receipt(task, tool_calls):
    """报告格式即使被打回，也保留已经真实发生的编译证据，供同一 HEAD 的重答复用。"""
    build_cfg = _state_config().get("编译方式", "")
    if not build_cfg or not _codecheck_build_call(tool_calls, build_cfg):
        return None
    rec = {
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "step": task.get("step", ""),
        "task_sha256": task.get("sha256", ""),
        "head": _git_head(),
        "build": build_cfg,
    }
    try:
        data = json.load(open(EVIDENCE_STATE, encoding="utf-8")) if os.path.exists(EVIDENCE_STATE) else {}
        data["CODECHECK_BUILD"] = rec
        _atomic_json(EVIDENCE_STATE, data)
        _log("CODECHECK 编译凭证: @%s" % (rec["head"][:9] or "no-git"))
    except Exception as e:
        _log("codecheck receipt EXC: " + str(e))
    return rec


_UT_RISK_PAT = re.compile(
    r"\b(?:disabled|excluded|skipped|pre-existing\s+(?:failure|segfault)|segmentation\s+fault|segfault)\b|"
    r"禁用|排除|跳过|段错误|绕过失败|屏蔽失败", re.I)
_UT_FILTER_PAT = re.compile(r"gtest_filter|--?exclude|--?skip|--?disable|--filter|-E(?:\s|=)", re.I)


def _bash_segment(call, expected):
    def n(s):
        return re.sub(r"\s+", " ", (s or "")).strip()
    want = n(expected).lower()
    if not call or not want:
        return ""
    inp = call.get("input", {}) or {}
    cmd = inp.get("command", "") if isinstance(inp, dict) else str(inp)
    for seg in re.split(r"&&|\|\||[;\n]", n(cmd)):
        if seg.strip().lower().startswith(want):
            return seg.strip()
    return ""


def _ut_execution_risk(report, run_call, expected):
    """PASS 不得靠临时禁用/过滤失败测试取得；配置本身带过滤时视为用户已明确授权。"""
    configured = re.sub(r"\s+", " ", expected or "").strip()
    segment = _bash_segment(run_call, configured)
    extra = segment[len(configured):].strip() if segment.lower().startswith(configured.lower()) else segment
    summary = _flex_field(report, "EXECUTED_UT") or ""
    result = (run_call or {}).get("result", "") or ""
    risk_text = summary + "\n" + result
    # 常见测试框架会正常打印“0 skipped/0 disabled”，这是全绿统计，不得误伤。
    risk_text = re.sub(r"\b(?:0|no)\s+(?:tests?\s+)?(?:disabled|excluded|skipped)\b", "",
                       risk_text, flags=re.I)
    risk_text = re.sub(r"\b(?:tests?\s+)?(?:disabled|excluded|skipped)\s*[:=]\s*0\b", "",
                       risk_text, flags=re.I)
    risk_text = re.sub(r"\bno\s+tests?\s+(?:were\s+)?(?:disabled|excluded|skipped)\b", "",
                       risk_text, flags=re.I)
    risk_text = re.sub(r"(?:跳过|禁用|排除)\s*[:：]?\s*0\s*(?:个|项|条|例)?", "", risk_text)
    text_risk = _UT_RISK_PAT.search(risk_text)
    filter_risk = _UT_FILTER_PAT.search(extra) and not _UT_FILTER_PAT.search(configured)
    if text_risk:
        return "测试报告或执行输出显示存在禁用、跳过或段错误；必须进入 KNOWN_FAILURES/SUSPECTED_BUGS 并用 NEEDS_INPUT，不能 PASS。"
    if filter_risk:
        return "实际 UT 命令在任务卡配置之外追加了过滤/排除参数；未经用户确认不能缩小测试范围后报告 PASS。"
    return ""


def _record_ut_receipts(task, report, tool_calls):
    """保存真实 AutoUT 与 UT 执行事实；后续仅修报告且代码未变时无需重做重活。"""
    cfg = _state_config()
    need = _required_skill(cfg.get("UT生成方式", ""))
    generator = _skill_call(tool_calls, need) if need else None
    run = _bash_call(tool_calls, cfg.get("UT运行命令", ""))
    records = {}
    common = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "step": task.get("step", ""),
              "task_sha256": task.get("sha256", ""), "head": _git_head()}
    if generator and not _call_failed(generator):
        records["UT_GENERATOR"] = dict(common, value=cfg.get("UT生成方式", ""))
    if run and not _call_failed(run) and not _ut_execution_risk(report, run, cfg.get("UT运行命令", "")):
        records["UT_RUN"] = dict(common, value=cfg.get("UT运行命令", ""))
    if not records:
        return
    try:
        data = json.load(open(EVIDENCE_STATE, encoding="utf-8")) if os.path.exists(EVIDENCE_STATE) else {}
        data.update(records)
        _atomic_json(EVIDENCE_STATE, data)
        _log("UT 执行凭证: " + "/".join(sorted(records)) + " @" + common["head"][:9])
    except Exception as e:
        _log("ut receipt EXC: " + str(e))


def _reusable_ut_receipt(key, task, expected):
    try:
        rec = json.load(open(EVIDENCE_STATE, encoding="utf-8")).get(key, {})
    except Exception:
        return None
    if not rec or rec.get("step") != task.get("step") \
            or rec.get("task_sha256") != task.get("sha256") \
            or not _same_config(rec.get("value", ""), expected):
        return None
    changed, err = _source_changed_since_receipt(rec.get("head", ""), {})
    return rec if not err and not changed else None


def _reusable_codecheck_build_receipt(task):
    """仅同任务卡、同步骤且源码未变化时复用；代码一变就必须重新编译。"""
    try:
        rec = json.load(open(EVIDENCE_STATE, encoding="utf-8")).get("CODECHECK_BUILD", {})
    except Exception:
        return None
    if not rec or rec.get("step") != task.get("step") \
            or rec.get("task_sha256") != task.get("sha256") \
            or not _same_config(rec.get("build", ""), _state_config().get("编译方式", "")):
        return None
    head = rec.get("head", "")
    if not head:
        return None
    try:
        st = json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return None
    changed, err = _source_changed_since_receipt(head, st)
    return rec if not err and not changed else None


def _source_changed_since_receipt(head, st):
    """dispatch 侧的轻量源码新鲜度检查，语义与 mae-flow 令牌检查一致。"""
    current = _git_head()
    if not current:
        return [], "当前 HEAD 不可读"
    if _git_out(f"git cat-file -t {head}").strip() != "commit":
        return [], "编译凭证 HEAD 不可解析"
    paths = [] if current == head else [p for p in _git_out(
        f"git -c core.quotepath=false diff --name-only {head} {current}").splitlines() if p.strip()]
    paths += [p for p in _changed_paths_since(current) if p]
    return [p for p in dict.fromkeys(paths) if _SOURCE_PAT.search(p)], ""


def _call_failed(call):
    if not call or not call.get("result_seen"):
        return False   # 老版本 transcript 没带 tool_result 时兼容放行；done/现场复核仍会兜底
    if call.get("is_error"):
        return True
    text = call.get("result", "") or ""
    return bool(re.search(r"(?:exit(?:ed)?\s*(?:code|status)?|return\s*code)\s*[:= ]\s*[1-9]\d*|"
                          r"command failed|tool[_ ]?error", text, re.I))


def _skill_call(tool_calls, wanted):
    if not wanted:
        return None
    for x in tool_calls or []:
        if str(x.get("name", "")).lower() != "skill":
            continue
        try:
            raw = json.dumps(x.get("input", {}), ensure_ascii=False).lower()
        except Exception:
            raw = str(x.get("input", "")).lower()
        if wanted in raw:
            return x
    return None


def _skill_called(tool_calls, wanted):
    return bool(_skill_call(tool_calls, wanted)) if wanted else True


def _bash_call(tool_calls, expected):
    def n(s):
        return re.sub(r"\s+", " ", (s or "")).strip().lower()
    want = n(expected)
    if not want:
        return None
    for x in reversed(tool_calls or []):
        if str(x.get("name", "")).lower() != "bash":
            continue
        inp = x.get("input", {}) or {}
        cmd = inp.get("command", "") if isinstance(inp, dict) else str(inp)
        # 只接受某个真实命令段以目标命令开头；echo/printf "目标命令" 不算执行。
        segs = re.split(r"&&|\|\||[;\n]", n(cmd))
        if any(seg.strip().startswith(want) for seg in segs):
            return x
    return None


def _bash_called(tool_calls, expected):
    return bool(_bash_call(tool_calls, expected))


def _require_bash_success(tool_calls, expected, bail, label):
    call = _bash_call(tool_calls, expected)
    if not call:
        bail(f"transcript 中没有真实执行配置的{label}命令；echo/文字提及不算执行。")
    if _call_failed(call):
        bail(f"最后一次{label}命令的工具结果明确失败，不能报告成功。")
    return call


def _section(report, name):
    m = re.search(r"^\s*" + re.escape(name) + r":\s*(.*?)(?=^\s*[A-Z][A-Z0-9_]+:\s*|\Z)",
                  report, re.M | re.S)
    return m.group(1).strip() if m else None


def _empty_section(value):
    return value is not None and re.sub(r"[\s`*_-]+", "", value).lower() in ("无", "none", "0", "暂无")


def _changed_paths_since(head):
    out = _git_out(f"git -c core.quotepath=false diff --name-only {head}..HEAD")
    paths = [x.strip() for x in out.splitlines() if x.strip()]
    for line in _git_out("git -c core.quotepath=false status --porcelain").splitlines():
        p = line.split(None, 1)
        if len(p) == 2:
            paths.append(p[1].split(" -> ")[-1].strip().strip('"'))
    return list(dict.fromkeys(x.replace("\\", "/") for x in paths))


_TEST_PAT = re.compile(r"(^|/)(tests?|__tests__|spec|[^/]+[_-]tests?)/|(^|/)src/test/|(^|/)test_[^/]+\.py$|"
                       r"(_test|\.test|\.spec)\.(c|cc|cpp|cxx|h|hh|hpp|hxx|py|go|rs|js|jsx|ts|tsx)$|"
                       r"Tests?\.(c|cc|cpp|cxx|h|hh|hpp|hxx|java|kt|cs)$", re.I)
_SOURCE_PAT = re.compile(r"\.(c|cc|cpp|cxx|h|hh|hpp|hxx|inl|ipp|tpp|java|kt|kts|groovy|scala|py|pyi|go|rs|cs|"
                         r"js|jsx|ts|tsx|vue|swift|m|mm|proto|sql|s|asm|cmake|gradle|sln|vcxproj|props|targets)$|"
                         r"(^|/)(CMakeLists\.txt|Makefile|pom\.xml|build\.gradle|settings\.gradle|package\.json|"
                         r"Cargo\.toml|go\.mod|meson\.build)$|(^|/)(service|src|include|lib|app|modules?)/", re.I)


def _test_like(path):
    if _TEST_PAT.search(path):
        return True
    pats = []
    try:
        v = (json.load(open(STATE, encoding="utf-8")).get("config", {}) or {}).get("测试路径", [])
        pats += [x.strip() for x in v.split(",") if x.strip()] if isinstance(v, str) else list(v or [])
    except Exception:
        pass
    try:
        v = json.load(open(".mae-flow-defaults.json", encoding="utf-8")).get("测试路径", [])
        pats += [x.strip() for x in v.split(",") if x.strip()] if isinstance(v, str) else list(v or [])
    except Exception:
        pass
    for pat in pats:
        try:
            if re.search(pat, path, re.I):
                return True
        except re.error:
            continue
    return False


def _enforce_agent_scope(kind, task, bail):
    changed = [p for p in _changed_paths_since(task.get("head", "")) if _SOURCE_PAT.search(p)]
    if kind == "COMPILE":
        bad = [p for p in changed if _test_like(p)]
        if bad:
            bail("compile-agent 越权修改了测试文件: " + "、".join(bad[:5]))
    elif kind == "CODECHECK":
        allowed = {str(x).replace("\\", "/").lower() for x in task.get("allowed_files", [])}
        bad = [p for p in changed if p.lower() not in allowed]
        if bad:
            bail("codecheck-fix-agent 修改了首检范围外文件: " + "、".join(bad[:5]))
    elif kind == "UT":
        bad = [p for p in changed if not _test_like(p)]
        if bad:
            bail("ut-generator-agent 修改了非测试源码: " + "、".join(bad[:5])
                 + "；源码缺陷必须先交用户裁决。")
    return changed


def _codecheck_contract(status, report, tool_calls=None, soft=False):
    """codecheck 报告的硬校验:fullcheck 实际执行 + 三数对账(FOUND=FIXED+REMAINING_COUNT)。
    遗漏告警最常见的形态是马虎吞掉,算术对不上当场打回;CLEAN 必须遗留为 0。
    soft=重答路径:违规不再 exit 2(防死循环),但直接 exit 0 不发令牌,由 done 的 agent_ran 拦截。"""
    def bail(msg):
        _contract_bail("CODECHECK", msg, soft)

    task = _task_card_contract("CODECHECK", report, soft)
    _enforce_agent_scope("CODECHECK", task, bail)
    # 先记真实编译调用：后续哪怕只因报告字段写法被打回，也无需把十几分钟编译重跑一遍。
    _record_codecheck_build_receipt(task, tool_calls)
    if not re.search(r"EXECUTED_COMMAND.*fullcheck", report, re.I):
        bail("必须包含 EXECUTED_COMMAND 字段且实际执行的是 fullcheck(用 increcheck 或未执行 = FAIL)。")
    if status == "FAIL":
        return   # FAIL 是诚实上报,不再苛求对账字段
    _require_bash_success(tool_calls, "codecheck fullcheck", bail, "CodeCheck")
    nums = {}
    for k in ("FOUND", "FIXED", "REMAINING_COUNT"):
        mm = re.search(r"^\s*" + k + r":\s*(\d+)\s*$", report, re.M)
        if not mm:
            bail(f"缺少机器对账字段 {k}: <数字>。")
        nums[k] = int(mm.group(1))
    try:
        st = json.load(open(STATE, encoding="utf-8"))
        scan = (st.get("quality", {}) or {}).get("codecheck_scan", {})
    except Exception:
        st, scan = {}, {}
    if st.get("current") in ("rf_codecheck", "tw_codecheck", "verify_codecheck") \
            and scan.get("step") == st.get("current"):
        if nums["FOUND"] != scan.get("count"):
            bail(f"FOUND({nums['FOUND']})与 harness 首检({scan.get('count')})不一致。"
                 "禁止主会话先修后让 agent 补手续；回到首检状态并由 agent 处理原告警。")
    if nums["FOUND"] != nums["FIXED"] + nums["REMAINING_COUNT"]:
        bail(f"对账不平:FOUND({nums['FOUND']}) != FIXED({nums['FIXED']}) + REMAINING_COUNT({nums['REMAINING_COUNT']})"
             ",有告警被吞掉或数字失实。")
    if status == "CLEAN" and nums["REMAINING_COUNT"] != 0:
        bail(f"标记 CLEAN 但 REMAINING_COUNT={nums['REMAINING_COUNT']},自相矛盾。")
    if status == "REMAINING" and nums["REMAINING_COUNT"] == 0:
        bail("标记 REMAINING 但 REMAINING_COUNT=0,自相矛盾。")
    if nums["FIXED"] > 0:
        build = _field(report, "EXECUTED_BUILD")
        build_cfg = _state_config().get("编译方式", "")
        current_call = _codecheck_build_call(tool_calls, build_cfg)
        reused = _reusable_codecheck_build_receipt(task) if soft and not current_call else None
        if current_call:
            # 工具调用是事实，字段只是摘要；不因摘要写成“无需”等小格式问题重跑长编译。
            if not _same_config(build, build_cfg):
                _log("CODECHECK EXECUTED_BUILD 摘要不准确,以 transcript 的真实编译调用为准")
        elif reused:
            _log("CODECHECK 重答复用编译凭证 @" + reused.get("head", "")[:9])
        else:
            need = _required_skill(build_cfg)
            if need:
                call = _skill_call(tool_calls, need)
                if call and _call_failed(call):
                    bail(f"{need} Skill 的工具结果明确失败，不能把本轮修复计为已编译。")
                bail(f"编译配置要求 {need} Skill，但本轮 transcript 中没有成功调用，"
                     "也没有同任务卡、同源码版本的可复用编译凭证。")
            else:
                call = _bash_call(tool_calls, build_cfg)
                if call and _call_failed(call):
                    bail("配置的编译命令明确失败，不能把本轮修复计为已编译。")
                bail("本轮 transcript 中没有成功执行配置的编译命令，"
                     "也没有同任务卡、同源码版本的可复用编译凭证。")
    # 与复验摘录对账:契约要求附「共有 N 条告警」原文,取最后一处(复验)与 REMAINING_COUNT 比对
    ex = re.findall(r"共有\s*(\d+)\s*条告警", report)
    if ex and int(ex[-1]) != nums["REMAINING_COUNT"]:
        bail(f"REMAINING_COUNT({nums['REMAINING_COUNT']})与复验摘录『共有 {ex[-1]} 条告警』矛盾——遗留数必须原样取自复验输出。")


def _ut_contract(status, report, tool_calls=None, soft=False):
    def bail(msg):
        _contract_bail("UT", msg, soft)

    task = _task_card_contract("UT", report, soft)
    _enforce_agent_scope("UT", task, bail)
    if status not in ("PASS", "NEEDS_INPUT", "FAIL"):
        bail("未知结果状态 " + status)
    if status != "PASS":
        return
    cfg = _state_config()
    need = _required_skill(cfg.get("UT生成方式", ""))
    _record_ut_receipts(task, report, tool_calls)
    if need:
        call = _skill_call(tool_calls, need)
        reused = _reusable_ut_receipt("UT_GENERATOR", task, cfg.get("UT生成方式", "")) \
            if soft and not call else None
        if call and _call_failed(call):
            bail(f"{need} Skill 的工具结果明确失败，不能报告 PASS。")
        if not call and not reused:
            bail(f"UT 配置要求 {need} Skill，但 transcript 中没有成功调用，"
                 "也没有同任务卡、同源码版本的可复用生成凭证；不能用手写测试冒充 Skill 产出。")
        label = _flex_field(report, "GENERATOR_USED") or ""
        if call and not _same_config(label, cfg.get("UT生成方式", "")):
            _log("UT GENERATOR_USED 摘要不准确,以 transcript 的真实 Skill 调用为准")
    elif not _same_config(_flex_field(report, "GENERATOR_USED") or "", cfg.get("UT生成方式", "")):
        bail("GENERATOR_USED 与任务卡的 UT生成方式不一致。")

    expected_ut = cfg.get("UT运行命令", "")
    run = _bash_call(tool_calls, expected_ut)
    risk = _ut_execution_risk(report, run, expected_ut)
    if risk:
        bail(risk)
    reused_run = _reusable_ut_receipt("UT_RUN", task, expected_ut) if soft and not run else None
    if run and _call_failed(run):
        bail("UT运行命令的工具结果明确失败，不能报告 PASS。")
    if not run and not reused_run:
        bail("transcript 中没有成功执行任务卡配置的 UT 命令，也没有同任务卡、同源码版本的可复用测试凭证。")
    if run and not _same_config(_flex_field(report, "EXECUTED_UT") or "", expected_ut):
        _log("UT EXECUTED_UT 摘要不准确,以 transcript 的真实 Bash 调用为准")

    for name in ("PENDING_QUESTIONS", "KNOWN_FAILURES", "SUSPECTED_BUGS"):
        value = _flex_field(report, name)
        if value is None:
            continue   # 真正全绿时省略空字段不值得打回；上面的风险扫描负责防隐藏失败
        if not _empty_section(value):
            bail(f"标记 PASS 但 {name} 非空；必须先交主会话和用户处理，不能带问题过关。")
    coverage = _flex_field(report, "AC_COVERAGE")
    if coverage is None or not coverage.strip() or _empty_section(coverage):
        bail("PASS 报告缺少有效的 AC_COVERAGE 验收场景对照。")
    if re.search(r"缺口|未覆盖|无对应", coverage):
        bail("AC_COVERAGE 仍有验收缺口，不能报告 PASS。")
    nums = {}
    for name in ("TESTS_TOTAL", "TESTS_PASSED", "TESTS_FAILED"):
        value = _number_field(report, name)
        if value is None:
            bail(f"PASS 报告缺少 {name}: <数字>。")
        nums[name] = value
    if nums["TESTS_FAILED"] != 0 or nums["TESTS_TOTAL"] != nums["TESTS_PASSED"]:
        bail("UT 数字对账不通过：PASS 必须 TESTS_FAILED=0 且 TOTAL=PASSED。")


def _git_out(cmd):
    """dispatch 内轻量 git 调用(编码/超时按军规)。失败返回空串,调用方按'不可算'处理。"""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=8)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def _compile_net_lines(head):
    """编译修复的净行数,git 亲算(agent 报数不作数):
    未提交改动 + 自 HEAD 回溯的连续「修复编译」commit,只统计代码文件。
    这是防掏空的机器不变量:删代码换编译通过,在这里得不了分。"""
    def net_of(out):
        n = 0
        for line in out.splitlines():
            p = line.split("\t")
            if len(p) == 3 and p[0].isdigit() and p[1].isdigit() and _SOURCE_PAT.search(p[2].replace("\\", "/")):
                n += int(p[0]) - int(p[1])
        return n

    return (net_of(_git_out(f"git -c core.quotepath=false diff --numstat {head}..HEAD"))
            + net_of(_git_out("git -c core.quotepath=false diff --numstat HEAD")))


def _compile_contract(status, report, tool_calls=None, soft=False):
    """编译 agent 收尾硬校验:格式对账(OK⇔零error)+ 净产出不变量(numstat 亲算防掏空)。
    优雅三件套之硬层:作弊(删代码换通过)从'被禁止'变'得不了分'。"""
    def bail(msg):
        _contract_bail("COMPILE", msg, soft)

    task = _task_card_contract("COMPILE", report, soft)
    _enforce_agent_scope("COMPILE", task, bail)
    if status == "FAIL":
        return   # 诚实上报工具/配置问题,不苛求对账
    if not re.search(r"EXECUTED_BUILD", report):
        bail("必须包含 EXECUTED_BUILD(实际执行的编译方式与输出摘录)。")
    build_cfg = _state_config().get("编译方式", "")
    if not _same_config(_field(report, "EXECUTED_BUILD"), build_cfg):
        bail("EXECUTED_BUILD 与配置确认的编译方式不一致,禁止自行猜测或替换编译命令。")
    need = _required_skill(build_cfg)
    if need:
        call = _skill_call(tool_calls, need)
        if not call:
            bail(f"编译配置要求 {need} Skill,但 transcript 中没有对应 Skill 工具调用。")
        if _call_failed(call):
            bail(f"{need} Skill 的工具结果明确失败，不能报告编译成功。")
    else:
        _require_bash_success(tool_calls, build_cfg, bail, "编译")
    m = re.search(r"^\s*BUILD_ERRORS:\s*(\d+)", report, re.M)
    if not m:
        bail("缺少 BUILD_ERRORS: <数字>(最终一次编译的 error 数)。")
    n = int(m.group(1))
    if status == "OK" and n != 0:
        bail(f"标记 OK 但 BUILD_ERRORS={n},自相矛盾。")
    if status == "BLOCKED" and n == 0:
        bail("标记 BLOCKED 但 BUILD_ERRORS=0,自相矛盾(编译已过应报 OK)。")
    net = _compile_net_lines(task.get("head", ""))
    shrink = _section(report, "SHRINK_EXEMPT")
    if net < 0 and (shrink is None or _empty_section(shrink)):
        bail(f"代码净删 {-net} 行(git 亲算:未提交+修复编译 commit)且无 SHRINK_EXEMPT 声明——"
             "禁止删代码/注释代码换编译通过;确属合理精简须逐项声明并接受下游评审复核。")


def ev_posttooluse(d):
    # 真实用户问答的事件令牌:AskUserQuestion 工具真被调用过才有——
    # "确认发生过"从此是 harness 签发的事实,不是模型可书写的文本
    if d.get("tool_name") == "AskUserQuestion":
        _capture_usermsg(_text_of(d.get("tool_response")))   # 应答原文进 ack 验真存储
        _record_agent_token("ASKUSER", "CONFIRMED")
        sys.exit(0)
    if d.get("tool_name") == "Bash":
        _maybe_utrun(d)
        sys.exit(0)
    p = ((d.get("tool_input") or {}).get("file_path", "") or "").replace("\\", "/")
    hit = None
    for pat, tf, label in ((r"docs/story/STORY-.*\.md$", "STORY-TEMPLATE.md", "STORY"),
                           (r"docs/chain/CHAIN-.*\.md$", "CHAIN-TEMPLATE.md", "CHAIN"),
                           (r"(^|/)\.mae-flow-work/grill-prep-.*\.md$", "GRILL-PREP-TEMPLATE.md", "GRILL-PREP"),
                           (r"docs/review/REVIEW-.*\.md$", "REVIEW-TEMPLATE.md", "REVIEW")):
        if re.search(pat, p, re.I):
            hit = (tf, label)
            break
    if not hit:
        sys.exit(0)
    tpl = os.path.join(HERE, "..", "skills", "mae-flow", "assets", hit[0])
    if not os.path.exists(tpl):
        _log(hit[1] + " 模板缺失: " + tpl)
        sys.exit(0)

    def heads(f):
        return [re.sub(r"\s+", " ", h.strip()) for h in
                re.findall(r"^#{1,3}\s+(.+)$", open(f, encoding="utf-8").read(), re.M)]

    def matched(t, got):
        # 模板章节含 {占位符}(如 STORY-{单号})时按通配匹配——实例化后的标题不该被判缺失
        if "{" in t:
            pat = "^" + re.sub(r"\\\{[^}]*\\\}", ".+", re.escape(t)) + "$"
            return any(re.match(pat, g) for g in got)
        return t in got

    try:
        got = heads(p)
        missing = [h for h in heads(tpl) if not matched(h, got)]
    except Exception:
        sys.exit(0)
    if missing:
        print(f"[mae-flow] {hit[1]} 结构与模板不符,缺少章节: " + " | ".join(missing)
              + "。请补齐缺失章节(无内容的章节按约定标注,不可省略标题)。", file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


def main():
    ev = sys.argv[1] if len(sys.argv) > 1 else ""
    _arm_watchdog()
    _log("start " + ev)
    rc = 0
    try:
        d = read_input()
        _chdir_root(d)
        if os.path.exists(EXIT_STATE):
            # 用户已明确退出：MAE-FLOW 完整让出控制权。不能只跳过源码 gate 而继续发令牌/注入步骤，
            # 否则会形成“表面直接开发，后台仍在推进旧流程”的半退出状态。
            if ev in ("userprompt", "sessionstart"):
                if ev == "userprompt":
                    _capture_direct_prompt(d.get("prompt") or "")
                print("[mae-flow] 本项目已退出交付流程，按用户的普通开发请求执行；"
                      "不要运行 current/done，也不要自行重新进入。只有用户明确要求重新接回原流程时才 init。")
            _log("direct mode: bypass " + ev)
            rc = 0
        elif ev == "pretooluse":
            ev_pretooluse(d)
        elif ev == "userprompt":
            ev_inject(d)
        elif ev == "sessionstart":
            ev_inject(d, session_start=True)
        elif ev == "subagentstop":
            ev_subagentstop(d)
        elif ev == "posttooluse":
            ev_posttooluse(d)
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 0
    except Exception as e:
        _log("EXC %s: %s" % (type(e).__name__, e))
        rc = 0   # fail-open:hook 自身异常不阻塞正常工作
    _log("end %s rc=%s %dms" % (ev, rc, int((time.time() - _T0) * 1000)))
    sys.exit(rc)


if __name__ == "__main__":
    main()
