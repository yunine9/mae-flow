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
import glob, json, os, re, subprocess, sys, tempfile, threading, time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
MAEFLOW = os.path.join(HERE, "..", "scripts", "mae-flow.py")
STATE = ".mae-flow.json"
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
    以 hook JSON 的 cwd 为基准向上找 .mae-flow.json 并 chdir;
    找不到则退回 JSON cwd(init 之前属正常)。mae-flow 自身还会再定位一次,双保险。"""
    base = d.get("cwd") or os.getcwd()
    probe = os.path.abspath(base)
    while True:
        if os.path.exists(os.path.join(probe, STATE)):
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
        # 用户消息原文进 ack 验真存储(payload 无 prompt 字段的 harness 上存储恒空,验真自动降级)
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
    prompt = users[0] if users else ""
    last = (asst[-1] if asst else "").strip()
    # 契约要求标记在第一行:只看首行,不用 re.M(埋在中间不算)
    first_line = last.splitlines()[0] if last else ""
    # 标记本身即身份证明:凡以合法契约标记收尾的 agent,直接验契约+发令牌,
    # 不依赖启动 prompt 的措辞(主模型派发时未必写 agent 文件名——已实际踩过)
    m = re.match(r"^(ENV|UT|CODECHECK|STORY|GRILL|COMPILE)_RESULT:\s*(\S+)", first_line)
    if m:
        if m.group(1) == "CODECHECK":
            _codecheck_contract(m.group(2), last, soft=retry)
        if m.group(1) == "COMPILE":
            _compile_contract(m.group(2), last, soft=retry)
        _record_agent_token(m.group(1))
        sys.exit(0)
    if retry:
        _autopsy(tp, asst)   # 留档(不进 stderr:此路径 exit 0,别被 harness 当 hook error 展示)
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


def _record_agent_token(kind):
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
        d[kind] = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "head": head}
        tmp = p + ".tmp"
        open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False))
        os.replace(tmp, p)
        _log("agent token: %s @%s" % (kind, head[:9] or "no-git"))
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
        msgs.append({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "text": text[:2000]})
        msgs = msgs[-10:]
        tmp = p + ".tmp"
        open(tmp, "w", encoding="utf-8").write(json.dumps(msgs, ensure_ascii=False))
        os.replace(tmp, p)
    except Exception as e:
        _log("usermsg EXC: %s" % e)


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
            _record_agent_token("UTRUN")
    except Exception as e:
        _log("utrun EXC: %s" % e)


def _codecheck_contract(status, report, soft=False):
    """codecheck 报告的硬校验:fullcheck 实际执行 + 三数对账(FOUND=FIXED+REMAINING_COUNT)。
    遗漏告警最常见的形态是马虎吞掉,算术对不上当场打回;CLEAN 必须遗留为 0。
    soft=重答路径:违规不再 exit 2(防死循环),但直接 exit 0 不发令牌,由 done 的 agent_ran 拦截。"""
    def bail(msg):
        if soft:
            _log("codecheck 重答仍违规: " + msg)
            sys.exit(0)
        print("[mae-flow] codecheck 契约违规:" + msg
              + " 请重新真实执行并按 Return format 输出完整报告(含 FOUND/FIXED/REMAINING_COUNT 三行)。",
              file=sys.stderr)
        sys.exit(2)

    if not re.search(r"EXECUTED_COMMAND.*fullcheck", report, re.I):
        bail("必须包含 EXECUTED_COMMAND 字段且实际执行的是 fullcheck(用 increcheck 或未执行 = FAIL)。")
    if status == "FAIL":
        return   # FAIL 是诚实上报,不再苛求对账字段
    nums = {}
    for k in ("FOUND", "FIXED", "REMAINING_COUNT"):
        mm = re.search(r"^\s*" + k + r":\s*(\d+)\s*$", report, re.M)
        if not mm:
            bail(f"缺少机器对账字段 {k}: <数字>。")
        nums[k] = int(mm.group(1))
    if nums["FOUND"] != nums["FIXED"] + nums["REMAINING_COUNT"]:
        bail(f"对账不平:FOUND({nums['FOUND']}) != FIXED({nums['FIXED']}) + REMAINING_COUNT({nums['REMAINING_COUNT']})"
             ",有告警被吞掉或数字失实。")
    if status == "CLEAN" and nums["REMAINING_COUNT"] != 0:
        bail(f"标记 CLEAN 但 REMAINING_COUNT={nums['REMAINING_COUNT']},自相矛盾。")
    if status == "REMAINING" and nums["REMAINING_COUNT"] == 0:
        bail("标记 REMAINING 但 REMAINING_COUNT=0,自相矛盾。")
    # 与复验摘录对账:契约要求附「共有 N 条告警」原文,取最后一处(复验)与 REMAINING_COUNT 比对
    ex = re.findall(r"共有\s*(\d+)\s*条告警", report)
    if ex and int(ex[-1]) != nums["REMAINING_COUNT"]:
        bail(f"REMAINING_COUNT({nums['REMAINING_COUNT']})与复验摘录『共有 {ex[-1]} 条告警』矛盾——遗留数必须原样取自复验输出。")


def _git_out(cmd):
    """dispatch 内轻量 git 调用(编码/超时按军规)。失败返回空串,调用方按'不可算'处理。"""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=8)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def _compile_net_lines():
    """编译修复的净行数,git 亲算(agent 报数不作数):
    未提交改动 + 自 HEAD 回溯的连续「修复编译」commit,只统计代码文件。
    这是防掏空的机器不变量:删代码换编译通过,在这里得不了分。"""
    exts = (".c", ".cc", ".cpp", ".h", ".hpp", ".java")

    def net_of(out):
        n = 0
        for line in out.splitlines():
            p = line.split("\t")
            if len(p) == 3 and p[0].isdigit() and p[1].isdigit() and p[2].lower().endswith(exts):
                n += int(p[0]) - int(p[1])
        return n

    total = net_of(_git_out("git -c core.quotepath=false diff --numstat"))
    for depth in range(10):
        subj = _git_out(f"git log -1 --skip={depth} --pretty=%s").strip()
        if "修复编译" not in subj:
            break
        total += net_of(_git_out(f"git -c core.quotepath=false show --numstat --pretty=format: HEAD~{depth}"))
    return total


def _compile_contract(status, report, soft=False):
    """编译 agent 收尾硬校验:格式对账(OK⇔零error)+ 净产出不变量(numstat 亲算防掏空)。
    优雅三件套之硬层:作弊(删代码换通过)从'被禁止'变'得不了分'。"""
    def bail(msg):
        if soft:
            _log("compile 重答仍违规: " + msg)
            sys.exit(0)
        print("[mae-flow] 编译契约违规:" + msg
              + " 请按契约 Return format 重新真实收尾(EXECUTED_BUILD/BUILD_ERRORS 必填)。", file=sys.stderr)
        sys.exit(2)

    if status == "FAIL":
        return   # 诚实上报工具/配置问题,不苛求对账
    if not re.search(r"EXECUTED_BUILD", report):
        bail("必须包含 EXECUTED_BUILD(实际执行的编译方式与输出摘录)。")
    m = re.search(r"^\s*BUILD_ERRORS:\s*(\d+)", report, re.M)
    if not m:
        bail("缺少 BUILD_ERRORS: <数字>(最终一次编译的 error 数)。")
    n = int(m.group(1))
    if status == "OK" and n != 0:
        bail(f"标记 OK 但 BUILD_ERRORS={n},自相矛盾。")
    if status == "BLOCKED" and n == 0:
        bail("标记 BLOCKED 但 BUILD_ERRORS=0,自相矛盾(编译已过应报 OK)。")
    net = _compile_net_lines()
    if net < 0 and "SHRINK_EXEMPT" not in report:
        bail(f"代码净删 {-net} 行(git 亲算:未提交+修复编译 commit)且无 SHRINK_EXEMPT 声明——"
             "禁止删代码/注释代码换编译通过;确属合理精简须逐项声明并接受下游评审复核。")


def ev_posttooluse(d):
    # 真实用户问答的事件令牌:AskUserQuestion 工具真被调用过才有——
    # "确认发生过"从此是 harness 签发的事实,不是模型可书写的文本
    if d.get("tool_name") == "AskUserQuestion":
        _capture_usermsg(_text_of(d.get("tool_response")))   # 应答原文进 ack 验真存储
        _record_agent_token("ASKUSER")
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
        if ev == "pretooluse":
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
