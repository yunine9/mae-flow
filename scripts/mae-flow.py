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
  mae-flow.py accept-risk <agent> --reason 风险 --ack 用户原话
                                         用户确认后只放行当前步骤的单个 Agent 令牌
  mae-flow.py moonlight on|off|report|defer|repair|finalize
                                         无人值守开发、带遗留推送与晨间修复闭环
  mae-flow.py exit [--reason 文本] [--ack 用户原话]
                                         保留现场并退出流程,之后按普通开发处理
退出码:0 成功;1 参数/状态错误;2 gate 拦截或证据不足。
"""
import argparse, glob as globmod, hashlib, json, os, re, shutil, subprocess, sys, tempfile, time

from comet_compat import ensure_direct_mode_compat

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
EXIT_PATH = ".mae-flow.json.exited"  # 复用既有 .mae-flow.json* ignore;存在时 Hook 不再接管普通开发
MOONLIGHT_INTENT_PATH = STATE_PATH + ".moonlight-intent"
HISTORY_PATH = ".mae-flow-history.jsonl"   # 交付历史账本:终态 init 时追加本单摘要(gitignored,gate 防篡改)
DEFAULTS_PATH = ".mae-flow-defaults.json"  # 仓库预设(团队提交进仓):require_sets 步骤 current 时预填展示
FLOW = None                      # main() 加载后填充,供证据函数读取 env_checks 等
MOONLIGHT_REPORT_PATH = os.path.join(".mae-flow-work", "moonlight-report.md")

# 月光宝盒允许“尽力后带遗留推进”的步骤。普通模式完全不读取这张表。
# build 同时承担实现收口和首次编译；只有工作区已经提交稳定后才能 defer。
MOONLIGHT_QUALITY_STEPS = {
    "env_setup": "environment",
    "build": "compile",
    "rf_compile": "compile",
    "tw_compile": "compile",
    "verify_post_ponytail_compile": "compile",
    "verify_recompile": "compile",
    "rf_codecheck": "codecheck",
    "tw_codecheck": "codecheck",
    "verify_codecheck": "codecheck",
    "rf_ut": "ut",
    "tw_ut": "ut",
    "verify_ut": "ut",
    "verify_comet": "comet",
}

MOONLIGHT_REPAIR_ENTRY = {
    "review": "rf_compile",
    "tweak": "tw_compile",
    "full": "verify_recompile",
    "hotfix": "verify_recompile",
}

# source_patterns 只适合识别目录，不能承担跨仓源码真相（顶层 include/lib/app 已真实漏过）。
# 扩展名与构建入口作为保守底座；仓库可用 defaults/config 的「源码路径」补私有布局。
SOURCE_EXTS = (
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl", ".ipp", ".tpp",
    ".java", ".kt", ".kts", ".groovy", ".scala", ".py", ".pyi", ".go", ".rs", ".cs",
    ".js", ".jsx", ".ts", ".tsx", ".vue", ".swift", ".m", ".mm", ".proto", ".sql",
    ".s", ".asm", ".cmake", ".gradle", ".sln", ".vcxproj", ".props", ".targets",
)
SOURCE_FILENAMES = {
    "cmakelists.txt", "makefile", "gnumakefile", "pom.xml", "build.gradle", "settings.gradle",
    "gradle.properties", "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "cargo.toml", "cargo.lock", "go.mod", "go.sum", "meson.build", "build.ninja",
}


def find_project_root(start=None):
    """从 start(默认 cwd)向上定位项目根,消除"模型 cd 进子目录后调用"的错位:
    优先找已有 .mae-flow.json 或退出标记;没有(init 场景)则找 .git / openspec 标记;
    都没有就留在原地。返回 (root, 是否已有状态文件)。"""
    d = os.path.abspath(start or os.getcwd())
    probe = d
    while True:
        if os.path.exists(os.path.join(probe, STATE_PATH)) or os.path.exists(os.path.join(probe, EXIT_PATH)):
            return probe, os.path.exists(os.path.join(probe, STATE_PATH))
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


def _moonlight(st):
    return bool(((st or {}).get("moonlight") or {}).get("enabled"))


def _moonlight_data(st):
    return (st or {}).setdefault("moonlight", {})


def _moonlight_unresolved(st):
    return [x for x in (_moonlight_data(st).get("issues") or []) if not x.get("resolved_at")]


def _moonlight_resolve_kind(st, kind):
    """某一质量关真实通过后，关闭之前同类遗留；新一轮 defer 会另建记录。"""
    if not _moonlight(st):
        return
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for issue in _moonlight_unresolved(st):
        if issue.get("kind") == kind:
            issue["resolved_at"] = now
            issue["resolved_head"] = sh("git rev-parse --verify HEAD")


def _moonlight_step_kind(sid):
    return MOONLIGHT_QUALITY_STEPS.get(sid, "")


def _moonlight_can_block(sid):
    """硬阻塞出口用于非质量工作；质量关有 defer，push 有 push-failed。build 例外：
    它既是实现步骤，也可能遇到需求/依赖阻塞。"""
    return sid == "build" or (
        sid not in MOONLIGHT_QUALITY_STEPS
        and sid not in ("push", "moonlight_review", "end")
    )


def _moonlight_issue_context(st):
    issues = _moonlight_unresolved(st)
    if not issues:
        return "当前无已记录遗留。"
    return "\n".join(
        f"- {x.get('id', '?')} [{x.get('kind', '?')}] {x.get('reason', '')}"
        for x in issues[-8:])


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


def _dirty_paths():
    """返回当前工作区脏路径。状态文件与过程目录由流程自己维护，不算交付改动。"""
    out = []
    for line in sh("git -c core.quotepath=false status --porcelain").splitlines():
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        p = norm(parts[1].split(" -> ")[-1].strip().strip('"'))
        if not p or p.startswith(".mae-flow") or p.startswith(".codecheckcli/"):
            continue
        out.append(p)
    return list(dict.fromkeys(out))


def _path_fingerprint(path):
    """记录初始化时脏文件的内容，防止同一路径后来被本单继续修改却仍冒充“原有脏文件”。"""
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
            # git status 可能把整棵未跟踪目录折叠成一个路径。这里只做浅层指纹，避免初始化时
            # 递归扫描巨大的构建目录；源码目录另有任务卡前“工作区必须干净”的硬检查。
            for name in sorted(os.listdir(p)):
                fp = os.path.join(p, name)
                s = os.stat(fp)
                h.update((name + "\0" + str(s.st_size) + "\0" + str(s.st_mtime_ns)).encode(
                    "utf-8", errors="replace"))
        else:
            h.update(b"missing\0")
    except OSError as e:
        h.update(("error:" + str(e)).encode("utf-8", errors="replace"))
    return h.hexdigest()


def _step_entered_at(st):
    """当前步骤的进入时间；旧状态没有精确记录时沿用 started。"""
    sid = st.get("current", "")
    for h in reversed(st.get("history", [])):
        if _resolved_next(FLOW or {}, st, h.get("step", "")) == sid or str(h.get("result", "")) == "goto:" + sid:
            return h.get("at", st.get("started", ""))
    return st.get("started", "")


def _allowed_set_keys(step):
    """配置只允许在声明它的步骤写入，防止后续把基线改成 HEAD 等方式洗空检查范围。"""
    keys = set(step.get("require_sets", []))
    if "基线分支" in keys:
        keys.add("分支名")
    return keys


def _validate_config_value(key, value):
    if not value:
        return "配置值不能为空"
    if key == "单号" and not re.fullmatch(r"(?:REQ|DTS)\w+", value):
        return "单号必须以 REQ 或 DTS 开头"
    if key in ("工号", "基线分支", "分支名") and re.search(r"[\\\s~^:?*\[\];&|`$<>()\"']", value):
        return "包含 git/shell 不安全字符"
    if key == "CHANGE_NAME" and not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        return "change 名只允许字母、数字、点、下划线和短横线"
    return ""


def _configured_source_patterns(st):
    """仓库私有源码布局；config 字符串优先，defaults 支持字符串或正则数组。"""
    raw = ((st or {}).get("config", {}) or {}).get("源码路径", "")
    if raw:
        return ([x.strip() for x in raw.split(",") if x.strip()]
                if isinstance(raw, str) else list(raw) if isinstance(raw, list) else [])
    try:
        v = json.load(open(DEFAULTS_PATH, encoding="utf-8")).get("源码路径", [])
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v if isinstance(v, list) else []
    except Exception:
        return []


def _matches_pattern(path, pattern):
    try:
        return bool(re.search(pattern, path, re.I))
    except re.error:
        return False


def _is_source_path(path, st=None, flow=None):
    """跨仓统一源码判定：扩展名/构建文件 + 通用目录 + 仓库私有路径，任一命中即算。

    Edit gate、Bash gate、令牌新鲜度和 UT 源码回流必须共用它，避免四套口径漂移。
    """
    p = norm(path).strip().strip('"\'')
    if p.endswith("(未提交)"):
        p = p[:-len("(未提交)")]
    low = p.lower()
    base = os.path.basename(low)
    if low.endswith(SOURCE_EXTS) or base in SOURCE_FILENAMES:
        return True
    rules = list((flow or FLOW or {}).get("source_patterns", [])) + _configured_source_patterns(st)
    return any(_matches_pattern(p, pat) for pat in rules)


def _is_review(st):
    return (st.get("choices", {}) or {}).get("workflow") == "review"


def _ensure_review_base(st):
    """记录评审返工开始前的原 MR HEAD。

    新流程在 branch_create 离开前直接取 HEAD；旧版在途状态优先按进入 rf_triage 的
    history 时间反推，保证升级后不会把整个原需求 diff 当成本轮增量。
    """
    if not _is_review(st):
        return "", "当前不是评审返工流程"
    old = st.get("review_base_head", "")
    if old and sh(f"git cat-file -t {old}") == "commit":
        return old, ""
    at = ""
    for h in st.get("history", []):
        if h.get("step") == "branch_create":
            at = h.get("at", "")
            break
    base = sh(f'git rev-list -1 --before="{at}" HEAD') if at else ""
    if not base:
        review_doc = "docs/review/REVIEW-" + st.get("config", {}).get("单号", "") + ".md"
        added = sh(f'git log --diff-filter=A -1 --format=%H -- "{review_doc}"')
        if added:
            base = sh(f"git rev-parse {added}^")
    if not base:
        return "", ("无法自动恢复返工基点。不要用当前 HEAD 代替，否则增量范围会变成空；"
                     "请把日志与原 MR 返工前 commit 交维护人处理")
    st["review_base_head"] = base
    save_state(st)
    return base, ""


def _scope_base(st):
    """本轮质量检查的代码基点：review 只看返工增量，其余流程看需求基线。"""
    if _is_review(st):
        return _ensure_review_base(st)
    base = st.get("config", {}).get("基线分支", "")
    if not base:
        return "", "缺基线分支配置"
    if not sh(f"git rev-parse --verify {base}"):
        return "", f"基线分支「{base}」无法解析(不存在/拼写错),diff 无从算起——先修配置"
    return base, ""


def _scope_diff(st):
    base, err = _scope_base(st)
    if err:
        return "", err
    return (f"{base}..HEAD" if _is_review(st) else f"{base}...HEAD"), ""


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


def _source_changed_since(head, st=None):
    """令牌签发时 HEAD 之后,源码是否变化:已提交 diff + 工作区未提交改动。
    返回 (变更清单, 错误);基点不可解析(amend/rebase/GC)属错误,由调用方判拒——重签令牌即可恢复。"""
    if not re.fullmatch(r"[0-9a-f]{7,64}", head):
        return None, "令牌基点格式异常"
    cur = sh("git rev-parse --verify HEAD")
    changed = []
    if cur and cur != head:
        # cat-file 探基点存在性(不用 rev-parse ^{commit}:^ 在 Windows cmd 是转义符)
        if sh(f"git cat-file -t {head}") != "commit":
            return None, "令牌基点 commit 不可解析(经历过 amend/rebase?)"
        # core.quotepath=false:否则非 ASCII 文件名被引号+八进制转义,pattern 匹配不到 = 漏检
        out = sh(f"git -c core.quotepath=false diff --name-only {head} {cur}")
        changed += [f for f in out.splitlines() if f and _is_source_path(f, st)]
    for line in sh("git -c core.quotepath=false status --porcelain").splitlines():
        # 按空白切"状态 路径",不用列偏移:sh() 会 strip 首行前导空格(' M' → 'M'),偏移取路径会错位
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        f = parts[1].split(" -> ")[-1].strip().strip('"')
        if f and _is_source_path(f, st):
            changed.append(f + "(未提交)")
    return changed, ""


RISK_AGENT_LABELS = {
    "COMPILE": "没有可验证的编译成功证据，代码可能无法构建",
    "CODECHECK": "CodeCheck 修复 Agent 没有合法令牌；现场复核仍会执行，真实遗留告警不会被放过",
    "UT": "没有可验证的 UT 生成/运行通过证据，回归问题可能进入后续阶段",
    "STORY": "没有可验证的 STORY 专项 Agent 收尾证据",
    "ENV": "环境修复 Agent 没有合法收尾，后续工具可能不可用",
    "GRILL": "需求追问 Agent 没有合法收尾，需求边界可能仍有遗漏",
    "ASKUSER": "宿主没有签发用户交互令牌；本次风险确认本身仍必须匹配用户真实原话",
    "UTRUN": "没有观测到 UT 命令真实调起",
}


def _risk_acceptance(kind, st):
    rec = (st.get("risk_acceptances", {}) or {}).get(kind, {})
    if not rec:
        return False, ""
    if rec.get("step") != st.get("current"):
        return False, f"旧风险确认属于步骤 {rec.get('step', '?')}"
    entered = _step_entered_at(st)
    if rec.get("at", "") < entered:
        return False, "旧风险确认早于当前步骤"
    task = (st.get("agent_tasks", {}) or {}).get(kind, {})
    if rec.get("task_sha256") and rec.get("task_sha256") != task.get("sha256", ""):
        return False, "风险确认绑定的任务卡已经变化"
    head = rec.get("head", "")
    changed, err = _source_changed_since(head, st) if head else ([], "风险确认缺少 HEAD")
    if err:
        return False, "风险确认新鲜度无法核实:" + err
    if changed:
        return False, "风险确认后代码发生变化:" + "、".join(changed[:5])
    return True, ""


def _risk_option(kind, expired=""):
    me = os.path.abspath(sys.argv[0])
    risk = RISK_AGENT_LABELS.get(kind, f"{kind} 专项 Agent 没有可验证的质量证据")
    prefix = ("已有风险确认已失效(" + expired + ")。" if expired else "")
    return (prefix + "如果不想继续重跑，可把以下风险原样展示给用户并让用户明确选择：" + risk
            + "。用户确认承担风险后执行: python \"" + me + "\" accept-risk " + kind.lower()
            + " --reason \"" + risk + "\" --ack \"<用户确认原话>\"；"
              "它只放行当前步骤的该 Agent 令牌，其他机器检查仍照常执行。")


def ev_agent_ran(spec, st):
    """默认硬证据:本步期间对应子 agent 真实收尾过。令牌由 SubagentStop hook(harness 调用)在
    契约标记验证通过后写入,模型无法伪造(令牌文件被 gate 双拦,手动调 dispatch 也被拦)。
    新格式令牌绑定签发时 HEAD:签发后源码再变(提交或未提交),证据即过期——旧证据不背新代码的书。
    旧格式(纯时间戳字符串)仅验时间,兼容在途单。宿主异常或重跑代价过高时，用户可显式承担风险，
    只替代当前步骤、当前任务卡与当前 HEAD 的这一枚令牌；其他证据仍由各自 evaluator 检查。"""
    kind = spec["agent"]
    if kind == "ASKUSER" and _moonlight(st):
        # 月光宝盒开启时，启动指令本身是本轮统一授权。内容证据仍照常检查；
        # 这里只替代必须在线点选的交互令牌，不替代文档和代码结果。
        return True, ""
    entered = st["history"][-1]["at"] if st["history"] else st["started"]
    accepted, accept_why = _risk_acceptance(kind, st)
    if accepted:
        return True, ""

    def blocked(msg):
        return False, msg + " " + _risk_option(kind, accept_why)

    try:
        tok = json.loads(open(".mae-flow.json.tokens", encoding="utf-8").read()).get(kind, "")
    except Exception:
        tok = ""
    ts = tok.get("at", "") if isinstance(tok, dict) else tok
    head = tok.get("head", "") if isinstance(tok, dict) else ""
    status = tok.get("status", "") if isinstance(tok, dict) else ""
    token_step = tok.get("step", "") if isinstance(tok, dict) else ""
    if ts and ts >= entered:
        if token_step and token_step != st.get("current"):
            return blocked(f"{kind} 令牌属于步骤 {token_step}，当前是 {st.get('current')}。"
                           "每个步骤必须重新执行，不能复用上一关同一秒签发的令牌。")
        wanted = spec.get("statuses") or ([spec["status"]] if spec.get("status") else [])
        if wanted and status not in wanted:
            return blocked(f"{kind} 子 agent 虽已收尾,但结果为 {status or '旧令牌未记录状态'},"
                           f"本步只接受 {'/'.join(wanted)}。FAIL/BLOCKED/NEEDS_INPUT 是有效上报,"
                           "但不是质量通过证据;处理报告中的问题后重启 agent。")
        if head:
            changed, err = _source_changed_since(head, st)
            if err:
                return blocked(f"{kind} 证据新鲜度无法核实({err})。"
                               "重新启动对应 agent(ASKUSER 则重新向用户提问)签发绑定当前代码状态的新令牌。")
            if changed:
                more = "…" if len(changed) > 5 else ""
                return blocked(f"{kind} 证据已过期:令牌签发后源码发生变更({'、'.join(changed[:5])}{more})。"
                               "变更若属本单成果先按规范 commit,然后重新启动对应 agent"
                               "(ASKUSER 则重新向用户确认)对最新代码收尾——旧证据对新代码无效。")
        return True, ""
    if kind == "ASKUSER":
        return blocked(f"本步内未发生过真实的 AskUserQuestion 用户交互(最近令牌: {ts or '无'};本步始于 {entered})。"
                       "待确认项必须用 AskUserQuestion 真实呈现给用户拍板——自行改写标注/口头声称已确认均无效。")
    try:
        rejects = json.load(open(STATE_PATH + ".agent-rejections", encoding="utf-8"))
        reject = rejects.get(kind, {}) or rejects.get("SUBAGENT", {})
    except Exception:
        reject = {}
    if reject.get("at", "") >= entered and reject.get("step") in ("", st.get("current")):
        return blocked(f"{kind} 子 agent 已运行但未签发令牌。真实拒签原因: {reject.get('reason', '未知')} "
                       "如果只是最终报告写法不合规且已有执行凭证，保持源码不变后重答即可复用；"
                       "只有缺少真实执行证据或源码又变化时才需要重跑。")
    return blocked(f"本步内未检测到 {kind} 子 agent 的合法收尾(最近令牌: {ts or '无'};本步始于 {entered})。"
                   "请启动对应专项 agent，并让它在最终回复中给出唯一的 XXX_RESULT: 标记。"
                   "主会话代写或口头汇报不算执行证据。")


def _changed_source_files(st, include_tests=True):
    """当前交付范围内所有源码/构建入口变化，包含删除项，不把语言范围写死成 C++/Java。"""
    diff, err = _scope_diff(st)
    if err:
        return None, err
    out = sh(f"git -c core.quotepath=false diff --name-only {diff}")
    files = [f for f in out.splitlines() if f and _is_source_path(f, st)]
    if not include_tests:
        files = [f for f in files if not _is_test_file(f, st)]
    return files, ""


def ev_agent_or_no_source(spec, st):
    """本轮没有任何源码/构建文件改动时自动放行，否则必须拿到专项 agent 的成功令牌。"""
    files, err = _changed_source_files(st)
    if err:
        return False, err
    if not files:
        return True, ""
    return ev_agent_ran(spec, st)


def ev_review_agent_or_no_code(spec, st):
    """旧流程证据名兼容层。"""
    return ev_agent_or_no_source(spec, st)


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


def ev_glob_absent(spec, st):
    """负向存在证据:pattern 必须一个都匹配不到。用于"动作必须留下'消失'这个事实"——
    如归档=移动,原 change 目录必须从 changes/ 消失;复制式假归档留了原件,在这里骗不过(2026-07-20 僵尸实战)。"""
    pats = [subst(p, st) for p in spec.get("any", [])]
    if any("{" in p and "}" in p for p in pats):
        return False, "证据 pattern 含未解析占位符: " + " | ".join(pats)
    hit = [p for p in pats if globmod.glob(p)]
    if not hit:
        return True, ""
    return False, spec.get("note", "以下路径必须已不存在(残留=动作未完成,如复制式假归档)") + ": " + "、".join(hit)


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
    cur_branch = sh("git branch --show-current")
    want = st.get("config", {}).get("分支名", "")
    if want and cur_branch != want:
        return False, f"当前分支 {cur_branch or '未知'} != 本单约定分支 {want}，禁止在错误分支结束交付"
    head = sh("git rev-parse --verify HEAD")
    up = sh("git rev-parse --verify @{u}")   # --verify:解析失败时 stdout 为空,不回显 @{u} 本身
    if not head:
        return False, "无法读取 HEAD"
    if not up:
        return False, "分支无上游跟踪——用 git push -u origin HEAD 推送并建立跟踪"
    if head != up:
        return False, "本地 HEAD 与远端上游不一致(未推送/推送失败/远端有新提交):git push -u origin HEAD;冲突则 git pull --rebase 后重推"
    current = set(_dirty_paths())
    initial = set(st.get("initial_dirty", []))
    if "initial_dirty" in st:
        changed_initial = set()
        fingerprints = st.get("initial_dirty_fingerprints", {}) or {}
        if fingerprints:
            changed_initial = {p for p in current & initial
                               if fingerprints.get(p) != _path_fingerprint(p)}
        new_dirty = (current - initial) | changed_initial
    else:
        new_dirty = {
            p for p in current if _is_source_path(p, st)
            or p.startswith(("openspec/", "docs/review/", "docs/req/", "docs/codecheck-exempt-"))}
    story_mode = str(st.get("config", {}).get("STORY入库", "")).lower()
    if any(x in story_mode for x in ("不入库", "不提交", "no", "false")):
        story = "docs/story/STORY-" + st.get("config", {}).get("单号", "") + ".md"
        tracked = sh(f'git ls-tree -r --name-only HEAD -- "{story}"')
        if tracked:
            return False, (f"STORY 已确认不入库，但 {story} 仍在当前提交中。"
                           "用 git rm --cached 精确移出索引并按单号提交修正；本地文件可以保留。")
        new_dirty = {p for p in new_dirty if not p.startswith("docs/story/")}
    if new_dirty:
        return False, "仍有本单产生但未提交的文件，远端并不包含它们: " + "、".join(sorted(new_dirty)[:8])
    return True, ""


def ev_commit_tagged(spec, st):
    dan = st["config"].get("单号", "")
    msg = sh("git log -1 --pretty=%s")
    if not msg:
        return False, "无法读取最新 commit"
    if re.match(r"^\[" + re.escape(dan) + r"\]\[(feat|fix)\]", msg):
        return True, ""
    return False, f"最新 commit「{msg}」不符合 [{dan}][feat|fix]描述 格式"


def ev_commit_tagged_after_entry(spec, st):
    """不仅看最新提交格式，还要求提交确实发生在当前步骤之后。"""
    sid = st.get("current", "")
    base = (st.get("step_heads", {}) or {}).get(sid, "")
    if not base or sh(f"git cat-file -t {base}") != "commit":
        return False, f"缺少 {sid} 的入口 HEAD，无法证明本步真的产生过提交"
    commits = sh(f"git log --format=%H {base}..HEAD").splitlines()
    if not commits:
        return False, "当前步骤之后没有新提交，不能拿上一步的提交冒充本步产出"
    return ev_commit_tagged(spec, st)


def _review_has_confirmed_fix(txt):
    """只认评审意见表中的正式裁决，不把模板说明文字当真实数据。"""
    # 只看意见清单的数据行。模板说明本身也会列出“修复(已确认)”这个合法值，
    # 全文搜关键词会把空模板误判成已有修复，导致没有代码可改时也被永久卡住。
    for line in txt.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [x.strip().strip("*`") for x in line.strip().strip("|").split("|")]
        if len(cells) < 4 or cells[0] == "#" or set(cells[0]) <= {"-", ":"}:
            continue
        if cells[-1] == "修复(已确认)":
            return True
    return False


def ev_review_fix_committed(spec, st):
    """没有待修意见时允许空过；存在“修复(已确认)”则必须有本步骤的新提交。"""
    p = "docs/review/REVIEW-" + st.get("config", {}).get("单号", "") + ".md"
    try:
        txt = open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        return False, "评审裁决文档不存在: " + p
    if not _review_has_confirmed_fix(txt):
        return True, ""
    return ev_commit_tagged_after_entry(spec, st)


CODE_EXTS = (".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl", ".ipp", ".tpp", ".java")
DEFAULT_TEST_PATS = [
    r"(^|/)(tests?|__tests__|spec|[^/]+[_-]tests?)/", r"(^|/)src/test/",
    r"(^|/)test_[^/]+\.py$",
    r"(_test|\.test|\.spec)\.(c|cc|cpp|cxx|h|hh|hpp|hxx|inl|ipp|tpp|py|go|rs|js|jsx|ts|tsx)$",
    r"Tests?\.(c|cc|cpp|cxx|h|hh|hpp|hxx|java|kt|cs)$",
]


def _is_test_file(path, st):
    """UT/测试文件判定:配置了「测试路径」用配置,否则用默认特征。codecheck 只查业务代码(团队约定)。"""
    # 仓库配置用于补充私有目录，不应关闭 Test.cpp、dt_tests 等通用识别。
    pats = DEFAULT_TEST_PATS + _test_patterns(st)
    return any(re.search(p, norm(path), re.I) for p in pats)


def _biz_changed_files(st):
    """本单变更中的业务代码文件(排除测试),codecheck 检查范围的唯一算法——agent 与证据同源。
    基线分支必须先验证可解析:diff 命令失败若被当成'无变更'会静默放行(冒烟抓过的真缺陷)。"""
    diff, err = _scope_diff(st)
    if err:
        return None, err
    out = sh(f"git -c core.quotepath=false diff --name-only {diff}")
    files = [f for f in out.splitlines()
             if f and f.lower().endswith(CODE_EXTS) and os.path.exists(f) and not _is_test_file(f, st)]
    return files, ""


def _batches(files, maxlen=6000):
    """按命令行长度分批；同名文件拆开，保证报告只给 basename 时仍能还原完整路径。"""
    out, cur, ln, names = [], [], 0, set()
    for f in files:
        bn = os.path.basename(f).lower()
        if cur and (ln + len(f) + 1 > maxlen or bn in names):
            out.append(cur)
            cur, ln, names = [], 0, set()
        cur.append(f)
        names.add(bn)
        ln += len(f) + 1
    if cur:
        out.append(cur)
    return out


def _codecheck_launch(batch, executable=None, windows=None):
    """构造 CodeCheck 启动方式；Windows 沿用已在公司实机验证过的 shell/PATHEXT 解析。"""
    is_windows = os.name == "nt" if windows is None else windows
    base_argv = ["codecheck", "fullcheck", "-f", ",".join(batch)]
    display = subprocess.list2cmdline(base_argv)
    if is_windows:
        # npm 全局 CLI 是 codecheck.cmd。旧版 shell=True 已在公司 Windows 实机稳定执行；
        # 不再手工套 cmd.exe /s /c，避免 cmd 的首尾引号规则破坏本来可用的命令。
        return display, True, display
    resolved = executable or shutil.which("codecheck")
    if resolved:
        return [resolved, "fullcheck", "-f", ",".join(batch)], False, display
    # 其他平台找不到实体时也保留 shell 恢复路径。
    return display, True, display


def _run_codecheck(files):
    """执行 CodeCheck 并返回机器结果；scan、done 复核共用，避免两套解析口径漂移。"""
    total, pairs, commands = 0, [], []
    for batch in _batches(files):
        launch, use_shell, cmd = _codecheck_launch(batch)
        commands.append(cmd)
        started = time.time()
        try:
            r = subprocess.run(launch, shell=use_shell, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=900)
        except subprocess.TimeoutExpired:
            return None, "codecheck 现场检查超时(>15min)——批次过大或服务异常"
        except OSError as e:
            return None, "codecheck CLI 无法启动: " + str(e)
        out = (r.stdout or "") + (r.stderr or "")
        rp = re.search(r"检查报告已保存到:\s*(.+)", out)
        rtxt = out
        if rp:
            try:
                rtxt = open(rp.group(1).strip(), encoding="utf-8", errors="replace").read()
            except OSError:
                pass
        count = _parse_codecheck_count(out, rtxt)
        json_pairs = []
        if count is None:
            candidates = [os.path.join(".codecheckcli", "codecheck-result.json")]
            if rp:
                candidates.append(os.path.join(os.path.dirname(rp.group(1).strip()), "codecheck-result.json"))
            for jp in candidates:
                try:
                    if os.path.getmtime(jp) + 2 < started:
                        continue
                    count, json_pairs = _parse_codecheck_json(jp)
                    if count is not None:
                        break
                except OSError:
                    continue
        if count is None:
            d = os.path.join(".mae-flow-work", "codecheck-diagnostics")
            os.makedirs(d, exist_ok=True)
            snap = os.path.join(d, time.strftime("%Y%m%d-%H%M%S") + ".txt")
            with open(snap, "w", encoding="utf-8") as f:
                f.write("COMMAND: " + cmd + "\nRETURN_CODE: " + str(r.returncode) + "\n\n" + out)
                if rtxt != out:
                    f.write("\n\n===== REPORT =====\n" + rtxt)
            me = os.path.abspath(sys.argv[0])
            return None, ("codecheck 已返回但告警数无法解析。已尝试控制台、Markdown 汇总/明细和 JSON 结果；"
                          f"完整现场已保存到 {snap}。这是工具兼容问题，不要派修复 Agent、不要猜 0 条。"
                          "可重试一次；仍失败时把诊断文件展示给用户人工核对，用户确认实际告警数后执行 "
                          f"python \"{me}\" codecheck-record --count <数字> --diagnostic \"{snap}\" "
                          "--reason \"输出格式暂不兼容，已人工核对\" --ack \"用户确认原话\"。"
                          "该记录绑定当前步骤、HEAD、文件清单和诊断内容，代码一变自动失效。")
        total += count
        fs = re.findall(r"- \*\*文件\*\*: `([^`]+)`", rtxt)
        rs = re.findall(r"- \*\*规则\*\*: (\S+)", rtxt)
        raw_pairs = json_pairs or list(zip(rs, fs))
        for rule, file_name in raw_pairs:
            matches = [x for x in batch if norm(x).lower() == norm(file_name).lower()
                       or os.path.basename(x).lower() == os.path.basename(file_name).lower()]
            pairs.append((rule, matches[0] if len(matches) == 1 else norm(file_name)))
    return {"total": total, "pairs": pairs, "commands": commands}, ""


def _parse_codecheck_count(console, report):
    """CodeCheckCLI 没有稳定 JSON/退出码契约，兼容已见的三种可信输出。

    1) 提示行「共有 N 条告警」；2) Markdown 汇总表「总计」；
    3) 明确的零告警文案。不能仅凭进程退出码判断（公司 CLI 成功也可能返回 1）。
    """
    text = (console or "") + "\n" + (report or "")
    nums = re.findall(r"共有\s*(\d+)\s*条告警", text)
    if nums:
        return int(nums[-1])
    totals = re.findall(r"\|\s*\*{0,2}总计\*{0,2}\s*\|\s*\*{0,2}(\d+)\*{0,2}\s*\|", text)
    if totals:
        return int(totals[-1])
    details = re.findall(r"^###\s+\d+\.\s+\[(?:Critical|Major|Minor|Suggestion|致命级|严重级|一般级|提示级)\]", text, re.M | re.I)
    if details:
        return len(details)
    zero_patterns = (r"未发现(?:任何)?(?:代码)?告警", r"没有发现(?:任何)?(?:代码)?告警",
                     r"(?:告警|问题)(?:总数)?\s*[:：]?\s*0\b", r"0\s*条告警")
    completed = ("代码检查完成" in text or "CodeCheck 检查报告" in text or "检查结果汇总" in text)
    if completed and any(re.search(p, text, re.I) for p in zero_patterns):
        return 0
    return None


def _parse_codecheck_json(path):
    """兼容 CodeCheckCLI 的 JSON 结果：不依赖固定顶层字段，按带 UUID/规则/文件的告警对象去重。"""
    data = json.load(open(path, encoding="utf-8", errors="replace"))
    rows = []

    def walk(v):
        if isinstance(v, dict):
            low = {str(k).lower(): x for k, x in v.items()}
            uid = low.get("uuid") or low.get("id") or low.get("issueid")
            rule = low.get("rule") or low.get("rulename") or low.get("ruleid")
            file_name = low.get("file") or low.get("filepath") or low.get("path")
            if uid and rule and file_name:
                rows.append((str(uid), str(rule).split()[0], norm(str(file_name))))
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(data)
    uniq = {}
    for uid, rule, file_name in rows:
        uniq[uid] = (rule, file_name)
    if uniq:
        return len(uniq), list(uniq.values())
    # 某些版本只有明确总数，没有逐条对象；只接受语义清楚的数字字段。
    if isinstance(data, dict):
        for k in ("total", "totalCount", "issueCount", "warningCount"):
            if isinstance(data.get(k), int):
                return data[k], []
    return None, []


def _approval_key(rule, path):
    return (rule.strip() + "|" + norm(path).strip().lstrip("./")).lower()


def _exemption_text_has_pair(text, rule, path):
    """规则与文件必须出现在同一条记录，不能拿两行内容交叉拼成一个假豁免。"""
    np = norm(path).lower()
    nr = rule.strip().lower()
    return any(nr in line.lower() and np in norm(line).lower() for line in text.splitlines())


def _approved_exemptions(st):
    return {_approval_key(x.get("rule", ""), x.get("file", ""))
            for x in st.get("codecheck_exemptions", []) if x.get("rule") and x.get("file")}


def _was_exempt_before_review(st, ex, rule, path):
    """原 MR 已存在的正式豁免不重复询问；本轮新豁免必须有状态机审批记录。"""
    if not _is_review(st):
        return False
    base = st.get("review_base_head", "")
    if not base:
        return False
    try:
        r = subprocess.run(["git", "show", f"{base}:{ex}"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=8)
        txt = r.stdout if r.returncode == 0 else ""
    except Exception:
        txt = ""
    return _exemption_text_has_pair(txt, rule, path)


def ev_codecheck_clean(spec, st):
    """最硬约束:done 现场重跑 codecheck CLI,harness 亲数遗留告警(agent 报数不作数)。
    0 条直接放行；遗留告警必须同时有豁免文件和用户审批账。告警数兼容控制台提示、
    Markdown 汇总表与明确零告警文案；不能依赖 CLI 退出码。必须在项目根执行。"""
    files, err = _biz_changed_files(st)
    if err:
        return False, err
    if not files:
        return True, ""
    result, err = _run_codecheck(files)
    if err:
        manual = (st.get("quality", {}) or {}).get("codecheck_manual", {})
        same_files = manual.get("files") == files
        same_head = manual.get("head") == sh("git rev-parse --verify HEAD")
        diag = manual.get("diagnostic", "")
        try:
            same_diag = (os.path.isfile(diag)
                         and hashlib.sha256(open(diag, "rb").read()).hexdigest()
                         == manual.get("diagnostic_sha256"))
        except OSError:
            same_diag = False
        if (manual.get("step") == st.get("current") and same_files and same_head
                and same_diag and manual.get("count") == 0):
            return True, ""
        return False, err + ("；若你已人工看过诊断文件并确认告警数，可使用 current 中给出的 "
                             "codecheck-record 恢复命令，记录会绑定当前 HEAD 和文件清单，代码一变即失效")
    total, pairs = result["total"], result["pairs"]
    if total == 0:
        return True, ""
    ex = "docs/codecheck-exempt-" + st["config"].get("单号", "") + ".md"
    if not os.path.exists(ex):
        return False, (f"harness 现场复核实测遗留 {total} 条告警,且无豁免清单({ex})。"
                       "两条路:修掉重试;或经用户逐条裁决豁免(AskUserQuestion),把「规则ID + 文件 + 用户原话」"
                       f"逐行写入 {ex} 并 commit 后重试——口头豁免无效")
    extxt = open(ex, encoding="utf-8", errors="replace").read()
    bad = [f"{r}({f})" for r, f in pairs if not _exemption_text_has_pair(extxt, r, f)]
    if len(pairs) < total and bad == []:
        bad = [f"(另有 {total - len(pairs)} 条未解析出明细,无法核对豁免)"]
    if bad:
        return False, (f"实测遗留 {total} 条告警,以下未被豁免清单覆盖: " + "、".join(bad[:5])
                       + ("…" if len(bad) > 5 else "") + f"。修掉或补齐 {ex}(须用户裁决原话)后重试")
    approved = _approved_exemptions(st)
    unauthorized = [f"{r}({f})" for r, f in pairs
                    if _approval_key(r, f) not in approved and not _was_exempt_before_review(st, ex, r, f)]
    if unauthorized:
        return False, ("豁免文件覆盖了告警,但以下本轮豁免没有用户审批令牌: " + "、".join(unauthorized[:5])
                       + "。逐项 AskUserQuestion 后执行 mae-flow approve-exemption --rule <规则ID> "
                       "--file <文件> --reason <理由> --ack \"用户原话\"；手写豁免文件不再算授权")
    dirty = sh(f'git status --porcelain -- "{ex}"')
    if dirty:
        return False, f"豁免记录 {ex} 尚未提交；本地文件不能替远端 MR 背书，请精确提交后重试"
    return True, ""


def ev_review_codecheck(spec, st):
    """统一规范检查协议：机器先扫；有告警才派修复 agent；最后机器复核。"""
    scan = (st.get("quality", {}) or {}).get("codecheck_scan", {})
    if scan.get("step") != st.get("current"):
        return False, "尚未执行本步的机器首检。先运行 mae-flow codecheck-scan，禁止主会话自行修复"
    if scan.get("count", 0) == 0:
        changed, err = _source_changed_since(scan.get("head", ""), st)
        if err:
            return False, "CodeCheck 首检基点失效:" + err + "；重新执行 codecheck-scan"
        if changed:
            return False, ("CodeCheck 首检为 0 后源码又发生变化: " + "、".join(changed[:5])
                           + "。旧首检不背新代码的书,重新执行 codecheck-scan")
    else:
        ok, why = ev_agent_ran({"agent": "CODECHECK", "statuses": ["CLEAN", "REMAINING"]}, st)
        if not ok:
            return False, why
    return ev_codecheck_clean(spec, st)


ENV_CACHE = os.path.join(os.path.expanduser("~"), ".mae-flow-env-ok")
ENV_MARK = "mae-flow-env-ok-v1"              # 缓存有效标记:防裸 touch 伪造(空文件/外来内容一律无效)
FAST_TYPES = ("path_any", "file_contains", "path_absent")   # 项目级快检查:不缓存,每次都跑


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
            elif t == "path_absent":   # 标记文件不存在才算就绪(如"待重启"标记被 SessionStart 清除后)
                ok = not any(os.path.exists(p) for p in v)
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


RELOAD_MARK = ".mae-flow-need-reload"


def ev_env_ok(spec, st):
    # 待重启标记优先于一切:磁盘装好了但会话没加载,派 agent/重装都没用,只有重启会话能清标记。
    # 提到最前面拦——不重启就往下走,skill/plugin 未注册,AI 会手搓空壳绕过(2026-07-20 实战)。
    if os.path.exists(RELOAD_MARK):
        try:
            why = open(RELOAD_MARK, encoding="utf-8", errors="replace").read().strip().replace("\n", ";")
        except Exception:
            why = ""
        return False, ("环境有变更待生效(不要派 env-setup-agent、不要重装):" + why
                       + "。二选一让它生效:①在当前会话执行 **/reload-skills**(装了插件的再执行 /reload-plugins,"
                       "若你的 codeagent 支持),完成后**用户明确说一声**(如\"刷新好了\"),你再执行 "
                       "`mae-flow reloaded --ack \"用户原话\"` 清标记继续;②或**重启会话**(自动清标记)后说\"继续\"。")
    fails = run_env_checks()
    if not fails:
        return True, ""
    return False, "环境未就绪(现场实测): " + "、".join(fails) + " —— 启动 env-setup-agent 修复后重试 done"


EVIDENCE = {"glob": ev_glob, "branch_ok": ev_branch_ok, "env_ok": ev_env_ok,
            "tasks_checked": ev_tasks_checked, "commit_tagged": ev_commit_tagged,
            "commit_tagged_after_entry": ev_commit_tagged_after_entry,
            "review_fix_committed": ev_review_fix_committed,
            "yaml_field": ev_yaml, "pushed": ev_pushed, "agent_ran": ev_agent_ran,
            "content_free": ev_content_free, "clean_paths": ev_clean_paths,
            "codecheck_clean": ev_codecheck_clean, "glob_absent": ev_glob_absent,
            "review_agent_or_no_code": ev_review_agent_or_no_code,
            "agent_or_no_source": ev_agent_or_no_source,
            "review_codecheck": ev_review_codecheck}


def _ack_verified(st, ack, exact=False):
    """ack 必须来自当前步骤之后的真实用户输入；旧步骤的“可以”不能循环使用。

    如果宿主拿不到 AskUserQuestion 的应答正文，用户再发一条普通消息即可恢复；不允许静默降级为
    “模型自己写一句 --ack 也算用户确认”。
    """
    try:
        msgs = json.loads(open(STATE_PATH + ".usermsg", encoding="utf-8").read() or "[]")
    except Exception:
        msgs = []
    if not msgs:
        return False, ("harness 尚未记录到用户回复。请把待确认内容展示给用户，等用户回复后再继续；"
                       "若 AskUserQuestion 的选项应答未被宿主回传，请让用户用普通消息再确认一次。")

    def nt(s):
        return re.sub(r"\s+", "", s or "")

    na = nt(ack)
    sid = st.get("current", "")
    entered = _step_entered_at(st)
    current_msgs = [m for m in msgs
                    if m.get("at", "") >= entered and (not m.get("step") or m.get("step") == sid)]

    def candidates(text):
        """AskUserQuestion 在不同宿主里可能存成 JSON；精确确认应匹配其中一个真实字符串值。"""
        out = [text or ""]
        try:
            value = json.loads(text)

            def walk(v):
                if isinstance(v, str):
                    out.append(v)
                elif isinstance(v, dict):
                    for item in v.values():
                        walk(item)
                elif isinstance(v, list):
                    for item in v:
                        walk(item)
            walk(value)
        except Exception:
            pass
        return [nt(v) for v in out if nt(v)]

    actual = [v for m in current_msgs for v in candidates(m.get("text", ""))]
    matched = any((na == v if exact else na in v) for v in actual) if na else False
    if matched:
        return True, ""
    return False, ("--ack 与当前步骤开始后的用户真实输入不匹配。"
                   "ack 必须是用户回复/选项的**原文复制**(禁止转述、概括、代答);"
                   "以前步骤说过的『可以』不能复用；先真实拿到本步输入,再以原文重试。")


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


# mae-flow 步骤 ↔ comet phase 合法区间(阶段互锁哨兵;未列出的步骤不检查)
# 依据 comet 0.3 语义:comet-design 收尾自带 guard design --apply → build;build 收尾 apply → verify
COMET_PHASE_EXPECT = {
    "story_ask": ("build",), "story": ("build",),
    "build": ("build", "verify"),
    "verify_ponytail": ("verify",), "verify_post_ponytail_compile": ("verify",),
    "verify_recompile": ("verify",), "verify_codecheck": ("verify",),
    "verify_ut": ("verify",), "verify_comet": ("verify",),
    "archive_confirm": ("verify",), "archive": ("verify", "archive"),
    "design": ("open", "design", "build"),
}


def _comet_phase(st):
    """读当前 change 的 comet phase(显式用 CHANGE_NAME,绝不学 comet 的字典序抽奖)。"""
    cn = (st.get("config", {}) or {}).get("CHANGE_NAME", "")
    if not cn:
        return ""
    p = f"openspec/changes/{cn}/.comet.yaml"
    if not os.path.exists(p):
        return ""
    m = re.search(r"^phase:\s*(\S+)", open(p, encoding="utf-8", errors="replace").read(), re.M)
    return m.group(1) if m else ""


def _active_change_count():
    """在建区活跃 change 计数(镜像 comet 的判定:排除 archive/ 子目录与 archived: true)。>1 = 僵尸在场。"""
    n = 0
    try:
        for d in os.listdir("openspec/changes"):
            full = os.path.join("openspec", "changes", d)
            if not os.path.isdir(full) or d == "archive":
                continue
            y = os.path.join(full, ".comet.yaml")
            if not os.path.exists(y):
                continue
            if re.search(r"^archived:\s*true", open(y, encoding="utf-8", errors="replace").read(), re.M):
                continue
            n += 1
    except OSError:
        pass
    return n


def _sentinel_lines(sid, st):
    """阶段互锁哨兵:把'谜之写入拦截'变'开局就有诊断'。只警告不硬拒(硬闸在转换点的 phase 证据上)。"""
    out = []
    ph = _comet_phase(st)
    exp = COMET_PHASE_EXPECT.get(sid)
    if exp and ph and ph not in exp:
        out.append(f"⚠ 阶段错位:comet phase={ph},本步期望 {'/'.join(exp)}。多为上一步的 comet-guard --apply"
                   " 未完成(闪退/中断)——按该阶段收尾指引补跑 guard --apply 再继续;"
                   "被 COMET PHASE GUARD 拦到写入时禁止换工具硬绕,先 doctor。")
    n = _active_change_count()
    if n > 1:
        out.append(f"⚠ 僵尸告警:openspec/changes/ 下有 {n} 个活跃 change(应只有当前单一个)。"
                   "comet 会按字典序抽一个管全场,极易造成谜之写入拦截。处理:当前单为 "
                   f"{(st.get('config', {}) or {}).get('CHANGE_NAME', '?')},其余为历史残留——"
                   "做完没归档的补归档,废弃的经用户确认移除。")
    return out


def _resolved_next(flow, st, sid):
    """按当前 choices 解析某历史步骤的去向，供旧状态恢复入口 HEAD。"""
    step = flow.get("steps", {}).get(sid, {})
    nxt = step.get("next")
    try:
        if step.get("next_by"):
            return nxt[st.get("choices", {}).get(step["next_by"])]
        if isinstance(nxt, dict):
            return nxt[st.get("choices", {}).get(step.get("choice_key"))]
    except Exception:
        return None
    return nxt


def _ensure_step_entry_head(flow, st, sid):
    """为旧版在途 tests_only 步骤恢复入口 HEAD。

    新版 advance 会直接记录精确 HEAD。旧状态只能从“上一阶段进入当前步骤”的历史时间反推，
    使用该时间之前最后一个 commit；时间同秒时最多多包含一笔旧改动，只会多验，不会漏验。
    绝不以当前 HEAD 兜底，因为当前 HEAD 可能已经包含 UT 阶段偷偷修改的源码。
    """
    old = (st.get("step_heads", {}) or {}).get(sid, "")
    if old and sh(f"git cat-file -t {old}") == "commit":
        return old, ""
    entered_at = ""
    for h in reversed(st.get("history", [])):
        result = str(h.get("result", ""))
        if result == "goto:" + sid or _resolved_next(flow, st, h.get("step", "")) == sid:
            entered_at = h.get("at", "")
            break
    if not entered_at:
        return "", f"历史中找不到进入 {sid} 的转换记录"
    base = sh(f'git rev-list -1 --before="{entered_at}" HEAD')
    if not base or sh(f"git cat-file -t {base}") != "commit":
        return "", f"无法按进入时间 {entered_at} 解析安全基点"
    st.setdefault("step_heads", {})[sid] = base
    st.setdefault("migrations", []).append({
        "type": "recover-step-head", "step": sid, "head": base,
        "from_history_at": entered_at, "at": time.strftime("%Y-%m-%d %H:%M:%S")})
    save_state(st)
    return base, ""


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
    txt = txt.replace("{MAEFLOW_PATH}", os.path.abspath(sys.argv[0]))
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
    if _moonlight(st):
        ml = _moonlight_data(st)
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
        unresolved = _moonlight_unresolved(st)
        if unresolved:
            print("──── 当前遗留（修复轮必须优先处理） ────")
            print(_moonlight_issue_context(st))
    print(perms_line(step))
    for _w in _sentinel_lines(sid, st):
        print(_w)
    ul = st.get("unlock") or {}
    if ul.get("step") == sid:
        print(f"🔓 本步源码修改已解锁(用户裁决: {ul.get('reason', '')};推进后自动失效)")
    for kind, rec in sorted((st.get("risk_acceptances", {}) or {}).items()):
        if rec.get("step") != sid:
            continue
        valid, why = _risk_acceptance(kind, st)
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
        tp = _test_patterns(st)
        if tp:
            print("🛡 UT 写入边界:使用仓库配置的测试路径硬拦非测试源码: " + " | ".join(tp))
        else:
            print("⚠ UT 写入边界:仓库未配置「测试路径」，当前使用内置保守规则硬拦非测试源码。"
                  "若本仓测试目录不符合 tests/、test/、src/test/、*_test.*、*Test.java，"
                  "请先在 .mae-flow-defaults.json 配置「测试路径」，禁止用 unlock 把长期目录差异当单次源码缺陷处理。")
    if step.get("clear_hint"):
        print("💡 会话卫生:本步开始前若会话已较长,建议 /clear 后说「继续」——状态在磁盘,进度不丢,防长上下文行为漂移。")
    if step.get("user_ack") and not _moonlight(st):
        print("⚠ 本步需要用户确认:优先用 AskUserQuestion 等结构化提问工具呈现选项拿用户选择(选完同轮继续);"
              "该工具不可用才结束回复纯文本等待。done 必须携带 --ack \"用户选择/回复原文\",拿到前禁止推进。")
    elif step.get("user_ack") and _moonlight(st):
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
    if _moonlight(st) and sid in MOONLIGHT_QUALITY_STEPS:
        print("──── 尽力而为出口 ────")
        print("先真实执行本步并尝试修复；确认继续尝试只会重复消耗后，提交当前有效改动，然后执行：")
        print(f"python \"{os.path.abspath(sys.argv[0])}\" moonlight defer "
              "--reason \"<遗留现象、已尝试修复、当前风险>\"")
        print("该命令会把问题写入晨间报告并继续下一阶段，不会把失败伪装成通过。")
    if _moonlight(st) and step.get("tests_only"):
        print("UT 若经自查后明确指向被测源码缺陷，不需要等用户：先执行")
        print(f"python \"{os.path.abspath(sys.argv[0])}\" moonlight unlock-source "
              "--reason \"<失败用例、规格依据、自查结论>\"")
        print("再修源码并提交；done 会自动回流编译、CodeCheck 和 UT。")
    if _moonlight(st) and sid == "push":
        print("push 若因认证、网络或冲突在有限重试后仍失败，禁止询问或谎报成功；执行：")
        print(f"python \"{os.path.abspath(sys.argv[0])}\" moonlight push-failed "
              "--reason \"<错误原文和已尝试处理>\"")
        print("状态会停在 push，早晨修好远端问题后直接重新 push + done。")
    if _moonlight(st) and _moonlight_can_block(sid):
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
                      if _moonlight(st) else
                      "预填值;仍须逐项经用户确认后 --set,基线分支/需求文档必须单独确认")
            print(f"──── 仓库预设({DEFAULTS_PATH},{suffix}) ────")
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
    if step.get("user_ack") and not _moonlight(st):
        extra += " --ack \"<用户原话>\""
    # python(非 python3:Windows 无此命令);abspath(非 relpath:跨盘符 relpath 抛 ValueError)
    print(f"python \"{os.path.abspath(sys.argv[0])}\" done{extra}")
    if step.get("skippable"):
        print(f"(可跳过: ... skip --reason \"<理由>\")")


# ---------------- 命令 ----------------

def _state_sidecars():
    return [STATE_PATH, STATE_PATH + ".tokens", STATE_PATH + ".usermsg",
            STATE_PATH + ".agent-rejections", STATE_PATH + ".agent-evidence",
            MOONLIGHT_INTENT_PATH, STATE_PATH + ".tmp"]


def _unique_exit_dir(st):
    ticket = re.sub(r"[^A-Za-z0-9._-]+", "-", (st.get("config", {}) or {}).get("单号", "unknown"))
    base = os.path.join(".mae-flow-work", "exited",
                        time.strftime("%Y%m%d-%H%M%S") + "-" + (ticket or "unknown"))
    path, n = base, 2
    while os.path.exists(path):
        path, n = base + "-" + str(n), n + 1
    os.makedirs(path, exist_ok=False)
    return path


def _snapshot_state_files(dst):
    """复制流程状态到可恢复目录；只处理明确白名单，不扫、不删用户文件。"""
    copied = []
    for src in _state_sidecars():
        if os.path.isfile(src):
            target = os.path.join(dst, os.path.basename(src))
            shutil.copy2(src, target)
            copied.append((src, target))
    return copied


def _write_json_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _reopen_comet_archive(st):
    cn = (st.get("config", {}) or {}).get("CHANGE_NAME", "")
    scripts = [os.path.join(base, "skills", "comet", "scripts", "comet-state.sh")
               for base in (".cac", ".claude")]
    script = next((p for p in scripts if os.path.isfile(p)), "")
    if not cn or not script:
        return False, "缺 CHANGE_NAME 或 comet-state.sh"
    try:
        result = subprocess.run(["bash", script, "transition", cn, "archive-reopen"],
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=30)
    except Exception as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, ((result.stdout or "") + (result.stderr or "")).strip()[-1000:]
    return True, ""


def _resume_direct_mode(ack=""):
    """恢复退出前现场；直接开发期间若改过源码，只回退到必要的质量链入口。"""
    if not os.path.exists(EXIT_PATH):
        return None
    try:
        rec = json.load(open(EXIT_PATH, encoding="utf-8"))
    except Exception:
        rec = {}
    normalized_ack = re.sub(r"\s+", "", ack or "")
    direct_messages = [re.sub(r"\s+", "", m.get("text", ""))
                       for m in (rec.get("direct_messages", []) or [])]
    if not normalized_ack or normalized_ack not in direct_messages:
        die("当前项目处于普通开发模式。重新启用 mae-flow 会恢复门禁，必须由用户明确提出，并执行 "
            "init --ack \"用户原话\"；普通改码请求不能由 Agent 自行解释成重新启用。", 2)
    dst = rec.get("snapshot", "")
    saved_state = os.path.join(dst, STATE_PATH) if dst else ""
    if not saved_state or not os.path.isfile(saved_state):
        die("退出现场缺少状态快照，不能自动恢复：%s。退出标记仍保留，请交维护人处理。" %
            (saved_state or "(无 snapshot)"), 2)
    try:
        st = json.load(open(saved_state, encoding="utf-8"))
    except Exception as exc:
        die("退出状态快照不可解析，不能自动恢复：%s" % exc, 2)

    changed, err = _source_changed_since(rec.get("head", ""), st)
    if err:
        die("无法判断退出期间的源码变化，不能安全恢复：" + err, 2)
    source_changed = any(_is_source_path(
        p[:-len("(未提交)")] if p.endswith("(未提交)") else p, st)
        for p in (changed or []))
    old_step = st.get("current", "")
    workflow = (st.get("choices", {}) or {}).get("workflow", "")
    target = old_step
    if source_changed:
        if workflow == "review" and old_step in ("rf_compile", "rf_codecheck", "rf_ut", "push", "end"):
            target = "rf_compile"
        elif workflow == "tweak" and old_step in (
                "tw_compile", "tw_codecheck", "tw_ut", "archive_confirm", "archive", "push", "end"):
            target = "tw_compile"
        elif old_step in ("verify_ponytail", "verify_post_ponytail_compile", "verify_recompile",
                          "verify_codecheck", "verify_ut", "verify_comet", "archive_confirm",
                          "archive", "push", "end"):
            if _comet_phase(st) == "archive":
                ok, why = _reopen_comet_archive(st)
                if not ok:
                    die("源码已变化且底层处于定稿阶段，但正规回退失败；尚未重新启用：" + why, 2)
            target = "verify_recompile"

    for path in _state_sidecars():
        if os.path.exists(path):
            os.remove(path)
    st.pop("unlock", None)
    st.pop("agent_tasks", None)
    st.pop("quality", None)
    st.pop("risk_acceptances", None)
    st["current"] = target
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    st.setdefault("history", []).append({"step": old_step, "result": "resumed:" + target,
                                          "note": "direct-source-changed" if source_changed else "no-source-change",
                                          "at": now})
    if target != old_step:
        st.setdefault("step_heads", {})[target] = rec.get("head", "")
    save_state(st)
    os.remove(EXIT_PATH)
    print("[mae-flow] 已重新启用流程，退出现场仍保留在 %s；旧 agent/CodeCheck 令牌已清空。"
          % (dst or ".mae-flow-work/exited/"))
    if target != old_step:
        print("检测到退出期间改过源码：%s → %s，重新执行后续质量链。" % (old_step, target))
    return st


def cmd_init(flow, args):
    resumed = _resume_direct_mode(args.ack or "")
    if resumed is not None:
        print_current(flow, resumed)
        return
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
    _gitignore()
    dirty = _dirty_paths()
    st = {"current": flow["start"], "config": {}, "choices": {},
          "history": [], "started": time.strftime("%Y-%m-%d %H:%M:%S"),
          "initial_dirty": dirty,
          "initial_dirty_fingerprints": {p: _path_fingerprint(p) for p in dirty}}
    save_state(st)
    print("[mae-flow] 流程已初始化。")
    print_current(flow, st)


def _gitignore():
    gi = ".gitignore"
    # .mae-flow.json* 含 .tmp 原子写中间件与 .last 交付备份;历史账本单列(pattern 不覆盖)
    lines = [".mae-flow.json*", EXIT_PATH, HISTORY_PATH, ".mae-flow-need-reload", ".mae-flow-work/"]
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
        base = sh("git rev-parse --verify HEAD")
        if not base:
            die("无法记录评审返工基点 HEAD,拒绝进入返工流程。", 2)
        st["review_base_head"] = base
    # 兼容 2.0.2 已经停在旧 rf_verify 的在途单：按 history 自动恢复返工前 HEAD。
    if sid == "rf_verify" and st.get("choices", {}).get("workflow") == "review":
        _, err = _ensure_review_base(st)
        if err:
            die(err, 2)
    st.pop("unlock", None)   # 源码解锁仅限本步实例,推进即失效
    st.pop("risk_acceptances", None)   # 风险放行同样只属于当前步骤实例
    st["history"].append({"step": sid, "result": tag, "note": note, "at": time.strftime("%Y-%m-%d %H:%M:%S")})
    nxt = step.get("next")
    if step.get("next_by"):
        nxt = step["next"][st["choices"][step["next_by"]]]
    elif isinstance(nxt, dict):
        nxt = nxt[st["choices"][step["choice_key"]]]
    if _moonlight(st) and nxt == "archive_confirm":
        st["history"].append({
            "step": sid, "result": "moonlight:archive-deferred",
            "note": "夜间先推送，规格定稿留到晨间 finalize",
            "at": time.strftime("%Y-%m-%d %H:%M:%S")})
        nxt = "push"
    if _moonlight(st) and sid == "push":
        _moonlight_resolve_kind(st, "push")
        ml = _moonlight_data(st)
        ml["pushed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        ml["pushed_head"] = sh("git rev-parse --verify HEAD")
        nxt = "moonlight_review"
    if _moonlight(st) and sid == "env_setup":
        # 晨间修复若先处理夜间遗留的环境问题，环境关结束后回到质量链入口，
        # 不重新跑配置确认、需求澄清和设计。
        repair_next = _moonlight_data(st).pop("repair_after_environment", "")
        if repair_next:
            nxt = repair_next
    st["current"] = nxt
    if nxt:
        st.setdefault("step_heads", {})[nxt] = sh("git rev-parse --verify HEAD")
    save_state(st)
    if _moonlight(st) and nxt == "moonlight_review":
        _write_moonlight_report(flow, st)
    print(f"[mae-flow] {sid} {tag} → 进入 {nxt}\n")
    print_current(flow, st)


def cmd_done(flow, st, args):
    sid = st["current"]
    step = flow["steps"][sid]
    if step.get("terminal"):
        die("流程已在终态。")
    if sid == "moonlight_review":
        die("月光宝盒已推送并等待早晨处理。请执行 moonlight report、moonlight repair 或 moonlight finalize，"
            "不能用 done 跳过报告闭环。", 2)
    allowed_sets = _allowed_set_keys(step)
    for kv in args.set or []:
        if "=" not in kv:
            die(f"--set 需为 k=v 形式: {kv}")
        k, v = kv.split("=", 1)
        if k not in allowed_sets:
            die(f"当前步骤 {sid} 不允许写配置项「{k}」。已确认配置不能在后续步骤偷偷改写；"
                "确需调整请经用户确认 goto config_confirm 后修改。", 2)
        bad = _validate_config_value(k, v)
        if bad:
            die(f"{k}「{v}」不合法:{bad}。", 2)
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
            remedy = ("用 --set 补齐；月光模式禁止询问用户，只能从本轮需求原话、仓库预设、"
                      "当前分支和代码事实中保守取得，不能编造"
                      if _moonlight(st) else "用 --set 补齐;缺失项应询问用户")
            die("配置缺失,禁止推进: " + "、".join(missing) + "(" + remedy + ")", 2)
        if "基线分支" in step["require_sets"] and not st["config"].get("分支名"):
            st["config"]["分支名"] = "{基线分支}_{工号}_{单号}".format(**st["config"])
    if step.get("user_ack") and not _moonlight(st) and not args.ack:
        die("本步需要用户确认:必须携带 --ack \"用户确认原话\"。没有拿到用户回复就调用 done = 违规。", 2)
    if step.get("user_ack") and not _moonlight(st) and args.ack:
        ok, why = _ack_verified(st, args.ack)
        if not ok:
            die(why, 2)
    if step.get("choice_key"):
        if args.choice not in step.get("choices", []):
            die(f"--choice 必须为: {'|'.join(step['choices'])}", 2)
        st["choices"][step["choice_key"]] = args.choice
    want = st.get("config", {}).get("分支名", "")
    if sid not in ("env_setup", "config_confirm", "workflow_select", "branch_create") and want:
        cur = sh("git branch --show-current")
        if cur != want:
            save_state(st)
            die(f"当前分支 {cur or '未知'} != 本单约定分支 {want}。先切回正确分支，禁止在别的分支推进。", 2)
    source_next = step.get("source_change_next")
    if source_next:
        _, migrate_err = _ensure_step_entry_head(flow, st, sid)
        if migrate_err:
            save_state(st)
            die("无法恢复步骤入口 HEAD:" + migrate_err + "。拒绝猜测源码是否变化。", 2)
        changed, why = _source_changed_since((st.get("step_heads", {}) or {}).get(sid, ""), st)
        if why:
            save_state(st)
            die("无法核对本步源码变化:" + why, 2)
        if changed:
            dirty = [x for x in changed if x.endswith("(未提交)")]
            if dirty:
                save_state(st)
                die("本步改过源码，但仍有未提交改动: " + "、".join(dirty[:5])
                    + "。先按单号格式精确提交，再 done；否则下一步任务卡看不到这些文件。", 2)
            ok, commit_why = ev_commit_tagged_after_entry({}, st)
            if not ok:
                save_state(st)
                die("源码变化尚未形成可追踪的本步提交:" + commit_why, 2)
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            st["history"].append({"step": sid, "result": "source-recheck:" + source_next,
                                  "note": "本步修改源码:" + "、".join(changed[:10]), "at": now})
            st["current"] = source_next
            st.setdefault("step_heads", {})[source_next] = sh("git rev-parse --verify HEAD")
            for kind in ("COMPILE", "CODECHECK", "UT"):
                (st.get("agent_tasks", {}) or {}).pop(kind, None)
            (st.get("quality", {}) or {}).pop("codecheck_scan", None)
            save_state(st)
            print(f"[mae-flow] {sid} 修改了源码，自动进入 {source_next} 重新编译；主会话不要自行编译。\n")
            print_current(flow, st)
            return
    recheck = step.get("source_change_recheck")
    if recheck:
        _, migrate_err = _ensure_step_entry_head(flow, st, sid)
        if migrate_err:
            save_state(st)
            die("无法恢复 UT 步骤入口 HEAD:" + migrate_err
                + "。为避免漏掉编译/CodeCheck，拒绝向后推进；请交维护人核对历史。", 2)
        changed, why = _business_source_changed_since_step(st, sid)
        if why:
            save_state(st)
            die("无法核对 UT 步骤内是否修改过被测源码:" + why
                + "。为避免漏掉编译/CodeCheck，拒绝向后推进；请交维护人恢复步骤入口基点。", 2)
        if changed:
            ul = st.get("unlock") or {}
            if ul.get("scope") != "source" or ul.get("step") != sid:
                save_state(st)
                die("UT 步骤内检测到未经 unlock source 用户裁决的被测源码变更: "
                    + "、".join(changed[:5])
                    + ("…" if len(changed) > 5 else "")
                    + "。这是越权修改，不能靠补跑验证洗白；先呈报变更和 UT 自查结论，由用户裁决后再处理。", 2)
            dirty = [x for x in changed if x.endswith("(未提交)")]
            if dirty:
                save_state(st)
                die("用户虽已解锁源码修复，但这些源码仍未提交: " + "、".join(dirty[:5])
                    + "。先按单号格式精确提交，再 done；否则回流任务卡无法覆盖真实改动。", 2)
            ok, commit_why = ev_commit_tagged_after_entry({}, st)
            if not ok:
                save_state(st)
                die("UT 暴露的源码修复尚未形成可追踪提交:" + commit_why, 2)
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            st["history"].append({"step": sid, "result": "source-recheck:" + recheck,
                                  "note": "UT 裁决后修改被测源码:" + "、".join(changed[:10]), "at": now})
            st["current"] = recheck
            st.setdefault("step_heads", {})[recheck] = sh("git rev-parse --verify HEAD")
            st.pop("unlock", None)
            # 旧任务卡和首检只描述旧源码。即使令牌新鲜度还能拦住，也主动清掉避免弱模型误用。
            for kind in ("COMPILE", "CODECHECK", "UT"):
                (st.get("agent_tasks", {}) or {}).pop(kind, None)
            (st.get("quality", {}) or {}).pop("codecheck_scan", None)
            save_state(st)
            print(f"[mae-flow] UT 阶段经用户裁决修改了被测源码，自动回流到 {recheck}。"
                  "必须重新经过编译、CodeCheck 与 UT；禁止直接推送。\n")
            print_current(flow, st)
            return
    fails = check_evidence(step, st)
    if fails:
        save_state(st)
        die("证据不足,拒绝推进:\n  - " + "\n  - ".join(fails), 2)
    kind = _moonlight_step_kind(sid)
    if kind:
        _moonlight_resolve_kind(st, kind)
    if sid == "story":
        story_mode = str(st.get("config", {}).get("STORY入库", "")).lower()
        if any(x in story_mode for x in ("不入库", "不提交", "no", "false")):
            src = "docs/story/STORY-" + st.get("config", {}).get("单号", "") + ".md"
            tracked = sh(f'git ls-files -- "{src}"')
            if tracked:
                save_state(st)
                die(f"用户选择 STORY 不入库，但 {src} 已被加入 Git。先用 git rm --cached 精确移出，"
                    "保留本地文件并按单号提交索引修正，再重试 done；禁止继续把它带进 MR。", 2)
            if os.path.exists(src):
                dst_dir = os.path.join(".mae-flow-work", "story")
                os.makedirs(dst_dir, exist_ok=True)
                dst = os.path.join(dst_dir, os.path.basename(src))
                os.replace(src, dst)
                print(f"[mae-flow] STORY 已按用户选择自动移入本地过程区: {dst}")
    note = args.ack or ("月光宝盒自动决策" if _moonlight(st) and step.get("user_ack") else "")
    advance(flow, st, sid, step, "done", note)


def cmd_skip(flow, st, args):
    sid = st["current"]
    step = flow["steps"][sid]
    if not step.get("skippable"):
        die(f"步骤 {sid} 不可跳过。", 2)
    if not args.reason:
        die("skip 必须 --reason 说明理由(留痕)。", 2)
    if step.get("skip_requires_ack"):
        die("本步不能由 Agent 自行 skip；请走当前步骤的用户确认分支。", 2)
    advance(flow, st, sid, step, "skipped", args.reason)


def _step_agent_kinds(step):
    kinds = set()
    for spec in step.get("evidence", []):
        typ = spec.get("type")
        if typ == "review_codecheck":
            kinds.add("CODECHECK")
        elif typ in ("agent_ran", "agent_or_no_source", "review_agent_or_no_code") and spec.get("agent"):
            kinds.add(str(spec["agent"]).upper())
    return kinds


def cmd_accept_risk(flow, st, args):
    """用户有意识地只放行当前步骤某个 Agent 令牌；不跳过同一步的其他机器证据。"""
    sid = st["current"]
    step = flow["steps"][sid]
    kind = args.agent.upper()
    required = _step_agent_kinds(step)
    if kind not in required:
        die(f"当前步骤 {sid} 不需要 {kind} 令牌，不能预先或跨步骤放行。"
            + ("本步可放行: " + "、".join(sorted(required)) if required else "本步没有可风险放行的 Agent 令牌。"), 2)
    if not args.reason:
        die("accept-risk 必须 --reason 写清具体风险，不能只写『继续』。", 2)
    if not args.ack:
        die("accept-risk 必须携带用户明确承担风险的原话:--ack \"用户原话\"。", 2)
    ok, why = _ack_verified(st, args.ack, exact=True)
    if not ok:
        die("accept-risk 授权验真失败:" + why, 2)
    dirty = [p for p in _dirty_paths() if _is_source_path(p, st, flow)]
    if dirty:
        die("风险确认必须绑定稳定代码版本，但仍有未提交源码/测试/构建文件: " + "、".join(dirty[:8])
            + "。先按本单规范提交，再向用户展示风险并重新确认。", 2)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    task = (st.get("agent_tasks", {}) or {}).get(kind, {})
    rec = {"step": sid, "head": sh("git rev-parse --verify HEAD"), "at": now,
           "task_sha256": task.get("sha256", ""), "reason": args.reason, "ack": args.ack}
    st.setdefault("risk_acceptances", {})[kind] = rec
    st.setdefault("history", []).append(
        {"step": sid, "result": "accept-risk:" + kind, "note": args.reason, "at": now})
    save_state(st)
    print(f"[mae-flow] 用户已确认承担 {kind} 令牌缺失风险；仅放行当前步骤 {sid}、当前代码版本。")
    print("风险: " + args.reason)
    print("其他机器证据不会跳过；源码/测试变化、任务卡变化或进入下一步后，本次放行自动失效。现在重新执行 done。")


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
        if _moonlight(st):
            parts.append("月光宝盒=无人值守;禁止向用户提问;质量失败尽力修复后用 moonlight defer 留痕继续")
        ctx = (";" + ";".join(parts)) if parts else ""
        me = os.path.abspath(sys.argv[0])
        print(f"[mae-flow 状态] 当前步骤: {sid}({step['title']}){ctx};{perms_line(step)}。"
              f"执行 python \"{me}\" current 获取指令(勿搜索脚本位置,以此路径为准),"
              f"禁止做当前步骤之外的流程动作。"
              f"(用户与流程无关的问答/阅读/分析不受此限,照常回应;但无关的源码改动应引导用户开 worktree,勿混入交付分支)")
        return
    print(json.dumps(st, ensure_ascii=False, indent=2))


def _test_patterns(st):
    """仓库测试路径配置：config「测试路径」逗号分隔正则优先，否则读 defaults 数组。
    未配置返回 []，调用方使用 DEFAULT_TEST_PATS 保守兜底，不再 fail-open。"""
    raw = ((st or {}).get("config", {}) or {}).get("测试路径", "")
    if raw:
        return [x.strip() for x in raw.split(",") if x.strip()]
    try:
        v = json.load(open(DEFAULTS_PATH, encoding="utf-8")).get("测试路径", [])
        return v if isinstance(v, list) else []
    except Exception:
        return []


def _effective_test_patterns(st):
    """tests_only 永远有机器边界：仓库配置优先，缺失时使用保守内置规则。

    非标准测试目录应落进 .mae-flow-defaults.json；不能因为团队尚未配置就退化为
    「UT agent 可以写任意源码」。误拦有 unlock 裁决出口，但 current/doctor 会提示先修长期配置。
    """
    return DEFAULT_TEST_PATS + _test_patterns(st)


def _business_source_changed_since_step(st, sid):
    """找出某 tests_only 步骤入口后发生的非测试源码变化（提交和工作区都算）。"""
    head = (st.get("step_heads", {}) or {}).get(sid, "")
    if not head:
        return None, (f"缺少步骤 {sid} 的入口 HEAD（可能是旧版在途状态）"
                      "，不能把当前 HEAD 当入口，否则会漏检")
    changed, err = _source_changed_since(head, st)
    if err:
        return None, err
    out = []
    for raw in changed or []:
        path = raw[:-len("(未提交)")] if raw.endswith("(未提交)") else raw
        if not _is_test_file(path, st):
            out.append(raw)
    return list(dict.fromkeys(out)), ""


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
        if re.search(r"\.mae-flow\.json(\.\w+)*$|\.mae-flow-history\.jsonl$|\.mae-flow-need-reload$"
                     r"|(^|/)\.mae-flow-work/moonlight-report\.md$", p, re.I):
            die("流程状态/令牌/历史账本/待重启标记/月光宝盒报告由 mae-flow 与 hook 维护,禁止直接编辑或删除。"
                "待重启标记只能靠**重启会话**清除(SessionStart 自动删),不许手动绕过——绕过 = skill 没加载就往下走。", 2)
        if re.search(r"(^|/)\.env(\.[\w.-]+)?$", p, re.I):
            die(".env 类密钥文件禁止写入(凭据保护);确需修改请用户手动操作。", 2)
        plugin_root = norm(os.path.abspath(os.path.join(HERE, ".."))).lower()
        if norm(os.path.abspath(args.arg)).lower().startswith(plugin_root + "/"):
            die("禁止修改插件自身(flow/steps/hooks/scripts):流程规则不是交付改动的对象。", 2)
        if re.search(flow["specs_truth"], p, re.I) and not step.get("allow_specs_write"):
            die(f"openspec/specs/ 为真相源,当前步骤 {sid or '未初始化'} 禁止写入(黑名单#3)。", 2)
        if _is_source_path(p, st, flow):
            if not st:
                die("流程未初始化(无 .mae-flow.json)。禁止直接修改源码——请先按 skill 走 mae-flow init。", 2)
            if not step.get("allow_source_edit"):
                die(f"当前步骤 {sid}({step.get('title','')})禁止修改源码;先 mae-flow current 查看该做什么。", 2)
            tp = _effective_test_patterns(st) if step.get("tests_only") else []
            ul = (st or {}).get("unlock") or {}
            unlocked = ul.get("scope") == "source" and ul.get("step") == sid
            if tp and not unlocked and not any(re.search(t, p, re.I) for t in tp):
                die(f"当前步骤 {sid} 仅允许写测试路径(当前生效规则: {'|'.join(tp)})。"
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

        # Edit/Write 之外，模型也可能用 python -c、node -e 等任意解释器直接碰状态文件。
        # 与其穷举所有写法，不如禁止 Bash 直接引用这些内部文件；读取统一走 status/current/doctor。
        if hits_path(r"(^|/)(\.mae-flow\.json(?:\.\w+)?|\.mae-flow-history\.jsonl|\.mae-flow-need-reload"
                     r"|\.mae-flow-work/moonlight-report\.md)$"):
            die("流程状态、令牌、历史账本、待重启标记和月光宝盒报告禁止经 Bash 直接访问；"
                "查看请用 mae-flow status/current/doctor/moonlight report，修改只能走对应子命令。", 2)

        m = re.search(r"git\s+(?:checkout\s+-[bB]|switch\s+-[cC])\s+(\S+)"
                      r"|git\s+(?:checkout|switch)\s+(?!-)(\S+)"
                      r"|git\s+branch\s+(?:-[mM]\s+\S+\s+)?(?!-)(\S+)\s*$", c)
        if m and st:
            name = m.group(1) or m.group(2) or m.group(3)
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
        if re.search(r"git\s+add\s+(-A\b|--all\b|\.(\s|$))", c):
            die("禁止宽提交(git add -A / --all / .):会把无关文件与不入库产物卷进交付分支"
                "(实战:STORY 选了不入库仍被卷进 MR)。git add 必须精确到文件/明确的产物目录。", 2)
        if re.search(r"(mkdir|md|new-item)\b", c, re.I) and hits_path(r"(^|/)openspec/"):
            die("禁止手动创建 openspec 目录:openspec/changes/ 由 comet 工具建(comet-open 技能 / comet-state init),"
                "它建目录的同时登记 .comet.yaml 状态——手搓的空壳目录没有状态登记,后续 guard/证据校验必然踩空(2026-07-20 实战)。"
                "若 /comet-open 调不起来,十有八九是 skill 没加载:先重启会话(检查有无 .mae-flow-need-reload 提示),别手搓绕过。", 2)
        if re.search(r"\bcomet\s+init\b", c):
            die("comet init 是交互式 TUI,禁止在会话内执行(含子 agent、含 echo/yes 管道喂输入等一切自动化变体)——"
                "非交互执行会把全部 agent 平台的配置初始化出来污染仓库(2026-07-20 实战)。"
                "把三要素交给用户手动执行:①目录=项目根 ②命令=comet init --language zh --scope project "
                "③交互里平台只选 Claude Code。用户跑完说\"好了\"再继续。", 2)
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
        if writeish and hits_path(r"\.mae-flow(\.json|-history\.jsonl|-need-reload)"
                                  r"|\.mae-flow-work/moonlight-report\.md"):
            die("流程状态/历史账本/待重启标记/月光宝盒报告由 mae-flow 维护,禁止经 Bash 改写/删除"
                "(待重启标记只能靠重启会话清)。", 2)
        if writeish and hits_path(flow["specs_truth"]) and not step.get("allow_specs_write"):
            die(f"openspec/specs/ 为真相源,当前步骤 {sid or '未初始化'} 禁止经 Bash 写入(黑名单#3)。", 2)
        source_toks = [t for t in toks if _is_source_path(t, st, flow)]
        if writeish and source_toks:
            if not st:
                die("流程未初始化(无 .mae-flow.json)。禁止经 Bash 写源码——请先按 skill 走 mae-flow init。", 2)
            if not step.get("allow_source_edit"):
                die(f"当前步骤 {sid} 禁止经 Bash 写源码文件。", 2)
            tp = _effective_test_patterns(st) if step.get("tests_only") else []
            ul = (st or {}).get("unlock") or {}
            if tp and not (ul.get("scope") == "source" and ul.get("step") == sid):
                bad = [t2 for t2 in source_toks
                       if not any(re.search(t, t2, re.I) for t in tp)]
                if bad:
                    die(f"当前步骤 {sid} 仅允许写测试路径(当前生效规则: {'|'.join(tp)});"
                        f"命中非测试源码: {'、'.join(bad[:3])}。经用户裁决确为代码缺陷时用 unlock source 解锁。", 2)
        sys.exit(0)
    die("gate 用法: gate edit <路径> | gate bash <命令>")


def _task_scope(st):
    diff, err = _scope_diff(st)
    if err:
        return "", [], err
    out = sh(f"git -c core.quotepath=false diff --name-status {diff}")
    return diff, [x for x in out.splitlines() if x.strip()], ""


def _requirement_sources(st):
    out = []
    doc = st.get("config", {}).get("需求文档", "")
    if doc and os.path.exists(doc):
        out.append(os.path.abspath(doc))
    cn = st.get("config", {}).get("CHANGE_NAME", "")
    if cn:
        pats = [f"openspec/changes/{cn}/specs/*/spec.md",
                f"openspec/changes/archive/*{cn}*/specs/*/spec.md",
                f"openspec/archive/*{cn}*/specs/*/spec.md"]
        for p in pats:
            out.extend(os.path.abspath(x) for x in globmod.glob(p))
    return list(dict.fromkeys(out))


def cmd_agent_task(flow, st, args):
    """由代码生成完整子 Agent 任务卡，主模型不再临时拼参数。"""
    kind = args.kind.upper()
    expected_steps = {"COMPILE": {"build", "rf_compile", "tw_compile", "verify_recompile", "verify_post_ponytail_compile"},
                      "CODECHECK": {"verify_codecheck", "tw_codecheck", "rf_codecheck", "rf_verify"},
                      "UT": {"verify_ut", "rf_ut", "tw_ut", "rf_verify"}}
    sid = st["current"]
    (st.get("risk_acceptances", {}) or {}).pop(kind, None)  # 新任务卡=新证据轮次，旧风险确认作废
    if sid not in expected_steps[kind]:
        die(f"当前步骤 {sid} 不允许生成 {kind} 任务卡；先执行 current,禁止提前派发。", 2)
    dirty_source = [p for p in _dirty_paths() if _is_source_path(p, st, flow)]
    if dirty_source:
        die("生成任务卡前仍有未提交源码/测试/构建文件: " + "、".join(dirty_source[:8])
            + "。任务卡只信 Git 可追踪范围；先按单号格式精确提交，或回退不属于本单的改动。", 2)
    if kind == "CODECHECK":
        scan = (st.get("quality", {}) or {}).get("codecheck_scan", {})
        if scan.get("step") != sid:
            die("先执行 codecheck-scan 冻结首检结果，再生成 CODECHECK 任务卡。", 2)
        if scan.get("count", 0) == 0:
            die("机器首检为 0 告警，不应派 codecheck-fix-agent；直接 done。", 2)
        changed, why = _source_changed_since(scan.get("head", ""), st)
        if why:
            die("CodeCheck 首检基点失效:" + why + "；重新执行 codecheck-scan", 2)
        if changed:
            die("首检后、修复 Agent 启动前源码已变化: " + "、".join(changed[:5])
                + "。禁止主会话先修再补手续；回退这些改动后重扫。", 2)
    diff, changes, err = _task_scope(st)
    if err:
        die(err, 2)
    cfg = st.get("config", {})
    task_head = sh("git rev-parse --verify HEAD")
    lines = [
        f"# Mae-Flow {kind} TASK CARD",
        "本文件由 harness 生成。不得猜测、替换或省略其中配置；缺项按 agent 契约 FAIL/BLOCKED 收尾。",
        f"项目根: {os.path.abspath(os.getcwd())}",
        f"当前步骤: {sid}",
        f"任务卡基点 HEAD: {task_head}",
        f"单号: {cfg.get('单号', '')}",
        f"单号类型: {cfg.get('单号类型', '')}",
        f"需求基线分支: {cfg.get('基线分支', '')}",
        f"本轮检查范围: {diff}",
        f"本次子任务范围: {args.scope or '任务卡文件清单全部'}",
        f"编译方式: {cfg.get('编译方式', '')}",
        f"UT生成方式: {cfg.get('UT生成方式', '')}",
        f"UT运行命令: {cfg.get('UT运行命令', '')}",
        "需求/规格依据:",
    ]
    sources = _requirement_sources(st)
    lines.extend("- " + x for x in sources)
    if not sources:
        lines.append("- （未找到；UT agent 必须 FAIL，禁止对着实现猜测试）")
    lines.append("本轮文件清单:")
    lines.extend("- " + x for x in changes)
    if not changes:
        lines.append("- （无代码变更）")
    scan = (st.get("quality", {}) or {}).get("codecheck_scan", {})
    if kind == "CODECHECK":
        lines += [f"Harness首检告警数: {scan.get('count', '未执行')}",
                  "Harness首检文件: " + "、".join(scan.get("files", [])),
                  "Harness首检告警(规则|文件): " + "、".join(r + "|" + f for r, f in scan.get("pairs", [])),
                  "职责:只处理任务卡范围内首检告警；主会话不得代修；修复后按任务卡编译方式验证并复验。"]
    elif kind == "UT":
        lines += ["职责:只对任务卡范围补/改测试；必须按 UT生成方式调用对应 Skill；参考 UT运行命令提示真实执行测试。该项写随生成方式自带时，由 UT Skill 按项目决定实际命令，并在 EXECUTED_UT 如实报告。",
                  "评审返工不修改规格，测试依据使用上面列出的既有需求/规格。"]
    else:
        lines += ["职责:严格按任务卡的编译方式执行；配置为 build-fix 时必须调用 build-fix Skill，禁止猜命令。"]
    body = "\n".join(lines).rstrip() + "\n"
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    body += f"TASK_CARD_SHA256: {digest}\n"
    d = os.path.abspath(os.path.join(".mae-flow-work", "agent-tasks"))
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{sid}-{kind.lower()}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    st.setdefault("agent_tasks", {})[kind] = {
        "step": sid, "path": path, "sha256": digest,
        "head": task_head, "scope": args.scope or "",
        "allowed_files": scan.get("files", []) if kind == "CODECHECK" else [],
        "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    save_state(st)
    print(f"[mae-flow] {kind} 任务卡已生成: {path}")
    print(f"启动对应专项 agent 时只传这一句:\n读取并严格执行任务卡 \"{path}\"；最终报告必须原样带 TASK_CARD_SHA256: {digest}")


def cmd_codecheck_scan(flow, st, args):
    if st["current"] not in ("verify_codecheck", "tw_codecheck", "rf_codecheck"):
        die("codecheck-scan 只能在规范检查步骤执行；先按 current 进入对应步骤。", 2)
    sid = st["current"]
    entry_head = (st.get("step_heads", {}) or {}).get(sid, "")
    if entry_head:
        changed, why = _source_changed_since(entry_head, st)
        if why:
            die("无法核对规范检查入口 HEAD:" + why, 2)
        if changed:
            try:
                tok = json.load(open(STATE_PATH + ".tokens", encoding="utf-8")).get("CODECHECK", {})
            except Exception:
                tok = {}
            legal_round = (isinstance(tok, dict) and tok.get("step") == sid
                           and tok.get("status") in ("CLEAN", "REMAINING"))
            after, token_err = _source_changed_since(tok.get("head", ""), st) if legal_round else (None, "无合法令牌")
            if not legal_round or token_err or after:
                die("进入规范检查后源码已被修改，但没有一轮可核实的 CodeCheck Agent 收尾: " + "、".join(changed[:5])
                    + "。禁止主会话先修再补跑首检；回退越权改动。若确为上一轮 Agent 修复，先让它按契约合法收尾。", 2)
    files, err = _biz_changed_files(st)
    if err:
        die(err, 2)
    result, err = _run_codecheck(files) if files else ({"total": 0, "pairs": [], "commands": []}, "")
    if err:
        die(err, 2)
    st.setdefault("quality", {})["codecheck_scan"] = {
        "step": sid, "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "head": sh("git rev-parse --verify HEAD"), "count": result["total"],
        "files": files, "pairs": result["pairs"], "commands": result["commands"]}
    # 每次重扫都是新一轮；旧 Agent 令牌不能替新告警背书。
    try:
        p = STATE_PATH + ".tokens"
        toks = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
        toks.pop("CODECHECK", None)
        tmp = p + ".tmp"
        open(tmp, "w", encoding="utf-8").write(json.dumps(toks, ensure_ascii=False))
        os.replace(tmp, p)
    except Exception:
        pass
    (st.get("agent_tasks", {}) or {}).pop("CODECHECK", None)
    save_state(st)
    print(f"[mae-flow] CodeCheck 首检完成:业务文件 {len(files)} 个,告警 {result['total']} 条。")
    if result["total"]:
        print("禁止主会话修复。下一步执行 agent-task codecheck 生成完整任务卡，再启动 codecheck-fix-agent。")
    else:
        print("零告警，不派修复 agent；直接 done（期间源码若变化，证据会过期并要求重扫）。")


def cmd_codecheck_record(flow, st, args):
    """CodeCheck 输出格式未知时的人工恢复口，不把工具兼容问题变成无解死锁。"""
    if st["current"] not in ("verify_codecheck", "tw_codecheck", "rf_codecheck"):
        die("codecheck-record 只能在规范检查步骤使用。", 2)
    if args.count < 0 or not args.reason or not args.ack:
        die("codecheck-record 需要非负 --count、--reason 和用户确认原话 --ack。", 2)
    ok, why = _ack_verified(st, args.ack)
    if not ok:
        die("人工确认验真失败:" + why, 2)
    diag = os.path.abspath(args.diagnostic)
    root = os.path.abspath(os.path.join(".mae-flow-work", "codecheck-diagnostics"))
    if not (diag == root or diag.startswith(root + os.sep)) or not os.path.isfile(diag):
        die("--diagnostic 必须是本流程保存的 .mae-flow-work/codecheck-diagnostics/ 文件。", 2)
    try:
        entered = time.mktime(time.strptime(_step_entered_at(st), "%Y-%m-%d %H:%M:%S"))
    except Exception:
        entered = 0
    if os.path.getmtime(diag) + 2 < entered:
        die("诊断文件早于当前 CodeCheck 步骤，不能拿旧现场登记本轮结果；请重新执行 codecheck-scan。", 2)
    files, err = _biz_changed_files(st)
    if err:
        die(err, 2)
    digest = hashlib.sha256(open(diag, "rb").read()).hexdigest()
    head = sh("git rev-parse --verify HEAD")
    rec = {"step": st["current"], "head": head, "files": files, "count": args.count,
           "diagnostic": diag, "diagnostic_sha256": digest, "reason": args.reason,
           "ack": args.ack, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    st.setdefault("quality", {})["codecheck_manual"] = rec
    st["quality"]["codecheck_scan"] = {"step": st["current"], "head": head,
        "files": files, "pairs": [], "commands": ["人工核对诊断文件:" + diag],
        "count": args.count, "at": rec["at"], "manual": True}
    try:
        p = STATE_PATH + ".tokens"
        toks = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
        toks.pop("CODECHECK", None)
        tmp = p + ".tmp"
        open(tmp, "w", encoding="utf-8").write(json.dumps(toks, ensure_ascii=False))
        os.replace(tmp, p)
    except Exception:
        pass
    (st.get("agent_tasks", {}) or {}).pop("CODECHECK", None)
    save_state(st)
    print(f"[mae-flow] 已记录人工核对结果: {args.count} 条，绑定 HEAD {head[:12]} 与诊断 SHA256 {digest[:12]}。")
    print("0 条可直接 done；大于 0 条必须生成 codecheck 任务卡交修复 Agent，不能把人工记录当豁免。")


def cmd_approve_exemption(flow, st, args):
    if st["current"] not in ("verify_codecheck", "tw_codecheck", "rf_codecheck"):
        die("规范告警豁免只能在 CodeCheck 步骤审批。", 2)
    if not args.ack or not args.reason:
        die("approve-exemption 必须带 --reason 和 --ack 用户原话。", 2)
    asked, why = ev_agent_ran({"agent": "ASKUSER"}, st)
    if not asked:
        die("豁免前必须真实使用 AskUserQuestion 逐项呈用户裁决:" + why, 2)
    ok, why = _ack_verified(st, args.ack)
    if not ok:
        die("豁免授权验真失败:" + why, 2)
    rule, file_name = args.rule.strip(), norm(args.file.strip()).lstrip("./")
    if not rule or not file_name:
        die("--rule/--file 不能为空。", 2)
    rec = {"rule": rule, "file": file_name, "reason": args.reason,
           "ack": args.ack, "step": st["current"], "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    rows = st.setdefault("codecheck_exemptions", [])
    key = _approval_key(rule, file_name)
    rows[:] = [x for x in rows if _approval_key(x.get("rule", ""), x.get("file", "")) != key]
    rows.append(rec)
    ex = os.path.join("docs", "codecheck-exempt-" + st["config"].get("单号", "") + ".md")
    os.makedirs(os.path.dirname(ex), exist_ok=True)
    if not os.path.exists(ex):
        open(ex, "w", encoding="utf-8").write("# CodeCheck 正式豁免记录\n\n")
    safe_ack = re.sub(r"[\r\n|]+", " ", args.ack).strip()
    safe_reason = re.sub(r"[\r\n|]+", " ", args.reason).strip()
    with open(ex, "a", encoding="utf-8") as f:
        f.write(f"- {rule} | {file_name} | {safe_reason} | 用户原话:{safe_ack}\n")
    save_state(st)
    print(f"[mae-flow] 已登记用户批准的正式豁免: {rule} | {file_name}\n"
          f"记录已写入 {ex}；请精确 git add/commit，禁止手写其他豁免冒充审批。")


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
    nac = _active_change_count()
    print(("✅" if nac <= 1 else "❌") + f" 活跃 change 数: {nac}" + ("(僵尸在场!comet 会抽错人,清理见下)" if nac > 1 else ""))
    for _w in _sentinel_lines(sid, st):
        print("   " + _w)
    for kind, rec in sorted((st.get("risk_acceptances", {}) or {}).items()):
        if rec.get("step") != sid:
            continue
        valid, why = _risk_acceptance(kind, st)
        if valid:
            print(f"⚠ 用户风险放行: {kind}（当前步骤/任务卡/HEAD 有效；其他证据不受影响）")
        else:
            print(f"❌ 用户风险放行已失效: {kind}（{why}）")
    if step.get("tests_only"):
        head, why = _ensure_step_entry_head(flow, st, sid)
        print(("✅" if head else "❌") + " UT 步骤入口 HEAD: "
              + ((head[:12] + "（旧状态已自动恢复或原本存在）") if head else why))
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
    if step.get("tests_only"):
        tp = _test_patterns(st)
        if tp:
            print("✅ 测试路径硬边界: " + " | ".join(tp))
        else:
            print("⚠ 测试路径未配置:当前使用内置保守规则硬拦非测试源码;"
                  "非标准测试目录请在 .mae-flow-defaults.json 补「测试路径」")
    sp = _configured_source_patterns(st)
    print(("✅" if sp else "ℹ") + " 私有源码路径: "
          + (" | ".join(sp) if sp else "未配置（使用跨仓扩展名、构建文件和通用目录规则）"))
    # 观测项(公司机金丝雀关注):ack 验真存储 与 UTRUN 令牌——两者依赖 harness payload 字段
    try:
        n = len(json.loads(open(STATE_PATH + ".usermsg", encoding="utf-8").read() or "[]"))
        print(f"✅ ack 验真存储: {n} 条用户输入" if n else
              "❌ ack 验真存储: 空(确认步骤会拒绝推进；请让用户发送一条普通消息后重试)")
    except Exception:
        print("❌ ack 验真存储: 不存在(确认步骤会拒绝推进；检查 UserPromptSubmit hook，"
              "临时恢复方式是让用户发送普通确认消息后重试)")
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
    risk_n = sum(1 for h in st["history"] if str(h.get("result", "")).startswith("accept-risk:"))
    if fr:
        print(f"摩擦统计: gate 拦截 {fr['gate拦截']} 次 · 子agent契约打回 {fr['契约打回']} 次"
              f" · hook 异常 {fr['hook异常']} 次 · goto 人工跳转 {goto_n} 次 · 风险放行 {risk_n} 次")
    else:
        print(f"摩擦统计: hook 日志不可读 · goto 人工跳转 {goto_n} 次 · 风险放行 {risk_n} 次")


def _moonlight_report_text(flow, st):
    ml = _moonlight_data(st)
    cfg = st.get("config", {}) or {}
    branch = sh("git branch --show-current") or "未知"
    head = sh("git rev-parse --verify HEAD") or "未知"
    upstream = sh("git rev-parse --abbrev-ref --symbolic-full-name @{u}") or "未设置"
    unresolved = _moonlight_unresolved(st)
    resolved = [x for x in (ml.get("issues") or []) if x.get("resolved_at")]
    lines = [
        "# 月光宝盒执行报告",
        "",
        f"- 单号：{cfg.get('单号', '未设置')}",
        f"- 工作流：{(st.get('choices', {}) or {}).get('workflow', '未选择')}",
        f"- 当前步骤：{st.get('current', '?')}",
        f"- 分支：{branch}",
        f"- HEAD：{head}",
        f"- 上游：{upstream}",
        f"- 启动时间：{ml.get('activated_at', '未知')}",
        f"- 最近推送：{ml.get('pushed_at', '尚未完成')}",
        f"- 无人值守轮次：{ml.get('cycle', 1)}",
        "",
        "## 启动需求原话",
        "",
        str(ml.get("request", "")).strip() or "旧状态未记录；以已确认需求文档和当前配置为准。",
        "",
        "## 当前结论",
        "",
    ]
    if st.get("current") == "moonlight_review":
        lines.append("夜间执行已经走到推送，规格尚未自动归档。")
    elif ml.get("hard_blocked"):
        lines.append("夜间执行遇到无法自行补齐的硬阻塞，已如实停在当前步骤，尚未推送。")
    else:
        lines.append("仍在执行中或尚未成功推送；可执行 moonlight report 随时刷新本报告。")
    lines += ["", "## 尚未解决的问题", ""]
    if unresolved:
        for x in unresolved:
            lines += [
                f"### {x.get('id', '?')} · {x.get('kind', '?')} · {x.get('step', '?')}",
                "",
                f"- 记录时间：{x.get('at', '')}",
                f"- 代码版本：{x.get('head', '')}",
                f"- 问题与已尝试处理：{x.get('reason', '')}",
            ]
            if x.get("rejection"):
                lines.append(f"- Harness 诊断：{x['rejection']}")
            if x.get("dirty_paths"):
                lines.append("- 未提交现场：" + "、".join(x["dirty_paths"]))
            lines.append("")
    else:
        lines += ["无。", ""]
    lines += ["## 已在后续复验中解决的问题", ""]
    if resolved:
        for x in resolved:
            lines.append(
                f"- {x.get('id', '?')} [{x.get('kind', '?')}] {x.get('reason', '')} "
                f"→ {x.get('resolved_at', '')} 已复验")
    else:
        lines.append("无。")
    lines += ["", "## 夜间推进记录", ""]
    activated = ml.get("activated_at", "")
    rows = [h for h in st.get("history", []) if not activated or h.get("at", "") >= activated]
    if rows:
        for h in rows:
            note = f"：{h.get('note')}" if h.get("note") else ""
            lines.append(f"- {h.get('at', '')} `{h.get('step', '?')}` {h.get('result', '')}{note}")
    else:
        lines.append("暂无。")
    lines += [
        "",
        "## 早晨操作",
        "",
        "- 继续修复遗留：`moonlight repair`",
        "- 重新查看报告：`moonlight report`",
        "- 结果满意并进入规格定稿：`moonlight finalize`",
        "",
        "报告位于 `.mae-flow-work/`，不会进入业务提交。",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _write_moonlight_report(flow, st):
    os.makedirs(os.path.dirname(MOONLIGHT_REPORT_PATH), exist_ok=True)
    text = _moonlight_report_text(flow, st)
    tmp = MOONLIGHT_REPORT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, MOONLIGHT_REPORT_PATH)
    return text


def _moonlight_latest_rejection(kind):
    try:
        data = json.load(open(STATE_PATH + ".agent-rejections", encoding="utf-8"))
    except Exception:
        return ""
    label = {"compile": "COMPILE", "codecheck": "CODECHECK", "ut": "UT"}.get(kind, "")
    rec = data.get(label, {}) if label else {}
    return str((rec or {}).get("reason", ""))[:1500]


def _new_state():
    _gitignore()
    dirty = _dirty_paths()
    return {
        "current": FLOW["start"], "config": {}, "choices": {},
        "history": [], "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "initial_dirty": dirty,
        "initial_dirty_fingerprints": {p: _path_fingerprint(p) for p in dirty},
    }


def _consume_preinit_moonlight_intent(ack):
    """消费 UserPromptSubmit Hook 在 STATE 创建前留下的一次性授权。

    仅接受十分钟内的记录，且命令携带的 ack 必须来自原始用户消息。这样既支持“一句话
    开启月光宝盒”，也不会把历史残留文件当成永久授权。
    """
    if not ack:
        return False, "命令未携带 --ack", ""
    try:
        rec = json.load(open(MOONLIGHT_INTENT_PATH, encoding="utf-8"))
    except Exception:
        return False, ("未捕获到本轮用户的月光宝盒授权。请让用户用普通消息明确说一次"
                       "“开启月光宝盒”，再执行本命令。"), ""
    try:
        age = time.time() - float(rec.get("epoch", 0))
    except Exception:
        age = 999999
    if age < -30 or age > 600:
        try:
            os.remove(MOONLIGHT_INTENT_PATH)
        except OSError:
            pass
        return False, "捕获到的月光宝盒授权已超过十分钟，请让用户重新明确授权。", ""

    def compact(value):
        return re.sub(r"\s+", "", value or "")

    text = rec.get("text", "")
    if not re.search(r"月光宝盒|moonlight", text, re.I):
        return False, "捕获的用户原话没有明确提到月光宝盒。", ""
    if compact(ack) not in compact(text):
        return False, "--ack 不在本轮用户原话中，禁止由 Agent 自行补授权。", ""
    try:
        os.remove(MOONLIGHT_INTENT_PATH)
    except OSError:
        pass
    return True, "", text


def _moonlight_request_from_messages(st, ack):
    """从当前步骤捕获的真实用户消息中取出完整启动原话，供断点恢复。"""
    try:
        msgs = json.loads(open(STATE_PATH + ".usermsg", encoding="utf-8").read() or "[]")
    except Exception:
        msgs = []
    needle = re.sub(r"\s+", "", ack or "")
    entered = _step_entered_at(st)
    sid = st.get("current", "")
    for msg in reversed(msgs):
        text = msg.get("text", "")
        if (needle and needle in re.sub(r"\s+", "", text)
                and msg.get("at", "") >= entered
                and (not msg.get("step") or msg.get("step") == sid)):
            return text
    return ""


def cmd_moonlight(flow, st, args):
    action = args.action
    if action in ("on", "continue"):
        if not args.ack:
            die("开启月光宝盒必须携带用户原话: --ack \"用户要求无人值守开发的原话\"。", 2)
        resumed_from_direct = False
        authorized_preinit = False
        activation_request = ""
        if os.path.exists(EXIT_PATH):
            # 直接开发模式的用户消息保存在退出记录中。允许 shell 只传“月光宝盒/moonlight”
            # 这个短词，但恢复函数仍使用捕获到的完整原文验真。
            try:
                rec = json.load(open(EXIT_PATH, encoding="utf-8"))
                needle = re.sub(r"\s+", "", args.ack or "")
                full_ack = next(
                    (m.get("text", "") for m in reversed(rec.get("direct_messages", []) or [])
                     if needle and needle in re.sub(r"\s+", "", m.get("text", ""))),
                    args.ack or "")
            except Exception:
                full_ack = args.ack or ""
            st = _resume_direct_mode(full_ack)
            resumed_from_direct = True
            activation_request = full_ack
        if st is None:
            authorized_preinit, why, activation_request = _consume_preinit_moonlight_intent(args.ack)
            if not authorized_preinit:
                die("月光宝盒授权验真失败:" + why, 2)
            st = _new_state()
            save_state(st)
        # 一键入口允许 --ack 取本轮用户消息中的“月光宝盒/moonlight”短语，
        # 避免把整段需求塞进 shell；仍必须命中当前步骤后的真实用户输入。
        if not resumed_from_direct and not authorized_preinit:
            ok, why = _ack_verified(st, args.ack, exact=False)
            if not ok:
                die("月光宝盒授权验真失败:" + why, 2)
            activation_request = _moonlight_request_from_messages(st, args.ack)
        ml = _moonlight_data(st)
        if not ml.get("enabled"):
            ml.update({
                "enabled": True,
                "activated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "ack": args.ack,
                "request": activation_request[:4000],
                "cycle": max(1, int(ml.get("cycle", 0) or 0) + 1),
            })
            st.setdefault("history", []).append({
                "step": st["current"], "result": "moonlight:on",
                "note": "用户授权无人值守、尽力修复并推送",
                "at": time.strftime("%Y-%m-%d %H:%M:%S")})
        if st.get("current") == "archive_confirm":
            st.setdefault("history", []).append({
                "step": "archive_confirm", "result": "moonlight:archive-deferred",
                "note": "中途切换月光宝盒，规格定稿留到早晨",
                "at": time.strftime("%Y-%m-%d %H:%M:%S")})
            st["current"] = "push"
            st.setdefault("step_heads", {})["push"] = sh("git rev-parse --verify HEAD")
        elif st.get("current") == "archive":
            # archive 是不可逆动作。尚未开始时直接推送；若活跃 change 已消失，说明定稿工具
            # 可能已执行到一半，不能为了夜间直行自动猜测、回滚或补做。
            change_name = (st.get("config", {}) or {}).get("CHANGE_NAME", "")
            active_change = os.path.join("openspec", "changes", change_name) if change_name else ""
            if active_change and os.path.isdir(active_change):
                st.setdefault("history", []).append({
                    "step": "archive", "result": "moonlight:archive-deferred",
                    "note": "定稿尚未执行，夜间先推送",
                    "at": time.strftime("%Y-%m-%d %H:%M:%S")})
                st["current"] = "push"
                st.setdefault("step_heads", {})["push"] = sh("git rev-parse --verify HEAD")
            else:
                now = time.strftime("%Y-%m-%d %H:%M:%S")
                issues = ml.setdefault("issues", [])
                issue = {
                    "id": "ML-%03d" % (len(issues) + 1), "step": "archive",
                    "kind": "blocker", "at": now,
                    "head": sh("git rev-parse --verify HEAD"),
                    "reason": "切换月光宝盒时规格定稿可能已经开始，活跃 change 已不存在或无法定位；"
                              "不可自动回滚、补做或假定完成，需要早晨核对定稿现场。",
                }
                issues.append(issue)
                ml["hard_blocked"] = {
                    "at": now, "step": "archive", "head": issue["head"],
                    "issue": issue["id"], "reason": issue["reason"],
                }
                st.setdefault("history", []).append({
                    "step": "archive", "result": "moonlight:blocked",
                    "note": issue["id"] + " " + issue["reason"], "at": now})
        save_state(st)
        _write_moonlight_report(flow, st)
        print("[mae-flow] 🌙 月光宝盒已开启。后续不再询问用户；质量问题尽力修复后可登记遗留继续，"
              "目标是推送分支并停在晨间检查。")
        print_current(flow, st)
        return

    if st is None:
        die("流程未初始化；开启新任务请先执行 moonlight on。", 2)
    if action == "report":
        text = _write_moonlight_report(flow, st)
        print(text, end="")
        print(f"\n[mae-flow] 报告已写入: {os.path.abspath(MOONLIGHT_REPORT_PATH)}")
        return
    if action == "off":
        if _moonlight(st):
            _moonlight_data(st)["enabled"] = False
            _moonlight_data(st)["disabled_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            st.setdefault("history", []).append({
                "step": st["current"], "result": "moonlight:off", "note": "恢复普通交互模式",
                "at": time.strftime("%Y-%m-%d %H:%M:%S")})
            save_state(st)
        print("[mae-flow] 月光宝盒已关闭，当前断点保留；后续恢复普通确认和严格门禁。")
        print_current(flow, st)
        return
    if not _moonlight(st):
        die("当前未开启月光宝盒。", 2)
    if action == "blocked":
        sid = st["current"]
        if not _moonlight_can_block(sid):
            kind = _moonlight_step_kind(sid)
            remedy = ("moonlight defer" if kind else
                      "moonlight push-failed" if sid == "push" else "当前已经处于安全停点")
            die(f"当前步骤 {sid} 不能使用 blocked；请使用 {remedy}。", 2)
        reason = (args.reason or "").strip()
        if len(reason) < 12:
            die("moonlight blocked 必须写清缺失条件、已经尝试的确认以及无法继续的原因。", 2)
        ml = _moonlight_data(st)
        issues = ml.setdefault("issues", [])
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        for old in _moonlight_unresolved(st):
            if old.get("kind") == "blocker":
                old["resolved_at"] = now
                old["resolved_as"] = "superseded"
        issue = {
            "id": "ML-%03d" % (len(issues) + 1), "step": sid, "kind": "blocker",
            "at": now, "head": sh("git rev-parse --verify HEAD"), "reason": reason,
            "dirty_paths": _dirty_paths()[:100],
        }
        issues.append(issue)
        ml["hard_blocked"] = {
            "at": now, "step": sid, "head": issue["head"],
            "issue": issue["id"], "reason": reason,
        }
        st.setdefault("history", []).append({
            "step": sid, "result": "moonlight:blocked",
            "note": issue["id"] + " " + reason, "at": now})
        save_state(st)
        _write_moonlight_report(flow, st)
        print("[mae-flow] 月光宝盒已记录无法自动解决的硬阻塞并保存现场。"
              "本轮允许正常停止；早晨执行 moonlight report 查看，条件补齐后执行 moonlight repair 继续当前步骤。")
        return
    if action == "push-failed":
        if st.get("current") != "push":
            die("moonlight push-failed 只允许在 push 步骤使用。", 2)
        reason = (args.reason or "").strip()
        if len(reason) < 12:
            die("push-failed 必须记录错误原文和已经尝试的处理。", 2)
        ml = _moonlight_data(st)
        issues = ml.setdefault("issues", [])
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        issue = {
            "id": "ML-%03d" % (len(issues) + 1), "step": "push", "kind": "push",
            "at": now, "head": sh("git rev-parse --verify HEAD"), "reason": reason,
        }
        issues.append(issue)
        st.setdefault("history", []).append({
            "step": "push", "result": "moonlight:push-failed",
            "note": issue["id"] + " " + reason, "at": now})
        save_state(st)
        _write_moonlight_report(flow, st)
        print("[mae-flow] push 失败已写入月光宝盒报告。保持在 push，不伪造远端成功；"
              "早晨处理认证/网络/冲突后重新 push，再执行 done。")
        return
    if action == "unlock-source":
        sid = st["current"]
        if not flow["steps"].get(sid, {}).get("tests_only"):
            die("moonlight unlock-source 只允许在 UT 步骤使用。", 2)
        reason = (args.reason or "").strip()
        if len(reason) < 12:
            die("unlock-source 必须写清失败用例、规格依据和自查结论，不能只写“源码有问题”。", 2)
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        st["unlock"] = {
            "scope": "source", "step": sid, "at": now,
            "reason": reason, "moonlight": True,
        }
        st.setdefault("history", []).append({
            "step": sid, "result": "moonlight:unlock-source", "note": reason, "at": now})
        save_state(st)
        print("[mae-flow] 月光宝盒已记录 UT 自查结论并解锁本步源码修复。"
              "修复后提交，再执行 done；harness 会自动回流完整质量链。")
        return
    if action == "defer":
        sid = st["current"]
        kind = _moonlight_step_kind(sid)
        if not kind:
            die(f"当前步骤 {sid} 不是可带遗留推进的质量步骤。分析、实现和推送本身不能伪装完成。", 2)
        reason = (args.reason or "").strip()
        if len(reason) < 12:
            die("moonlight defer 的 --reason 必须写清遗留现象、已尝试处理和风险，不能只写“失败/继续”。", 2)
        if sid == "build":
            # build 同时承担需求实现与编译收尾。月光模式只能放过编译结果，不能把未实现完的
            # tasks 一起跳过，否则“尽力而为”会退化成推送半成品。
            for evaluator in (ev_tasks_checked, ev_commit_tagged_after_entry):
                ok, why = evaluator({}, st)
                if not ok:
                    die("build 尚未达到“实现完成、仅编译遗留”的边界，不能 defer: " + why
                        + "。继续完成实现；若需求/权限/外部依赖客观缺失，改用 moonlight blocked 留痕停止。", 2)
        dirty = [p for p in _dirty_paths() if _is_source_path(p, st, flow)]
        if dirty:
            die("带遗留推进前必须先提交当前有效源码/测试/构建改动，否则 push 会漏文件: "
                + "、".join(dirty[:8]), 2)
        ml = _moonlight_data(st)
        issues = ml.setdefault("issues", [])
        issue_id = "ML-%03d" % (len(issues) + 1)
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        for old in _moonlight_unresolved(st):
            if old.get("kind") == kind:
                old["resolved_at"] = now
                old["resolved_as"] = "superseded"
                old["superseded_by"] = issue_id
        issue = {
            "id": issue_id, "step": sid, "kind": kind, "at": now,
            "head": sh("git rev-parse --verify HEAD"), "reason": reason,
            "rejection": _moonlight_latest_rejection(kind),
        }
        issues.append(issue)
        st.setdefault("history", []).append({
            "step": sid, "result": "moonlight:defer", "note": issue_id + " " + reason,
            "at": now})
        save_state(st)
        _write_moonlight_report(flow, st)
        advance(flow, st, sid, flow["steps"][sid], "moonlight-deferred", issue_id)
        return
    if action == "repair":
        ml = _moonlight_data(st)
        if ml.get("hard_blocked"):
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            blocker = ml.pop("hard_blocked")
            for issue in _moonlight_unresolved(st):
                if issue.get("kind") == "blocker":
                    issue["resolved_at"] = now
                    issue["resolved_as"] = "morning-retry"
            ml["cycle"] = int(ml.get("cycle", 1)) + 1
            st.setdefault("history", []).append({
                "step": st["current"], "result": "moonlight:repair-blocker",
                "note": str(blocker.get("issue", "")), "at": now})
            save_state(st)
            _write_moonlight_report(flow, st)
            print(f"[mae-flow] 已解除夜间硬阻塞标记，开始第 {ml['cycle']} 轮，"
                  f"从原步骤 {st['current']} 继续；旧质量证据仍按代码版本校验。")
            print_current(flow, st)
            return
        if st.get("current") != "moonlight_review":
            die("只有夜间推送完成、停在 moonlight_review 后才能按报告开启修复轮。"
                "当前仍在执行中，请先继续到 push。", 2)
        issues = _moonlight_unresolved(st)
        if not issues:
            print("[mae-flow] 报告中没有尚未解决的问题，无需开启修复轮；可直接 moonlight finalize。")
            return
        workflow = (st.get("choices", {}) or {}).get("workflow", "")
        target = MOONLIGHT_REPAIR_ENTRY.get(workflow)
        if not target:
            die("无法根据工作流选择修复入口，当前 workflow=" + (workflow or "未设置"), 2)
        ml = _moonlight_data(st)
        if any(x.get("kind") == "environment" for x in issues):
            ml["repair_after_environment"] = target
            target = "env_setup"
        ml["cycle"] = int(ml.get("cycle", 1)) + 1
        ml["repair_started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        for issue in issues:
            issue["repair_cycle"] = ml["cycle"]
        st.setdefault("history", []).append({
            "step": "moonlight_review", "result": "moonlight:repair",
            "note": "、".join(x.get("id", "?") for x in issues),
            "at": ml["repair_started_at"]})
        st["current"] = target
        st.setdefault("step_heads", {})[target] = sh("git rev-parse --verify HEAD")
        st.pop("unlock", None)
        st.pop("risk_acceptances", None)
        st.pop("agent_tasks", None)
        st.pop("quality", None)
        save_state(st)
        _write_moonlight_report(flow, st)
        print(f"[mae-flow] 已根据报告开启第 {ml['cycle']} 轮修复，从 {target} 重新进入。"
              "先处理报告遗留，再完整重跑后续质量链并推送。")
        print_current(flow, st)
        return
    if action == "finalize":
        if st.get("current") != "moonlight_review":
            die("只有推送完成并停在 moonlight_review 时才能 finalize。", 2)
        issues = _moonlight_unresolved(st)
        if issues:
            if not args.ack:
                die("报告仍有遗留。建议先 moonlight repair；若用户决定带遗留结束，"
                    "必须 --ack 携带用户明确接受这些遗留的原话。", 2)
            ok, why = _ack_verified(st, args.ack, exact=True)
            if not ok:
                die("带遗留 finalize 授权验真失败:" + why, 2)
        ml = _moonlight_data(st)
        ml["enabled"] = False
        ml["finalized_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        workflow = (st.get("choices", {}) or {}).get("workflow", "")
        target = "end" if workflow == "review" or not st.get("config", {}).get("CHANGE_NAME") else "archive_confirm"
        st.setdefault("history", []).append({
            "step": "moonlight_review", "result": "moonlight:finalize",
            "note": ("带遗留确认" if issues else "晨间检查完成"),
            "at": ml["finalized_at"]})
        st["current"] = target
        st.setdefault("step_heads", {})[target] = sh("git rev-parse --verify HEAD")
        save_state(st)
        _write_moonlight_report(flow, st)
        print("[mae-flow] 月光宝盒晨间检查已结束。"
              + ("评审返工流程已完成。" if target == "end" else
                 "已恢复普通模式并进入规格定稿；定稿提交后还要再次 push。"))
        print_current(flow, st)
        return
    die("未知 moonlight 动作: " + action, 2)


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

    print(f"{'单号':<16} {'workflow':<8} {'耗时':>7} {'gate拦':>5} {'打回':>4} {'goto':>4} {'风险':>4}  完成时间")
    for r in recs:
        print(f"{r.get('单号', '?'):<16} {r.get('workflow', '?'):<8} {fmt(r.get('耗时秒', 0)):>7} "
              f"{str(r.get('gate拦截', '-')):>5} {str(r.get('契约打回', '-')):>4} "
              f"{str(r.get('goto次数', '-')):>4} {str(r.get('风险放行次数', '-')):>4}  {r.get('结束', '?')}")
    n = len(recs)
    print(f"合计 {n} 单 · 平均耗时 {fmt(sum(r.get('耗时秒', 0) for r in recs) / n)}"
          f" · goto 总计 {sum(r.get('goto次数', 0) for r in recs)} 次"
          f" · 风险放行总计 {sum(r.get('风险放行次数', 0) for r in recs)} 次")


def cmd_reloaded(flow, st, args):
    """用户在当前会话手动 /reload-skills(+/reload-plugins)后清除待重启标记的合法通道。
    外部脚本测不了 skill 是否真加载,所以靠用户确认(--ack 三级验真,伪造被拒)+ open 步兜底
    (真没 reload 成功,/comet-open 仍会失败并指回本处)。重启会话则由 SessionStart 自动清,不用本命令。"""
    if not os.path.exists(RELOAD_MARK):
        print("[mae-flow] 无待重启标记,无需操作,直接 current 继续。")
        return
    if not args.ack:
        die("reloaded 需携带用户确认原话:--ack \"用户原话\"。必须是用户**明确说过**已执行 /reload-skills"
            "(或已重启),你不能替用户声称刷新过——没 reload 就清标记,skill 仍没加载,open 步照样卡。", 2)
    ok, why = _ack_verified(st, args.ack)
    if not ok:
        die("reloaded 授权验真失败:" + why, 2)
    try:
        os.remove(RELOAD_MARK)
    except Exception as e:
        die("清除待重启标记失败: %s" % e)
    print("[mae-flow] 已确认 skill/plugin 重载,待重启标记已清除。执行 current 继续"
          "(若后续 /comet-open 等技能仍报不存在,说明 reload 未生效,请改用重启会话)。")


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
    st.pop("risk_acceptances", None)
    st["history"].append({"step": st["current"], "result": "goto:" + args.step,
                          "note": "manual", "at": time.strftime("%Y-%m-%d %H:%M:%S")})
    st["current"] = args.step
    st.setdefault("step_heads", {})[args.step] = sh("git rev-parse --verify HEAD")
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
    if step.get("tests_only"):
        target = step.get("source_change_recheck", "")
        print(f"[mae-flow] 已解锁本步({sid})的源码修改(仅本步有效,推进后自动失效)。"
              "修复后按 [单号][类型] 规范 commit，再执行 done。"
              + (f"harness 检测到被测源码变化后会自动回流到 {target}，"
                 "重跑编译、CodeCheck、UT；不允许就地直接推送。" if target else
                 "旧 UT 证据会因源码变化失效，必须重跑验证。"))
    else:
        print("[mae-flow] 本仓未启用测试路径收紧,无需实际解锁;裁决已留痕。"
              "直接修复源码 → 编译 → 按规范 commit → 重启 ut-generator-agent 重新收尾。")


def _print_exit_preview(flow, st):
    sid = st.get("current", "?")
    title = (flow.get("steps", {}).get(sid, {}) or {}).get("title", "未知步骤")
    branch = sh("git branch --show-current") or "(无法读取)"
    head = sh("git rev-parse --short HEAD") or "(无法读取)"
    dirty = _dirty_paths()
    print("[mae-flow] 准备退出流程（尚未执行）")
    print("  当前步骤: %s — %s" % (sid, title))
    print("  当前分支/HEAD: %s / %s" % (branch, head))
    print("  未提交文件: %s" % ("、".join(dirty) if dirty else "无"))
    print("  退出会保留全部代码、提交和文档，不回滚、不删除业务文件。")
    print("  退出后按普通开发处理，不再强制执行本流程的编译、CodeCheck、UT、归档和提交检查。")
    print("  若之后明确重新接回 mae-flow，会恢复原断点；源码变过则回退质量链，旧质量结果不会复用。")


def cmd_exit(flow, st, args):
    """保留现场并解除项目接管。高风险降级动作必须由本步之后的用户原话精确确认。"""
    _print_exit_preview(flow, st)
    if not args.ack:
        print("\n请用户明确回复，例如：确认退出 mae-flow，保留当前代码并改为直接开发")
        print("拿到回复后原文复制执行：")
        print('python "%s" exit --reason "<退出原因>" --ack "<用户确认原话>"'
              % os.path.abspath(sys.argv[0]))
        return
    if not args.reason:
        die("exit 必须 --reason 记录为什么退出，不能只写‘用户要求’。", 2)
    ok, why = _ack_verified(st, args.ack, exact=True)
    if not ok:
        die("exit 授权验真失败（退出会解除质量约束，因此要求整条原话精确匹配）:" + why, 2)

    found, patched, errors = ensure_direct_mode_compat(os.getcwd())
    if errors:
        die("底层阶段门禁兼容更新失败，尚未退出：" + "；".join(errors), 2)
    if _active_change_count() > 0 and not found:
        die("检测到仍有在建规格，但没找到项目级 Comet Hook，无法保证退出后源码不再被拦。"
            "请先执行 mae-flow setup 修复项目初始化，再重试 exit；本次尚未退出。", 2)

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    sid = st.get("current", "")
    st.pop("unlock", None)
    st.setdefault("history", []).append(
        {"step": sid, "result": "exited", "note": args.reason, "at": now})
    save_state(st)
    _append_history(st, outcome="用户主动退出")

    snapshot = _unique_exit_dir(st)
    copied = _snapshot_state_files(snapshot)
    record = {
        "version": 1,
        "status": "exited",
        "at": now,
        "reason": args.reason,
        "ack": args.ack,
        "step": sid,
        "title": (flow.get("steps", {}).get(sid, {}) or {}).get("title", ""),
        "ticket": (st.get("config", {}) or {}).get("单号", ""),
        "workflow": (st.get("choices", {}) or {}).get("workflow", ""),
        "head": sh("git rev-parse --verify HEAD"),
        "branch": sh("git branch --show-current"),
        "dirty_paths": _dirty_paths(),
        "snapshot": norm(snapshot),
        "comet_guard_paths": [norm(p) for p in found],
    }
    _write_json_atomic(os.path.join(snapshot, "exit-record.json"), record)
    _write_json_atomic(EXIT_PATH, record)
    cleanup_errors = []
    for src, _ in copied:
        try:
            os.remove(src)
        except OSError as exc:
            cleanup_errors.append("%s: %s" % (src, exc))

    print("\n[mae-flow] 已退出流程。代码、提交和文档均已保留；流程现场已保存到 " + norm(snapshot))
    if patched:
        print("已让项目阶段门禁识别直接开发模式：" + "、".join(norm(p) for p in patched))
    if cleanup_errors:
        print("⚠ 部分旧状态文件未清理，但退出标记已生效：" + "；".join(cleanup_errors), file=sys.stderr)
    print("现在可以直接让 AI 修改代码或补 UT。后续质量检查由用户自行决定。")


def print_direct_mode_status():
    try:
        rec = json.load(open(EXIT_PATH, encoding="utf-8"))
    except Exception:
        rec = {}
    print("[mae-flow] 当前项目已退出流程，正在按普通开发方式工作。")
    print("退出时间: %s  原步骤: %s  原因: %s" %
          (rec.get("at", "?"), rec.get("step", "?"), rec.get("reason", "?")))
    print("现场保留在: " + rec.get("snapshot", ".mae-flow-work/exited/"))
    print("只有用户明确要求重新接回原流程时才执行 init；init 会恢复原断点并重新取证。另一张新单请另开 worktree。")


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
              "其余子命令: status|doctor|report|envcheck|skip|goto|unlock|template|agent-task|"
              "accept-risk|moonlight|codecheck-scan|codecheck-record|approve-exemption|exit"
              "(用法见 current/exit 指令)。\n"
              "注意:子命令不带连字符(是 current 不是 --current);done 的 --set 可重复,值含空格要加引号。",
              file=sys.stderr)
        sys.exit(2)


def main():
    ap = MFParser(prog="mae-flow")
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init"); i.add_argument("--ack")
    sub.add_parser("current")
    d = sub.add_parser("done")
    d.add_argument("--ack"); d.add_argument("--choice"); d.add_argument("--set", action="append")
    s = sub.add_parser("skip"); s.add_argument("--reason")
    t = sub.add_parser("status"); t.add_argument("--inject", action="store_true")
    g = sub.add_parser("gate"); g.add_argument("what", choices=["edit", "bash"]); g.add_argument("arg")
    o = sub.add_parser("goto"); o.add_argument("step"); o.add_argument("--force", action="store_true"); o.add_argument("--ack")
    u = sub.add_parser("unlock"); u.add_argument("what", choices=["source"]); u.add_argument("--reason"); u.add_argument("--ack")
    ar = sub.add_parser("accept-risk")
    ar.add_argument("agent", help="当前步骤报错中显示的 Agent 名称，如 compile/codecheck/ut")
    ar.add_argument("--reason", required=True); ar.add_argument("--ack", required=True)
    ml = sub.add_parser("moonlight")
    ml.add_argument("action", choices=[
        "on", "continue", "off", "report", "push-failed",
        "unlock-source", "defer", "blocked", "repair", "finalize"])
    ml.add_argument("--reason"); ml.add_argument("--ack")
    x = sub.add_parser("exit"); x.add_argument("--reason"); x.add_argument("--ack")
    rl = sub.add_parser("reloaded"); rl.add_argument("--ack")
    sub.add_parser("doctor")
    sub.add_parser("envcheck")
    r = sub.add_parser("report")
    r.add_argument("--all", action="store_true")   # 聚合历史账本(无在途单也可用)
    tp = sub.add_parser("template")
    tp.add_argument("kind", nargs="?", default="story", choices=["story", "chain", "grill", "review"])
    at = sub.add_parser("agent-task")
    at.add_argument("kind", choices=["compile", "codecheck", "ut"])
    at.add_argument("--scope", help="批次/单告警范围说明；写入受指纹保护的任务卡")
    sub.add_parser("codecheck-scan")
    cr = sub.add_parser("codecheck-record")
    cr.add_argument("--count", required=True, type=int)
    cr.add_argument("--diagnostic", required=True)
    cr.add_argument("--reason", required=True)
    cr.add_argument("--ack", required=True)
    ae = sub.add_parser("approve-exemption")
    ae.add_argument("--rule", required=True); ae.add_argument("--file", required=True)
    ae.add_argument("--reason", required=True); ae.add_argument("--ack", required=True)
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
    if args.cmd == "moonlight" and args.action in ("on", "continue"):
        return cmd_moonlight(flow, st, args)
    if args.cmd == "gate":
        return cmd_gate(flow, st, args)
    if args.cmd == "report" and args.all:
        return cmd_report_all()   # 账本聚合是无状态命令,不要求存在在途单
    if os.path.exists(EXIT_PATH):
        if args.cmd in ("current", "status", "doctor", "exit"):
            return print_direct_mode_status()
        die("当前项目已退出 mae-flow，普通开发不需要执行流程命令。"
            "若用户明确要重新进入流程，请执行 init；旧质量证据不会复用。", 2)
    if st is None:
        die("流程未初始化,先执行 init。")
    if args.cmd == "exit":
        return cmd_exit(flow, st, args)
    if args.cmd == "moonlight":
        return cmd_moonlight(flow, st, args)
    if args.cmd == "current":
        return print_current(flow, st)
    if args.cmd == "agent-task":
        return cmd_agent_task(flow, st, args)
    if args.cmd == "codecheck-scan":
        return cmd_codecheck_scan(flow, st, args)
    if args.cmd == "codecheck-record":
        return cmd_codecheck_record(flow, st, args)
    if args.cmd == "approve-exemption":
        return cmd_approve_exemption(flow, st, args)
    if args.cmd == "accept-risk":
        return cmd_accept_risk(flow, st, args)
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
    if args.cmd == "reloaded":
        return cmd_reloaded(flow, st, args)
    if args.cmd == "doctor":
        return cmd_doctor(flow, st, args)
    if args.cmd == "report":
        return cmd_report(flow, st, args)


if __name__ == "__main__":
    main()
