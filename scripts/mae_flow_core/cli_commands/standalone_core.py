"""CLI responsibilities extracted from the historical entrypoint."""

import hashlib

from .shared import (
    AGENT_WRITES_PATH, CODE_EXTS, DEFAULTS_PATH, EXIT_INTENT_PATH,
    EXIT_PATH, FAILURE_PATH, GATE_PERMITS_PATH, GATE_STRIKES_PATH,
    MOONLIGHT_INTENT_PATH, STATE_PATH, StateStoreError, append_codecheck_event,
    atomic_write_json, atomic_write_text, codecheck_log_path, core_action_work_dir,
    core_archive_action, core_load_action, core_save_action, load_json, os,
    quality_task_card_documents, quality_task_card_use_cases, re, remove_with_retry,
    shutil, sys, time,
)
from .wiring import api

def _state_sidecars():
    return [STATE_PATH, STATE_PATH + ".tokens", STATE_PATH + ".usermsg",
            STATE_PATH + ".agent-rejections", STATE_PATH + ".agent-evidence",
            AGENT_WRITES_PATH,
            STATE_PATH + ".stop-guard", GATE_STRIKES_PATH, GATE_PERMITS_PATH,
            MOONLIGHT_INTENT_PATH, EXIT_INTENT_PATH, FAILURE_PATH, STATE_PATH + ".tmp"]

def _clear_auxiliary_state():
    """A new delivery round must not inherit tokens/messages from the old one."""
    failed = []
    for path in _state_sidecars():
        if path == STATE_PATH or not os.path.exists(path):
            continue
        try:
            remove_with_retry(path)
        except OSError as exc:
            failed.append("%s: %s" % (path, exc))
    if failed:
        api.die("开启新流程前无法清理旧辅助状态，继续会造成证据或消息串单："
            + "；".join(failed)
            + "。关闭占用这些文件的程序后重试；主状态和退出现场均未覆盖。", 2)

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
    atomic_write_json(path, data)

def _load_action():
    action, err, expired = core_load_action()
    if err:
        api.die("独立任务状态损坏：%s。它不会拦普通开发；可执行 action cancel 归档坏现场。" % err, 2)
    if action and expired:
        _archive_action(action, "expired", "独立任务超过 24 小时自动失效")
        return None
    return action

def _save_action(action):
    try:
        core_save_action(action)
    except StateStoreError as exc:
        api.die("独立任务状态存在并发更新或不可读，拒绝覆盖：" + str(exc)
            + "。重新执行 action status 后继续。", 2)

def _git_local_runtime_ignore():
    """独立任务不改团队 .gitignore，只把本机运行现场加入当前仓的本地排除。"""
    path = api.sh("git rev-parse --git-path info/exclude")
    if not path:
        return
    path = os.path.abspath(path)
    marker = "/.mae-flow-work/"
    try:
        old = ""
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as stream:
                old = stream.read()
        if marker in {line.strip() for line in old.splitlines()}:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            if old and not old.endswith("\n"):
                f.write("\n")
            f.write("# mae-flow local runtime\n" + marker + "\n")
    except OSError as exc:
        # 排除失败不应阻止用户工作，但必须说清楚，避免过程文件被误提交。
        print("[mae-flow] ⚠ 无法写 Git 本地排除文件：%s；请勿提交 .mae-flow-work/。" % exc,
              file=sys.stderr)

def _action_dir(action):
    return core_action_work_dir(action)

def _archive_action(action, outcome, note=""):
    """结束独立任务只移除控制指针，不删除代码和报告，也不触碰主流程现场。"""
    try:
        return core_archive_action(action, outcome, note)
    except StateStoreError as exc:
        api.die("独立任务在归档前发生并发更新或状态不可读：" + str(exc)
            + "。重新执行 action status 后继续。", 2)

def _standalone_config(terminal_state=None):
    """独立任务只继承项目运行方式，不继承单号、步骤、令牌或质量结论。"""
    merged = {}
    candidates = []
    if os.path.isfile(STATE_PATH + ".last"):
        candidates.append(STATE_PATH + ".last")
    if os.path.isfile(EXIT_PATH):
        try:
            rec = load_json(EXIT_PATH)
            saved = os.path.join(rec.get("snapshot", ""), STATE_PATH)
            if os.path.isfile(saved):
                candidates.append(saved)
        except Exception:
            pass
    for path in candidates:
        try:
            cfg = load_json(path).get("config", {}) or {}
            for key in ("编译方式", "UT生成方式", "UT运行命令", "测试路径"):
                if cfg.get(key):
                    merged[key] = cfg[key]
        except Exception:
            pass
    if terminal_state:
        cfg = terminal_state.get("config", {}) or {}
        for key in ("编译方式", "UT生成方式", "UT运行命令", "测试路径"):
            if cfg.get(key):
                merged[key] = cfg[key]
    try:
        defaults = load_json(DEFAULTS_PATH, encoding="utf-8-sig") if os.path.isfile(DEFAULTS_PATH) else {}
        for key in ("编译方式", "UT生成方式", "UT运行命令", "测试路径"):
            if defaults.get(key):
                merged[key] = defaults[key]
    except Exception:
        pass
    return merged

def _action_files(raw, st=None):
    values = []
    for item in raw or []:
        values.extend(x.strip() for x in item.split(",") if x.strip())
    if not values:
        values = [p for p in api._dirty_paths() if api._is_source_path(p, st or {}, api.FLOW or {})]
    out = []
    root = os.path.abspath(os.getcwd())
    for value in values:
        path = os.path.abspath(value)
        try:
            rel = api.norm(os.path.relpath(path, root))
        except ValueError:
            api.die("独立任务文件必须位于当前项目内：" + value, 2)
        if rel == ".." or rel.startswith("../"):
            api.die("独立任务文件必须位于当前项目内：" + value, 2)
        if not os.path.exists(path):
            api.die("独立任务文件不存在：" + value, 2)
        if rel not in out:
            out.append(rel)
    return out

def _action_target_files(values, kind, config, flow):
    """Turn explicit/inferred paths into the frozen scope shown to the user."""
    source_files = [p for p in values if api._is_source_path(p, {}, flow)]
    if kind == "codecheck":
        return [p for p in source_files
                if p.lower().endswith(CODE_EXTS)
                and not api._is_test_file(p, {"config": config})]
    if kind == "ut":
        business = [p for p in source_files
                    if not api._is_build_path(p)
                    and not api._is_test_file(p, {"config": config})]
        if not business:
            api.die("独立 UT 范围至少要包含一个被测业务文件；"
                "空范围、只有测试文件或只有构建文件都不能启动。"
                "请先定位被测源码，再用 --files 明确传入。", 2)
        return source_files
    return values

def _scope_confirmation_answer(value):
    """Accept an affirmative scope decision, never questions or rework intent."""
    compact = re.sub(r"[\s，。；;：:、!！]+", "", value or "")
    if not compact or re.search(
            r"不确认|还没确认|不同意|不是|不要|不能|拒绝|暂不|取消|"
            r"需要修改|需要调整|先别|等等|不对|有误|有问题|"
            r"什么意思|怎么|是否|能否|为什么|[?？]",
            compact, re.I):
        return False
    if api._is_positive_confirmation(value):
        return True
    return bool(re.match(
        r"^(?:以上)?范围(?:没问题|无问题|无异议|正确|可以|确认)",
        compact, re.I))


def _action_scope_receipt(action):
    """Resolve a fresh user answer bound to the displayed standalone scope."""
    proposed = float(action.get("scope_proposed_epoch", 0) or 0)
    scope_sha = str(action.get("scope_sha256", "") or "")
    if not scope_sha:
        return False, {}, "独立任务缺少范围指纹；取消后重新展示范围。"
    for message in reversed(action.get("user_messages", []) or []):
        if float(message.get("epoch", 0) or 0) + 0.001 < proposed:
            continue
        if str(message.get("scope_sha256", "") or "") != scope_sha:
            continue
        candidates = api._trusted_answer_values(
            str(message.get("text", "")))
        for candidate in reversed(candidates):
            if _scope_confirmation_answer(candidate):
                return True, {
                    "message_id": str(message.get("id", "") or ""),
                    "answer_sha256": hashlib.sha256(
                        candidate.encode("utf-8")).hexdigest(),
                    "scope_sha256": scope_sha,
                    "captured_at": str(message.get("at", "") or ""),
                }, ""
    return False, {}, (
        "没有捕获到范围展示后的用户确认。请使用 AskUserQuestion 让用户选择「确认以上范围」；"
        "工具应答未被宿主回传时，让用户直接说明当前范围是否可执行；"
        "不要由 Agent 拼接固定确认口令。")

def _print_action_scope(action, inferred):
    print("[mae-flow] 独立 %s 待确认执行范围（尚未运行工具、尚未派子 Agent）：" %
          action.get("kind", "").upper())
    print("范围来源：" + ("当前工作区改动自动推导" if inferred else "用户点名/Agent 定位后传入"))
    for index, path in enumerate(action.get("files", []), 1):
        suffix = "（测试文件）" if api._is_test_file(
            path, {"config": action.get("config", {})}) else "（被测/业务文件）"
        print("  %d. %s%s" % (index, path, suffix))
    print("现在必须用 AskUserQuestion 让用户二选一：")
    print("  - 确认以上范围")
    print("  - 需要调整范围")
    print("用户确认后执行：")
    print('python "%s" action confirm-scope' %
          os.path.abspath(sys.argv[0]))
    print("若用户要求调整，执行 action cancel 后按新范围重新 action start；禁止自行扩大文件清单。")

def _action_request(action, request="", source=""):
    work = _action_dir(action)
    os.makedirs(work, exist_ok=True)
    sources = []
    if source:
        src = os.path.abspath(source)
        text, _, err = api._read_text_source(src, normalize=True)
        if err:
            api.die("独立任务输入材料不可读：" + err, 2)
        sources.append(src)
        request = (request.strip() + "\n\n" if request.strip() else "") + text
    if request.strip():
        path = os.path.join(work, "request.md")
        atomic_write_text(path, "# 独立任务输入\n\n" + request.strip() + "\n")
        sources.insert(0, path)
    return sources

def _action_task_card(action, kind, stage=""):
    """为独立任务生成与主流程同等级的受指纹保护任务卡。"""
    label = kind.upper()
    config = action.get("config", {}) or {}
    head = api.sh("git rev-parse --verify HEAD")
    sid = "standalone_" + action["kind"]
    files = action.get("files", [])
    groups = api._classify_task_files_from_runtime(
        files, {"config": config})
    scan = action.get("quality", {}).get("codecheck_scan", {})
    execution_files = (
        groups["business"]
        or groups["tests"]
        or groups["build"]
    )
    roots, unresolved = api._resolve_task_roots_from_runtime(
        execution_files)
    execution_plan = quality_task_card_use_cases.ExecutionRootPlan(
        roots=tuple(roots),
        unresolved=tuple(unresolved),
    )
    standalone_targets = (
        api._hunk_targets_for_diff(
            action.get("base_head", "HEAD"),
            groups["business"],
        )
        if label == "UT" else {}
    )
    lines = quality_task_card_documents.build_standalone_task_document({
        "label": label,
        "action_id": action["id"],
        "kind": action["kind"],
        "stage": stage,
        "project_root": os.path.abspath(os.getcwd()),
        "head": head,
        "request": action.get("request", ""),
        "files": tuple(files),
        "config": config,
        "sources": tuple(
            os.path.abspath(path)
            for path in action.get("sources", [])
        ),
        "groups": quality_task_card_use_cases.TaskFileGroups(
            business=tuple(groups["business"]),
            tests=tuple(groups["tests"]),
            build=tuple(groups["build"]),
        ),
        "execution_plan": execution_plan,
        "scan": scan,
        "ut_targets": standalone_targets,
    })
    work = _action_dir(action)
    suffix = ("-" + stage) if stage else ""
    artifact = quality_task_card_use_cases.store_task_card(
        lines,
        work,
        f"{label.lower()}{suffix}-task.md",
        quality_task_card_use_cases.TaskCardStorePorts(
            absolute=os.path.abspath,
            make_directory=lambda path: os.makedirs(
                path, exist_ok=True),
            write_text=atomic_write_text,
        ),
    )
    path = artifact.path
    digest = artifact.digest
    initial = {
        p: api._path_fingerprint(p)
        for p in api._dirty_paths()
        if api._is_source_path(p, {}, api.FLOW or {})
    }
    action.setdefault("agent_tasks", {})[label] = (
        quality_task_card_use_cases.standalone_task_record(
            step=sid,
            path=path,
            digest=digest,
            head=head,
            scope=action.get("request", ""),
            allowed_files=(
                scan.get("files", [])
                if label == "CODECHECK" else []),
            task_files=files,
            execution_roots=[
                root for root, _reason
                in api._resolve_task_roots_from_runtime(
                    groups["business"]
                    or groups["tests"]
                    or groups["build"])[0]
            ],
            initial_source_fingerprints=initial,
            stage=stage,
            at=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
    )
    action.setdefault("tokens", {}).pop(label, None)
    action.setdefault("rejections", {}).pop(label, None)
    if label == "CODECHECK":
        append_codecheck_event(
            os.getcwd(), action, "agent.task_created", {
                "standalone": True,
                "task_path": os.path.abspath(path),
                "task_sha256": digest,
                "head": head,
                "allowed_files": scan.get("files", []),
                "scan_count": scan.get("count"),
            })
    _save_action(action)
    agent = {"UT": "ut-generator-agent", "CODECHECK": "codecheck-fix-agent",
             "GRILL": "grill-critic-agent"}[label]
    print(f"[mae-flow] 独立 {label} 任务卡已生成: {path}")
    if label == "CODECHECK":
        print("[mae-flow] CodeCheck 详细日志: %s"
              % api.norm(codecheck_log_path(os.getcwd(), action)))
    print("启动 %s 时只传这一句:\n读取并严格执行任务卡 \"%s\"；"
          "最终报告必须原样带 TASK_CARD_SHA256: %s" % (agent, path, digest))
    return path
