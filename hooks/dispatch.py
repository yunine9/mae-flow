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
    append_codecheck_event,
    atomic_write_json,
    atomic_write_text,
    codecheck_log_path,
    find_project_root,
    load_action as core_load_action,
    normalize_document,
    resolve_runtime,
    safe_read_json,
    save_codecheck_artifact,
    update_json,
    update_versioned_json,
)
from mae_flow_core.foundation.fingerprints import (
    path_fingerprint as _shared_path_fingerprint,
    review_path_fingerprint as _shared_review_path_fingerprint,
)
from mae_flow_core.foundation import source_paths
from mae_flow_core.file_io import load_json, read_lines, read_text, write_text
from mae_flow_core.application.hooks.task_cards import (
    TaskCardPorts as _TaskCardPorts,
    verify_agent_scope as _verify_agent_scope,
    verify_completion_task as _verify_completion_task,
    verify_dispatch_task as _verify_dispatch_task,
)
from mae_flow_core.application.hooks.receipts import (
    ReceiptContext as _ReceiptContext,
    plan_codecheck_build_receipt as _plan_codecheck_build_receipt,
    plan_codecheck_fullcheck_receipt as _plan_codecheck_fullcheck_receipt,
    plan_ut_generator_receipt as _plan_ut_generator_receipt,
    plan_ut_run_receipt as _plan_ut_run_receipt,
    reusable_codecheck_build_receipt as _core_reusable_codecheck_build,
    reusable_codecheck_fullcheck_receipt as _core_reusable_codecheck_fullcheck,
    reusable_ut_receipt as _core_reusable_ut_receipt,
)
from mae_flow_core.application.hooks.agent_completion import (
    AgentCompletionPorts as _AgentCompletionPorts,
    handle_agent_completion as _handle_agent_completion,
)
from mae_flow_core.application.hooks.models import (
    HookResponse as _HookResponse,
)
from mae_flow_core.quality.agent_reports import (
    ac_coverage_has_mapping as _core_ac_coverage_has_mapping,
    empty_section as _core_empty_section,
    report_field as _core_report_field,
    report_number as _core_report_number,
    report_section as _core_report_section,
)
from mae_flow_core.quality.tool_transcript import (
    ToolCall as _ToolCall,
    call_failed as _core_call_failed,
    parse_transcript as _parse_tool_transcript,
    reported_bash_call as _core_reported_bash_call,
    select_contract_marker as _select_contract_marker,
    skill_call as _core_skill_call,
)
from mae_flow_core.quality.agent_contracts import (
    AgentContractContext as _AgentContractContext,
)
from mae_flow_core.quality.compile_contract import (
    evaluate_compile_contract as _evaluate_compile_contract,
)
from mae_flow_core.quality.codecheck_contract import (
    evaluate_codecheck_contract as _evaluate_codecheck_contract,
)
from mae_flow_core.quality.grill_contract import (
    evaluate_grill_contract as _evaluate_grill_contract,
)
from mae_flow_core.quality.unit_test_contract import (
    evaluate_unit_test_contract as _evaluate_unit_test_contract,
)
from mae_flow_core.quality.unit_test_execution import (
    report_counts as _core_ut_report_counts,
    reported_bash_segment as _core_reported_bash_segment,
    unit_test_execution_risk as _core_ut_execution_risk,
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


def _task_card_ports():
    return _TaskCardPorts(
        read_text=read_text,
        current_head=_git_head,
        merge_base=lambda head, _current: _git_out(
            f"git merge-base {head} HEAD").strip(),
        changed_paths_since=_changed_paths_since,
        source_changed_since=_source_changed_since_receipt,
        source_snapshot=_source_snapshot,
        path_fingerprint=_path_fingerprint,
        review_path_fingerprint=_review_path_fingerprint,
        source_like=_source_like,
        test_like=_test_like,
        path_exists=os.path.exists,
        script_path=lambda: os.path.abspath(MAEFLOW),
    )


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
        "CODECHECK": _codecheck_contract,
        "UT": _ut_contract,
        "COMPILE": _compile_contract,
        "GRILL": _grill_contract,
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
        contract_state=_contract_state,
        record_codecheck_trace=lambda status, report, calls, path, retry:
            _record_codecheck_agent_trace(
                status,
                report,
                [call.to_legacy() for call in calls],
                path,
                retry=retry,
            ),
        run_contract=_run_agent_contract,
        record_token=_record_agent_token,
        record_rejection=_record_rejection,
        autopsy=_autopsy,
        log=_log,
    )


def ev_subagentstop(d):
    response = _handle_agent_completion(d, _agent_completion_ports())
    if response.stderr:
        print(response.stderr, file=sys.stderr, end="")
    sys.exit(response.exit_code)


def _git_head():
    """当前 HEAD sha(令牌新鲜度绑定用)。拿不到返回空串=该令牌不做新鲜度校验(fail-open)。"""
    try:
        r = subprocess.run("git rev-parse --verify HEAD", shell=True, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _flow_task_for_token(kind):
    try:
        raw, err = safe_read_json(STATE)
        if err or not raw:
            return {}
        current = normalize_document(raw, "flow")
        return (current.get("agent_tasks", {}) or {}).get(kind, {})
    except Exception:
        return {}


def _flow_token_source_snapshot(kind, fallback_head):
    task = _flow_task_for_token(kind)
    if task.get("precommit_review"):
        return _source_snapshot(task.get("head", fallback_head))
    return None


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
            if kind == "CODECHECK":
                append_codecheck_event(
                    os.getcwd(), action, "agent.token_issued", {
                        "status": status, "head": head,
                        "report_path": report_path,
                        "standalone": True,
                    }, source="hook")
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
            token = {
                "at": time.strftime("%Y-%m-%d %H:%M:%S"), "head": head,
                "status": status, "step": step,
            }
            source_snapshot = _flow_token_source_snapshot(kind, head)
            if source_snapshot is not None:
                token["source_snapshot"] = source_snapshot
            tokens[kind] = token
            return tokens

        update_json(p, update_tokens, default={}, recover_corrupt=True)
        if kind == "CODECHECK":
            _codecheck_log_event("agent.token_issued", {
                "status": status, "head": head,
                "step": step, "standalone": False,
            })
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
    # 宿主真实插件命令是 `/插件:命令 参数`；保留短形式只为兼容旧宿主和
    # 已有测试。命名空间形式若漏掉，Hook 不会签发退出 intent，Agent 随后
    # 只能调用无凭据 CLI，最终错误地逼用户去真实终端执行 --interactive。
    if re.search(
            r"^/mae-flow(?::mae-flow)?\s+(?:exit|direct)(?:\s|$)",
            value, re.I):
        return True
    lower = value.lower()
    names_flow = "mae-flow" in lower or "mae flow" in lower or "这个工作流" in value
    explicit_verb = bool(re.search(
        r"(退出|停止使用|不想(?:再)?用|不用|关闭)\s*(?:mae[- ]?flow|这个工作流)", value, re.I))
    direct_after = any(x in value for x in (
        "直接开发", "直接改代码", "直接让", "直接写", "直接补", "补UT", "补 UT", "保留现场", "不走流程"))
    question = any(x in value for x in ("能不能", "可以吗", "会怎样", "怎么退出", "如何退出", "？", "?"))
    return names_flow and explicit_verb and direct_after and not question


def _explicit_flow_start_prompt(text):
    """识别宿主真实 Slash 入口中会开启完整流程的动作。

    终态 Hook 虽然全面旁路门禁，仍需把这类用户原话交给下一轮 init；独立
    ut/codecheck/grill/story/chain/help/cancel 不属于完整流程重入。
    """
    value = re.sub(r"\s+", " ", (text or "").strip()).lower()
    command = re.match(
        r"^/mae-flow(?::mae-flow)?(?:\s+([^\s]+))?", value)
    if not command:
        return False
    action = (command.group(1) or "").strip()
    return action in ("", "review-fix", "moonlight", "月光宝盒")


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
        captured = text[:2000]
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        row = {
            "id": hashlib.sha256(
                (str(time.time_ns()) + "\0direct\0" + captured).encode(
                    "utf-8")).hexdigest()[:12],
            "at": stamp,
            "epoch": time.time(),
            "text": captured,
        }

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
        st = load_json(STATE)
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


def _codecheck_log_state():
    """Return the real persisted document so standalone logs use its work_dir."""
    if not os.path.isfile(STATE):
        action = _load_action()
        if action:
            return action
    return _contract_state()


def _codecheck_log_event(event, details=None):
    return append_codecheck_event(
        os.getcwd(), _codecheck_log_state(), event, details, source="hook")


def _git_trace(args):
    """Bounded read-only Git capture for diagnostics; never affects a gate."""
    try:
        result = subprocess.run(
            ["git", "-c", "core.quotepath=false", *args],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=2)
        return {
            "return_code": result.returncode,
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
        }
    except Exception as exc:
        return {"return_code": None, "stdout": "", "stderr": str(exc)}


def _tool_trace_summary(call):
    value = call.get("input", {}) or {}
    summary = {}
    if isinstance(value, dict):
        for key in ("command", "file_path", "path", "skill", "name"):
            if value.get(key) not in (None, ""):
                summary[key] = value.get(key)
    elif value:
        summary["input"] = str(value)[:2000]
    return summary


def _record_codecheck_agent_trace(
        status, report, tool_calls, transcript_path, retry=False):
    """Persist the agent's commands, results and actual Git delta.

    This deliberately has no return-value contract: logging must never become
    a new reason to reject an otherwise valid CodeCheck run.
    """
    try:
        state = _codecheck_log_state()
        task = (state.get("agent_tasks", {}) or {}).get("CODECHECK", {})
        head = str(task.get("head", "") or "")
        report_artifact = save_codecheck_artifact(
            os.getcwd(), state, "agent-final-report", report or "", ".md")
        changed = []
        source_changed = []
        diff_artifact = None
        name_status = {"return_code": None, "stdout": "", "stderr": ""}
        diff_stat = {"return_code": None, "stdout": "", "stderr": ""}
        worktree_status = {"return_code": None, "stdout": "", "stderr": ""}
        if re.fullmatch(r"[0-9a-fA-F]{7,64}", head):
            raw_diff = _git_trace(["diff", "--no-ext-diff", "--binary", head, "--"])
            diff_artifact = save_codecheck_artifact(
                os.getcwd(), state, "agent-working-tree", raw_diff["stdout"], ".diff")
            if raw_diff.get("stderr"):
                diff_artifact["stderr"] = raw_diff["stderr"][-2000:]
            diff_artifact["return_code"] = raw_diff.get("return_code")
            name_status = _git_trace(["diff", "--name-status", head, "--"])
            diff_stat = _git_trace(["diff", "--stat", head, "--"])
            worktree_status = _git_trace(["status", "--porcelain"])
            for line in name_status.get("stdout", "").splitlines():
                fields = line.split("\t")
                if len(fields) >= 2:
                    changed.append(fields[-1].strip().strip('"'))
            for line in worktree_status.get("stdout", "").splitlines():
                value = line[3:] if len(line) > 3 else ""
                if " -> " in value:
                    value = value.split(" -> ")[-1]
                if value.strip():
                    changed.append(value.strip().strip('"'))
            changed = list(dict.fromkeys(
                path.replace("\\", "/") for path in changed if path))
            source_changed = [path for path in changed if _source_like(path)]

        traced_tools = {
            "bash", "write", "edit", "multiedit", "skill",
            "shell", "exec", "execcommand",
        }
        tool_rows = []
        artifact_count = 0
        for index, call in enumerate(tool_calls or [], 1):
            name = str(call.get("name", "") or "")
            normalized = re.sub(r"[^a-z]", "", name.lower())
            if normalized not in traced_tools:
                continue
            input_text = json.dumps(
                call.get("input", {}), ensure_ascii=False,
                sort_keys=True, default=str)
            result_text = str(call.get("result", "") or "")
            if artifact_count < 40:
                input_artifact = save_codecheck_artifact(
                    os.getcwd(), state, "agent-tool-%03d-input" % index,
                    input_text, ".json", max_bytes=64 * 1024)
                result_artifact = save_codecheck_artifact(
                    os.getcwd(), state, "agent-tool-%03d-result" % index,
                    result_text, ".txt", max_bytes=64 * 1024)
                artifact_count += 1
            else:
                input_artifact = {
                    "omitted": "artifact-limit",
                    "bytes": len(input_text.encode("utf-8", errors="replace")),
                    "sha256": hashlib.sha256(
                        input_text.encode("utf-8", errors="replace")).hexdigest(),
                }
                result_artifact = {
                    "omitted": "artifact-limit",
                    "bytes": len(result_text.encode("utf-8", errors="replace")),
                    "sha256": hashlib.sha256(
                        result_text.encode("utf-8", errors="replace")).hexdigest(),
                }
            row = {
                "index": index, "name": name,
                "summary": _tool_trace_summary(call),
                "result_seen": bool(call.get("result_seen")),
                "is_error": bool(call.get("is_error")),
                "input": input_artifact,
                "result": result_artifact,
            }
            tool_rows.append(row)
            append_codecheck_event(
                os.getcwd(), state, "agent.tool", row, source="hook")

        fixed = ""
        match = re.search(
            r"^\s*FIXED_CHANGES:\s*(.*?)(?=^\s*[A-Z][A-Z0-9_]+:\s*|\Z)",
            report or "", re.M | re.S)
        if match:
            fixed = match.group(1).strip()
        append_codecheck_event(
            os.getcwd(), state, "agent.stopped", {
                "status": status,
                "retry": bool(retry),
                "task_path": task.get("path", ""),
                "task_sha256": task.get("sha256", ""),
                "task_head": head,
                "transcript_path": os.path.abspath(transcript_path)
                if transcript_path else "",
                "report": report_artifact,
                "fixed_changes_reported": fixed,
                "changed_paths": changed,
                "changed_source_paths": source_changed,
                "name_status": name_status,
                "diff_stat": diff_stat,
                "worktree_status": worktree_status,
                "diff": diff_artifact,
                "traced_tool_count": len(tool_rows),
                "tool_artifact_limit": 40,
            }, source="hook")
    except Exception as exc:
        _log("codecheck trace EXC: " + str(exc))


def _evidence_data():
    action = _load_action()
    if action and not os.path.isfile(STATE):
        return dict(action.get("evidence", {}) or {})
    try:
        return load_json(
            EVIDENCE_STATE) if os.path.exists(EVIDENCE_STATE) else {}
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
    if label == "CODECHECK":
        _codecheck_log_event("agent.contract_rejected", {
            "reason": msg, "soft_retry": bool(soft),
            "head": _git_head(),
        })
    if soft:
        _log(label + " 重答仍违规: " + msg)
        sys.exit(0)
    print("[mae-flow] " + label + " 契约违规:" + msg
          + " 请按 agent 定义的 Return format 重新真实收尾。", file=sys.stderr)
    sys.exit(2)


def _tool_call_values(tool_calls):
    return tuple(_ToolCall(
        call_id=call.get("id", ""),
        name=call.get("name", ""),
        input=call.get("input", {}),
        result_seen=bool(call.get("result_seen")),
        is_error=bool(call.get("is_error")),
        result=str(call.get("result", "") or ""),
    ) for call in (tool_calls or []))


def _contract_context(
        kind, status, report, task, tool_calls, changed=(),
        compile_net=0, reusable_receipts=None, facts=None):
    return _AgentContractContext(
        kind=kind,
        status=status,
        report=report,
        task=task,
        config=_state_config(),
        calls=_tool_call_values(tool_calls),
        changed_paths=tuple(changed),
        compile_net=compile_net,
        reusable_receipts=reusable_receipts or {},
        facts=facts or {},
    )


def _task_card_contract(kind, report, soft=False):
    """报告必须回传 harness 任务卡指纹；缺配置时不再允许子 agent 边猜边做。"""
    st = _contract_state()
    decision = _verify_completion_task(
        kind, report, st, _task_card_ports())
    if not decision.accepted:
        _contract_bail(kind, decision.reason, soft)
    return decision.task


def _state_config():
    return (_contract_state().get("config", {}) or {})


def _field(report, name):
    m = re.search(r"^\s*" + re.escape(name) + r":\s*(.+?)\s*$", report, re.M)
    return m.group(1).strip() if m else ""


def _flex_field(report, name):
    """弱模型常把机器字段挤在一行或加 Markdown bullet；按下一个已知字段切开而非卡排版。"""
    return _core_report_field(report, name)


def _number_field(report, name):
    return _core_report_number(report, name)


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


def _receipt_context(task):
    snapshot = (
        _source_snapshot(task.get("head", ""))
        if task.get("standalone") else None
    )
    return _ReceiptContext(
        at=time.strftime("%Y-%m-%d %H:%M:%S"),
        head=_git_head(),
        source_snapshot=snapshot,
    )


def _record_codecheck_build_receipt(task, tool_calls):
    """报告格式即使被打回，也保留已经真实发生的编译证据，供同一 HEAD 的重答复用。"""
    build_cfg = _state_config().get("编译方式", "")
    if not build_cfg or not _codecheck_build_call(tool_calls, build_cfg):
        return None
    rec = _plan_codecheck_build_receipt(
        task, _receipt_context(task), build_cfg)
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
    rec = _plan_codecheck_fullcheck_receipt(
        task,
        _receipt_context(task),
        command_count,
        raw_counts,
        scan,
        expected_raw=expected_raw,
        result_hashes=result_hashes,
    )
    counts_complete = rec["machine_counts_complete"]
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


def _record_ut_receipts(task, report, tool_calls, require_baseline=False):
    """保存真实 AutoUT 与 UT 执行事实；后续仅修报告且代码未变时无需重做重活。"""
    cfg = _state_config()
    need = _required_skill(cfg.get("UT生成方式", ""))
    calls = _tool_call_values(tool_calls)
    generator = _core_skill_call(calls, need) if need else None
    executed = _flex_field(report, "EXECUTED_UT") or ""
    run = _core_reported_bash_call(calls, executed)
    records = {}
    context = _receipt_context(task)
    if generator and not _core_call_failed(generator):
        records["UT_GENERATOR"] = _plan_ut_generator_receipt(
            task, context, cfg.get("UT生成方式", ""))
    reported_counts = _core_ut_report_counts(report)
    counts_complete = all(v is not None for v in reported_counts.values())
    if run and counts_complete and not _core_call_failed(
            run) and not _core_ut_execution_risk(
                report,
                run,
                cfg.get("UT运行命令", ""),
                calls,
                require_baseline):
        actual = _core_reported_bash_segment(run, executed) or executed
        records["UT_RUN"] = _plan_ut_run_receipt(
            task,
            context,
            actual,
            reported_counts,
            run.result,
        )
    if not records:
        return
    try:
        data = _evidence_data()
        data.update(records)
        _save_evidence(data)
        _log("UT 执行凭证: " + "/".join(sorted(records))
             + " @" + context.head[:9])
    except Exception as e:
        _log("ut receipt EXC: " + str(e))


def _reuse_source_facts(receipt, task):
    if task.get("standalone"):
        return _source_snapshot(task.get("head", "")), (), ""
    changed, err = _source_changed_since_receipt(
        receipt.get("head", ""), _contract_state())
    return None, tuple(changed), err


def _reusable_ut_receipt(key, task, expected=None):
    rec = _evidence_data().get(key, {})
    if not rec:
        return None
    snapshot, changed, err = _reuse_source_facts(rec, task)
    return _core_reusable_ut_receipt(
        rec,
        task,
        expected=expected,
        standalone_snapshot=snapshot,
        changed_paths=changed,
        source_error=err,
    )


def _reusable_codecheck_build_receipt(task):
    """仅同任务卡、同步骤且源码未变化时复用；代码一变就必须重新编译。"""
    rec = _evidence_data().get("CODECHECK_BUILD", {})
    if not rec:
        return None
    snapshot, changed, err = _reuse_source_facts(rec, task)
    return _core_reusable_codecheck_build(
        rec,
        task,
        _state_config().get("编译方式", ""),
        standalone_snapshot=snapshot,
        changed_paths=changed,
        source_error=err,
    )


def _reusable_codecheck_fullcheck_receipt(task, command_count, scan):
    rec = _evidence_data().get("CODECHECK_FULLCHECK", {})
    if not rec:
        return None
    snapshot, changed, err = _reuse_source_facts(rec, task)
    return _core_reusable_codecheck_fullcheck(
        rec,
        task,
        command_count,
        scan,
        standalone_snapshot=snapshot,
        changed_paths=changed,
        source_error=err,
    )


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
    return _core_report_section(report, name)


def _empty_section(value):
    return _core_empty_section(value)


def _changed_paths_since(head):
    out = _git_out(
        f"git -c core.quotepath=false diff --name-only --no-renames {head}..HEAD")
    paths = [x.strip() for x in out.splitlines() if x.strip()]
    paths.extend(
        x.strip() for x in _git_out(
            "git -c core.quotepath=false diff --name-only --no-renames HEAD"
        ).splitlines() if x.strip())
    for line in _git_out(
            "git -c core.quotepath=false status --porcelain --untracked-files=all").splitlines():
        p = line.split(None, 1)
        if len(p) == 2:
            paths.append(p[1].split(" -> ")[-1].strip().strip('"'))
    return list(dict.fromkeys(x.replace("\\", "/") for x in paths))


def _path_fingerprint(path):
    return _shared_path_fingerprint(path)


_path_fingerprint.__wrapped__ = _shared_path_fingerprint


def _review_path_fingerprint(path):
    return _shared_review_path_fingerprint(path)


_review_path_fingerprint.__wrapped__ = _shared_review_path_fingerprint


def _unchanged_initial_dirty(path, st):
    rel = str(path or "").replace("\\", "/").strip().strip('"')
    initial = set((st or {}).get("initial_dirty", []) or [])
    fingerprints = (st or {}).get("initial_dirty_fingerprints", {}) or {}
    return bool(rel in initial and fingerprints.get(rel) == _path_fingerprint(rel))


def _source_snapshot(head):
    return {
        p: _review_path_fingerprint(p)
        for p in _changed_paths_since(head)
        if _source_like(p)
    }


_TEST_PAT = re.compile(
    r"(^|/)(tests?|__tests__|spec|[^/]+[_-]tests?)/|"
    r"(^|/)src/test/|(^|/)test_[^/]+\.py$|"
    r"(_test|\.test|\.spec)\."
    r"(c|cc|cpp|cxx|h|hh|hpp|hxx|inl|ipp|tpp|py|go|rs|"
    r"js|jsx|cjs|mjs|ts|tsx|cts|mts)$|"
                       r"Tests?\.(c|cc|cpp|cxx|h|hh|hpp|hxx|java|kt|cs)$", re.I)
_COMMON_SOURCE_PATTERN = (
    r"(^|/)(service|src|include|lib|app|modules?)/")


def _source_like(path):
    """dispatch 侧源码判定，顺序与主状态机一致：文件名/扩展名 > 文档排除 > 目录/私有规则。"""
    normalized = str(path or "")
    known = source_paths.known_source_classification(normalized)
    if known is not None:
        return known
    if source_paths.is_source_path(
            normalized, [_COMMON_SOURCE_PATTERN]):
        return True
    patterns = []
    value = _state_config().get("源码路径", [])
    patterns += ([x.strip() for x in value.split(",") if x.strip()]
                 if isinstance(value, str) else list(value or []))
    try:
        value = load_json(
            ".mae-flow-defaults.json",
            encoding="utf-8-sig",
        ).get("源码路径", [])
        patterns += ([x.strip() for x in value.split(",") if x.strip()]
                     if isinstance(value, str) else list(value or []))
    except FileNotFoundError:
        pass
    except Exception as exc:
        _log("defaults 源码路径解析失败(已忽略,请修复该 JSON): %s" % exc)
    return source_paths.is_source_path(
        normalized, [str(pattern) for pattern in patterns])


def _test_like(path):
    if _TEST_PAT.search(path):
        return True
    pats = []
    v = _state_config().get("测试路径", [])
    pats += [x.strip() for x in v.split(",") if x.strip()] if isinstance(v, str) else list(v or [])
    try:
        # utf-8-sig:团队手写 defaults 常带 BOM;strict 失败必须留痕,
        # 否则「测试路径」静默失效会让 gate 口径变宽而无人知晓。
        v = load_json(
            ".mae-flow-defaults.json",
            encoding="utf-8-sig",
        ).get("测试路径", [])
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
    decision = _verify_agent_scope(
        kind, task, _contract_state(), _task_card_ports())
    if not decision.accepted:
        bail(decision.reason)
    return list(decision.changed_paths)


def _codecheck_contract(status, report, tool_calls=None, soft=False):
    """Validate CodeCheck through the pure contract and persist its effects."""
    def bail(msg):
        _contract_bail("CODECHECK", msg, soft)

    task = _task_card_contract("CODECHECK", report, soft)
    changed = _enforce_agent_scope("CODECHECK", task, bail)
    _record_codecheck_build_receipt(task, tool_calls)

    state = _contract_state()
    scan = (state.get("quality", {}) or {}).get(
        "codecheck_scan", {})
    command_count = (
        len(scan.get("commands") or [])
        if scan.get("step") == state.get("current") else 1
    )
    command_count = max(1, command_count)
    reusable = {}
    fullcheck_calls = _bash_calls(
        tool_calls, "codecheck fullcheck")
    if soft and not fullcheck_calls:
        receipt = _reusable_codecheck_fullcheck_receipt(
            task, command_count, scan)
        if receipt:
            reusable["CODECHECK_FULLCHECK"] = receipt
    build_cfg = _state_config().get("编译方式", "")
    current_build = _codecheck_build_call(tool_calls, build_cfg)
    if soft and not current_build:
        receipt = _reusable_codecheck_build_receipt(task)
        if receipt:
            reusable["CODECHECK_BUILD"] = receipt

    decision = _evaluate_codecheck_contract(_contract_context(
        "CODECHECK",
        status,
        report,
        task,
        tool_calls,
        changed,
        reusable_receipts=reusable,
        facts={
            "current": state.get("current", ""),
            "scan": scan,
            "soft": bool(soft),
        },
    ))
    details = dict(decision.details)
    receipt = details.get("fullcheck_receipt")
    if receipt:
        _record_codecheck_fullcheck_receipt(
            task,
            receipt["command_count"],
            receipt["raw_counts"],
            receipt["scan"],
            receipt.get("expected_raw"),
            result_hashes=receipt.get("result_hashes"),
        )
    if details.get("reused_fullcheck"):
        reused = reusable.get("CODECHECK_FULLCHECK", {})
        _log("CODECHECK 重答复用完整 fullcheck 凭证 @"
             + reused.get("head", "")[:9])
    if details.get("reused_build"):
        reused = reusable.get("CODECHECK_BUILD", {})
        _log("CODECHECK 重答复用编译凭证 @"
             + reused.get("head", "")[:9])
    if details.get("build_summary_inaccurate"):
        _log("CODECHECK EXECUTED_BUILD 摘要不准确,"
             "以 transcript 的真实编译调用为准")
    if not decision.accepted:
        bail(decision.reason)

    if details.get("result") == "accepted-honest-failure":
        _codecheck_log_event("agent.contract_validated", {
            "status": status,
            "task_sha256": task.get("sha256", ""),
            "task_head": task.get("head", ""),
            "changed_source_paths": changed,
            "result": "accepted-honest-failure",
        })
        return
    _codecheck_log_event("agent.contract_validated", {
        "status": status,
        "task_sha256": task.get("sha256", ""),
        "task_head": task.get("head", ""),
        "changed_source_paths": changed,
        "found": details["found"],
        "fixed": details["fixed"],
        "remaining": details["remaining"],
        "fullcheck_raw_counts": details["fullcheck_raw_counts"],
        "fullcheck_expected_raw": details["fullcheck_expected_raw"],
        "fullcheck_command_count": details["command_count"],
        "result": "accepted",
    })

def _ac_coverage_has_mapping(coverage):
    """Accept either arrow mappings or a real Markdown EARS/test table.

    The agent contract asks for a comparison table, so requiring a literal
    arrow rejects the most natural compliant representation.  A Markdown table
    only counts when it has a separator row and at least one non-empty data row;
    a header-only table or a prose assertion still does not prove coverage.
    """
    return _core_ac_coverage_has_mapping(coverage)


def _ut_contract(status, report, tool_calls=None, soft=False):
    def bail(msg):
        _contract_bail("UT", msg, soft)

    task = _task_card_contract("UT", report, soft)
    changed = _enforce_agent_scope("UT", task, bail)
    require_baseline = bool(changed)
    _record_ut_receipts(
        task, report, tool_calls, require_baseline)

    config = _state_config()
    reusable = {}
    need = _required_skill(config.get("UT生成方式", ""))
    calls = _tool_call_values(tool_calls)
    generator = _core_skill_call(calls, need) if need else None
    if soft and need and not generator:
        receipt = _reusable_ut_receipt(
            "UT_GENERATOR", task, config.get("UT生成方式", ""))
        if receipt:
            reusable["UT_GENERATOR"] = receipt
    executed = _flex_field(report, "EXECUTED_UT") or ""
    run = _core_reported_bash_call(calls, executed)
    if soft and not run:
        receipt = _reusable_ut_receipt("UT_RUN", task)
        if receipt:
            reusable["UT_RUN"] = receipt

    decision = _evaluate_unit_test_contract(_contract_context(
        "UT",
        status,
        report,
        task,
        tool_calls,
        changed,
        reusable_receipts=reusable,
        facts={"soft": bool(soft)},
    ))
    if decision.details.get("generator_summary_inaccurate"):
        _log("UT GENERATOR_USED 摘要不准确,"
             "以 transcript 的真实 Skill 调用为准")
    if not decision.accepted:
        bail(decision.reason)

def _grill_contract(status, report, tool_calls=None, soft=False):
    """Grill critic 只做遗漏审查；GAPS 是有效产出，不因发现问题被当成执行失败。"""
    def bail(msg):
        _contract_bail("GRILL", msg, soft)

    task = _task_card_contract("GRILL", report, soft)
    changed = _enforce_agent_scope("GRILL", task, bail)
    decision = _evaluate_grill_contract(_contract_context(
        "GRILL", status, report, task, tool_calls, changed))
    if not decision.accepted:
        bail(decision.reason)


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

    untracked = 0
    for path in _git_out(
            "git ls-files --others --exclude-standard").splitlines():
        if not _source_like(path):
            continue
        try:
            with open(path, "rb") as stream:
                untracked += sum(1 for _line in stream)
        except OSError:
            pass
    return (
        net_of(_git_out(
            f"git -c core.quotepath=false diff --numstat {head}..HEAD"))
        + net_of(_git_out(
            "git -c core.quotepath=false diff --numstat HEAD"))
        + untracked)


def _compile_agent_net(task):
    """Only attribute source growth/shrinkage after the compile task was issued."""
    net = _compile_net_lines(task.get("head", ""))
    if task.get("precommit_review"):
        net -= int(task.get("initial_compile_net", 0) or 0)
    return net


def _compile_contract(status, report, tool_calls=None, soft=False):
    """编译 agent 收尾硬校验:格式对账(OK⇔零error)+ 净产出不变量(numstat 亲算防掏空)。
    优雅三件套之硬层:作弊(删代码换通过)从'被禁止'变'得不了分'。"""
    def bail(msg):
        _contract_bail("COMPILE", msg, soft)

    task = _task_card_contract("COMPILE", report, soft)
    changed = _enforce_agent_scope("COMPILE", task, bail)
    decision = _evaluate_compile_contract(_contract_context(
        "COMPILE",
        status,
        report,
        task,
        tool_calls,
        changed,
        compile_net=_compile_agent_net(task),
    ))
    if not decision.accepted:
        bail(decision.reason)


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
                re.findall(r"^#{1,3}\s+(.+)$", read_text(f), re.M)]

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
        st = load_json(STATE)
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
        guard = load_json(guard_path)
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
            if (not runtime.flow_terminal
                    and ev in ("userprompt", "sessionstart")):
                print("[mae-flow] ⚠ 检测到流程状态冲突：%s。完整流程继续作为唯一控制源；"
                      "请执行 mae-flow doctor 查看并清理陈旧独立任务。"
                      % "、".join(runtime.conflicts))
        action_active = runtime.mode == RuntimeMode.STANDALONE
        if runtime.mode == RuntimeMode.CORRUPT:
            _log("runtime corrupt: " + ";".join(runtime.errors))
            if ev in ("userprompt", "sessionstart") and _session_notice_due("corrupt", d, ev):
                if os.path.isfile(STATE):
                    print("[mae-flow] ⚠ 完整流程状态损坏，Hook 已按 fail-open 放行普通开发。"
                          "发送 `/mae-flow:mae-flow exit` 可保存坏现场并解除流程；不要手删状态。")
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
        elif runtime.flow_terminal:
            # end 是审计/换单所需的持久终态，不是仍在运行的门禁。状态文件必须
            # 留给 current/status/report 和下一次 init 滚动，但所有 Hook 入口
            # 都立即让出控制权：否则旧月光标记会拦 AskUserQuestion、旧任务卡会
            # 拦 Task、PostToolUse 还会把下一单普通改动记进上一单账本。
            if ev == "userprompt":
                prompt = d.get("prompt") or ""
                if _explicit_exit_prompt(prompt):
                    # end 已经完全解除门禁；再转成 .exited 只会让下一单平白多出
                    # message-id 重入授权。终态 exit 因此是幂等成功，且明确阻止
                    # Agent 继续调用裸 CLI / --interactive。
                    print("[mae-flow] 流程已经完成且 Hook 门禁已解除，无需再次退出；"
                          "终态记录会保留给 current/status/report 和下一单自动滚动。"
                          "不要再执行 mae-flow.py exit 或 exit --interactive。")
                    _log("terminal flow: idempotent exit")
                    raise SystemExit(0)
                elif (_explicit_flow_start_prompt(prompt)
                      or re.search(r"月光宝盒|moonlight", prompt, re.I)):
                    # 终态门禁虽已旁路，但下一轮仍要拿到本次 review-fix /
                    # moonlight / 完整入口的真实原话。只捕获明确 Slash 控制命令，
                    # 普通开发消息仍不写入上一单账本。
                    _capture_usermsg(prompt)
            if (ev in ("userprompt", "sessionstart")
                    and _session_notice_due("terminal", d, ev)):
                print("[mae-flow] 上一单已交付完成，Hook 门禁已全部解除；"
                      "当前按普通开发处理。终态记录仍可用 current/status/report 查看，"
                      "发起下一单时 init 会自动归档并开启新流程。")
            _log("terminal flow: bypass " + ev)
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
                          "不要运行 current/done。用户明确要求恢复原流程或执行 /mae-flow:mae-flow review-fix 时，"
                          "先运行 messages 取得真实消息 ID，再按命令说明执行 init；"
                          ".mae-flow.json.exited 是退出指针，不是主状态，禁止移动或改名。")
            elif ev == "posttooluse" and d.get("tool_name") == "AskUserQuestion":
                # Direct 模式不恢复任何 gate/令牌，但若 Agent 为“是否重新启用”发起按钮确认，
                # 真实答案必须进入同一授权账本。旧逻辑把整个 PostToolUse 旁路，造成用户明明
                # 点了确认，init 却永远验不到。
                _capture_direct_prompt(_text_of(d.get("tool_response")))
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
