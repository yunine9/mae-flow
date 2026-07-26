#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dispatch.py — 跨平台 hook 分发器(Windows 优先,零 POSIX 依赖)。

用法(hooks.json 中,shell form——公司 codeagent 实测**不支持** exec form 的 args 数组:
只执行 command 本体,payload 落进 python 的 stdin 被当脚本解析,JSON 的 false 炸 NameError,2026-07-20 实战):
  python "${CODEAGENT3_PLUGIN_ROOT}/hooks/dispatch.py" <事件>
事件:pretooluse | userprompt | sessionstart | subagentstop | posttooluse | stop
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
import glob, hashlib, json, locale, os, re, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.abspath(os.path.join(HERE, "..", "scripts"))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from mae_flow_core import (
    ACTION_FILE,
    EXIT_FILE,
    FLOW_FILE,
    RuntimeMode,
    atomic_write_json,
    atomic_write_text,
    find_project_root,
    load_action as core_load_action,
    normalize_document,
    resolve_runtime,
    safe_read_json,
    update_json,
    update_versioned_json,
)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

MAEFLOW = os.path.join(HERE, "..", "scripts", "mae-flow.py")
STATE = FLOW_FILE
EXIT_STATE = EXIT_FILE
MOONLIGHT_INTENT = STATE + ".moonlight-intent"
EXIT_INTENT = STATE + ".exit-intent"
REJECTION_STATE = STATE + ".agent-rejections"
EVIDENCE_STATE = STATE + ".agent-evidence"
AGENT_WRITES_STATE = STATE + ".agent-writes"
ACTION_STATE = ACTION_FILE
LOG = os.path.join(tempfile.gettempdir(), "mae-flow-hook.log")
WATCHDOG_SECS = 12
STDIN_SECS = 3
SUBPROC_SECS = 8
_T0 = time.time()
_INPUT_ENCODING = ""
_STDIN_THREAD = None   # stdin 读线程句柄:超时未归还时,收尾必须绕过解释器 finalization


def _log(msg):
    try:
        try:
            # 无上限追加会按月涨到几十 MB;超 5MB 滚动一份 .old(单份保留,足够取证)。
            if os.path.getsize(LOG) > 5 * 1024 * 1024:
                os.replace(LOG, LOG + ".old")
        except OSError:
            pass
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
    """以当前解释器调 mae-flow,stderr 透传,返回退出码。超时视为放行。

    退出码白名单:只有 0(放行)/2(门禁拦截)是 gate 协议语义。脚本缺失(升级半途/
    杀软隔离,python 打不开文件恰好也退 2)或自身崩溃(rc=1 traceback)属于插件故障,
    必须 fail-open——否则在途流程里每次 Edit/Bash 都被拦,用户连自救编辑都做不了。"""
    if not os.path.isfile(MAEFLOW):
        _log("maeflow missing at %s — fail-open" % MAEFLOW)
        return 0
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
    if r.returncode not in (0, 2):
        _log("maeflow %s rc=%s — 非门禁语义退出码,按 fail-open 放行" % (args[:2], r.returncode))
        return 0
    return r.returncode


def _decode_hook_json(raw):
    """Hook 协议是 JSON 字节流，不能让 Windows 控制台代码页先替我们解码。

    公司环境的 harness 正常发送 UTF-8；同时保留 GB18030/系统代码页兼容旧宿主。
    每种编码都必须 strict 解码且成功解析 JSON，绝不用 errors=replace 把乱码写进确认账本。
    """
    global _INPUT_ENCODING
    if isinstance(raw, str):
        _INPUT_ENCODING = getattr(sys.stdin, "encoding", "") or "text"
        return json.loads(raw or "{}")
    encodings = ["utf-8-sig"]
    preferred = locale.getpreferredencoding(False)
    for enc in (preferred, "gb18030"):
        if enc and enc.lower().replace("-", "") not in {
                x.lower().replace("-", "") for x in encodings}:
            encodings.append(enc)
    last = None
    for enc in encodings:
        try:
            text = raw.decode(enc, errors="strict")
            value = json.loads(text or "{}")
            _INPUT_ENCODING = enc
            if enc != "utf-8-sig":
                _log("stdin decoded with fallback encoding=" + enc)
            return value
        except (UnicodeDecodeError, LookupError, json.JSONDecodeError) as exc:
            last = exc
    raise ValueError("hook JSON 无法按 UTF-8/系统代码页解析: %s" % last)


def read_input():
    """守护线程读 stdin。payload 惯例是单行 JSON,用 readline(见换行即返回)而非 read()(等 EOF):
    公司 harness 写完 payload 后关闭管道晚/不关,read() 等 EOF 会在 3s 兜底处误判超时、把已到的数据丢掉
    (2026-07-20 实战定位:exec form 时代 python 把 stdin 当脚本能读到完整 JSON,证明数据在管道里,只是 EOF 迟)。
    readline 解析失败(罕见多行 payload)再补读到 EOF;3s 仍拿不到按空输入,只兜底不阻塞。"""
    box = {}

    def _r():
        try:
            stream = getattr(sys.stdin, "buffer", sys.stdin)
            buf = stream.readline()
            try:
                box["d"] = _decode_hook_json(buf)
                box["n"] = len(buf)
                return
            except Exception:
                pass
            buf += stream.read()
            box["d"] = _decode_hook_json(buf)
            box["n"] = len(buf)
        except Exception as exc:
            box["d"] = {}
            box["n"] = -1
            box["error"] = str(exc)

    global _STDIN_THREAD
    th = threading.Thread(target=_r, daemon=True)
    th.start()
    th.join(STDIN_SECS)
    _STDIN_THREAD = th
    if "d" not in box:
        _log("stdin read timeout(%ss) — 按空输入处理" % STDIN_SECS)
        return {}
    if not box["d"]:
        _log("stdin empty/unparsed(n=%s,error=%s) — 按空输入处理"
             % (box.get("n"), box.get("error", "-")))
    return box["d"]


def _session_notice_due(tag, d, ev):
    """DIRECT/CORRUPT 提示每会话注入一次即可:逐条消息重复注入只膨胀上下文、烧 token。
    sessionstart 恒提示并盖标记;拿不到会话标识时退回旧行为(每条提示,宁噪勿哑)。"""
    sid = str(d.get("session_id") or d.get("sessionId") or "")
    if not sid:
        return True
    digest = hashlib.sha256(sid.encode("utf-8", errors="replace")).hexdigest()[:16]
    marker = os.path.join(tempfile.gettempdir(), "mae-flow-note-%s-%s" % (tag, digest))
    if ev != "sessionstart" and os.path.exists(marker):
        return False
    try:
        open(marker, "w").close()
    except OSError:
        pass
    return True


def _chdir_root(d):
    """hook 进程的 cwd 是 codeagent 启动目录,未必是项目根。
    以 hook JSON 的 cwd 为基准向上定位；最近仓库边界会阻断更高层的陈旧状态，
    避免一个父目录流程误接管从未启用 mae-flow 的独立子仓。"""
    base = d.get("cwd") or os.getcwd()
    root = find_project_root(base)
    try:
        if root != os.getcwd():
            _log("chdir 项目根: " + root)
        os.chdir(root)
    except Exception:
        pass


def _gate_agent_dispatch(ti):
    """质量 agent 派发前验任务卡——拦截时机 = 错误发生时机。

    卡缺失/过期若留到 SubagentStop/done 才发现,代价是整只 agent 上百轮白跑;
    在派发这一刻拦下,损失只有一次工具调用。完整流程与独立任务统一从
    _contract_state 取任务卡；识别不到或状态读不了一律放行(fail-open)。"""
    try:
        blob = " ".join(str(ti.get(k, "") or "") for k in
                        ("subagent_type", "description", "prompt"))
        kind = next((k for name, k in (("compile-agent", "COMPILE"),
                                       ("codecheck-fix-agent", "CODECHECK"),
                                       ("ut-generator-agent", "UT"),
                                       ("grill-critic-agent", "GRILL"))
                     if name in blob), None)
        if not kind:
            return
        st = _contract_state()
        task = (st.get("agent_tasks", {}) or {}).get(kind) or {}
        me = os.path.abspath(MAEFLOW)
        if not task:
            remedy = (
                f'python "{me}" action status，并按输出执行 action critic 生成 GRILL 任务卡'
                if kind == "GRILL"
                else f'python "{me}" agent-task {kind.lower()} 生成并签发任务卡')
            print("[mae-flow] 派发前拦截:%s 尚无本步任务卡。先执行 "
                  "%s,再按其输出话术派发。"
                  "现在拦下只损失一次调用;跑完整只 agent 才被契约打回,重做要上百轮。"
                  % (kind, remedy), file=sys.stderr)
            sys.exit(2)
        if task.get("step") != st.get("current"):
            print("[mae-flow] 派发前拦截:%s 任务卡属于旧步骤 %s，当前步骤为 %s。"
                  "先按 current/action status 生成当前步骤的新任务卡，再派发。"
                  % (kind, task.get("step", "?"), st.get("current", "?")),
                  file=sys.stderr)
            sys.exit(2)
        try:
            txt = open(task.get("path", ""), encoding="utf-8").read()
            body = txt.rsplit("TASK_CARD_SHA256:", 1)[0]
            actual = hashlib.sha256(body.encode("utf-8")).hexdigest()
        except Exception as exc:
            print("[mae-flow] 派发前拦截:%s 任务卡不可读(%s)。"
                  "先重新生成任务卡，避免整只 agent 跑完才发现输入失效。"
                  % (kind, exc), file=sys.stderr)
            sys.exit(2)
        if actual != task.get("sha256"):
            print("[mae-flow] 派发前拦截:%s 任务卡内容已变化。"
                  "先重新生成任务卡；旧卡不能代表当前任务。"
                  % kind, file=sys.stderr)
            sys.exit(2)
        head, cur = task.get("head", ""), _git_head()
        if head and cur and head != cur:
            remedy = (
                f'python "{me}" action status，并重新执行当前 action critic'
                if kind == "GRILL"
                else f'python "{me}" agent-task {kind.lower()}')
            print("[mae-flow] 派发前拦截:%s 任务卡签发于 HEAD %s,当前 HEAD %s——源码已变化,"
                  "旧卡描述的不是现在的代码,跑完也拿不到令牌。先重新执行 %s 再派发。"
                  % (kind, head[:10], cur[:10], remedy), file=sys.stderr)
            sys.exit(2)
        # 完整流程签卡前已强制工作区源码干净（启动前遗留且指纹未变者除外）。
        # 因此同 HEAD 下出现新的未提交源码变化，必然发生在签卡后；现在拦比
        # SubagentStop 才拒签便宜得多。独立任务允许带脏工作区执行，仍由其
        # initial_source_fingerprints 在收尾契约中审计，不能在这里误伤恢复。
        if not task.get("standalone") and head:
            changed, err = _source_changed_since_receipt(head, st)
            if err:
                print("[mae-flow] 派发前拦截:%s 无法核对任务卡新鲜度(%s)。"
                      "先重新生成任务卡。" % (kind, err), file=sys.stderr)
                sys.exit(2)
            if changed:
                print("[mae-flow] 派发前拦截:%s 签卡后源码又发生未提交变化: %s。"
                      "先提交本单改动并重新生成任务卡；现在拦下可避免整只 agent 白跑。"
                      % (kind, "、".join(changed[:5])), file=sys.stderr)
                sys.exit(2)
    except SystemExit:
        raise
    except Exception as e:
        _log("agent dispatch gate EXC(fail-open): %s" % e)


def ev_pretooluse(d):
    tool = d.get("tool_name", "")
    ti = d.get("tool_input") or {}
    if tool == "Task":
        _gate_agent_dispatch(ti)
        sys.exit(0)
    if tool == "AskUserQuestion":
        try:
            st = json.load(open(STATE, encoding="utf-8"))
            moonlight = bool((st.get("moonlight") or {}).get("enabled"))
        except Exception:
            moonlight = False
        if moonlight:
            print("[mae-flow] 月光宝盒处于无人值守模式，禁止询问用户。"
                  "请根据需求、代码和仓库规则采用不扩大范围的保守结论并留痕；"
                  "质量步骤有限尝试后仍失败，使用 current 输出的 moonlight defer 记录遗留并继续。",
                  file=sys.stderr)
            sys.exit(2)
    if tool in ("Edit", "Write", "MultiEdit"):
        p = ti.get("file_path", "") or ""
        if p:
            sys.exit(maeflow("gate", "edit", p))
    elif tool == "Bash":
        c = ti.get("command", "") or ""
        if c:
            sys.exit(maeflow("gate", "bash", c))
    sys.exit(0)


def ev_action_pretooluse(d):
    """独立任务只保护自己的控制文件；普通源码、命令和用户开发行为一律不接管。"""
    tool = d.get("tool_name", "")
    ti = d.get("tool_input") or {}
    if tool == "Task":
        _gate_agent_dispatch(ti)
        sys.exit(0)

    def protected(value):
        path = str(value or "").replace("\\", "/").lower()
        return (
            ".mae-flow-work/standalone-action.json" in path
            or (
                ".mae-flow-work/standalone/" in path
                and bool(re.search(r"(?:-task\.md|/action\.json|/result-[^/\s\"']+\.md)", path))
            )
        )

    if tool in ("Edit", "Write", "MultiEdit"):
        if protected(ti.get("file_path") or ti.get("path")):
            print("[mae-flow] 独立任务状态和任务卡由 harness 维护，禁止直接编辑；"
                  "普通业务代码不受此限制。", file=sys.stderr)
            sys.exit(2)
    if tool == "Bash":
        cmd = str(ti.get("command", "") or "").replace("\\", "/").lower()
        if protected(cmd) or "dispatch.py" in cmd:
            print("[mae-flow] 禁止通过命令修改独立任务状态、任务卡或手工调用 Hook。"
                  "查看用 action status，退出用 action cancel。", file=sys.stderr)
            sys.exit(2)
    sys.exit(0)


def ev_inject(d, session_start=False):
    if session_start:
        # Plugin-owned capabilities are available with the installed plugin;
        # no project marker or reload handshake is required.
        pass
    else:
        # 用户消息原文进 ack 验真存储。payload 无 prompt 字段时确认步骤会明确拒绝并要求用户
        # 再发一条普通消息，不再降级成模型自行填写 ack。
        prompt = d.get("prompt") or ""
        _capture_moonlight_intent(prompt)
        _capture_usermsg(prompt)
        exit_intent = _capture_exit_intent(prompt)
        if exit_intent:
            rc = maeflow("exit", "--intent", exit_intent)
            # 实测死角修复:宣布"已退出"前必须核实事实(STATE 确已消失)。
            # 旧逻辑按 rc==0 宣布,而 maeflow() 的 fail-open 会把 CLI crash/
            # 脚本缺失翻译成 0——按谎话放行,用户以为退了、门禁还在,
            # 脚本恢复后旧流程还会复活反咬。
            if rc == 0 and not os.path.exists(STATE):
                print("[mae-flow] 用户已明确退出，本条消息开始按普通开发请求处理；"
                      "不要再运行 current/done。")
                sys.exit(0)
            print("[mae-flow] 自动退出未完成(流程状态仍在)。不要重复要求用户确认；"
                  "请执行 doctor 查看原因，用户始终可在真实终端运行 "
                  "`mae-flow exit --interactive`；若插件脚本本身不可用,恢复插件后"
                  "重试,或(确认放弃流程时)由用户手动删除项目根的 .mae-flow.json* "
                  "文件。", file=sys.stderr)
    me = os.path.abspath(MAEFLOW)
    readme = os.path.abspath(os.path.join(HERE, "..", "README.md"))
    if os.path.exists(STATE):
        maeflow("status", "--inject")
        if session_start:
            print(f"[mae-flow] 存在进行中的交付流程。续跑先执行 python \"{me}\" current 获取当前步骤指令。"
                  f"用户问 mae-flow 用法/流程类问题时,先读 \"{readme}\" 再按其内容作答,禁止凭记忆即兴。")
    else:
        action = _load_action()
        if action:
            print("[mae-flow] 当前有独立 %s 任务 %s；它不启用完整流程，也不限制普通改码。"
                  "继续请执行 action status，完成后 action finish，随时可 action cancel。"
                  % (str(action.get("kind", "")).upper(), action.get("id", "?")))
            if action.get("status") == "awaiting_scope_confirmation":
                print("[mae-flow] 当前任务尚未执行，正在等待用户确认已展示的文件范围。"
                      "用户选择「确认以上范围」后执行 action confirm-scope "
                      "--ack \"确认以上范围\"；用户要求调整则 action cancel 后按新范围重开。")
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
    reject_reason = ""
    if len(matches) > 1:
        kinds = {x.group(1) + "/" + x.group(2) for x in matches}
        if len(kinds) == 1:
            # 重答/汇报场景常在正文引用同一结论(如先引格式说明再给结果)。
            # 同名同值不构成歧义;为一个可判定的回复重跑整只编译/UT agent 才是浪费。
            m = m or matches[-1]
            _log("subagentstop: 多个相同结果标记(%s),判定无歧义,接受" % next(iter(kinds)))
        else:
            reject_reason = (
                "最终回复包含互相矛盾的结果标记(%s)，无法判断本轮真实结论。"
                "重新输出时整个回复只保留一行顶行的 XXX_RESULT: 标记(本轮真实结果)；"
                "引用历史结论或格式说明时不要顶行书写标记。" % "、".join(sorted(kinds)))
            _record_rejection("SUBAGENT", reject_reason)
            m = None
    elif not m and len(matches) == 1:
        m = matches[0]
        _log("subagentstop: 契约标记不在第一行,兼容接受并继续验完整契约")
    runtime = _contract_state()
    standalone_expected = ""
    if runtime.get("_standalone"):
        standalone_expected = {
            "ut": "UT", "codecheck": "CODECHECK", "grill": "GRILL",
        }.get(str(runtime.get("current", "")).replace("standalone_", ""), "")
        if m and m.group(1) != standalone_expected:
            _log("standalone action ignores unrelated contract agent: " + m.group(1))
            sys.exit(0)
    # 凡以唯一合法契约标记收尾的 agent,直接验契约+发令牌,
    # 不依赖启动 prompt 的措辞(主模型派发时未必写 agent 文件名——已实际踩过)
    if m:
        if m.group(1) == "CODECHECK":
            _codecheck_contract(m.group(2), last, tool_calls, soft=retry)
        if m.group(1) == "UT":
            _ut_contract(m.group(2), last, tool_calls, soft=retry)
        if m.group(1) == "COMPILE":
            _compile_contract(m.group(2), last, tool_calls, soft=retry)
        if m.group(1) == "GRILL":
            _grill_contract(m.group(2), last, tool_calls, soft=retry)
        _record_agent_token(m.group(1), m.group(2), last)
        sys.exit(0)
    if retry:
        _autopsy(tp, asst)   # 留档(不进 stderr:此路径 exit 0,别被 harness 当 hook error 展示)
        _record_rejection("SUBAGENT", reject_reason
                          or "重答后仍未找到唯一的 XXX_RESULT 结果标记。")
        _log("subagentstop: 重答后仍无可判定契约标记,放行防死循环(不发令牌,done 会拦;尸检已留档)")
        sys.exit(0)
    # 无标记:判定是否我方契约 agent——扫 transcript 头部(含 agent 系统提示,必带 agent 名/契约字样),
    # 不依赖任务 prompt 措辞(主模型派"定稿"类子任务时不会写 agent 名——已实际踩过)
    try:
        head = open(tp, encoding="utf-8", errors="replace").read(16000)
    except OSError:
        head = prompt
    if standalone_expected:
        expected_agent = {
            "UT": "ut-generator-agent",
            "CODECHECK": "codecheck-fix-agent",
            "GRILL": "grill-critic-agent",
        }.get(standalone_expected, "")
        if expected_agent not in head and not re.search(
                r"\b" + re.escape(standalone_expected) + r"_RESULT:", head):
            _log("standalone action ignores unrelated subagent without expected contract")
            sys.exit(0)
    if not re.search(r"_RESULT:|ut-generator-agent|codecheck-fix-agent|"
                     r"story-generator-agent|compile-agent|grill-critic-agent", head):
        _log("subagentstop: 无契约标记且 transcript 头部未见契约 agent 特征,跳过")
        sys.exit(0)
    clue = _autopsy(tp, asst)
    # 打回话术必须与真实拒签原因一致:矛盾标记场景若仍说"第一行必须是标记",
    # 弱模型会按错误指引改写(第一行明明就是标记)再死一遍,循环重跑昂贵 agent。
    reason_text = reject_reason or (
        "最终回复必须以 XXX_RESULT: <状态> 开头(第一行)。"
        "请按你的定义文件顶部「最终回复格式」重新输出完整结果;不确定时用失败/待确认类状态,禁止省略标记。")
    print("[mae-flow] 子 agent 契约违规:" + reason_text + "\n"
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


def _record_agent_token(kind, status="", report=""):
    """子 agent 合法收尾的硬令牌:仅由本 hook(harness 调用)写入,是模型无法伪造的证据源——
    令牌文件在 gate 黑名单中(Edit/Bash 双拦),手动调 dispatch.py 也被 gate 拦截。
    mae-flow 的 agent_ran 证据据此判定"本步期间该 agent 真实跑过"。
    令牌同时绑定签发时 HEAD(新鲜度):签发后源码再变,证据即过期(mae-flow 侧校验)。"""
    try:
        action = _load_action() if not os.path.isfile(STATE) else None
        if action:
            head = _git_head()
            work = action.get("work_dir") or os.path.dirname(os.path.abspath(ACTION_STATE))
            os.makedirs(work, exist_ok=True)
            report_path = os.path.join(work, "result-" + kind.lower() + ".md")
            atomic_write_text(report_path, (report or "").rstrip() + "\n")

            def update_action(current):
                task = (current.get("agent_tasks", {}) or {}).get(kind, {})
                current.setdefault("tokens", {})[kind] = {
                    "at": time.strftime("%Y-%m-%d %H:%M:%S"), "head": head,
                    "status": status, "step": "standalone_" + current.get("kind", ""),
                    "task_sha256": task.get("sha256", ""), "report_path": report_path,
                }
                current.setdefault("rejections", {}).pop(kind, None)
                current["rejections"].pop("SUBAGENT", None)
                return current

            update_versioned_json(ACTION_STATE, "action", update_action)
            _log("standalone agent token: %s/%s @%s" % (
                kind, status or "-", head[:9] or "no-git"))
            return
        p = ".mae-flow.json.tokens"
        head = _git_head()
        step = ""
        try:
            raw, err = safe_read_json(STATE)
            step = normalize_document(raw, "flow").get("current", "") if not err and raw else ""
        except Exception:
            pass

        def update_tokens(tokens):
            tokens[kind] = {
                "at": time.strftime("%Y-%m-%d %H:%M:%S"), "head": head,
                "status": status, "step": step,
            }
            return tokens

        update_json(p, update_tokens, default={}, recover_corrupt=True)
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


def _record_agent_write(path):
    """Record a successful direct Agent file edit as a commit candidate.

    The ledger narrows review scope only. It never means every recorded file
    must be staged, and command-generated files intentionally receive no entry.
    """
    try:
        # macOS 的 tempfile 常给 /var/...，而 cwd 会解析成 /private/var/...；
        # realpath 后再判边界，避免同一文件因系统软链接被误当仓库外路径。
        root = os.path.realpath(os.path.abspath(os.getcwd()))
        absolute = os.path.realpath(os.path.abspath(path))
        if os.path.commonpath([root, absolute]) != root:
            return
        relative = os.path.relpath(absolute, root).replace("\\", "/")
        if relative in ("", ".") or relative.startswith("../"):
            return

        def update_writes(data):
            paths = data.setdefault("paths", {})
            paths[relative] = {
                "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "tool": "file-write",
            }
            # A flow should rarely touch this many files. Bound stale/corrupt
            # growth without changing the provenance semantics.
            if len(paths) > 2000:
                keep = sorted(
                    paths.items(),
                    key=lambda item: str((item[1] or {}).get("at", "")),
                    reverse=True)[:2000]
                data["paths"] = dict(keep)
            return data

        update_json(
            AGENT_WRITES_STATE, update_writes, default={"paths": {}},
            recover_corrupt=True)
    except Exception as exc:
        _log("agent write ledger EXC: %s" % exc)


def _capture_usermsg(text):
    """harness 捕获的用户真实输入(UserPromptSubmit 的 prompt / AskUserQuestion 的应答),
    供完整流程 ack 与独立任务范围确认验真。没有流程/独立任务时不落盘；
    保留最近 10 条、单条截断 2000 字，写失败留日志不阻塞。"""
    try:
        text = (text or "").strip()
        if not text:
            return
        step = ""
        config_review_sha = ""
        config_review_id = ""
        action = None
        if os.path.exists(STATE):
            try:
                raw, err = safe_read_json(STATE)
                flow_state = normalize_document(
                    raw, "flow") if not err and raw else {}
                step = flow_state.get("current", "")
                review = flow_state.get("config_review") or {}
                if step == "config_confirm" and review.get("step") == step:
                    config_review_sha = str(review.get("sha256", ""))
                    config_review_id = str(review.get("id", ""))
            except Exception:
                pass
        else:
            action = _load_action()
            if not action:
                return
            step = "standalone_" + action.get("kind", "")
        captured = text[:2000]
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        msg_id = hashlib.sha256(
            (stamp + "\0" + step + "\0" + captured).encode("utf-8")).hexdigest()[:12]
        row = {
            "id": msg_id,
            "at": stamp,
            "epoch": time.time(),
            "step": step,
            "text": captured,
            "sha256": hashlib.sha256(captured.encode("utf-8")).hexdigest(),
            "input_encoding": _INPUT_ENCODING or "unknown",
        }
        if config_review_sha:
            row["config_review_sha256"] = config_review_sha
            row["config_review_id"] = config_review_id

        def append_message(msgs):
            if not isinstance(msgs, list):
                msgs = []
            msgs.append(row)
            return msgs[-10:]

        if action:
            def append_action(current):
                current["user_messages"] = append_message(
                    current.get("user_messages", []))
                return current
            update_versioned_json(ACTION_STATE, "action", append_action)
        else:
            update_json(
                STATE + ".usermsg", append_message, default=[],
                recover_corrupt=True)
    except Exception as e:
        _log("usermsg EXC: %s" % e)


def _explicit_exit_prompt(text):
    """只识别没有歧义的退出指令；询问“能不能退出”不应误触发。"""
    value = re.sub(r"\s+", " ", (text or "").strip())
    if re.search(r"^/mae-flow\s+(?:exit|direct)(?:\s|$)", value, re.I):
        return True
    lower = value.lower()
    names_flow = "mae-flow" in lower or "mae flow" in lower or "这个工作流" in value
    explicit_verb = bool(re.search(
        r"(退出|停止使用|不想(?:再)?用|不用|关闭)\s*(?:mae[- ]?flow|这个工作流)", value, re.I))
    direct_after = any(x in value for x in (
        "直接开发", "直接改代码", "直接让", "直接写", "直接补", "补UT", "补 UT", "保留现场", "不走流程"))
    question = any(x in value for x in ("能不能", "可以吗", "会怎样", "怎么退出", "如何退出", "？", "?"))
    return names_flow and explicit_verb and direct_after and not question


def _capture_exit_intent(text):
    """用户事件本身签发一次性退出凭据，避免 exit 再依赖已经故障的 ack 账本。"""
    try:
        text = (text or "").strip()
        if not text or not os.path.isfile(STATE) or not _explicit_exit_prompt(text):
            return ""
        # 实测死角修复:签发与消费必须同一把尺——旧逻辑用裸 json.load,
        # JSON 可解析但 schema 非法(revision 被改坏等)时记真实步骤,而 CLI
        # load_state 严格校验判损坏,intent 对不上,主逃生口永久失效循环。
        try:
            raw, err = safe_read_json(STATE)
            if err or not isinstance(raw, dict):
                step = "__corrupt_state__"
            else:
                step = str(normalize_document(raw, "flow").get("current", ""))
        except Exception:
            step = "__corrupt_state__"
        nonce = hashlib.sha256(
            (str(time.time_ns()) + "\0" + step + "\0" + text).encode("utf-8")).hexdigest()[:24]
        rec = {
            "id": nonce,
            "epoch": time.time(),
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "step": step,
            "text": text[:2000],
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
        atomic_write_json(EXIT_INTENT, rec)
        _log("captured explicit exit intent step=%s id=%s" % (step, nonce))
        return nonce
    except Exception as exc:
        _log("exit intent EXC: %s" % exc)
        return ""


def _capture_moonlight_intent(text):
    """全新项目尚无 STATE 时，暂存本轮明确的月光宝盒授权。

    启动脚本只接受十分钟内、且 --ack 能命中原文的记录，并在消费后删除。
    它只解决“先有用户指令还是先有状态文件”的鸡生蛋问题，不替代正常 ack 验真。
    """
    try:
        text = (text or "").strip()
        if not text or resolve_runtime(os.getcwd()).mode != RuntimeMode.INACTIVE:
            return
        if not re.search(r"月光宝盒|moonlight", text, re.I):
            return
        rec = {"at": time.strftime("%Y-%m-%d %H:%M:%S"),
               "epoch": time.time(), "text": text[:2000]}
        atomic_write_json(MOONLIGHT_INTENT, rec)
        _log("captured pre-init moonlight intent")
    except Exception as e:
        _log("moonlight intent EXC: %s" % e)


def _capture_direct_prompt(text):
    """直接模式也只为“用户明确重新启用”保留最近原话；不恢复任何旧流程令牌。"""
    try:
        text = (text or "").strip()
        if not text or not os.path.isfile(EXIT_STATE):
            return
        row = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "text": text[:2000]}

        def append_direct(rec):
            msgs = rec.get("direct_messages", []) or []
            msgs.append(row)
            rec["direct_messages"] = msgs[-10:]
            return rec

        update_versioned_json(EXIT_STATE, "exit", append_direct)
    except Exception as e:
        _log("direct prompt EXC: %s" % e)


def _maybe_utrun(d):
    """UT 运行命令被真实调起 → UTRUN 事件令牌。当前仅观测(doctor 可见);
    升级为 verify_ut 硬证据前,须公司机确认子 agent 的 Bash 也触发 PostToolUse。
    只在 UT 步骤检测(FIELD-TEST 0.2 待办):这是每条 Bash 都要付的 PostToolUse 开销,
    其他步骤读状态+比对纯属浪费,令牌也只会在 UT 步骤被消费。"""
    try:
        if not os.path.exists(STATE):
            return
        st = json.load(open(STATE, encoding="utf-8"))
        if st.get("current") not in ("verify_ut", "rf_ut", "tw_ut"):
            return
        cmd = re.sub(r"\s+", " ", ((d.get("tool_input") or {}).get("command", "") or ""))
        ut = re.sub(r"\s+", " ", (st.get("config", {}) or {}).get("UT运行命令", "") or "").strip()
        if ut and ut in cmd:
            _record_agent_token("UTRUN", "EXECUTED")
    except Exception as e:
        _log("utrun EXC: %s" % e)


def _load_action():
    action, err, expired = core_load_action()
    if err:
        _log("standalone action unreadable: " + err)
        return None
    if action and expired:
        _log("standalone action expired: " + action.get("id", "?"))
        return None
    return action


def _contract_state():
    """完整流程与独立任务共用契约器，但独立任务绝不创建主状态或启用源码 gate。"""
    try:
        if os.path.isfile(STATE):
            raw, err = safe_read_json(STATE)
            return normalize_document(raw, "flow") if not err and raw else {}
    except Exception:
        return {}
    action = _load_action()
    if not action:
        return {}
    return {
        "current": "standalone_" + action.get("kind", ""),
        "config": action.get("config", {}) or {},
        "agent_tasks": action.get("agent_tasks", {}) or {},
        "quality": action.get("quality", {}) or {},
        "_standalone": True,
        "_action_id": action.get("id", ""),
    }


def _evidence_data():
    action = _load_action()
    if action and not os.path.isfile(STATE):
        return dict(action.get("evidence", {}) or {})
    try:
        return json.load(open(EVIDENCE_STATE, encoding="utf-8")) if os.path.exists(EVIDENCE_STATE) else {}
    except Exception:
        return {}


def _save_evidence(data):
    action = _load_action()
    if action and not os.path.isfile(STATE):
        def merge_action(current):
            current.setdefault("evidence", {}).update(data)
            return current
        update_versioned_json(ACTION_STATE, "action", merge_action)
    else:
        def merge_evidence(current):
            current.update(data)
            return current
        update_json(
            EVIDENCE_STATE, merge_evidence, default={}, recover_corrupt=True)


def _record_rejection(label, msg):
    """把真实拒签原因留给 done/doctor；Hook stderr 被宿主吞掉时也不能让主模型猜。"""
    try:
        action = _load_action() if not os.path.isfile(STATE) else None
        st = _contract_state()
        task = (st.get("agent_tasks", {}) or {}).get(label, {})
        rejection = {
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "step": st.get("current", ""),
            "head": _git_head(),
            "task_sha256": task.get("sha256", ""),
            "reason": msg,
        }
        if action:
            def reject_action(current):
                current.setdefault("rejections", {})[label] = rejection
                return current
            update_versioned_json(ACTION_STATE, "action", reject_action)
        else:
            def reject_flow(data):
                data[label] = rejection
                return data
            update_json(
                REJECTION_STATE, reject_flow, default={}, recover_corrupt=True)
        _log(label + " 拒签: " + msg)
    except Exception as e:
        _log("rejection EXC: " + str(e))


def _clear_rejection(label):
    try:
        action = _load_action() if not os.path.isfile(STATE) else None
        if action:
            def clear_action(current):
                data = current.setdefault("rejections", {})
                data.pop(label, None)
                data.pop("SUBAGENT", None)
                return current
            update_versioned_json(ACTION_STATE, "action", clear_action)
        else:
            if not os.path.exists(REJECTION_STATE):
                return
            def clear_flow(data):
                data.pop(label, None)
                data.pop("SUBAGENT", None)
                return data
            update_json(
                REJECTION_STATE, clear_flow, default={}, recover_corrupt=True)
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
    st = _contract_state()
    task = (st.get("agent_tasks", {}) or {}).get(kind, {})
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
    if task.get("standalone") and _git_head() != head:
        _contract_bail(kind, "独立任务禁止自动 commit，但当前 HEAD 已变化。"
                       "保留代码后结束本任务并由用户自行决定是否提交。", soft)
    return task


def _state_config():
    return (_contract_state().get("config", {}) or {})


def _field(report, name):
    m = re.search(r"^\s*" + re.escape(name) + r":\s*(.+?)\s*$", report, re.M)
    return m.group(1).strip() if m else ""


_REPORT_FIELDS = (
    "TASK_CARD_SHA256", "GENERATOR_USED", "EXECUTED_UT", "EXECUTED_BUILD", "EXECUTED_COMMAND",
    "TESTS_TOTAL", "TESTS_PASSED", "TESTS_FAILED", "AC_COVERAGE", "PENDING_QUESTIONS",
    "KNOWN_FAILURES", "SUSPECTED_BUGS", "FOUND", "FIXED", "REMAINING_COUNT",
    "STAGE", "GAPS_FOUND", "MISSING_BRANCHES",
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


def _embedded_build_command(build_cfg):
    return "mcde build -i" if "build-fix" in (build_cfg or "").lower() else ""


def _build_call(tool_calls, build_cfg):
    """Find the real compilation call selected by the confirmed build route."""
    need = _required_skill(build_cfg)
    if need:
        return _skill_call(tool_calls, need)
    embedded = _embedded_build_command(build_cfg)
    return _bash_call(tool_calls, embedded or build_cfg)


def _build_summary_matches(summary, build_cfg):
    if _same_config(summary, build_cfg):
        return True
    embedded = _embedded_build_command(build_cfg)
    return bool(embedded and (
        "build-fix" in (summary or "").lower()
        or _same_config(summary, embedded)))


def _codecheck_build_call(tool_calls, build_cfg):
    """返回当前 transcript 中与配置一致且未明确失败的编译调用。"""
    call = _build_call(tool_calls, build_cfg)
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
    if task.get("standalone"):
        rec["source_snapshot"] = _source_snapshot(task.get("head", ""))
    try:
        data = _evidence_data()
        data["CODECHECK_BUILD"] = rec
        _save_evidence(data)
        _log("CODECHECK 编译凭证: @%s" % (rec["head"][:9] or "no-git"))
    except Exception as e:
        _log("codecheck receipt EXC: " + str(e))
    return rec


def _record_codecheck_fullcheck_receipt(
        task, command_count, raw_counts, scan, expected_raw=None,
        result_hashes=None):
    """保存最终分批的执行事实，供“只修报告”跨 agent 复用。

    精确计数可解析时同时保存机器对账；未知成功输出只保存执行凭证，并把
    CodeCheck 结论视为建议项。源码、任务卡或首检口径任一变化都会让凭证失效。
    """
    counts_complete = (
        len(raw_counts) == int(command_count)
        and all(isinstance(x, int) and x >= 0 for x in raw_counts))
    rec = {
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "step": task.get("step", ""),
        "task_sha256": task.get("sha256", ""),
        "head": _git_head(),
        "command_count": int(command_count),
        "raw_counts": list(raw_counts),
        "raw_total": int(sum(raw_counts)),
        "machine_counts_complete": counts_complete,
        "expected_raw": int(expected_raw) if expected_raw is not None else None,
        "result_hashes": list(result_hashes or []),
        "scan_count": scan.get("count"),
        "stock_excluded": scan.get("stock_excluded"),
    }
    if task.get("standalone"):
        rec["source_snapshot"] = _source_snapshot(task.get("head", ""))
    try:
        data = _evidence_data()
        data["CODECHECK_FULLCHECK"] = rec
        _save_evidence(data)
        _log("CODECHECK fullcheck 凭证: %s 批/%s @%s"
             % (command_count,
                (str(rec["raw_total"]) + " 条" if counts_complete else "计数格式未知"),
                rec["head"][:9]))
    except Exception as exc:
        _log("codecheck fullcheck receipt EXC: " + str(exc))
        return None
    return rec


def _codecheck_counts_from_text(text):
    """提取 CodeCheck CLI 已公开的机器计数格式；不依赖进程退出码。

    公司 CLI 在“检查成功但发现告警”时可能返回非零码。只要 result 完整且
    含可信计数锚点，非零码不是执行失败；未知格式仍不猜数。
    """
    text = str(text or "")
    counts = [int(x) for x in re.findall(r"共有\s*(\d+)\s*条告警", text)]
    if counts:
        return counts
    counts = [int(x) for x in re.findall(
        r"\|\s*\*{0,2}总计\*{0,2}\s*\|\s*\*{0,2}(\d+)\*{0,2}\s*\|",
        text)]
    if counts:
        return counts
    details = re.findall(
        r"^###\s+\d+\.\s+\[(?:Critical|Major|Minor|Suggestion|"
        r"致命级|严重级|一般级|提示级)\]",
        text, re.M | re.I)
    if details:
        return [len(details)]
    completed = (
        "代码检查完成" in text or "CodeCheck 检查报告" in text
        or "检查结果汇总" in text)
    zero_patterns = (
        r"未发现(?:任何)?(?:代码)?告警",
        r"没有发现(?:任何)?(?:代码)?告警",
        r"(?:告警|问题)(?:总数)?\s*[:：]?\s*0\b",
        r"0\s*条告警",
    )
    return [0] if completed and any(
        re.search(pattern, text, re.I) for pattern in zero_patterns) else []


_UT_NONRUN_PAT = re.compile(
    r"\b(?:disabled|excluded|deselected|skipped)\b|禁用|排除|跳过", re.I)
_UT_HARD_RISK_PAT = re.compile(
    r"\b(?:pre-existing\s+(?:failure|segfault)|segmentation\s+fault|segfault)\b|"
    r"段错误|绕过失败|屏蔽失败", re.I)
_UT_FILTER_ARG_PAT = re.compile(
    r"(?P<flag>--?gtest_filter|--?exclude|--?skip|--?disable|--filter|-E|-R|-k|-m|-t|"
    r"--deselect|--ignore|--tests|--tests-regex|--exclude-regex|--runTestsByPath|"
    r"--testPathPattern|--testNamePattern|-D(?:test|tests|it\.test))"
    r"(?=\s|=|$)(?:\s*=\s*|\s+)?"
    r"(?P<value>\"[^\"]*\"|'[^']*'|[^\s;&|]+)?", re.I)


def _ut_filter_args(command):
    # 过滤参数的排列顺序不改变测试集合；统一排序后再比较，避免等价命令
    # 仅因 -R/-E 换位被误判为缩小范围。
    return sorted([
        (m.group("flag").lower(), re.sub(
            r"\s+", " ", (m.group("value") or "").strip().strip("\"'")).lower())
        for m in _UT_FILTER_ARG_PAT.finditer(command or "")
    ])


def _command_swallows_failure(command):
    return bool(re.search(
        r"(?:\|\||;|&)\s*(?:true|exit(?:\s+/b)?\s+0|"
        r"\$(?:global:)?LASTEXITCODE\s*=\s*0)\b",
        command or "", re.I))


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


def _reported_bash_call(tool_calls, reported):
    """按报告里的实际命令反查真实 Bash 调用，不与配置提示逐字绑定。"""
    def n(s):
        return re.sub(r"\s+", " ", (s or "")).strip().strip("`").lower()

    want = n(reported)
    if not want:
        return None
    exact = _bash_call(tool_calls, want)
    if exact:
        return exact
    for x in reversed(tool_calls or []):
        if str(x.get("name", "")).lower() != "bash":
            continue
        inp = x.get("input", {}) or {}
        cmd = inp.get("command", "") if isinstance(inp, dict) else str(inp)
        for seg in re.split(r"&&|\|\||[;\n]", n(cmd)):
            seg = seg.strip()
            if not seg or not want.startswith(seg):
                continue
            # 兼容“命令（补充说明）”，不接受任意自然语言包含一段命令。
            tail = want[len(seg):].lstrip()
            if not tail or tail[0] in "([（，,;；—":
                return x
    return None


def _reported_bash_segment(call, reported):
    """取报告所指向的真实命令段，供过滤、跳过风险检测使用。"""
    def n(s):
        return re.sub(r"\s+", " ", (s or "")).strip().strip("`")

    want = n(reported).lower()
    if not call or not want:
        return ""
    inp = call.get("input", {}) or {}
    cmd = inp.get("command", "") if isinstance(inp, dict) else str(inp)
    for seg in re.split(r"&&|\|\||[;\n]", n(cmd)):
        clean = seg.strip()
        low = clean.lower()
        if low.startswith(want) or want.startswith(low):
            return clean
    return ""


def _ut_nonrunning_counts(text):
    """提取测试框架末次汇总中的 disabled/skipped/excluded 精确计数。"""
    patterns = {
        "disabled": (
            r"\b(\d+)\s+(?:tests?\s+)?disabled\b",
            r"\bdisabled(?:\s+tests?)?\s*[:=]\s*(\d+)\b",
        ),
        "skipped": (
            r"\b(\d+)\s+(?:tests?\s+)?skipped\b",
            r"\bskipped(?:\s+tests?)?\s*[:=]\s*(\d+)\b",
        ),
        "excluded": (
            r"\b(\d+)\s+(?:tests?\s+)?(?:excluded|deselected)\b",
            r"\b(?:excluded|deselected)(?:\s+tests?)?\s*[:=]\s*(\d+)\b",
        ),
    }
    out = {}
    for kind, regexes in patterns.items():
        hits = []
        for regex in regexes:
            hits.extend((m.start(), int(m.group(1)))
                        for m in re.finditer(regex, text or "", re.I))
        if hits:
            out[kind] = max(hits, key=lambda item: item[0])[1]
    return out


def _ut_nonrunning_kinds(text):
    kinds = set()
    if re.search(r"\bdisabled\b|禁用", text or "", re.I):
        kinds.add("disabled")
    if re.search(r"\bskipped\b|跳过", text or "", re.I):
        kinds.add("skipped")
    if re.search(r"\b(?:excluded|deselected)\b|排除", text or "", re.I):
        kinds.add("excluded")
    return kinds


def _matching_ut_runs(tool_calls, reported):
    return [call for call in (tool_calls or [])
            if str(call.get("name", "")).lower() == "bash"
            and _reported_bash_segment(call, reported)
            and call.get("result_seen") and not _call_failed(call)]


def _ut_observed_counts(text):
    """从常见 Windows/C++/Java/Python 测试器真实输出提取末次总数与失败数。

    这里只是已知格式的额外加固，不是跨语言真相源。识别不到时由真实工具
    成功状态 + 专项 Agent 的统一报告合同兜底，禁止因未知框架格式误阻断。
    """
    text = str(text or "")
    candidates = []
    for m in re.finditer(
            r"(\d+)%\s+tests\s+passed,\s*(\d+)\s+tests?\s+failed\s+out\s+of\s+(\d+)",
            text, re.I):
        candidates.append((m.start(), {
            "total": int(m.group(3)), "failed": int(m.group(2)),
            "passed": int(m.group(3)) - int(m.group(2))}))
    for m in re.finditer(
            r"Tests\s+run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+)"
            r"(?:,\s*Skipped:\s*(\d+))?", text, re.I):
        total, failures, errors = map(int, m.group(1, 2, 3))
        skipped = int(m.group(4) or 0)
        candidates.append((m.start(), {
            "total": total, "failed": failures + errors,
            "passed": max(0, total - failures - errors - skipped)}))
    g_pass = list(re.finditer(r"\[\s*PASSED\s*\]\s*(\d+)\s+tests?", text, re.I))
    g_fail = list(re.finditer(r"\[\s*FAILED\s*\]\s*(\d+)\s+tests?", text, re.I))
    if g_pass or g_fail:
        passed = int(g_pass[-1].group(1)) if g_pass else 0
        failed = int(g_fail[-1].group(1)) if g_fail else 0
        pos = max((g_pass[-1].start() if g_pass else -1),
                  (g_fail[-1].start() if g_fail else -1))
        candidates.append((pos, {
            "total": passed + failed, "failed": failed, "passed": passed}))
    # pytest 与轻量自研 runner 常只有“77 passed, 2 failed”一行。
    for line_match in re.finditer(r"^.*(?:passed|failed).*$", text, re.I | re.M):
        line = line_match.group(0)
        passed_hits = re.findall(r"\b(\d+)\s+passed\b", line, re.I)
        failed_hits = re.findall(r"\b(\d+)\s+failed\b|\bfailed\s*[:=]\s*(\d+)\b",
                                 line, re.I)
        if not passed_hits and not failed_hits:
            continue
        passed = int(passed_hits[-1]) if passed_hits else None
        failed = int(next(x for x in failed_hits[-1] if x)) if failed_hits else 0
        candidates.append((line_match.start(), {
            "total": (passed + failed) if passed is not None else None,
            "failed": failed, "passed": passed}))
    if re.search(r"\bNo tests were found\b|\bno tests collected\b", text, re.I):
        candidates.append((len(text), {"total": 0, "failed": 0, "passed": 0}))
    return max(candidates, key=lambda item: item[0])[1] if candidates else {}


def _ut_report_counts(report):
    return {
        key: _number_field(report, field)
        for key, field in (
            ("total", "TESTS_TOTAL"),
            ("passed", "TESTS_PASSED"),
            ("failed", "TESTS_FAILED"),
        )
    }


def _bash_mutates_before_ut_baseline(call):
    """基线前只允许明确的只读探查；未知 Bash 倒向阻断，防 sed/python 偷改测试。"""
    name = str((call or {}).get("name", "")).lower()
    if name in ("read", "grep", "glob"):
        return False
    if name in ("write", "edit", "multiedit", "skill"):
        return True
    if name != "bash":
        return False
    inp = (call or {}).get("input", {}) or {}
    command = inp.get("command", "") if isinstance(inp, dict) else str(inp)
    without_fd_copy = re.sub(r"\d*>\s*&\s*\d+", "", command)
    if re.search(r"(?:^|[\s;&|])(?:sed|perl)\s+-i\b|"
                 r"\b(?:Set-Content|Out-File|Add-Content|tee)\b",
                 command, re.I) or re.search(r"\d*>{1,2}", without_fd_copy):
        return True
    safe = re.compile(
        r"^(?:cd|pwd|ls|dir|find|rg|grep|cat|type|Get-Content|"
        r"git\s+(?:status|diff|log|show|rev-parse|ls-files))\b", re.I)
    segments = [x.strip() for x in re.split(r"&&|[;\n]", command) if x.strip()]
    return not segments or any(not safe.search(seg) for seg in segments)


def _ut_execution_risk(report, run_call, expected, tool_calls=None, require_baseline=False):
    """PASS 不得靠临时禁用/过滤失败测试取得；配置本身带过滤时视为用户已明确授权。"""
    configured = re.sub(r"\s+", " ", expected or "").strip()
    summary = _flex_field(report, "EXECUTED_UT") or ""
    segment = _reported_bash_segment(run_call, summary)
    result = (run_call or {}).get("result", "") or ""
    inp = (run_call or {}).get("input", {}) or {}
    raw_command = inp.get("command", "") if isinstance(inp, dict) else str(inp)
    if _command_swallows_failure(raw_command):
        return ("实际 UT 命令吞掉了失败退出码（如 || true / ; exit 0）；"
                "即使工具调用显示成功也不能报告 PASS。")
    observed = _ut_observed_counts(result)
    if observed.get("failed", 0) > 0:
        return ("测试器真实输出显示 %d 个失败，但报告声称 PASS；"
                "必须按 NEEDS_INPUT/FAIL 如实收尾。" % observed["failed"])
    report_total = _number_field(report, "TESTS_TOTAL")
    if observed.get("total") is not None and report_total is not None:
        # 各框架对 total 是否包含 skipped 的定义不同。保留机器对账，但接受
        # “框架总数”与“实际执行数(passed+failed)”这两种已知合法口径；
        # 识别不到的格式不猜，由 Skill/Agent 的统一报告合同负责归一。
        legitimate = {observed["total"]}
        if observed.get("passed") is not None and observed.get("failed") is not None:
            legitimate.add(observed["passed"] + observed["failed"])
        if report_total not in legitimate:
            return ("TESTS_TOTAL(%d)与测试器真实末次汇总口径(%s)不一致；"
                    "数字必须取自真实执行输出。"
                    % (report_total, "/".join(str(x) for x in sorted(legitimate))))
    risk_text = summary + "\n" + result
    # 常见测试框架会正常打印“0 skipped/0 disabled”，这是全绿统计，不得误伤。
    risk_text = re.sub(r"\b(?:0|no)\s+(?:tests?\s+)?(?:disabled|excluded|skipped)\b", "",
                       risk_text, flags=re.I)
    risk_text = re.sub(r"\b(?:tests?\s+)?(?:disabled|excluded|skipped)\s*[:=]\s*0\b", "",
                       risk_text, flags=re.I)
    risk_text = re.sub(r"\bno\s+tests?\s+(?:were\s+)?(?:disabled|excluded|skipped)\b", "",
                       risk_text, flags=re.I)
    risk_text = re.sub(r"(?:跳过|禁用|排除)\s*[:：]?\s*0\s*(?:个|项|条|例)?", "", risk_text)
    actual_filters = _ut_filter_args(segment)
    configured_filters = _ut_filter_args(configured)
    filter_risk = bool(actual_filters and actual_filters != configured_filters)
    if filter_risk:
        return "实际 UT 命令在任务卡配置之外追加了过滤/排除参数；未经用户确认不能缩小测试范围后报告 PASS。"
    if _UT_HARD_RISK_PAT.search(risk_text):
        return ("测试报告或执行输出显示段错误、绕过失败或其他硬失败；"
                "必须进入 KNOWN_FAILURES/SUSPECTED_BUGS，不能 PASS。")
    calls = list(tool_calls or [])
    try:
        final_index = next(i for i, call in enumerate(calls) if call is run_call)
    except StopIteration:
        final_index = len(calls)
    # 同口径首跑不再是每单必跑：正常路径只跑一次最终 UT。只有终跑明确报告
    # 非零 disabled/skipped/excluded，且 Agent 要把它认定为存量时，才使用
    # 可选首跑基线做增量对账。这样不让所有语言为极少数异常天然付双倍成本。
    earlier = [(i, call) for i, call in enumerate(calls[:final_index])
               if str(call.get("name", "")).lower() == "bash"
               and _reported_bash_segment(call, summary)
               and call.get("result_seen")]
    final_counts = {
        kind: count for kind, count in _ut_nonrunning_counts(result).items()
        if count > 0
    }
    if final_counts:
        if not earlier:
            return ("终跑存在 disabled/skipped/excluded，但修改测试前没有同口径首跑基线；"
                    "不能区分存量项与本单新增项，需按非 PASS 收尾。")
        baseline_index, baseline_call = earlier[0]
        if any(_bash_mutates_before_ut_baseline(call)
               for call in calls[:baseline_index]):
            return ("用于认领存量 disabled/skipped/excluded 的 UT 首跑发生在"
                    "写测试、生成 Skill 或未知写盘命令之后，不能作为存量基线。")
        baseline_counts = _ut_nonrunning_counts(
            str(baseline_call.get("result", "") or ""))
        missing = [kind for kind in final_counts if kind not in baseline_counts]
        increased = [kind for kind in final_counts
                     if kind in baseline_counts
                     and final_counts.get(kind, 0) > baseline_counts[kind]]
        if missing or increased:
            detail = "、".join(
                f"{kind}:{baseline_counts.get(kind, '无基线')}→{final_counts.get(kind, 0)}"
                for kind in sorted(set(missing + increased)))
            return ("本轮新增 disabled/skipped/excluded，必须进入 KNOWN_FAILURES/"
                    f"SUSPECTED_BUGS，不能 PASS（{detail}）。")
        baseline_observed = _ut_observed_counts(
            str(baseline_call.get("result", "") or ""))
        if baseline_observed.get("total") is not None \
                and observed.get("total") is not None \
                and observed["total"] < baseline_observed["total"]:
            return ("终跑测试总数从存量基线 %d 降为 %d；不能通过删除/缩减"
                    "既有测试取得 PASS。"
                    % (baseline_observed["total"], observed["total"]))
    return ""


def _record_ut_receipts(task, report, tool_calls, require_baseline=False):
    """保存真实 AutoUT 与 UT 执行事实；后续仅修报告且代码未变时无需重做重活。"""
    cfg = _state_config()
    need = _required_skill(cfg.get("UT生成方式", ""))
    generator = _skill_call(tool_calls, need) if need else None
    executed = _flex_field(report, "EXECUTED_UT") or ""
    run = _reported_bash_call(tool_calls, executed)
    records = {}
    common = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "step": task.get("step", ""),
              "task_sha256": task.get("sha256", ""), "head": _git_head()}
    if task.get("standalone"):
        common["source_snapshot"] = _source_snapshot(task.get("head", ""))
    if generator and not _call_failed(generator):
        records["UT_GENERATOR"] = dict(common, value=cfg.get("UT生成方式", ""))
    reported_counts = _ut_report_counts(report)
    counts_complete = all(v is not None for v in reported_counts.values())
    if run and counts_complete and not _call_failed(run) and not _ut_execution_risk(
            report, run, cfg.get("UT运行命令", ""), tool_calls, require_baseline):
        actual = _reported_bash_segment(run, executed) or executed
        records["UT_RUN"] = dict(
            common, value=actual, reported_counts=reported_counts,
            result_sha256=hashlib.sha256(
                str(run.get("result", "") or "").encode(
                    "utf-8", errors="replace")).hexdigest())
    if not records:
        return
    try:
        data = _evidence_data()
        data.update(records)
        _save_evidence(data)
        _log("UT 执行凭证: " + "/".join(sorted(records)) + " @" + common["head"][:9])
    except Exception as e:
        _log("ut receipt EXC: " + str(e))


def _reusable_ut_receipt(key, task, expected=None):
    rec = _evidence_data().get(key, {})
    if not rec or rec.get("step") != task.get("step") \
            or rec.get("task_sha256") != task.get("sha256") \
            or (expected is not None and not _same_config(rec.get("value", ""), expected)):
        return None
    if task.get("standalone"):
        return rec if rec.get("source_snapshot") == _source_snapshot(task.get("head", "")) else None
    changed, err = _source_changed_since_receipt(
        rec.get("head", ""), _contract_state())
    return rec if not err and not changed else None


def _reusable_codecheck_build_receipt(task):
    """仅同任务卡、同步骤且源码未变化时复用；代码一变就必须重新编译。"""
    rec = _evidence_data().get("CODECHECK_BUILD", {})
    if not rec or rec.get("step") != task.get("step") \
            or rec.get("task_sha256") != task.get("sha256") \
            or not _same_config(rec.get("build", ""), _state_config().get("编译方式", "")):
        return None
    if task.get("standalone"):
        return rec if rec.get("source_snapshot") == _source_snapshot(task.get("head", "")) else None
    head = rec.get("head", "")
    if not head:
        return None
    st = _contract_state()
    changed, err = _source_changed_since_receipt(head, st)
    return rec if not err and not changed else None


def _reusable_codecheck_fullcheck_receipt(task, command_count, scan):
    rec = _evidence_data().get("CODECHECK_FULLCHECK", {})
    if not rec or rec.get("step") != task.get("step") \
            or rec.get("task_sha256") != task.get("sha256") \
            or rec.get("command_count") != int(command_count) \
            or rec.get("scan_count") != scan.get("count") \
            or rec.get("stock_excluded") != scan.get("stock_excluded"):
        return None
    counts = rec.get("raw_counts")
    if not isinstance(counts, list) \
            or not all(isinstance(x, int) and x >= 0 for x in counts) \
            or sum(counts) != rec.get("raw_total"):
        return None
    if rec.get("machine_counts_complete"):
        if len(counts) != int(command_count):
            return None
    else:
        if counts or not rec.get("result_hashes"):
            return None
    if task.get("standalone"):
        return rec if rec.get("source_snapshot") == _source_snapshot(
            task.get("head", "")) else None
    changed, err = _source_changed_since_receipt(
        rec.get("head", ""), _contract_state())
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
    paths += [p for p in _changed_paths_since(current)
              if p and not _unchanged_initial_dirty(p, st)]
    return [p for p in dict.fromkeys(paths) if _source_like(p)], ""


def _call_failed(call):
    if not call:
        return False
    if not call.get("result_seen"):
        # 没有 tool_result 就没有成功事实。standalone 没有 done 现场复核，兼容放行
        # 会直接把半截 transcript 当成功；旧宿主应走现有 accept-risk 显式裁决。
        return True
    if call.get("is_error"):
        return True
    # Skill 的 tool_result 是插件自定义协议：不同语言/不同版本可能返回
    # 自然语言、JSON 或摘要，其中出现 failed/error 并不等于宿主调用失败。
    # 这里只对 Bash 的进程语义做兜底识别；Skill 是否完成业务目标由
    # Agent 的统一结构化 Return format 判断。
    if str(call.get("name", "")).lower() != "bash":
        return False
    text = call.get("result", "") or ""
    return bool(re.search(
        r"(?:^|\n)\s*(?:(?:process|command)\s+)?exited?\s+with\s+(?:exit\s+)?code"
        r"\s*[:= ]\s*[1-9]\d*|"
        r"(?:^|\n)\s*(?:exit[_ ]code|return[_ ]?code|errorlevel)"
        r"\s*[:= ]\s*[1-9]\d*|"
        r"(?:^|\n)\s*(?:process|command)\s+failed\s+with\s+(?:exit\s+)?code"
        r"\s*[:= ]\s*[1-9]\d*|"
        r"returned\s+non-zero\s+exit\s+status\s+[1-9]\d*|"
        r"(?:exit(?:ed)?\s*(?:code|status)?|return\s*code)\s*[:= ]\s*[1-9]\d*",
        text, re.I))


def _skill_call(tool_calls, wanted):
    if not wanted:
        return None
    # 编译/生成 Skill 允许多轮修复；最终证据必须看最后一次匹配调用，
    # 与 Bash 证据一致。取首轮会把“先失败后成功”误拒，也可能忽略最终失败。
    for x in reversed(tool_calls or []):
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


def _bash_calls(tool_calls, expected):
    """按时间顺序返回命中目标命令的 Bash 调用及每次调用中的执行段数。"""
    want = re.sub(r"\s+", " ", (expected or "")).strip().lower()
    found = []
    if not want:
        return found
    for call in tool_calls or []:
        if str(call.get("name", "")).lower() != "bash":
            continue
        inp = call.get("input", {}) or {}
        command = inp.get("command", "") if isinstance(inp, dict) else str(inp)
        segments = re.split(r"&&|\|\||[;\n]", re.sub(r"\s+", " ", command).lower())
        count = sum(1 for seg in segments if seg.strip().startswith(want))
        if count:
            found.append((call, count))
    return found


def _bash_called(tool_calls, expected):
    return bool(_bash_call(tool_calls, expected))


def _require_bash_success(tool_calls, expected, bail, label):
    call = _bash_call(tool_calls, expected)
    if not call:
        bail(f"transcript 中没有真实执行配置的{label}命令；echo/文字提及不算执行。")
    if not call.get("result_seen"):
        bail(f"最后一次{label}命令缺少 tool_result，无法证明执行完成；"
             "请恢复完整 transcript，旧宿主无法提供时由用户走 accept-risk 裁决。")
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


def _path_fingerprint(path):
    h = hashlib.sha256()
    p = os.path.abspath(path)
    try:
        if os.path.isfile(p):
            h.update(b"file\0")
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
        elif os.path.isdir(p):
            h.update(b"dir\0")
            for name in sorted(os.listdir(p)):
                fp = os.path.join(p, name)
                stat = os.stat(fp)
                h.update((name + "\0" + str(stat.st_size) + "\0" + str(stat.st_mtime_ns)).encode(
                    "utf-8", errors="replace"))
        else:
            h.update(b"missing\0")
    except OSError as exc:
        h.update(("error:" + str(exc)).encode("utf-8", errors="replace"))
    return h.hexdigest()


def _unchanged_initial_dirty(path, st):
    rel = str(path or "").replace("\\", "/").strip().strip('"')
    initial = set((st or {}).get("initial_dirty", []) or [])
    fingerprints = (st or {}).get("initial_dirty_fingerprints", {}) or {}
    return bool(rel in initial and fingerprints.get(rel) == _path_fingerprint(rel))


def _source_snapshot(head):
    return {
        p: _path_fingerprint(p)
        for p in _changed_paths_since(head)
        if _source_like(p)
    }


_TEST_PAT = re.compile(r"(^|/)(tests?|__tests__|spec|[^/]+[_-]tests?)/|(^|/)src/test/|(^|/)test_[^/]+\.py$|"
                       r"(_test|\.test|\.spec)\.(c|cc|cpp|cxx|h|hh|hpp|hxx|inl|ipp|tpp|py|go|rs|js|jsx|ts|tsx)$|"
                       r"Tests?\.(c|cc|cpp|cxx|h|hh|hpp|hxx|java|kt|cs)$", re.I)
_SOURCE_EXT_PAT = re.compile(
    r"\.(c|cc|cpp|cxx|h|hh|hpp|hxx|inl|ipp|tpp|java|kt|kts|groovy|scala|py|pyi|"
    r"go|rs|cs|js|jsx|ts|tsx|vue|swift|m|mm|proto|sql|s|asm|cmake|gradle|sln|"
    r"vcxproj|props|targets|sh|bash|bat|cmd|ps1|mk|gn|gni|bzl)$", re.I)
_SOURCE_NAME_PAT = re.compile(
    r"^(CMakeLists\.txt|Makefile|GNUMakefile|pom\.xml|build\.gradle|settings\.gradle|"
    r"gradle\.properties|package\.json|package-lock\.json|pnpm-lock\.yaml|yarn\.lock|"
    r"Cargo\.toml|Cargo\.lock|go\.mod|go\.sum|meson\.build|build\.ninja)$", re.I)
_SOURCE_DIR_PAT = re.compile(r"(^|/)(service|src|include|lib|app|modules?)/", re.I)


def _source_like(path):
    """dispatch 侧源码判定，顺序与主状态机一致：文件名/扩展名 > 文档排除 > 目录/私有规则。"""
    p = str(path or "").replace("\\", "/").strip().strip("\"'")
    base = p.rsplit("/", 1)[-1]
    if _SOURCE_EXT_PAT.search(p) or _SOURCE_NAME_PAT.search(base):
        return True
    if re.search(r"\.(md|rst|adoc|txt)$", p, re.I):
        return False
    if _SOURCE_DIR_PAT.search(p):
        return True
    patterns = []
    value = _state_config().get("源码路径", [])
    patterns += ([x.strip() for x in value.split(",") if x.strip()]
                 if isinstance(value, str) else list(value or []))
    try:
        value = json.load(open(
            ".mae-flow-defaults.json", encoding="utf-8-sig")).get("源码路径", [])
        patterns += ([x.strip() for x in value.split(",") if x.strip()]
                     if isinstance(value, str) else list(value or []))
    except FileNotFoundError:
        pass
    except Exception as exc:
        _log("defaults 源码路径解析失败(已忽略,请修复该 JSON): %s" % exc)
    for pattern in patterns:
        try:
            if re.search(str(pattern), p, re.I):
                return True
        except re.error:
            continue
    return False


def _test_like(path):
    if _TEST_PAT.search(path):
        return True
    pats = []
    v = _state_config().get("测试路径", [])
    pats += [x.strip() for x in v.split(",") if x.strip()] if isinstance(v, str) else list(v or [])
    try:
        # utf-8-sig:团队手写 defaults 常带 BOM;strict 失败必须留痕,
        # 否则「测试路径」静默失效会让 gate 口径变宽而无人知晓。
        v = json.load(open(".mae-flow-defaults.json", encoding="utf-8-sig")).get("测试路径", [])
        pats += [x.strip() for x in v.split(",") if x.strip()] if isinstance(v, str) else list(v or [])
    except FileNotFoundError:
        pass
    except Exception as e:
        _log("defaults 测试路径 解析失败(已忽略,请修复该 JSON): %s" % e)
    for pat in pats:
        try:
            if re.search(pat, path, re.I):
                return True
        except re.error:
            continue
    return False


def _enforce_agent_scope(kind, task, bail):
    changed = [p for p in _changed_paths_since(task.get("head", "")) if _source_like(p)]
    if task.get("standalone"):
        initial = task.get("initial_source_fingerprints", {}) or {}
        # 独立任务允许用户带着未提交代码开始；只审计任务启动后真正发生变化的路径。
        changed = [p for p in changed if initial.get(p) != _path_fingerprint(p)]
    else:
        # 完整流程同样可能在 init 前已有未提交源码。它不属于本任务，且只在
        # 指纹仍与初始快照一致时豁免；本轮再次改动仍会进入越权审计。
        st = _contract_state()
        changed = [p for p in changed if not _unchanged_initial_dirty(p, st)]
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
        deleted = [p for p in changed if _test_like(p) and not os.path.exists(p)]
        if deleted:
            bail("ut-generator-agent 删除了既有测试文件: " + "、".join(deleted[:5])
                 + "；不能通过删测试取得 PASS。")
        bad = [p for p in changed if not _test_like(p)]
        if bad:
            bail("ut-generator-agent 修改了非测试源码: " + "、".join(bad[:5])
                 + "；源码缺陷必须先交用户裁决。")
    elif kind == "GRILL":
        if changed:
            bail("grill-critic-agent 是只读审查角色，却修改了文件: " + "、".join(changed[:5]))
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
    # FAIL 早退必须先于字段对账(与 compile/grill/UT 契约排序一致——校准实锤:
    # CLI 不可用时 agent 写不出真实 fullcheck 命令,旧排序逼诚实者编造字段)。
    if status == "FAIL":
        return   # FAIL 是诚实上报,不再苛求对账字段
    if not re.search(r"EXECUTED_COMMAND.*fullcheck", report, re.I):
        bail("必须包含 EXECUTED_COMMAND 字段且实际执行的是 fullcheck(用 increcheck 或未执行 = FAIL)。")
    nums = {}
    for k in ("FOUND", "FIXED", "REMAINING_COUNT"):
        mm = re.search(r"^\s*" + k + r":\s*(\d+)\s*$", report, re.M)
        if not mm:
            bail(f"缺少机器对账字段 {k}: <数字>。")
        nums[k] = int(mm.group(1))
    st = _contract_state()
    scan = (st.get("quality", {}) or {}).get("codecheck_scan", {})
    if scan.get("step") == st.get("current"):
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
    # 复验可能因 Windows 命令行长度限制拆成多批，且 harness 的首检会过滤
    # 本次修改行之外的存量告警。真实 CLI 原始数应为各批次之和，并与
    # “本单遗留 + 已识别存量”对拍，不能只看最后一批或拿 raw 对 scoped。
    command_count = len(scan.get("commands") or []) if scan.get("step") == st.get("current") else 1
    command_count = max(1, command_count)
    all_fullcheck_calls = _bash_calls(tool_calls, "codecheck fullcheck")
    selected, invocations = [], 0
    receipt = None
    real_counts = []
    result_hashes = []
    if all_fullcheck_calls:
        for call, count in reversed(all_fullcheck_calls):
            selected.append((call, count))
            invocations += count
            if invocations >= command_count:
                break
        if invocations < command_count:
            bail(f"最终一轮 CodeCheck 只找到 {invocations}/{command_count} 个 fullcheck 分批调用；"
                 "不能跳过前面批次后只拿最后一批收尾。")
        for call, count in reversed(selected):
            inp = call.get("input", {}) or {}
            raw_command = inp.get("command", "") if isinstance(inp, dict) else str(inp)
            if _command_swallows_failure(raw_command):
                bail("CodeCheck 命令使用了 || true / ; exit 0 等方式吞掉失败退出码。")
            if not call.get("result_seen"):
                bail("最终一轮 CodeCheck 分批调用缺少 tool_result，不能报告成功。")
            hits = _codecheck_counts_from_text(call.get("result"))
            # CodeCheckCLI 发现告警时可能返回非零码；可信机器计数比通用 Bash
            # 退出状态更能表达该工具是否完成。没有计数时仍按失败状态阻断。
            if _call_failed(call) and not hits:
                bail("最终一轮 CodeCheck 分批调用失败，且 tool_result 没有可验证的"
                     "告警计数，不能报告成功。")
            result_hashes.append(hashlib.sha256(
                str(call.get("result") or "").encode(
                    "utf-8", errors="replace")).hexdigest())
            real_counts.extend(hits[-count:])
        if len(real_counts) < command_count:
            _record_codecheck_fullcheck_receipt(
                task, command_count, [], scan,
                result_hashes=result_hashes)
    elif soft:
        receipt = _reusable_codecheck_fullcheck_receipt(
            task, command_count, scan)
        if receipt:
            real_counts = list(receipt.get("raw_counts") or [])
            _log("CODECHECK 重答复用完整 fullcheck 凭证 @"
                 + receipt.get("head", "")[:9])
    if not all_fullcheck_calls and not receipt:
        bail("transcript 中没有完整执行本轮 CodeCheck fullcheck，且没有同任务卡、"
             "同源码版本、同分批口径的可复用机器凭证。")
    if len(real_counts) >= command_count:
        real_counts = real_counts[-command_count:]
        real_raw = sum(real_counts)
        stock = scan.get("stock_excluded")
        expected_raw = nums["REMAINING_COUNT"] + stock if isinstance(stock, int) \
            else nums["REMAINING_COUNT"]
        if real_raw != expected_raw:
            bail(f"真实 fullcheck 最终 {command_count} 批合计 {real_raw} 条告警，"
                 f"但本单遗留({nums['REMAINING_COUNT']})"
                 + (f"+存量过滤({stock})={expected_raw}" if isinstance(stock, int)
                    else f"={expected_raw}")
                 + "；复验摘录不能自说自话，修完或如实上报后重答。")
        if all_fullcheck_calls:
            _record_codecheck_fullcheck_receipt(
                task, command_count, real_counts, scan, expected_raw,
                result_hashes=result_hashes)
    if nums["FIXED"] > 0:
        build = _field(report, "EXECUTED_BUILD")
        build_cfg = _state_config().get("编译方式", "")
        current_call = _codecheck_build_call(tool_calls, build_cfg)
        reused = _reusable_codecheck_build_receipt(task) if soft and not current_call else None
        if current_call:
            # 工具调用是事实，字段只是摘要；不因摘要写成“无需”等小格式问题重跑长编译。
            if not _build_summary_matches(build, build_cfg):
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
                call = _build_call(tool_calls, build_cfg)
                if call and _call_failed(call):
                    bail("配置的编译命令明确失败，不能把本轮修复计为已编译。")
                bail("本轮 transcript 中没有成功执行配置的编译命令，"
                     "也没有同任务卡、同源码版本的可复用编译凭证。")
    # 与复验摘录对账:契约要求附「共有 N 条告警」原文,取最后一处(复验)与 REMAINING_COUNT 比对
    ex = re.findall(r"共有\s*(\d+)\s*条告警", report)
    stock = scan.get("stock_excluded")
    excerpt_expected = nums["REMAINING_COUNT"] + stock if isinstance(stock, int) \
        else nums["REMAINING_COUNT"]
    excerpt_actual = (
        sum(int(x) for x in ex[-command_count:])
        if command_count > 1 and len(ex) >= command_count
        else int(ex[-1]) if ex else None)
    if excerpt_actual is not None and excerpt_actual != excerpt_expected:
        bail(f"复验摘录合计 {excerpt_actual} 条告警与真实对账口径"
             f"（本单遗留 {nums['REMAINING_COUNT']}"
             + (f" + 存量 {stock}" if isinstance(stock, int) else "")
             + f" = {excerpt_expected}）矛盾。")


def _ut_contract(status, report, tool_calls=None, soft=False):
    def bail(msg):
        _contract_bail("UT", msg, soft)

    task = _task_card_contract("UT", report, soft)
    changed = _enforce_agent_scope("UT", task, bail)
    if status not in ("PASS", "NEEDS_INPUT", "FAIL"):
        bail("未知结果状态 " + status)
    if status != "PASS":
        return
    cfg = _state_config()
    need = _required_skill(cfg.get("UT生成方式", ""))
    require_baseline = bool(changed)
    _record_ut_receipts(task, report, tool_calls, require_baseline)
    if need:
        call = _skill_call(tool_calls, need)
        reused = _reusable_ut_receipt("UT_GENERATOR", task, cfg.get("UT生成方式", "")) \
            if soft and not call else None
        if call and _call_failed(call):
            bail(f"{need} Skill 的工具结果明确失败，不能报告 PASS。")
        if not call and not reused:
            bail(f"UT 配置要求 {need} Skill，但 transcript 中没有成功调用，"
                 "也没有同任务卡、同源码版本的可复用生成凭证。"
                 "若宿主确实未暴露子会话工具调用，主会话应展示风险并使用 accept-risk，"
                 "不要重启长任务形成循环。")
        label = _flex_field(report, "GENERATOR_USED") or ""
        if call and not _same_config(label, cfg.get("UT生成方式", "")):
            _log("UT GENERATOR_USED 摘要不准确,以 transcript 的真实 Skill 调用为准")
    elif not _same_config(_flex_field(report, "GENERATOR_USED") or "", cfg.get("UT生成方式", "")):
        bail("GENERATOR_USED 与任务卡的 UT生成方式不一致。")

    configured_ut = cfg.get("UT运行命令", "")
    executed_ut = _flex_field(report, "EXECUTED_UT") or ""
    if not executed_ut:
        bail("PASS 报告缺少 EXECUTED_UT: <实际执行的 UT 命令>。")
    run = _reported_bash_call(tool_calls, executed_ut)
    reused_run = _reusable_ut_receipt("UT_RUN", task) if soft and not run else None
    if run:
        risk = _ut_execution_risk(
            report, run, configured_ut, tool_calls, require_baseline)
        if risk:
            bail(risk)
    elif reused_run:
        # 报告重答可以免跑长 UT，但不能借复用凭证改写数字。凭证记录的是
        # 首次真实输出已校验过的三数，并绑定任务卡、步骤和源码版本。
        bound = reused_run.get("reported_counts", {}) or {}
        current = _ut_report_counts(report)
        if bound and current != bound:
            bail("报告重答的 TESTS_TOTAL/PASSED/FAILED 与已绑定的真实执行凭证不一致；"
                 "只修格式不得改写测试事实。")
    if run and _call_failed(run):
        bail("UT运行命令的工具结果明确失败，不能报告 PASS。")
    if not run and not reused_run:
        bail("EXECUTED_UT 未对应到 transcript 中真实执行成功的 Bash 命令，"
             "也没有同任务卡、同源码版本的可复用测试凭证。")

    for name in ("PENDING_QUESTIONS", "KNOWN_FAILURES", "SUSPECTED_BUGS"):
        value = _flex_field(report, name)
        if value is None:
            continue   # 真正全绿时省略空字段不值得打回；上面的风险扫描负责防隐藏失败
        if not _empty_section(value):
            bail(f"标记 PASS 但 {name} 非空；必须先交主会话和用户处理，不能带问题过关。")
    coverage = _flex_field(report, "AC_COVERAGE")
    if coverage is None or not coverage.strip() or _empty_section(coverage):
        bail("PASS 报告缺少有效的 AC_COVERAGE 验收场景对照。")
    # 否定/零值形态先洗白(校准实锤:诚实的「无未覆盖场景」「缺口: 0」曾被
    # 子串误命中打回——门禁不能逼诚实措辞改口;同 disabled/skipped 的既有模式)
    cleaned = re.sub(r"无\s*(?:未覆盖|缺口|无对应)(?:场景|项)?"
                     r"|(?:缺口|未覆盖|无对应)\s*[:：]?\s*(?:0|无|零)\b",
                     "", coverage)
    if re.search(r"缺口|未覆盖|无对应", cleaned):
        bail("AC_COVERAGE 仍有验收缺口，不能报告 PASS(若只是措辞请改写为"
             "正向表述;若为事实缺口按契约用 NEEDS_INPUT/缺口标注上报)。")
    # 校准实锤:AC_COVERAGE 需至少一行"条目 → 用例名"映射,纯声明式单行
    # (「全部已覆盖」)不算对照——UT agent 的存在目的是逐条映射,不是背书。
    if not re.search(r"(->|→|=>)", coverage):
        bail("AC_COVERAGE 必须是「EARS 条目 → 对应测试用例名」的逐行映射"
             "(至少一行含 → 分隔),而非一句『全部已覆盖』的声明。")
    nums = {}
    for name in ("TESTS_TOTAL", "TESTS_PASSED", "TESTS_FAILED"):
        value = _number_field(report, name)
        if value is None:
            bail(f"PASS 报告缺少 {name}: <数字>。")
        nums[name] = value
    if nums["TESTS_FAILED"] != 0 or nums["TESTS_TOTAL"] != nums["TESTS_PASSED"]:
        bail("UT 数字对账不通过：PASS 必须 TESTS_FAILED=0 且 TOTAL=PASSED。")
    # 校准实锤:0 条测试的空跑不是 PASS——UT agent 跑出零用例还报通过违反
    # 其存在目的(ctest "No tests were found" + 0/0/0 恒等式曾放行)。
    if nums["TESTS_TOTAL"] < 1:
        bail("UT PASS 要求至少运行 1 个测试(TESTS_TOTAL>=1);0 条=空跑,"
             "不能证明任何回归保证。收口批跑全量,真实仓库恒成立。")


def _grill_contract(status, report, tool_calls=None, soft=False):
    """Grill critic 只做遗漏审查；GAPS 是有效产出，不因发现问题被当成执行失败。"""
    def bail(msg):
        _contract_bail("GRILL", msg, soft)

    task = _task_card_contract("GRILL", report, soft)
    _enforce_agent_scope("GRILL", task, bail)
    if status not in ("CLEAR", "GAPS", "FAIL"):
        bail("未知结果状态 " + status + "；只能是 CLEAR/GAPS/FAIL。")
    if status == "FAIL":
        return
    # 校准实锤:grill 的唯一价值是"真读过材料后说没遗漏",而 CLEAR/GAPS 令牌
    # 曾零阅读即发(tool_calls 传入却完全没用)——一个一轮未读、直接输出样板的
    # agent 与认真审查者在门禁眼中无差别。要求至少一次成功的只读检索;transcript
    # 完全无 tool_use 块的老宿主场景沿用既有话术(展示风险+accept-risk),不新增死锁。
    calls = tool_calls or []
    read_ok = any(str(c.get("name", "")).lower() in ("read", "grep", "glob")
                  and c.get("result_seen") and not c.get("is_error")
                  for c in calls)
    if not read_ok:
        bail("grill critic 报 %s 但 transcript 无任何成功的 Read/Grep/Glob "
             "调用——'没有遗漏'的结论必须建立在真读过需求/代码材料之上,"
             "而非样板输出。若宿主确未暴露子会话工具调用,主会话展示风险后"
             "用 accept-risk grill。" % status)
    stage = _flex_field(report, "STAGE") or ""
    if stage.lower() != str(task.get("stage", "")).lower():
        bail("STAGE 与任务卡的质询检查阶段不一致。")
    count = _number_field(report, "GAPS_FOUND")
    if count is None:
        bail("缺少 GAPS_FOUND: <数字>。")
    if status == "CLEAR" and count != 0:
        bail("标记 CLEAR 但 GAPS_FOUND 不是 0。")
    if status == "GAPS" and count == 0:
        bail("标记 GAPS 但 GAPS_FOUND=0。")
    branches = _flex_field(report, "MISSING_BRANCHES")
    if status == "GAPS" and (branches is None or _empty_section(branches)):
        bail("发现遗漏时必须在 MISSING_BRANCHES 中列出可继续追问的决策分支。")


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
            if len(p) == 3 and p[0].isdigit() and p[1].isdigit() and _source_like(p[2]):
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
    if not _build_summary_matches(_field(report, "EXECUTED_BUILD"), build_cfg):
        bail("EXECUTED_BUILD 与配置确认的编译方式不一致,禁止自行猜测或替换编译命令。")
    need = _required_skill(build_cfg)
    if need:
        call = _skill_call(tool_calls, need)
        if not call:
            bail(f"编译配置要求 {need} Skill,但 transcript 中没有对应 Skill 工具调用。")
        # BLOCKED 的定义就是"修复上限内仍编译不过"——最后一次调用失败正是
        # BLOCKED 的证明而非反证。校准实锤:成功性检查曾把诚实 BLOCKED 结构性
        # 打回,形成重派整只 agent 的死循环。BLOCKED+零 error 的矛盾由下方
        # BUILD_ERRORS 对账兜住,此豁免不放宽任何造假面。
        if status != "BLOCKED" and _call_failed(call):
            bail(f"{need} Skill 的工具结果明确失败，不能报告编译成功。")
    else:
        expected = _embedded_build_command(build_cfg) or build_cfg
        if status != "BLOCKED":
            _require_bash_success(tool_calls, expected, bail, "编译")
        else:
            # BLOCKED 仍须证明真跑过编译(防空口弃权),只豁免"必须成功"
            if not _bash_call(tool_calls, expected):
                bail("标记 BLOCKED 但 transcript 中没有配置编译命令的真实调用"
                     "——弃权也必须先真实尝试过编译。")
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
    tool = d.get("tool_name")
    if tool in ("Write", "Edit", "MultiEdit"):
        ti = d.get("tool_input") or {}
        p = ti.get("file_path", "") or ti.get("path", "") or ""
        if p:
            _record_agent_write(p)
    # 真实用户问答的事件令牌:AskUserQuestion 工具真被调用过才有——
    # "确认发生过"从此是 harness 签发的事实,不是模型可书写的文本
    if tool == "AskUserQuestion":
        _capture_usermsg(_text_of(d.get("tool_response")))   # 应答原文进 ack 验真存储
        _record_agent_token("ASKUSER", "CONFIRMED")
        sys.exit(0)
    if tool == "Bash":
        _maybe_utrun(d)
        sys.exit(0)
    p = ((d.get("tool_input") or {}).get("file_path", "") or "").replace("\\", "/")
    hit = None
    for pat, tf, label in ((r"docs/story/STORY-.*\.md$", "STORY-TEMPLATE.md", "STORY"),
                           (r"docs/chain/CHAIN-.*\.md$", "CHAIN-TEMPLATE.md", "CHAIN"),
                           (r"(^|/)\.mae-flow-work/(?:\S+/)*grill-prep[^/]*\.md$", "GRILL-PREP-TEMPLATE.md", "GRILL-PREP"),
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


def ev_stop(d):
    """月光宝盒未到安全停点时，阻止主 Agent 提前结束。

    Stop Hook 只补“主模型自行收工”这一处硬洞。真实硬阻塞必须先用 moonlight blocked 留痕；
    push 失败则由 push-failed 留痕。stop_hook_active 时放行，避免宿主递归触发形成死循环。
    """
    try:
        st = json.load(open(STATE, encoding="utf-8"))
    except Exception:
        sys.exit(0)
    ml = st.get("moonlight") or {}
    if not ml.get("enabled"):
        sys.exit(0)
    sid = st.get("current", "")
    unresolved = [x for x in (ml.get("issues") or []) if not x.get("resolved_at")]
    safe = (
        sid in ("moonlight_review", "end")
        or bool(ml.get("hard_blocked"))
        or (sid == "push" and any(x.get("kind") == "push" for x in unresolved))
    )
    if safe:
        sys.exit(0)
    # 反收工护栏必须是「无进展计数」而不是「链级一发」:Claude Code 的 stop_hook_active
    # 在同一延续链里一直为 true,夜里没有用户消息复位它——旧写法第一次打回后,
    # 后续任何一次自然收尾都被放行,整夜保护恰好等于一段续命(静默白夜)。
    # 现在:状态 revision 有推进就继续拦(干活的 Agent 拦到安全停点为止);
    # 连续 3 次零进展才 fail-open(真卡死的 Agent 不会被无限打回)。
    revision = int(st.get("revision", 0) or 0)
    guard_path = STATE + ".stop-guard"
    guard = {}
    try:
        guard = json.load(open(guard_path, encoding="utf-8"))
    except Exception:
        guard = {}
    if d.get("stop_hook_active"):
        if int(guard.get("revision", -1) or -1) == revision:
            blocks = int(guard.get("blocks", 0) or 0) + 1
        else:
            blocks = 1   # 上次打回后状态推进过:重新计数,继续拦
        if blocks > 3:
            _log("stop guard: revision=%s 连续 %s 次零进展,fail-open 放行(防死循环)"
                 % (revision, blocks - 1))
            sys.exit(0)
    else:
        blocks = 1
    try:
        atomic_write_json(guard_path, {
            "revision": revision, "blocks": blocks,
            "at": time.strftime("%Y-%m-%d %H:%M:%S")})
    except Exception:
        # 护栏自身写不进时退回旧行为(放行),不能让护栏故障卡死会话
        _log("stop guard write failed — allow")
        sys.exit(0)
    print("[mae-flow] 月光宝盒仍在执行，当前步骤 %s，禁止提前结束回复或等待用户。"
          "继续执行 mae-flow current 给出的动作；质量问题尽力后用 moonlight defer，"
          "确实缺少需求/权限/外部条件而无法继续时用 moonlight blocked --reason 留痕后再停止。"
          % (sid or "未知"), file=sys.stderr)
    sys.exit(2)


def main():
    ev = sys.argv[1] if len(sys.argv) > 1 else ""
    _arm_watchdog()
    _log("start " + ev)
    rc = 0
    try:
        d = read_input()
        _chdir_root(d)
        runtime = resolve_runtime(os.getcwd())
        if runtime.has_conflict:
            _log("runtime conflict: " + ",".join(runtime.conflicts))
            if ev in ("userprompt", "sessionstart"):
                print("[mae-flow] ⚠ 检测到流程状态冲突：%s。完整流程继续作为唯一控制源；"
                      "请执行 mae-flow doctor 查看并清理陈旧独立任务。"
                      % "、".join(runtime.conflicts))
        action_active = runtime.mode == RuntimeMode.STANDALONE
        if runtime.mode == RuntimeMode.CORRUPT:
            _log("runtime corrupt: " + ";".join(runtime.errors))
            if ev in ("userprompt", "sessionstart") and _session_notice_due("corrupt", d, ev):
                if os.path.isfile(STATE):
                    print("[mae-flow] ⚠ 完整流程状态损坏，Hook 已按 fail-open 放行普通开发。"
                          "发送 `/mae-flow exit` 可保存坏现场并解除流程；不要手删状态。")
                elif os.path.isfile(ACTION_STATE):
                    print("[mae-flow] ⚠ 独立任务状态损坏，Hook 已按 fail-open 放行普通开发。"
                          "执行 `mae-flow action cancel` 可保存坏现场并清理控制指针。")
                else:
                    print("[mae-flow] ⚠ 退出标记损坏，Hook 已按 fail-open 放行普通开发。"
                          "执行 `mae-flow doctor` 查看现场；不要直接删除文件。")
                # 保留损坏主状态下的一键退出通道；status 失败不会阻止普通对话。
                if os.path.isfile(STATE):
                    ev_inject(d, session_start=(ev == "sessionstart"))
            rc = 0
        elif action_active and ev == "pretooluse":
            ev_action_pretooluse(d)
        elif action_active and ev == "subagentstop":
            ev_subagentstop(d)
        elif action_active and ev in ("userprompt", "sessionstart"):
            # 退出过完整流程后仍会保留 EXIT_STATE；独立任务是用户此刻的新意图，
            # 状态注入必须优先于旧的“普通开发模式”提示，否则主 Agent 会丢失单项任务上下文。
            ev_inject(d, session_start=(ev == "sessionstart"))
        elif runtime.mode == RuntimeMode.DIRECT:
            # 用户已明确退出：MAE-FLOW 完整让出控制权。不能只跳过源码 gate 而继续发令牌/注入步骤，
            # 否则会形成“表面直接开发，后台仍在推进旧流程”的半退出状态。
            if ev in ("userprompt", "sessionstart"):
                if ev == "userprompt":
                    _capture_direct_prompt(d.get("prompt") or "")
                if _session_notice_due("direct", d, ev):
                    print("[mae-flow] 本项目已退出交付流程，按用户的普通开发请求执行；"
                          "不要运行 current/done，也不要自行重新进入。只有用户明确要求重新接回原流程时才 init。")
            _log("direct mode: bypass " + ev)
            rc = 0
        elif runtime.mode == RuntimeMode.INACTIVE and ev in (
                "pretooluse", "posttooluse", "subagentstop", "stop"):
            # 安装插件不等于启用工作流。没有在途状态时，任何工具调用都必须完整旁路；
            # 否则全局插件 Hook 会让从未使用 mae-flow 的普通项目也无法修改源码。
            # SessionStart/UserPromptSubmit 仍保留轻量发现入口与显式月光宝盒意图捕获，
            # init 成功创建 STATE 后，下一次工具调用才开始受门禁约束。
            _log("inactive: bypass " + ev)
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
        elif ev == "stop":
            ev_stop(d)
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 0
    except Exception as e:
        _log("EXC %s: %s" % (type(e).__name__, e))
        rc = 0   # fail-open:hook 自身异常不阻塞正常工作
    _log("end %s rc=%s %dms" % (ev, rc, int((time.time() - _T0) * 1000)))
    if _STDIN_THREAD is not None and _STDIN_THREAD.is_alive():
        # stdin 读线程仍阻塞在 BufferedReader 上并持有其锁:正常 sys.exit 的解释器
        # 收尾去 flush/close 标准流会争锁失败,触发 "Fatal Python error" 并以 134 退出
        # (逻辑 rc 被吞、stderr 喷 abort、看门狗此时已失效)。flush 后直接 os._exit,
        # 保住真实退出码——这正是"宿主不关 stdin"兜底场景自身的兜底。
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(rc if isinstance(rc, int) else 0)
    sys.exit(rc)


if __name__ == "__main__":
    main()
