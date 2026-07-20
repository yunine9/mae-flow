#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mae-flow — Mae-Flow 交付流程驱动器。

模型不再自己解释流程:执行 `current` 拿当前步指令,做完 `done` 推进,
`done` 会先校验证据(文件系统里的实物),不信口头汇报。
状态存于项目根 .mae-flow.json;流程定义在插件 flow/flow.json;
步骤指令在 flow/steps/<step>.md。

用法:
  mae-flow.py init                       在当前项目初始化流程
  mae-flow.py current                    打印当前步骤的执行指令
  mae-flow.py done [--ack 文本] [--set k=v ...] [--choice 值]
                                         声明完成,校验证据后推进并打印下一步
  mae-flow.py skip --reason 文本         跳过当前步(仅 skippable 步)
  mae-flow.py status [--inject]          查看状态;--inject 输出单行注入用摘要
  mae-flow.py gate edit <路径>           hook 判定:此刻能否编辑该文件(exit 0/2)
  mae-flow.py gate bash <命令>           hook 判定:git 分支/commit 命令是否合规
  mae-flow.py goto <step> --force        人工修复:强制跳转(留痕)
退出码:0 成功;1 参数/状态错误;2 gate 拦截或证据不足。
"""
import argparse, glob as globmod, json, os, re, subprocess, sys, tempfile, time

# Windows cmd 默认 GBK,强制 UTF-8 避免 ✅/中文 输出炸编码
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def norm(p):
    """路径/命令归一化:Windows 反斜杠 → 正斜杠,供正则匹配。"""
    return (p or "").replace("\\", "/")

HERE = os.path.dirname(os.path.abspath(__file__))
FLOW_PATH = os.path.join(HERE, "..", "flow", "flow.json")
STEPS_DIR = os.path.join(HERE, "..", "flow", "steps")
STATE_PATH = ".mae-flow.json"   # 相对项目根;启动时 find_project_root() 自动 chdir,不赌调用方 cwd
HISTORY_PATH = ".mae-flow-history.jsonl"   # 交付历史账本:终态 init 时追加本单摘要(gitignored,gate 防篡改)
DEFAULTS_PATH = ".mae-flow-defaults.json"  # 仓库预设(团队提交进仓):require_sets 步骤 current 时预填展示
FLOW = None                      # main() 加载后填充,供证据函数读取 env_checks 等


def find_project_root(start=None):
    """从 start(默认 cwd)向上定位项目根,消除"模型 cd 进子目录后调用"的错位:
    优先找已有 .mae-flow.json;没有(init 场景)则找 .git / openspec 标记;
    都没有就留在原地。返回 (root, 是否已有状态文件)。"""
    d = os.path.abspath(start or os.getcwd())
    probe = d
    while True:
        if os.path.exists(os.path.join(probe, STATE_PATH)):
            return probe, True
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    probe = d
    while True:
        if os.path.isdir(os.path.join(probe, ".git")) or os.path.isdir(os.path.join(probe, "openspec")):
            return probe, False
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    return d, False


def load_flow():
    with open(FLOW_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_state():
    if not os.path.exists(STATE_PATH):
        return None
    with open(STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_state(st):
    # 原子写:Windows 上杀软锁文件/中途崩溃写坏 JSON 会让所有 gate 静默失效(fail-open)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)


def die(msg, code=1):
    print("[mae-flow] " + msg, file=sys.stderr)
    sys.exit(code)


def sh(cmd):
    # encoding 必须显式 utf-8:中文 Windows 下 text=True 默认 GBK,
    # 读 UTF-8 的 git 输出(中文 commit message)会解码失败或乱码
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=15).stdout.strip()
    except Exception:
        return ""


# ---------------- 证据校验 ----------------

def subst(p, st):
    """将 pattern 中的 {配置键} 替换为已确认的配置值(如 {CHANGE_NAME}、{单号})。"""
    for k, v in st.get("config", {}).items():
        p = p.replace("{" + k + "}", v)
    return p


def ev_glob(spec, st):
    pats = [subst(p, st) for p in spec.get("any", [])]
    if any("{" in p and "}" in p for p in pats):
        return False, "证据 pattern 含未解析占位符(对应配置未 --set): " + " | ".join(pats)
    for p in pats:
        if globmod.glob(p):
            return True, ""
    return False, "未找到证据文件(任一即可): " + " | ".join(pats)


def ev_branch_ok(spec, st):
    want = st["config"].get("分支名", "")
    cur = sh("git branch --show-current")
    if not want:
        return False, "配置中无分支名(config_confirm 未 --set 分支名?)"
    if cur == want:
        return True, ""
    return False, f"当前分支 {cur or '未知'} != 约定分支 {want}。请 git checkout -b {want}(已存在则 checkout;错误命名分支用 git branch -m 重命名)"


def ev_tasks_checked(spec, st):
    cn = st["config"].get("CHANGE_NAME", "")
    files = globmod.glob(f"openspec/changes/{cn}/tasks.md") if cn else []
    if not files:
        return False, ("未找到本 change 的 tasks.md: openspec/changes/%s/tasks.md" % (cn or "{CHANGE_NAME 未设置}"))
    txt = open(files[0], encoding="utf-8").read()
    n = len(re.findall(r"^\s*[-*]\s*\[\s\]", txt, re.M))
    return (n == 0, "" if n == 0 else f"tasks.md 还有 {n} 个未勾选任务")


def ev_yaml(spec, st):
    """读本 change 的 .comet.yaml 字段作证据(comet-guard 机器写入,比文件存在性可信)。
    spec: {"field": 名, "equals": 期望值} 或 {"field": 名}(非空即过)。"""
    cn = st["config"].get("CHANGE_NAME", "")
    if not cn:
        return False, "CHANGE_NAME 未设置,无法读取 .comet.yaml"
    path = f"openspec/changes/{cn}/.comet.yaml"
    if not os.path.exists(path):
        return False, "未找到 " + path
    txt = open(path, encoding="utf-8", errors="replace").read()
    m = re.search(r"^\s*" + re.escape(spec["field"]) + r":\s*(.*?)\s*$", txt, re.M)
    val = (m.group(1).strip().strip("'\"") if m else "")
    if spec.get("equals") is not None:
        if val == spec["equals"]:
            return True, ""
        return False, (f".comet.yaml 的 {spec['field']}={val or '(空)'},需要 {spec['equals']}"
                       "——先完成本步的 comet 阶段并通过 comet-guard --apply,谎报无效")
    if val in ("", "null", "~"):
        return False, f".comet.yaml 的 {spec['field']} 为空——本步的 comet 产物尚未生成/登记"
    return True, ""


def _source_changed_since(head):
    """令牌签发时 HEAD 之后,源码(source_patterns)是否变化:已提交 diff + 工作区未提交改动。
    返回 (变更清单, 错误);基点不可解析(amend/rebase/GC)属错误,由调用方判拒——重签令牌即可恢复。"""
    if not re.fullmatch(r"[0-9a-f]{7,64}", head):
        return None, "令牌基点格式异常"
    pats = (FLOW or {}).get("source_patterns", [])
    cur = sh("git rev-parse --verify HEAD")
    changed = []
    if cur and cur != head:
        # cat-file 探基点存在性(不用 rev-parse ^{commit}:^ 在 Windows cmd 是转义符)
        if sh(f"git cat-file -t {head}") != "commit":
            return None, "令牌基点 commit 不可解析(经历过 amend/rebase?)"
        # core.quotepath=false:否则非 ASCII 文件名被引号+八进制转义,pattern 匹配不到 = 漏检
        out = sh(f"git -c core.quotepath=false diff --name-only {head} {cur}")
        changed += [f for f in out.splitlines()
                    if f and any(re.search(p, norm(f), re.I) for p in pats)]
    for line in sh("git -c core.quotepath=false status --porcelain").splitlines():
        # 按空白切"状态 路径",不用列偏移:sh() 会 strip 首行前导空格(' M' → 'M'),偏移取路径会错位
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        f = parts[1].split(" -> ")[-1].strip().strip('"')
        if f and any(re.search(p, norm(f), re.I) for p in pats):
            changed.append(f + "(未提交)")
    return changed, ""


def ev_agent_ran(spec, st):
    """硬证据:本步期间对应子 agent 真实收尾过。令牌由 SubagentStop hook(harness 调用)在
    契约标记验证通过后写入,模型无法伪造(令牌文件被 gate 双拦,手动调 dispatch 也被拦)。
    新格式令牌绑定签发时 HEAD:签发后源码再变(提交或未提交),证据即过期——旧证据不背新代码的书。
    旧格式(纯时间戳字符串)仅验时间,兼容在途单。"""
    kind = spec["agent"]
    entered = st["history"][-1]["at"] if st["history"] else st["started"]
    try:
        tok = json.loads(open(".mae-flow.json.tokens", encoding="utf-8").read()).get(kind, "")
    except Exception:
        tok = ""
    ts = tok.get("at", "") if isinstance(tok, dict) else tok
    head = tok.get("head", "") if isinstance(tok, dict) else ""
    if ts and ts >= entered:
        if head:
            changed, err = _source_changed_since(head)
            if err:
                return False, (f"{kind} 证据新鲜度无法核实({err})。"
                               "重新启动对应 agent(ASKUSER 则重新向用户提问)签发绑定当前代码状态的新令牌。")
            if changed:
                more = "…" if len(changed) > 5 else ""
                return False, (f"{kind} 证据已过期:令牌签发后源码发生变更({'、'.join(changed[:5])}{more})。"
                               "变更若属本单成果先按规范 commit,然后重新启动对应 agent"
                               "(ASKUSER 则重新向用户确认)对最新代码收尾——旧证据对新代码无效。")
        return True, ""
    if kind == "ASKUSER":
        return False, (f"本步内未发生过真实的 AskUserQuestion 用户交互(最近令牌: {ts or '无'};本步始于 {entered})。"
                       "待确认项必须用 AskUserQuestion 真实呈现给用户拍板——自行改写标注/口头声称已确认均无效。")
    return False, (f"本步内未检测到 {kind} 子 agent 的合法收尾(最近令牌: {ts or '无'};本步始于 {entered})。"
                   "必须真实启动对应 agent 且其**最终回复第一行为 XXX_RESULT: 标记**才会发放令牌——"
                   "主会话代写/口头汇报无效;若你已启动过 agent 仍见此错,原因就是它收尾没带标记,"
                   "重启该 agent 并在任务中明确要求按契约的「最终回复格式」收尾。")


def ev_content_free(spec, st):
    """文件内容不得命中任何禁止 pattern(正则)。用于把'标注协议'变成机器可查的终态校验。"""
    path = subst(spec["file"], st)
    if "{" in path and "}" in path:
        return False, "证据 pattern 含未解析占位符: " + path
    files = globmod.glob(path)
    if not files:
        return False, "未找到文件: " + path
    txt = open(files[0], encoding="utf-8", errors="replace").read()
    hit = [p for p in spec["patterns"] if re.search(p, txt)]
    if not hit:
        return True, ""
    return False, spec.get("note", "内容含禁止残留") + "(命中 pattern: " + " | ".join(hit) + ")"


def ev_clean_paths(spec, st):
    """指定路径必须已提交且无未提交改动(git 实测)。硬化'产物必须 commit'义务——
    忘提交的产物不进 MR,spec 白写。"""
    dirty = []
    for p in spec["paths"]:
        p = subst(p, st)
        if "{" in p and "}" in p:
            return False, "证据 pattern 含未解析占位符: " + p
        out = sh(f'git status --porcelain -- "{p}"')
        if out:
            dirty.append(f"{p}({out.splitlines()[0][:2].strip()})")
    if not dirty:
        return True, ""
    return False, "以下产物未提交(或有未提交改动),先 git add/commit 再 done: " + "、".join(dirty)


def ev_pushed(spec, st):
    """实测本地 HEAD 已推送到远端上游(push 步证据,推没推成不看口头汇报)。"""
    head = sh("git rev-parse --verify HEAD")
    up = sh("git rev-parse --verify @{u}")   # --verify:解析失败时 stdout 为空,不回显 @{u} 本身
    if not head:
        return False, "无法读取 HEAD"
    if not up:
        return False, "分支无上游跟踪——用 git push -u origin HEAD 推送并建立跟踪"
    if head == up:
        return True, ""
    return False, "本地 HEAD 与远端上游不一致(未推送/推送失败/远端有新提交):git push -u origin HEAD;冲突则 git pull --rebase 后重推"


def ev_commit_tagged(spec, st):
    dan = st["config"].get("单号", "")
    msg = sh("git log -1 --pretty=%s")
    if not msg:
        return False, "无法读取最新 commit"
    if re.match(r"^\[" + re.escape(dan) + r"\]\[(feat|fix)\]", msg):
        return True, ""
    return False, f"最新 commit「{msg}」不符合 [{dan}][feat|fix]描述 格式"


ENV_CACHE = os.path.join(os.path.expanduser("~"), ".mae-flow-env-ok")
ENV_MARK = "mae-flow-env-ok-v1"              # 缓存有效标记:防裸 touch 伪造(空文件/外来内容一律无效)
FAST_TYPES = ("path_any", "file_contains")   # 项目级快检查:不缓存,每次都跑


def run_env_checks(force_all=False):
    """现场实测环境就绪度,返回失败项名列表。检查项定义在 flow.json 的 env_checks。
    机器级慢检查(CLI/插件探测)全绿后缓存 24h(标记文件 ~/.mae-flow-env-ok),
    项目级快检查每次都跑;envcheck 命令 force_all 全量实测并刷新缓存。"""
    cached = False
    if not force_all:
        try:
            cached = (time.time() - os.path.getmtime(ENV_CACHE) < 86400
                      and open(ENV_CACHE, encoding="utf-8").read().strip() == ENV_MARK)
        except OSError:
            pass
    fails = []
    for c in (FLOW or {}).get("env_checks", []):
        if cached and c["type"] not in FAST_TYPES:
            continue
        t, v, ok = c["type"], c["value"], False
        try:
            if t == "cmd":
                ok = subprocess.run(v, shell=True, capture_output=True, timeout=20).returncode == 0
            elif t == "cmd_contains":
                r = subprocess.run(v, shell=True, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=20)
                ok = c["contains"].lower() in (r.stdout + r.stderr).lower()
            elif t == "node_min":
                m = re.match(r"v(\d+)\.(\d+)\.(\d+)", sh("node --version"))
                ok = bool(m) and tuple(map(int, m.groups())) >= tuple(map(int, v.split(".")))
            elif t == "path_any":
                ok = any(os.path.exists(p) for p in v)
            elif t == "file_contains":
                ok = os.path.exists(v) and c["contains"] in open(v, encoding="utf-8", errors="replace").read()
        except Exception:
            ok = False
        if not ok:
            fails.append(c["name"])
    if not fails and not cached:
        try:
            open(ENV_CACHE, "w", encoding="utf-8").write(ENV_MARK)
        except Exception:
            pass
    return fails


def ev_env_ok(spec, st):
    fails = run_env_checks()
    if not fails:
        return True, ""
    return False, "环境未就绪(现场实测): " + "、".join(fails) + " —— 启动 env-setup-agent 修复后重试 done"


EVIDENCE = {"glob": ev_glob, "branch_ok": ev_branch_ok, "env_ok": ev_env_ok,
            "tasks_checked": ev_tasks_checked, "commit_tagged": ev_commit_tagged,
            "yaml_field": ev_yaml, "pushed": ev_pushed, "agent_ran": ev_agent_ran,
            "content_free": ev_content_free, "clean_paths": ev_clean_paths}


def _ack_verified(st, ack):
    """ack 三级验真(fail-open 设计,存储恒空的 harness 上行为与旧版完全一致,永不误卡):
    ① ack 与 harness 捕获的近期用户输入(UserPromptSubmit prompt / AskUserQuestion 应答)匹配 → 过;
    ② 不匹配但本步内有 ASKUSER 令牌(交互真实性已证,内容不可验) → 过;
    ③ 存储非空且两者皆无 → 拒(伪造 ack 的形态:没有任何用户交互却声称拿到确认);
    存储不存在/为空 → 跳过(harness 未提供字段,自动降级)。"""
    try:
        msgs = json.loads(open(STATE_PATH + ".usermsg", encoding="utf-8").read() or "[]")
    except Exception:
        return True, ""
    if not msgs:
        return True, ""

    def nt(s):
        return re.sub(r"\s+", "", s or "")

    na = nt(ack)
    if na and any(na in nt(m.get("text", "")) for m in msgs):
        return True, ""
    ok, _ = ev_agent_ran({"agent": "ASKUSER"}, st)
    if ok:
        return True, ""
    return False, ("--ack 与 harness 记录的近期用户真实输入不匹配,且本步内无 AskUserQuestion 交互。"
                   "ack 必须是用户回复/选项的**原文复制**(禁止转述、概括、代答);"
                   "先真实拿到用户输入,再以原文重试。")


def check_evidence(step, st):
    fails = []
    for spec in step.get("evidence", []):
        ok, why = EVIDENCE[spec["type"]](spec, st)
        if not ok:
            fails.append(why)
    return fails


# ---------------- 步骤展示 ----------------

def perms_line(step):
    allow, forbid = [], []
    (allow if step.get("allow_source_edit") else forbid).append("修改源码")
    (allow if step.get("allow_specs_write") else forbid).append("写 openspec/specs/ 真相源")
    return "允许: " + ("、".join(allow) or "仅本步指令内动作") + ";禁止: " + "、".join(forbid + ["编辑 .comet.yaml"])


def _step_md_text(sid, st):
    """步骤指令文本:模板路径与已确认配置全部替换后返回(无该 md 返回 None)。
    占位符替换 = 把"需要模型去拿"的信息直接喂到嘴边(弱模型会跳过"去拿"的动作);
    未确认的配置键保持 {原样},不误伤。"""
    md = os.path.join(STEPS_DIR, sid + ".md")
    if not os.path.exists(md):
        return None
    txt = open(md, encoding="utf-8").read().rstrip()
    for ph, name in (("{STORY_TEMPLATE_PATH}", "STORY-TEMPLATE.md"),
                     ("{GRILL_PREP_TEMPLATE_PATH}", "GRILL-PREP-TEMPLATE.md"),
                     ("{REVIEW_TEMPLATE_PATH}", "REVIEW-TEMPLATE.md")):
        txt = txt.replace(ph, os.path.abspath(
            os.path.join(HERE, "..", "skills", "mae-flow", "assets", name)))
    return subst(txt, st)


def _defaults():
    """读仓库预设 .mae-flow-defaults.json。解析失败必须可见(fail-open 但可观测,不静默吞)。"""
    if not os.path.exists(DEFAULTS_PATH):
        return None, ""
    try:
        return json.load(open(DEFAULTS_PATH, encoding="utf-8")), ""
    except Exception as e:
        return None, f"⚠ {DEFAULTS_PATH} 解析失败,已忽略(修复该 JSON 或删除): {e}"


def print_current(flow, st):
    sid = st["current"]
    step = flow["steps"][sid]
    print(f"═══ 当前步骤: {sid} — {step['title']} ═══")
    print(perms_line(step))
    ul = st.get("unlock") or {}
    if ul.get("step") == sid:
        print(f"🔓 本步源码修改已解锁(用户裁决: {ul.get('reason', '')};推进后自动失效)")
    if step.get("clear_hint"):
        print("💡 会话卫生:本步开始前若会话已较长,建议 /clear 后说「继续」——状态在磁盘,进度不丢,防长上下文行为漂移。")
    if step.get("user_ack"):
        print("⚠ 本步需要用户确认:优先用 AskUserQuestion 等结构化提问工具呈现选项拿用户选择(选完同轮继续);"
              "该工具不可用才结束回复纯文本等待。done 必须携带 --ack \"用户选择/回复原文\",拿到前禁止推进。")
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
    if step.get("require_sets"):
        dft, warn = _defaults()
        if warn:
            print(warn)
        show = {k: v for k, v in (dft or {}).items() if k in step["require_sets"]}
        if show:
            print(f"──── 仓库预设({DEFAULTS_PATH},预填值;仍须逐项经用户确认后 --set,基线分支/需求文档必须单独确认) ────")
            for k, v in show.items():
                print(f"  {k} = {v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)}")
    print("──── 完成后执行 ────")
    extra = ""
    if step.get("choice_key"):
        extra += f" --choice <{'|'.join(step['choices'])}>"
    if step.get("require_sets"):
        extra += " --set " + " --set ".join(k + "=<值>" for k in step["require_sets"])
        if "基线分支" in step["require_sets"]:   # 分支名派生自基线分支,只在 config_confirm 提示
            extra += " --set 分支名=<基线分支>_<工号>_<单号>"
    if step.get("user_ack"):
        extra += " --ack \"<用户原话>\""
    # python(非 python3:Windows 无此命令);abspath(非 relpath:跨盘符 relpath 抛 ValueError)
    print(f"python \"{os.path.abspath(sys.argv[0])}\" done{extra}")
    if step.get("skippable"):
        print(f"(可跳过: ... skip --reason \"<理由>\")")


# ---------------- 命令 ----------------

def cmd_init(flow, args):
    old = load_state()
    if old:
        sid = old.get("current")
        if flow["steps"].get(sid, {}).get("terminal"):
            _append_history(old)
            os.replace(STATE_PATH, STATE_PATH + ".last")
            print(f"[mae-flow] 上一单({old.get('config', {}).get('单号', '?')})已交付完成,"
                  f"旧状态备份为 {STATE_PATH}.last,开启新流程。")
        else:
            die(f"流程已存在(进行中,当前步骤 {sid}),查看用 status;确要重来先删除 " + STATE_PATH)
    st = {"current": flow["start"], "config": {}, "choices": {},
          "history": [], "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    save_state(st)
    _gitignore()
    print("[mae-flow] 流程已初始化。")
    print_current(flow, st)


def _gitignore():
    gi = ".gitignore"
    # .mae-flow.json* 含 .tmp 原子写中间件与 .last 交付备份;历史账本单列(pattern 不覆盖)
    lines = [".mae-flow.json*", HISTORY_PATH]
    txt = open(gi, encoding="utf-8").read() if os.path.exists(gi) else ""
    add = [l for l in lines if l not in txt]
    if add:
        open(gi, "a", encoding="utf-8").write(
            ("\n" if txt and not txt.endswith("\n") else "") + "\n".join(add) + "\n")


def _friction_from_log(st):
    """从 hook 日志统计本单起始时间之后的摩擦(gate 拦截/契约打回/hook 异常)。
    日志不可读返回空 dict(账本/报告按缺项处理,不阻塞)。"""
    gate = bounce = anom = 0
    try:
        for line in open(os.path.join(tempfile.gettempdir(), "mae-flow-hook.log"),
                         encoding="utf-8", errors="replace"):
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


def _append_history(st):
    """终态备份前把本单摘要追加进历史账本(团队度量/推广数据)。
    失败不阻塞开新单,但必须可见(stderr)。"""
    try:
        hist = st.get("history", [])
        ended = hist[-1]["at"] if hist else st.get("started", "")

        def ts(s):
            return time.mktime(time.strptime(s, "%Y-%m-%d %H:%M:%S"))

        rec = {"单号": st.get("config", {}).get("单号", "?"),
               "workflow": st.get("choices", {}).get("workflow", "?"),
               "开始": st.get("started", ""), "结束": ended,
               "耗时秒": int(max(0, ts(ended) - ts(st.get("started", ended)))),
               "goto次数": sum(1 for h in hist if str(h.get("result", "")).startswith("goto:")),
               "skip次数": sum(1 for h in hist if h.get("result") == "skipped")}
        rec.update(_friction_from_log(st))
        with open(HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[mae-flow] 历史账本写入失败(不影响流程): {e}", file=sys.stderr)


def advance(flow, st, sid, step, tag, note=""):
    st.pop("unlock", None)   # 源码解锁仅限本步实例,推进即失效
    st["history"].append({"step": sid, "result": tag, "note": note, "at": time.strftime("%Y-%m-%d %H:%M:%S")})
    nxt = step.get("next")
    if step.get("next_by"):
        nxt = step["next"][st["choices"][step["next_by"]]]
    elif isinstance(nxt, dict):
        nxt = nxt[st["choices"][step["choice_key"]]]
    st["current"] = nxt
    save_state(st)
    print(f"[mae-flow] {sid} {tag} → 进入 {nxt}\n")
    print_current(flow, st)


def cmd_done(flow, st, args):
    sid = st["current"]
    step = flow["steps"][sid]
    if step.get("terminal"):
        die("流程已在终态。")
    for kv in args.set or []:
        if "=" not in kv:
            die(f"--set 需为 k=v 形式: {kv}")
        k, v = kv.split("=", 1)
        if k == "单号" and not re.match(r"^(REQ|DTS)\w+$", v):
            die(f"单号「{v}」不合法:必须 REQ 或 DTS 开头。多个单号须先与用户确认拆分/合并。", 2)
        if k in ("工号", "基线分支", "分支名") and re.search(r"[\\\s~^:?*\[\]]", v):
            die(f"{k}「{v}」含非法字符(空格/反斜杠等不能进 git 分支名)。"
                "Windows whoami 返回「域\\用户名」时,工号只取反斜杠后的部分。", 2)
        st["config"][k] = v
    if st["config"].get("单号") and not st["config"].get("单号类型"):
        st["config"]["单号类型"] = "feat" if st["config"]["单号"].startswith("REQ") else "fix"
    # 需求文档:单号与需求完全解耦(单号只管 git 命名,需求只管做什么),内容对不对只有用户能判定,
    # 机器只拦"路径是假的"这一种硬错;"拿对文档"靠 config_confirm 的单独确认(展示摘录给用户核实)
    new_keys = [kv.split("=", 1)[0] for kv in (args.set or []) if "=" in kv]
    doc = st["config"].get("需求文档", "")
    if "需求文档" in new_keys and not os.path.exists(doc):
        save_state(st)
        die(f"需求文档「{doc}」不存在——路径必须真实可读。"
            "用户口述/粘贴的需求须先原文照录落盘(如 docs/req/REQ-<单号>.md)并经用户确认,再以该路径 --set。", 2)
    if step.get("require_sets"):
        missing = [k for k in step["require_sets"] if not st["config"].get(k)]
        if missing:
            die("配置缺失,禁止推进: " + "、".join(missing) + "(用 --set 补齐;缺失项应询问用户)", 2)
        if "基线分支" in step["require_sets"] and not st["config"].get("分支名"):
            st["config"]["分支名"] = "{基线分支}_{工号}_{单号}".format(**st["config"])
    if step.get("user_ack") and not args.ack:
        die("本步需要用户确认:必须携带 --ack \"用户确认原话\"。没有拿到用户回复就调用 done = 违规。", 2)
    if step.get("user_ack") and args.ack:
        ok, why = _ack_verified(st, args.ack)
        if not ok:
            die(why, 2)
    if step.get("choice_key"):
        if args.choice not in step.get("choices", []):
            die(f"--choice 必须为: {'|'.join(step['choices'])}", 2)
        st["choices"][step["choice_key"]] = args.choice
    fails = check_evidence(step, st)
    if fails:
        save_state(st)
        die("证据不足,拒绝推进:\n  - " + "\n  - ".join(fails), 2)
    advance(flow, st, sid, step, "done", args.ack or "")


def cmd_skip(flow, st, args):
    sid = st["current"]
    step = flow["steps"][sid]
    if not step.get("skippable"):
        die(f"步骤 {sid} 不可跳过。", 2)
    if not args.reason:
        die("skip 必须 --reason 说明理由(留痕)。", 2)
    advance(flow, st, sid, step, "skipped", args.reason)


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
        ctx = (";" + ";".join(parts)) if parts else ""
        me = os.path.abspath(sys.argv[0])
        print(f"[mae-flow 状态] 当前步骤: {sid}({step['title']}){ctx};{perms_line(step)}。"
              f"执行 python \"{me}\" current 获取指令(勿搜索脚本位置,以此路径为准),"
              f"禁止做当前步骤之外的流程动作。"
              f"(用户与流程无关的问答/阅读/分析不受此限,照常回应;但无关的源码改动应引导用户开 worktree,勿混入交付分支)")
        return
    print(json.dumps(st, ensure_ascii=False, indent=2))


def _test_patterns(st):
    """测试路径 pattern(per-repo opt-in):config「测试路径」(逗号分隔的正则)优先,
    否则读 .mae-flow-defaults.json 的「测试路径」数组;未配置返回 []=不启用收紧,行为与旧版一致。"""
    raw = ((st or {}).get("config", {}) or {}).get("测试路径", "")
    if raw:
        return [x.strip() for x in raw.split(",") if x.strip()]
    try:
        v = json.load(open(DEFAULTS_PATH, encoding="utf-8")).get("测试路径", [])
        return v if isinstance(v, list) else []
    except Exception:
        return []


# Bash 命令里能落盘的动作(cmd/PowerShell/git-bash 常见写法都算)
WRITEISH = (r"(sed\s+-i|>>?\s*|\btee\s+|\bcp\s+|\bmv\s+|\bcopy\b|\bmove\b|\bdel\b|\brm\s+"
            r"|Set-Content|Out-File|Add-Content|perl\s+-i|git\s+apply|\bpatch\b)")


def cmd_gate(flow, st, args):
    sid = st["current"] if st else None
    step = flow["steps"].get(sid, {}) if st else {}
    # NTFS 不区分大小写:所有路径匹配一律 re.I
    if args.what == "edit":
        p = norm(args.arg)
        if p.lower().endswith((".comet.yaml", ".openspec.yaml")):
            die("禁止手动编辑 comet/openspec 状态文件(.comet.yaml/.openspec.yaml),它们由 comet-state 维护(黑名单#4)。", 2)
        if re.search(r"\.mae-flow\.json(\.\w+)*$|\.mae-flow-history\.jsonl$", p, re.I):
            die("流程状态/令牌/历史账本文件由 mae-flow 与 hook 维护,禁止直接编辑。推进用 done,人工修复用 goto <step> --force。", 2)
        if re.search(r"(^|/)\.env(\.[\w.-]+)?$", p, re.I):
            die(".env 类密钥文件禁止写入(凭据保护);确需修改请用户手动操作。", 2)
        plugin_root = norm(os.path.abspath(os.path.join(HERE, ".."))).lower()
        if norm(os.path.abspath(args.arg)).lower().startswith(plugin_root + "/"):
            die("禁止修改插件自身(flow/steps/hooks/scripts):流程规则不是交付改动的对象。", 2)
        if re.search(flow["specs_truth"], p, re.I) and not step.get("allow_specs_write"):
            die(f"openspec/specs/ 为真相源,当前步骤 {sid or '未初始化'} 禁止写入(黑名单#3)。", 2)
        if any(re.search(pat, p, re.I) for pat in flow["source_patterns"]):
            if not st:
                die("流程未初始化(无 .mae-flow.json)。禁止直接修改源码——请先按 skill 走 mae-flow init。", 2)
            if not step.get("allow_source_edit"):
                die(f"当前步骤 {sid}({step.get('title','')})禁止修改源码;先 mae-flow current 查看该做什么。", 2)
            tp = _test_patterns(st) if step.get("tests_only") else []
            ul = (st or {}).get("unlock") or {}
            unlocked = ul.get("scope") == "source" and ul.get("step") == sid
            if tp and not unlocked and not any(re.search(t, p, re.I) for t in tp):
                die(f"当前步骤 {sid} 仅允许写测试路径(本仓配置: {'|'.join(tp)})。"
                    "UT 暴露的疑似源码缺陷不是死路:自查确认后带报告呈用户裁决,用户判定确为代码缺陷时执行 "
                    "mae-flow unlock source --reason <裁决结论> --ack \"用户原话\" 解锁本步修复;"
                    "禁止未经用户裁决自行改源码。", 2)
        sys.exit(0)
    if args.what == "bash":
        c = norm(args.arg)
        # 按 token 匹配路径类 pattern:整串匹配时 `(^|/)src/` 对空格后的相对路径
        # (如 `sed -i ... src/main.c`)永远不命中
        toks = [t for t in re.split(r"""[\s;|&()<>'"]+""", c) if t]

        def hits_path(pat):
            return any(re.search(pat, t, re.I) for t in toks)

        m = re.search(r"git\s+(?:checkout\s+-[bB]|switch\s+-[cC])\s+(\S+)"
                      r"|git\s+branch\s+(?:-[mM]\s+\S+\s+)?(?!-)(\S+)\s*$", c)
        if m and st:
            name = m.group(1) or m.group(2)
            want = st["config"].get("分支名", "")
            if want and name != want:
                die(f"分支名 {name} 不符合约定 {want}(内部流程建议的 feature/xx 命名一律拒绝)。", 2)
        m = re.search(r"git\s+commit\b.*?-m\s+(?:\"([^\"]*)\"|'([^']*)'|(\S+))", c)
        if m and st:
            msg = m.group(1) or m.group(2) or m.group(3) or ""
            dan = st["config"].get("单号", "")
            if dan and not re.match(r"^\[" + re.escape(dan) + r"\]\[(feat|fix)\]", msg):
                die(f"commit message「{msg}」不符合 [{dan}][feat|fix]描述 格式。", 2)
        if re.search(r"git\s+push\b.*(--force|-f\b)", c) or re.search(r"git\s+push\b.*\s\+\S+", c):
            die("禁止 force push(含 +refspec 形式)。", 2)
        if re.search(r"dispatch\.py", c):
            die("hook 分发器(dispatch.py)由 harness 自动调用,禁止手动执行——这是伪造 agent 收尾令牌的通道。", 2)
        # 危险命令 denylist(社区共识高信号项;普通目录的 rm -r 不拦,只拦毁灭性目标)
        if re.search(r"(curl|wget|iwr|invoke-webrequest)[^|&;]*\|\s*(sudo\s+)?(sh|bash|zsh|iex|powershell)", c, re.I):
            die("危险命令拦截:管道执行远程脚本(供应链风险)。确需执行请用户手动运行。", 2)
        if re.search(r"git\s+clean\s+-\S*[xX]", c):
            die("危险命令拦截:git clean -x 会删除 ignore 文件(含 mae-flow 状态与令牌)。", 2)
        if re.search(r"\brm\s+-\S*r", c, re.I) or re.search(r"\b(rd|rmdir)\s+/s", c, re.I):
            nuke = {"/", "~", "*", ".", "..", "$home", "%userprofile%"}
            for t in toks[1:]:
                tl = t.lower()
                if not t.startswith("-") and (tl in nuke or re.match(r"^[a-z]:[\\/]*$", tl)):
                    die(f"危险命令拦截:对「{t}」的递归删除。确需执行请用户手动运行。", 2)
        if st and re.search(r"git\s+worktree\s+add", c):
            die("本流程约定 branch 隔离,worktree 会使 mae-flow 状态机失联(新目录无状态文件,gate 全拦)。"
                "若是为并行另一单开工作区:请用户手动建 worktree 并在新目录另起会话独立 init,本流程内不执行该命令。", 2)
        writeish = re.search(WRITEISH, c, re.I)
        if writeish and hits_path(r"\.mae-flow(\.json|-history\.jsonl)"):
            die("流程状态/历史账本文件由 mae-flow 维护,禁止经 Bash 改写/删除。", 2)
        if writeish and hits_path(flow["specs_truth"]) and not step.get("allow_specs_write"):
            die(f"openspec/specs/ 为真相源,当前步骤 {sid or '未初始化'} 禁止经 Bash 写入(黑名单#3)。", 2)
        if writeish and any(hits_path(pat) for pat in flow["source_patterns"]):
            if not st:
                die("流程未初始化(无 .mae-flow.json)。禁止经 Bash 写源码——请先按 skill 走 mae-flow init。", 2)
            if not step.get("allow_source_edit"):
                die(f"当前步骤 {sid} 禁止经 Bash 写源码文件。", 2)
            tp = _test_patterns(st) if step.get("tests_only") else []
            ul = (st or {}).get("unlock") or {}
            if tp and not (ul.get("scope") == "source" and ul.get("step") == sid):
                bad = [t2 for t2 in toks
                       if any(re.search(pat, t2, re.I) for pat in flow["source_patterns"])
                       and not any(re.search(t, t2, re.I) for t in tp)]
                if bad:
                    die(f"当前步骤 {sid} 仅允许写测试路径(本仓配置: {'|'.join(tp)});"
                        f"命中非测试源码: {'、'.join(bad[:3])}。经用户裁决确为代码缺陷时用 unlock source 解锁。", 2)
        sys.exit(0)
    die("gate 用法: gate edit <路径> | gate bash <命令>")


def cmd_template(flow, args):
    """打印模板绝对路径(story|chain)。子 agent/会话在项目目录里搜不到插件安装目录,
    必须经本命令拿路径。"""
    name = {"story": "STORY-TEMPLATE.md", "chain": "CHAIN-TEMPLATE.md",
            "grill": "GRILL-PREP-TEMPLATE.md", "review": "REVIEW-TEMPLATE.md"}[args.kind]
    p = os.path.abspath(os.path.join(HERE, "..", "skills", "mae-flow", "assets", name))
    if not os.path.exists(p):
        die(name + " 模板缺失: " + p)
    print(p)


def cmd_envcheck(flow, args):
    fails = run_env_checks(force_all=True)
    names = [c["name"] for c in flow.get("env_checks", [])]
    for n in names:
        print(("❌ " if n in fails else "✅ ") + n)
    if fails:
        sys.exit(2)


def cmd_doctor(flow, st, args):
    sid = st["current"]
    step = flow["steps"][sid]
    print(f"项目根(状态文件所在): {os.getcwd()}")
    print(f"当前步骤: {sid} — {step['title']}")
    cur = sh("git branch --show-current")
    want = st["config"].get("分支名", "(未设置)")
    print(("✅" if cur == want else "❌") + f" 分支: 当前 {cur or '未知'} / 约定 {want}")
    cn = st["config"].get("CHANGE_NAME", "")
    yml = f"openspec/changes/{cn}/.comet.yaml" if cn else ""
    if yml and os.path.exists(yml):
        ph = re.search(r"phase:\s*(\S+)", open(yml, encoding="utf-8").read())
        print(f"✅ change: {cn},phase={ph.group(1) if ph else '?'}")
    else:
        print(f"{'⚠' if not cn else '❌'} change: " + (cn + " 的 .comet.yaml 不存在" if cn else "CHANGE_NAME 未设置(open 之前属正常)"))
    fails = check_evidence(step, st)
    if fails:
        print("❌ 当前步证据未满足:")
        for x in fails:
            print("   - " + x)
    else:
        print("✅ 当前步证据已满足(或本步无证据要求)")
    ef = run_env_checks()
    print(("✅ 环境实测: 全部就绪" if not ef else "❌ 环境实测未就绪: " + "、".join(ef)))
    for k in ("单号", "编译方式", "UT生成方式"):
        print(("✅" if st["config"].get(k) else "❌") + f" 配置 {k}: {st['config'].get(k, '缺失')}")
    # 观测项(公司机金丝雀关注):ack 验真存储 与 UTRUN 令牌——两者依赖 harness payload 字段
    try:
        n = len(json.loads(open(STATE_PATH + ".usermsg", encoding="utf-8").read() or "[]"))
        print(f"✅ ack 验真存储: {n} 条用户输入" if n else "⚠ ack 验真存储: 空(验真降级中)")
    except Exception:
        print("⚠ ack 验真存储: 不存在(harness 未提供 prompt/tool_response 字段时属正常,验真自动降级)")
    try:
        tok = json.loads(open(STATE_PATH + ".tokens", encoding="utf-8").read()).get("UTRUN", "")
        uts = tok.get("at") if isinstance(tok, dict) else tok
        print(("✅" if uts else "⚠") + f" UTRUN 令牌(UT 命令真实调起): {uts or '未记录(尚未跑 UT,或 PostToolUse-Bash 未触发)'}")
    except Exception:
        print("⚠ UTRUN 令牌: 无令牌文件")


def cmd_report(flow, st, args):
    """按 history 时间戳输出各步骤耗时,供交付复盘/团队度量。"""
    def ts(s):
        return time.mktime(time.strptime(s, "%Y-%m-%d %H:%M:%S"))

    def fmt(sec):
        sec = int(sec)
        return f"{sec // 3600}h{sec % 3600 // 60:02d}m" if sec >= 3600 else f"{sec // 60}m{sec % 60:02d}s"

    cfg = st.get("config", {})
    print(f"单号: {cfg.get('单号', '?')}  分支: {cfg.get('分支名', '?')}  开始: {st['started']}")
    prev, total = ts(st["started"]), 0
    for h in st["history"]:
        cur = ts(h["at"])
        dur = max(0, cur - prev)
        prev, total = cur, total + dur
        note = ("  # " + h["note"][:40]) if h.get("note") else ""
        print(f"  {h['step']:<18} {h['result']:<10} {fmt(dur):>8}{note}")
    print(f"合计: {fmt(total)}  当前步骤: {st['current']}")
    # 摩擦统计:量化本单的 harness 干预(验收线指标:gate 误拦/单 应为个位数)
    fr = _friction_from_log(st)
    goto_n = sum(1 for h in st["history"] if str(h.get("result", "")).startswith("goto:"))
    if fr:
        print(f"摩擦统计: gate 拦截 {fr['gate拦截']} 次 · 子agent契约打回 {fr['契约打回']} 次"
              f" · hook 异常 {fr['hook异常']} 次 · goto 人工跳转 {goto_n} 次")
    else:
        print(f"摩擦统计: hook 日志不可读 · goto 人工跳转 {goto_n} 次")


def cmd_report_all():
    """聚合历史交付账本:每单一行 + 均值,团队度量/推广数据出口。无状态命令,无在途单也可用。"""
    if not os.path.exists(HISTORY_PATH):
        print("[mae-flow] 暂无历史交付记录(每单交付完成后开下一单时自动记账)。")
        return
    recs = []
    for line in open(HISTORY_PATH, encoding="utf-8", errors="replace"):
        try:
            recs.append(json.loads(line))
        except Exception:
            pass   # 坏行跳过,不因单行损坏丢整本账
    if not recs:
        print("[mae-flow] 账本为空或不可解析: " + HISTORY_PATH)
        return

    def fmt(sec):
        sec = int(sec)
        return f"{sec // 3600}h{sec % 3600 // 60:02d}m" if sec >= 3600 else f"{sec // 60}m{sec % 60:02d}s"

    print(f"{'单号':<16} {'workflow':<8} {'耗时':>7} {'gate拦':>5} {'打回':>4} {'goto':>4}  完成时间")
    for r in recs:
        print(f"{r.get('单号', '?'):<16} {r.get('workflow', '?'):<8} {fmt(r.get('耗时秒', 0)):>7} "
              f"{str(r.get('gate拦截', '-')):>5} {str(r.get('契约打回', '-')):>4} "
              f"{str(r.get('goto次数', '-')):>4}  {r.get('结束', '?')}")
    n = len(recs)
    print(f"合计 {n} 单 · 平均耗时 {fmt(sum(r.get('耗时秒', 0) for r in recs) / n)}"
          f" · goto 总计 {sum(r.get('goto次数', 0) for r in recs)} 次")


def cmd_goto(flow, st, args):
    if not args.force:
        die("goto 是人工修复通道,必须 --force。")
    if not args.ack:
        die("goto 是**人工**修复通道,必须携带用户明确授权:--ack \"用户原话\"。"
            "证据不足该修证据/重跑 agent,禁止用 goto 绕过关卡——绕过 = 最严重违规。", 2)
    ok, why = _ack_verified(st, args.ack)
    if not ok:
        die("goto 授权验真失败:" + why, 2)
    if args.step not in flow["steps"]:
        die("未知步骤: " + args.step)
    st.pop("unlock", None)   # 跳转同样使解锁失效
    st["history"].append({"step": st["current"], "result": "goto:" + args.step,
                          "note": "manual", "at": time.strftime("%Y-%m-%d %H:%M:%S")})
    st["current"] = args.step
    save_state(st)
    print_current(flow, st)


def cmd_unlock(flow, st, args):
    """用户裁决通道:UT 揭出疑似代码缺陷、用户判定"确为代码缺陷,本单修"后,
    解锁当前步的测试路径收紧(仅本步有效,done/goto 自动失效,历史留痕)。
    不是绕过 gate 的后门:--ack 走与 done 相同的三级验真,伪造授权会被拒;
    未启用收紧的仓也可执行(裁决留痕,无实际解锁动作)。"""
    if not args.reason:
        die("unlock 必须 --reason 说明裁决结论(如\"SUSPECTED_BUG#1 确认为代码缺陷\"),留痕供审计。", 2)
    if not args.ack:
        die("unlock 必须携带用户裁决原话:--ack \"用户原话\"。未经用户裁决解锁源码 = 最严重违规。", 2)
    ok, why = _ack_verified(st, args.ack)
    if not ok:
        die("unlock 授权验真失败:" + why, 2)
    sid = st["current"]
    step = flow["steps"][sid]
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    st["unlock"] = {"scope": args.what, "step": sid, "at": now, "reason": args.reason}
    st["history"].append({"step": sid, "result": "unlock:" + args.what, "note": args.reason, "at": now})
    save_state(st)
    if step.get("tests_only") and _test_patterns(st):
        print(f"[mae-flow] 已解锁本步({sid})的源码修改(仅本步有效,推进后自动失效)。"
              "修复后:编译 → 按 [单号][类型] 规范 commit → 重启 ut-generator-agent 对新代码重新收尾"
              "(新鲜度绑定:源码已变,旧 UT 证据过期,重跑不是可选项)。")
    else:
        print("[mae-flow] 本仓未启用测试路径收紧,无需实际解锁;裁决已留痕。"
              "直接修复源码 → 编译 → 按规范 commit → 重启 ut-generator-agent 重新收尾。")


class MFParser(argparse.ArgumentParser):
    """参数错误即教学:argparse 默认英文 usage 弱模型读不懂会瞎试第二次。
    报错直接给中文速查 + 可复制的正确命令(错误即文档;子命令解析器自动继承本类)。"""

    def error(self, message):
        me = os.path.abspath(sys.argv[0])
        print("[mae-flow] 参数错误: " + message, file=sys.stderr)
        print("正确用法(高频三条,直接复制):\n"
              f"  python \"{me}\" current\n"
              f"  python \"{me}\" done --ack \"用户原话\" [--choice 值] [--set 键=值]\n"
              f"  python \"{me}\" init\n"
              "其余子命令: status|doctor|report|envcheck|skip|goto|unlock|template(用法见 skill 指令)。\n"
              "注意:子命令不带连字符(是 current 不是 --current);done 的 --set 可重复,值含空格要加引号。",
              file=sys.stderr)
        sys.exit(2)


def main():
    ap = MFParser(prog="mae-flow")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sub.add_parser("current")
    d = sub.add_parser("done")
    d.add_argument("--ack"); d.add_argument("--choice"); d.add_argument("--set", action="append")
    s = sub.add_parser("skip"); s.add_argument("--reason")
    t = sub.add_parser("status"); t.add_argument("--inject", action="store_true")
    g = sub.add_parser("gate"); g.add_argument("what", choices=["edit", "bash"]); g.add_argument("arg")
    o = sub.add_parser("goto"); o.add_argument("step"); o.add_argument("--force", action="store_true"); o.add_argument("--ack")
    u = sub.add_parser("unlock"); u.add_argument("what", choices=["source"]); u.add_argument("--reason"); u.add_argument("--ack")
    sub.add_parser("doctor")
    sub.add_parser("envcheck")
    r = sub.add_parser("report")
    r.add_argument("--all", action="store_true")   # 聚合历史账本(无在途单也可用)
    tp = sub.add_parser("template")
    tp.add_argument("kind", nargs="?", default="story", choices=["story", "chain", "grill", "review"])
    args = ap.parse_args()

    root, _ = find_project_root()
    if root != os.getcwd():
        os.chdir(root)
        if args.cmd != "gate":   # gate 保持输出纯净(stderr 会回传模型)
            print(f"[mae-flow] 调用目录非项目根,已定位到: {root}", file=sys.stderr)

    global FLOW
    flow = load_flow()
    FLOW = flow
    st = load_state()
    if args.cmd == "envcheck":
        return cmd_envcheck(flow, args)
    if args.cmd == "template":
        return cmd_template(flow, args)
    if args.cmd == "init":
        return cmd_init(flow, args)
    if args.cmd == "gate":
        return cmd_gate(flow, st, args)
    if args.cmd == "report" and args.all:
        return cmd_report_all()   # 账本聚合是无状态命令,不要求存在在途单
    if st is None:
        die("流程未初始化,先执行 init。")
    if args.cmd == "current":
        return print_current(flow, st)
    if args.cmd == "done":
        return cmd_done(flow, st, args)
    if args.cmd == "skip":
        return cmd_skip(flow, st, args)
    if args.cmd == "status":
        return cmd_status(flow, st, args)
    if args.cmd == "goto":
        return cmd_goto(flow, st, args)
    if args.cmd == "unlock":
        return cmd_unlock(flow, st, args)
    if args.cmd == "doctor":
        return cmd_doctor(flow, st, args)
    if args.cmd == "report":
        return cmd_report(flow, st, args)


if __name__ == "__main__":
    main()
