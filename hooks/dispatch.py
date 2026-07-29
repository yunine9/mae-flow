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
    atomic_write_json,
    find_project_root,
    resolve_runtime,
)
from mae_flow_core.file_io import load_json, read_lines, read_text, write_text
from mae_flow_core.application.hooks.task_cards import (
    TaskCardPorts as _TaskCardPorts,
    verify_dispatch_task as _verify_dispatch_task,
)
from mae_flow_core.application.hooks.agent_completion import (
    AgentCompletionPorts as _AgentCompletionPorts,
    handle_agent_completion as _handle_agent_completion,
)
from mae_flow_core.application.hooks.models import (
    HookResponse as _HookResponse,
)
from mae_flow_core.application.hooks.event_policies import (
    stop_decision as _stop_decision,
    template_decision as _template_decision,
)
from mae_flow_core.application.hooks.events import (
    handle_hook_event as _handle_hook_event,
)
from mae_flow_core.adapters.hook_events import HookEventAdapter
from mae_flow_core.adapters.hook_runtime import HookRuntimeAdapter

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
        write_text(marker, "")
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


_HOOK_RUNTIME = None
_MOVED_RUNTIME_NAMES = frozenset(["_git_head","_flow_task_for_token","_flow_token_source_snapshot","_record_agent_token","_text_of","_record_agent_write","_capture_usermsg","_explicit_exit_prompt","_explicit_flow_start_prompt","_capture_exit_intent","_capture_moonlight_intent","_capture_direct_prompt","_maybe_utrun","_load_action","_contract_state","_codecheck_log_state","_codecheck_log_event","_git_trace","_tool_trace_summary","_record_codecheck_agent_trace","_evidence_data","_save_evidence","_record_rejection","_clear_rejection","_contract_bail","_tool_call_values","_contract_context","_task_card_contract","_state_config","_field","_flex_field","_number_field","_same_config","_required_skill","_embedded_build_command","_build_call","_build_summary_matches","_codecheck_build_call","_receipt_context","_record_codecheck_build_receipt","_record_codecheck_fullcheck_receipt","_record_ut_receipts","_reuse_source_facts","_reusable_ut_receipt","_reusable_codecheck_build_receipt","_reusable_codecheck_fullcheck_receipt","_source_changed_since_receipt","_call_failed","_skill_call","_skill_called","_bash_call","_bash_calls","_bash_called","_require_bash_success","_section","_empty_section","_changed_paths_since","_path_fingerprint","_review_path_fingerprint","_unchanged_initial_dirty","_source_snapshot","_source_like","_test_like","_enforce_agent_scope","_codecheck_contract","_ac_coverage_has_mapping","_ut_contract","_grill_contract","_git_out","_compile_net_lines","_compile_agent_net","_compile_contract"])


def _runtime_adapter():
    global _HOOK_RUNTIME
    if _HOOK_RUNTIME is None:
        _HOOK_RUNTIME = HookRuntimeAdapter(
            state=STATE, exit_state=EXIT_STATE, action_state=ACTION_STATE,
            rejection_state=REJECTION_STATE, evidence_state=EVIDENCE_STATE,
            agent_writes_state=AGENT_WRITES_STATE,
            moonlight_intent=MOONLIGHT_INTENT, exit_intent=EXIT_INTENT,
            maeflow=MAEFLOW, log=_log,
            task_card_ports_factory=lambda: _task_card_ports())
    _HOOK_RUNTIME.STATE = STATE
    _HOOK_RUNTIME.EXIT_STATE = EXIT_STATE
    _HOOK_RUNTIME.ACTION_STATE = ACTION_STATE
    _HOOK_RUNTIME.input_encoding = _INPUT_ENCODING
    return _HOOK_RUNTIME


def __getattr__(name):
    if name in _MOVED_RUNTIME_NAMES:
        return getattr(_runtime_adapter(), name)
    raise AttributeError(name)


def _task_card_ports():
    return _TaskCardPorts(
        read_text=read_text,
        current_head=_runtime_adapter()._git_head,
        merge_base=lambda head, _current: _runtime_adapter()._git_out(
            f"git merge-base {head} HEAD").strip(),
        changed_paths_since=_runtime_adapter()._changed_paths_since,
        source_changed_since=_runtime_adapter()._source_changed_since_receipt,
        source_snapshot=_runtime_adapter()._source_snapshot,
        path_fingerprint=_runtime_adapter()._path_fingerprint,
        review_path_fingerprint=_runtime_adapter()._review_path_fingerprint,
        source_like=_runtime_adapter()._source_like,
        test_like=_runtime_adapter()._test_like,
        path_exists=os.path.exists,
        script_path=lambda: os.path.abspath(MAEFLOW),
    )


def _gate_agent_dispatch(ti):
    """质量 agent 派发前验任务卡——拦截时机 = 错误发生时机。

    卡缺失/过期若留到 SubagentStop/done 才发现,代价是整只 agent 上百轮白跑;
    在派发这一刻拦下,损失只有一次工具调用。完整流程与独立任务统一从
    _runtime_adapter()._contract_state 取任务卡；识别不到或状态读不了一律放行(fail-open)。"""
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
        st = _runtime_adapter()._contract_state()
        decision = _verify_dispatch_task(kind, st, _task_card_ports())
        if not decision.accepted:
            print(decision.reason, file=sys.stderr)
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
            st = load_json(STATE)
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
        _runtime_adapter()._capture_moonlight_intent(prompt)
        _runtime_adapter()._capture_usermsg(prompt)
        exit_intent = _runtime_adapter()._capture_exit_intent(prompt)
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
        action = _runtime_adapter()._load_action()
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
                  f"或敲 /mae-flow:mae-flow;新手指南敲 /mae-flow:mae-flow help。"
                  f"(流程脚本: python \"{me}\";"
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


def _latest_subagent_transcript(main_path):
    stem = os.path.splitext(main_path)[0]
    candidates = glob.glob(
        os.path.join(stem, "subagents", "agent-*.jsonl"))
    return max(candidates, key=os.path.getmtime) if candidates else ""


def _load_agent_transcript(path):
    return [
        json.loads(line)
        for line in read_lines(path)
        if line.strip()
    ]


def _run_agent_contract(kind, status, report, calls, retry):
    legacy_calls = [call.to_legacy() for call in calls]
    validators = {
        "CODECHECK": _runtime_adapter()._codecheck_contract,
        "UT": _runtime_adapter()._ut_contract,
        "COMPILE": _runtime_adapter()._compile_contract,
        "GRILL": _runtime_adapter()._grill_contract,
    }
    validator = validators.get(kind)
    if validator:
        validator(status, report, legacy_calls, soft=retry)
    return _HookResponse()


def _agent_completion_ports():
    return _AgentCompletionPorts(
        latest_subagent_transcript=_latest_subagent_transcript,
        load_transcript=_load_agent_transcript,
        read_transcript_head=lambda path, limit: read_text(
            path, errors="replace", limit=limit),
        contract_state=_runtime_adapter()._contract_state,
        record_codecheck_trace=lambda status, report, calls, path, retry:
            _runtime_adapter()._record_codecheck_agent_trace(
                status,
                report,
                [call.to_legacy() for call in calls],
                path,
                retry=retry,
            ),
        run_contract=_run_agent_contract,
        record_token=_runtime_adapter()._record_agent_token,
        record_rejection=_runtime_adapter()._record_rejection,
        autopsy=_autopsy,
        log=_log,
    )


def ev_subagentstop(d):
    response = _handle_agent_completion(d, _agent_completion_ports())
    if response.stderr:
        print(response.stderr, file=sys.stderr, end="")
    sys.exit(response.exit_code)


def ev_posttooluse(d):
    tool = d.get("tool_name")
    if tool in ("Write", "Edit", "MultiEdit"):
        ti = d.get("tool_input") or {}
        p = ti.get("file_path", "") or ti.get("path", "") or ""
        if p:
            _runtime_adapter()._record_agent_write(p)
    # 真实用户问答的事件令牌:AskUserQuestion 工具真被调用过才有——
    # "确认发生过"从此是 harness 签发的事实,不是模型可书写的文本
    if tool == "AskUserQuestion":
        _runtime_adapter()._capture_usermsg(_runtime_adapter()._text_of(d.get("tool_response")))   # 应答原文进 ack 验真存储
        _runtime_adapter()._record_agent_token("ASKUSER", "CONFIRMED")
        sys.exit(0)
    if tool == "Bash":
        _runtime_adapter()._maybe_utrun(d)
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

    try:
        document = read_text(p)
        template = read_text(tpl)
        decision = _template_decision(template, document)
    except Exception:
        sys.exit(0)
    if not decision.accepted:
        print(f"[mae-flow] {hit[1]} 结构与模板不符,缺少章节: "
              + " | ".join(decision.missing)
              + "。请补齐缺失章节(无内容的章节按约定标注,不可省略标题)。", file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


def ev_stop(d):
    """月光宝盒未到安全停点时，阻止主 Agent 提前结束。

    Stop Hook 只补“主模型自行收工”这一处硬洞。真实硬阻塞必须先用 moonlight blocked 留痕；
    push 失败则由 push-failed 留痕。stop_hook_active 时放行，避免宿主递归触发形成死循环。
    """
    try:
        st = load_json(STATE)
    except Exception:
        sys.exit(0)
    initial = _stop_decision(st, False, {})
    if initial.allow:
        sys.exit(0)
    sid = st.get("current", "")
    # 反收工护栏必须是「无进展计数」而不是「链级一发」:Claude Code 的 stop_hook_active
    # 在同一延续链里一直为 true,夜里没有用户消息复位它——旧写法第一次打回后,
    # 后续任何一次自然收尾都被放行,整夜保护恰好等于一段续命(静默白夜)。
    # 现在:状态 revision 有推进就继续拦(干活的 Agent 拦到安全停点为止);
    # 连续 3 次零进展才 fail-open(真卡死的 Agent 不会被无限打回)。
    guard_path = STATE + ".stop-guard"
    try:
        guard = load_json(guard_path)
    except Exception:
        guard = {}
    decision = _stop_decision(
        st, bool(d.get("stop_hook_active")), guard)
    if decision.allow:
        _log("stop guard: revision=%s 连续 %s 次零进展,fail-open 放行(防死循环)"
             % (decision.revision, decision.blocks - 1))
        sys.exit(0)
    try:
        atomic_write_json(guard_path, {
            "revision": decision.revision, "blocks": decision.blocks,
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


def _hook_event_ports():
    return HookEventAdapter(
        state=STATE,
        action_state=ACTION_STATE,
        runtime_adapter=_runtime_adapter(),
        log=_log,
        session_notice_due=_session_notice_due,
        pretool=ev_pretooluse,
        standalone_pretool=ev_action_pretooluse,
        inject=ev_inject,
        subagentstop=ev_subagentstop,
        posttool=ev_posttooluse,
        stop=ev_stop,
    ).ports()


def main():
    ev = sys.argv[1] if len(sys.argv) > 1 else ""
    _arm_watchdog()
    _log("start " + ev)
    rc = 0
    try:
        d = read_input()
        _chdir_root(d)
        runtime = resolve_runtime(os.getcwd())
        response = _handle_hook_event(
            ev, d, runtime, _hook_event_ports())
        if response.stdout:
            print(response.stdout, end="")
        if response.stderr:
            print(response.stderr, end="", file=sys.stderr)
        rc = response.exit_code
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
