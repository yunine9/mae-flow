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
  mae-flow.py done [--set k=v ...] [--choice 值]
                                         普通按钮选择自动验真；--ack 仅用于高风险裁决
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
  mae-flow.py messages                    查看当前步骤捕获的用户消息 ID/编码
  mae-flow.py config-review --set k=v ... 校验并展示完整配置，生成待确认收据
  mae-flow.py checkpoint plan|ready|status|final|decide
                                         开发节奏、小步 push 与代码检视收据
  mae-flow.py requirement-record ...      将用户原话/已有文本规范化为 UTF-8 需求入口
  mae-flow.py action start|confirm-scope|status|critic|finish|cancel
                                         独立运行 UT/CodeCheck/Grill，不启动完整流程
  mae-flow.py exit [--reason 文本] [--ack 用户原话]
                                         保留现场并退出流程,之后按普通开发处理
退出码:0 成功;1 参数/状态错误;2 gate 拦截或证据不足。
"""
import glob as globmod, hashlib, json, os, re, shlex, shutil, subprocess, sys, tempfile, time
from io import BytesIO

from comet_compat import BEGIN as COMET_COMPAT_BEGIN, comet_guard_paths, ensure_direct_mode_compat
from mae_flow_core import (
    CapabilityError,
    RuntimeMode,
    StateStoreError,
    action_work_dir as core_action_work_dir,
    archive_action as core_archive_action,
    archive_corrupt_action as core_archive_corrupt_action,
    atomic_write_json,
    atomic_write_text,
    find_project_root as core_find_project_root,
    load_action as core_load_action,
    normalize_document,
    remove_with_retry,
    resolve_runtime,
    safe_read_json,
    save_action as core_save_action,
    save_versioned_json,
    update_json,
    append_codecheck_event,
    capability_diagnostics,
    codecheck_log_path,
    ensure_codecheck,
    prepare_project,
    render_pack,
    run_comet,
    run_openspec,
    save_codecheck_artifact,
)
from mae_flow_core.moonlight import (
    QUALITY_STEPS as MOONLIGHT_QUALITY_STEPS,
    REPAIR_ENTRY as MOONLIGHT_REPAIR_ENTRY,
    can_hard_block as moonlight_can_hard_block,
    data as moonlight_data,
    enabled as moonlight_enabled,
    resolve_kind as moonlight_resolve_kind,
    step_kind as moonlight_step_kind,
    unresolved as moonlight_unresolved,
)
from mae_flow_core.cli_parser import parse_args
from mae_flow_core import command_dispatch
from mae_flow_core.lightcheck import (
    analyze_changed_with_timeout,
    render_markdown,
)
from mae_flow_core.foundation.fingerprints import (
    path_fingerprint as _shared_path_fingerprint,
    review_path_fingerprint as _shared_review_path_fingerprint,
)
from mae_flow_core.foundation import source_paths
from mae_flow_core.foundation import git_intent
from mae_flow_core.delivery import checkpoints as delivery_checkpoints
from mae_flow_core.delivery import moonlight as delivery_moonlight
from mae_flow_core.guard import intent as guard_intent
from mae_flow_core.quality import task_cards as quality_task_cards
from mae_flow_core.workflow import advancement as workflow_advancement
from mae_flow_core.workflow import completion as workflow_completion
from mae_flow_core.workflow import definition as workflow_definition
from mae_flow_core.workflow import transitions as workflow_transitions

# Windows cmd 默认 GBK,强制 UTF-8 避免 ✅/中文 输出炸编码
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def norm(p):
    """路径/命令归一化:Windows 反斜杠 → 正斜杠,供正则匹配。"""
    return source_paths.normalize_path(p)


def _repo_path_identity(path, case_insensitive=None):
    """Normalize a repository path for identity comparisons.

    Git normally reports the index spelling while file tools may preserve the
    caller's spelling. On Windows those names address the same file, so exact
    string comparison would lose Agent-write provenance.
    """
    value = re.sub(r"^(?:\./)+", "", norm(path).strip().strip("\"'"))
    if case_insensitive is None:
        case_insensitive = os.name == "nt"
    return value.casefold() if case_insensitive else value


HERE = os.path.dirname(os.path.abspath(__file__))
FLOW_PATH = os.path.join(HERE, "..", "flow", "flow.json")
STEPS_DIR = os.path.join(HERE, "..", "flow", "steps")
STATE_PATH = ".mae-flow.json"   # 相对项目根;启动时 find_project_root() 自动 chdir,不赌调用方 cwd
EXIT_PATH = ".mae-flow.json.exited"
AGENT_WRITES_PATH = STATE_PATH + ".agent-writes"


def _clear_broken_exit_marker():
    """写退出标记前收殓坏旧标记(实测死角:坏标记的 CAS 校验曾让三条退出
    路径全部 crash——退出标记的唯一写方就是"正在退出",旧标记本该被覆盖,
    坏了更该被收殓而不是挡路)。"""
    from mae_flow_core.state_store import safe_read_json as _srj
    if not os.path.exists(EXIT_PATH):
        return
    _raw, err = _srj(EXIT_PATH)
    if not err:
        return
    try:
        os.replace(EXIT_PATH,
                   EXIT_PATH + ".corrupt." + time.strftime("%Y%m%d-%H%M%S"))
    except OSError:
        try:
            os.remove(EXIT_PATH)
        except OSError:
            pass  # 复用既有 .mae-flow.json* ignore;存在时 Hook 不再接管普通开发
MOONLIGHT_INTENT_PATH = STATE_PATH + ".moonlight-intent"
EXIT_INTENT_PATH = STATE_PATH + ".exit-intent"
FAILURE_PATH = STATE_PATH + ".failures"
ACTION_PATH = os.path.join(".mae-flow-work", "standalone-action.json")
ACTION_SCOPE_ACK = "确认以上范围"
CONFIG_CONFIRM_ACK = "确认以上全部配置"
CHECKPOINT_CONTINUE_ACK = "我已认真检视并完成自验证，继续"
CHECKPOINT_REVISE_ACK = "需要调整代码"
CHECKPOINT_CONTINUOUS_ACK = "当前批次先不确认，剩余代码一次完成后统一检视"
HISTORY_PATH = ".mae-flow-history.jsonl"   # 交付历史账本:终态 init 时追加本单摘要(gitignored,gate 防篡改)
DEFAULTS_PATH = ".mae-flow-defaults.json"  # 仓库预设(团队提交进仓):require_sets 步骤 current 时预填展示
FLOW = None                      # main() 加载后填充,供证据函数读取 env_checks 等
MOONLIGHT_REPORT_PATH = os.path.join(".mae-flow-work", "moonlight-report.md")
PACE_STEPS = workflow_advancement.PACE_STEPS
CHECKPOINT_CODE_STEPS = delivery_checkpoints.CODE_STEPS

# source_patterns 只适合识别目录，不能承担跨仓源码真相（顶层 include/lib/app 已真实漏过）。
# 扩展名与构建入口作为保守底座；仓库可用 defaults/config 的「源码路径」补私有布局。
SOURCE_EXTS = source_paths.SOURCE_EXTENSIONS
SOURCE_FILENAMES = source_paths.SOURCE_FILENAMES
BUILD_DESCRIPTOR_EXTS = source_paths.BUILD_DESCRIPTOR_EXTENSIONS
BUILD_SCRIPT_EXTS = source_paths.BUILD_SCRIPT_EXTENSIONS

# 只把“几乎不可能是源码/交付物”的中间文件做提交硬拦。build/dist/out/target
# 与 jar/dll/so 等可能是项目约定的发布件，只提示不阻断，避免为了防误提交反而漏交付。
BUILD_ARTIFACT_STRONG_SUFFIXES = (
    ".o", ".obj", ".pyc", ".pyo", ".class", ".gcda", ".gcno",
    ".profraw", ".profdata", ".ilk", ".tlog", ".lastbuildstate",
    ".ninja_deps", ".ninja_log",
)
BUILD_ARTIFACT_STRONG_NAMES = {
    "cmakecache.txt", "cmake_install.cmake",
}
BUILD_ARTIFACT_STRONG_DIRS = {
    "cmakefiles", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".gradle", "node_modules", "coverage", "htmlcov",
}
BUILD_ARTIFACT_AMBIGUOUS_SUFFIXES = (
    ".a", ".lib", ".so", ".dll", ".dylib", ".exe", ".pdb",
    ".jar", ".war", ".ear",
)
BUILD_ARTIFACT_AMBIGUOUS_DIRS = {
    "build", "dist", "out", "target", "bin", "obj", "debug", "release",
    ".next", ".nuxt", ".svelte-kit", ".vite", ".turbo", ".parcel-cache",
}


def _build_artifact_confidence(path):
    """Return strong/ambiguous/empty for a repository-relative path.

    This deliberately classifies paths, not build commands. Only newly staged
    files are checked by the caller, so already tracked generated assets keep
    following the repository's existing contract.
    """
    p = re.sub(r"^(?:\./)+", "", norm(path).strip().strip("\"'"))
    if not p:
        return ""
    low = p.lower()
    parts = [item for item in low.split("/") if item]
    base = parts[-1] if parts else low
    if (base in BUILD_ARTIFACT_STRONG_NAMES
            or low.endswith(BUILD_ARTIFACT_STRONG_SUFFIXES)
            or any(item in BUILD_ARTIFACT_STRONG_DIRS for item in parts)
            or any(item.startswith("cmake-build-") for item in parts)
            or any(item.endswith(".dsym") for item in parts)):
        return "strong"
    if (low.endswith(BUILD_ARTIFACT_AMBIGUOUS_SUFFIXES)
            or any(item in BUILD_ARTIFACT_AMBIGUOUS_DIRS for item in parts)):
        return "ambiguous"
    return ""


def _git_status_paths(pathspecs, include_ignored=False):
    """List changed/untracked paths under explicit git-add pathspecs."""
    if not pathspecs:
        return []
    args = [
        "git", "-c", "core.quotepath=false", "status", "--porcelain",
        "--untracked-files=all",
    ]
    if include_ignored:
        args.append("--ignored=matching")
    out = argv_out([*args, "--", *pathspecs])
    paths = []
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        status, path = parts
        if status == "!!" and not include_ignored:
            continue
        paths.append(norm(path.split(" -> ")[-1].strip().strip('"')))
    return list(dict.fromkeys(paths))


def _git_add_pathspecs(command):
    """Extract explicit pathspecs from git-add segments in a compound command."""
    paths, force = [], False
    for intent in _git_add_intents(command):
        paths.extend(intent["pathspecs"])
        force = force or intent["force"]
    return list(dict.fromkeys(paths)), force


def _git_subcommand_tokens(command, subcommand):
    return git_intent.git_subcommand_tokens(command, subcommand)


_COMMIT_VALUE_OPTIONS = git_intent.COMMIT_VALUE_OPTIONS


def _option_consumes_following(token, value_options):
    return git_intent.option_consumes_following(token, value_options)


_PathspecCollector = git_intent.PathspecCollector


def _command_pathspecs(tokens, value_options=None):
    return git_intent.command_pathspecs(tokens, value_options)


def _git_add_intent(tokens):
    return git_intent.git_add_intent(tokens)


def _git_add_intents(command):
    return git_intent.git_add_intents(command)


def _short_option_flags(tokens):
    return git_intent.short_option_flags(tokens)


def _git_commit_intent(command):
    return git_intent.git_commit_intent(command)


def _agent_written_paths():
    """Return paths successfully changed through Agent file-writing tools.

    This is deliberately a candidate set, not a commit allowlist: a file being
    touched by the Agent does not mean it belongs in the commit.
    """
    raw, err = safe_read_json(AGENT_WRITES_PATH)
    if err or not isinstance(raw, dict):
        return set()
    entries = raw.get("paths", raw)
    if not isinstance(entries, dict):
        return set()
    return {
        _repo_path_identity(path) for path in entries
        if isinstance(path, str) and _repo_path_identity(path)
    }


def _is_story_document(path):
    """Recognize STORY content even when an agent writes it to the wrong tree."""
    p = re.sub(r"^(?:\./)+", "", norm(path))
    if not p.lower().endswith(".md"):
        return False
    if "story" in os.path.basename(p).lower():
        return True
    try:
        with open(p, encoding="utf-8", errors="replace") as stream:
            sample = stream.read(65536)
    except OSError:
        # A staged file may have been moved/deleted from the worktree while its
        # old blob is still queued for commit. Inspect the index too, otherwise
        # `notes.md` containing a STORY could evade the content check.
        sample = argv_out(["git", "show", ":" + p])[:65536]
        if not sample:
            return False
    return bool(re.search(r"(?mi)^#\s*STORY[-：:]|Story转测自检表", sample))


def _trusted_harness_commit_path(path, st=None):
    """Paths the current delivery may create without an Edit/Write event.

    OpenSpec is deliberately scoped to the active change/archive. Treating the
    whole tree as trusted lets an old untracked file ride a later
    ``git add openspec/`` without even a provenance warning.
    """
    p = re.sub(r"^(?:\./)+", "", norm(path))
    if p in {".gitignore", ".gitattributes"}:
        return True
    if (p.startswith("docs/req/") or p.startswith("docs/review/")
            or p.startswith("docs/clarifications-")
            or p.startswith("docs/codecheck-exempt-")):
        return True
    if not p.startswith("openspec/") or _is_story_document(p):
        return False
    if p in {"openspec/config.yaml", "openspec/config.yml"}:
        return True
    state = st or {}
    config = state.get("config", {}) or {}
    change_name = str(config.get("CHANGE_NAME", "") or "")
    active = "openspec/changes/" + change_name if change_name else ""
    if active and (p == active or p.startswith(active + "/")):
        return True
    spec_data = state.get("spec", {}) or {}
    archive_name = str(spec_data.get("archived_to", "") or "")
    archived = ("openspec/changes/archive/" + archive_name
                if archive_name else "")
    if archived and (p == archived or p.startswith(archived + "/")):
        return True
    archive_paths = {
        re.sub(r"^(?:\./)+", "", norm(item))
        for item in spec_data.get("archive_paths", []) or []
    }
    if any(p == item or p.startswith(item.rstrip("/") + "/")
           for item in archive_paths if item):
        return True
    # Old in-flight states predate archive_paths. During their archive/push
    # handoff, specs are legitimate harness output; unchanged initial dirt is
    # still rejected independently by the carry-over check below.
    if (p.startswith("openspec/specs/")
            and (state.get("current") == "archive"
                 or (spec_data.get("phase") == "archived"
                     and state.get("current") == "push"))):
        return True
    return False


def _staged_commit_candidates():
    staged_all = argv_out([
        "git", "-c", "core.quotepath=false", "diff", "--cached",
        "--name-only", "--no-renames", "--",
    ]).splitlines()
    staged_new = argv_out([
        "git", "-c", "core.quotepath=false", "diff", "--cached",
        "--name-only", "--diff-filter=A", "--no-renames", "--",
    ]).splitlines()
    return (
        [norm(path) for path in staged_all if path],
        [norm(path) for path in staged_new if path],
    )


def _git_diff_name_args(diff, pathspecs, cached):
    args = [
        "git", "-c", "core.quotepath=false", "diff",
        "--name-only", "--no-renames",
    ]
    if cached:
        args.append("--cached")
    if diff:
        args.append(diff)
    args += ["--", *(pathspecs or [])]
    return args


def _git_diff_names(diff="HEAD", pathspecs=None, cached=False):
    args = _git_diff_name_args(diff, pathspecs, cached)
    return [
        norm(path) for path in argv_out(args).splitlines()
        if path
    ]


def _intent_candidate_paths(intent):
    pathspecs = intent["pathspecs"]
    if not pathspecs:
        return []
    if intent["tracked_only"]:
        return _git_diff_names("HEAD", pathspecs)
    return _git_status_paths(
        pathspecs, include_ignored=intent["force"])


def _untracked_candidate_paths(paths):
    return [
        path for path in paths
        if not argv_out([
            "git", "ls-files", "--error-unmatch", "--", path])
    ]


def _compound_add_candidates(command):
    pending, new_candidates = [], []
    for intent in _git_add_intents(command):
        current = _intent_candidate_paths(intent)
        pending.extend(current)
        new_candidates.extend(_untracked_candidate_paths(current))
    return list(dict.fromkeys(pending)), list(dict.fromkeys(new_candidates))


def _commit_worktree_candidates(command):
    intent = _git_commit_intent(command)
    pathspecs = intent["pathspecs"]
    if intent["all"]:
        return _git_diff_names("HEAD"), False
    if pathspecs:
        return _git_diff_names("HEAD", pathspecs), not intent["include"]
    return [], False


def _pending_commit_candidates(command=""):
    """Return exact staged/compound-add candidates before a commit runs."""
    candidates, new_candidates = _staged_commit_candidates()
    pending, pending_new = _compound_add_candidates(command)
    commit_working, commit_only = _commit_worktree_candidates(command)
    if commit_only:
        candidates = list(commit_working)
        new_candidates = [
            path for path in new_candidates if path in candidates
        ]
    else:
        candidates.extend(pending)
        candidates.extend(commit_working)
        new_candidates.extend(pending_new)
    candidates = list(dict.fromkeys(candidates))
    return {
        "paths": candidates,
        "new_paths": set(new_candidates),
        "working_paths": set(pending) | set(commit_working),
    }


def _pending_commit_files(command="", st=None, candidate_snapshot=None):
    """Inspect files that a commit is about to include.

    Staged paths are authoritative. For `git add ... && git commit ...` in one
    Bash call, explicit pathspecs are also inspected before either command has
    run. A missing Write/Edit provenance is warning-only unless the path is also
    a newly added, high-confidence temporary build artifact.
    """
    if candidate_snapshot is None:
        candidate_snapshot = _pending_commit_candidates(command)
    candidates = candidate_snapshot["paths"]
    new_candidates = candidate_snapshot["new_paths"]
    written = _agent_written_paths()

    def has_provenance(path):
        return (_repo_path_identity(path) in written
                or _trusted_harness_commit_path(path, st))

    inherited = [
        path for path in candidates
        if _unchanged_initial_dirty(path, st or {})
        and _repo_path_identity(path) not in written
    ]
    foreign_openspec = [
        path for path in candidates
        if path.startswith("openspec/")
        and not _trusted_harness_commit_path(path, st)
    ]
    unproven = [path for path in candidates if not has_provenance(path)]
    strong_unproven = [
        path for path in unproven
        if path in new_candidates and _build_artifact_confidence(path) == "strong"
    ]
    artifact_hints = [
        path for path in candidates
        if path not in strong_unproven and _build_artifact_confidence(path)
    ]
    return inherited, foreign_openspec, strong_unproven, unproven, artifact_hints


def find_project_root(start=None):
    """从 start(默认 cwd)向上定位项目根,消除"模型 cd 进子目录后调用"的错位:
    每层先找已有 .mae-flow.json 或退出标记，再判断 .git / openspec 项目边界；
    不越过最近仓库去捡父目录的陈旧状态。都没有就留在原地。
    返回 (root, 是否已有状态文件)。"""
    root = core_find_project_root(start)
    return root, os.path.exists(os.path.join(root, STATE_PATH))


def load_flow():
    return workflow_definition.load_definition(FLOW_PATH)


def load_state():
    if not os.path.exists(STATE_PATH):
        return None
    raw, err = safe_read_json(STATE_PATH)
    if err:
        raise ValueError(err)
    st = normalize_document(raw, "flow")
    # Older releases could stop in the project setup phase. Setup is no longer
    # part of the workflow; migrate in place so an upgrade resumes normally.
    if st.get("current") == "env_setup":
        st["current"] = "config_confirm"
        st.setdefault("migrations", []).append({
            "type": "remove-project-setup", "from": "env_setup",
            "to": "config_confirm", "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        save_state(st)
    return st


def save_state(st):
    # 共享 StateStore 同时提供原子写、revision/CAS 和跨 Hook 进程锁。
    try:
        save_versioned_json(STATE_PATH, st, "flow")
    except StateStoreError as exc:
        die("流程状态存在并发更新或不可读，已拒绝覆盖：" + str(exc)
            + "。重新执行 current 获取最新状态；若仍失败可直接 `/mae-flow:mae-flow exit` 保存现场并退出。", 2)


def _drop_agent_token(kind):
    """清理单个令牌时保留其他并发 Hook 刚签发的事实。"""
    path = STATE_PATH + ".tokens"

    def remove_one(tokens):
        if not isinstance(tokens, dict):
            tokens = {}
        tokens.pop(kind, None)
        return tokens

    try:
        update_json(path, remove_one, default={}, recover_corrupt=True)
    except Exception:
        # token 清理是防旧证据复用；文件损坏时删除当前内存任务卡仍会让 done
        # 拒绝推进，不能反过来让恢复命令因附属文件故障卡死。
        pass


def _moonlight(st):
    return moonlight_enabled(st)


def _moonlight_data(st):
    return moonlight_data(st)


def _moonlight_unresolved(st):
    return moonlight_unresolved(st)


def _moonlight_resolve_kind(st, kind):
    """某一质量关真实通过后，关闭之前同类遗留；新一轮 defer 会另建记录。"""
    moonlight_resolve_kind(st, kind, sh("git rev-parse --verify HEAD"))


def _moonlight_step_kind(sid):
    return moonlight_step_kind(sid)


def _moonlight_can_block(sid):
    """硬阻塞出口用于非质量工作；质量关有 defer，push 有 push-failed。build 例外：
    它既是实现步骤，也可能遇到需求/依赖阻塞。"""
    return moonlight_can_hard_block(sid)


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


def argv_out(args, timeout=15):
    """无需 shell 的命令输出；文件名、ref 等外部值只能走参数数组，跨平台防注入。"""
    try:
        return subprocess.run(
            list(args), shell=False, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        ).stdout.strip()
    except Exception:
        return ""


def _dirty_paths():
    """返回当前工作区脏路径。状态文件与过程目录由流程自己维护，不算交付改动。"""
    out = []
    for line in sh("git -c core.quotepath=false status --porcelain --untracked-files=all").splitlines():
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
    return _shared_path_fingerprint(path)


_path_fingerprint.__wrapped__ = _shared_path_fingerprint


def _review_path_fingerprint(path):
    """Hash the Git-relevant worktree state without changing legacy dirt IDs."""
    return _shared_review_path_fingerprint(path)


_review_path_fingerprint.__wrapped__ = _shared_review_path_fingerprint


def _step_entered_at(st):
    """当前步骤的进入时间；旧状态没有精确记录时沿用 started。

    除正常推进(next 解析)与 goto 外,回流转移(source-recheck:)与恢复转移
    (resumed:)同样是"进入本步"——漏认会取到过早时间,令旧轮令牌复活。"""
    sid = st.get("current", "")
    for h in reversed(st.get("history", [])):
        result = str(h.get("result", ""))
        if (_resolved_next(FLOW or {}, st, h.get("step", "")) == sid
                or result == "goto:" + sid
                or result == "source-recheck:" + sid
                or result == "resumed:" + sid):
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
    if "\x00" in value or "\ufffd" in value:
        return "包含 NUL/Unicode 替换字符，疑似发生编码损坏"
    if key == "单号" and not re.fullmatch(r"(?:REQ|DTS)\w+", value):
        return "单号必须以 REQ 或 DTS 开头"
    if key in ("工号", "基线分支", "分支名") and re.search(r"[\\\s~^:?*\[\];&|`$<>()\"']", value):
        return "包含 git/shell 不安全字符"
    if key in ("基线分支", "分支名"):
        try:
            checked = subprocess.run(
                ["git", "check-ref-format", "--branch", value],
                shell=False, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=10,
            )
        except Exception as exc:
            return "无法调用 git check-ref-format 校验分支名: " + str(exc)
        if checked.returncode != 0 or checked.stdout.strip() != value:
            return "不是合法且无隐式展开的 Git 分支名"
    if key == "CHANGE_NAME" and not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        return "change 名只允许字母、数字、下划线和短横线"
    return ""


REQ_SHA_MARKER = "MAE-FLOW-USERMSG-SHA256:"
_BINARY_PREFIXES = (b"%PDF-", b"PK\x03\x04", b"\x89PNG", b"\xff\xd8\xff", b"GIF8")


def _text_corruption_reason(text):
    """只拦高置信度损坏，不把普通中文内容误判成乱码。"""
    if "\x00" in text:
        return "包含 NUL 字符，疑似二进制或错误的 UTF-16 解码"
    if "\ufffd" in text:
        return "包含 Unicode 替换字符 �"
    controls = sum(1 for ch in text if ord(ch) < 32 and ch not in "\r\n\t")
    if controls:
        return "包含不可见控制字符"
    # UTF-8 被 GBK/Latin-1 错解后最常见的高信号组合；至少命中三次才拒绝，避免误伤正常用词。
    mojibake = re.findall(r"(?:锟斤拷|ï¿½|Ã.|Â.|(?:銆|锛|鈥|涔|鐨|鏃|鎴|璇|鍙|缂))", text)
    if len(mojibake) >= 3:
        return "命中多处常见乱码片段(" + "、".join(mojibake[:5]) + ")"
    return ""


def _read_text_source(path, normalize=False):
    """严格读取需求文本；normalize=True 时兼容常见 Windows 文本编码并返回编码名。"""
    try:
        raw = open(path, "rb").read()
    except OSError as exc:
        return "", "", "无法读取: %s" % exc
    if not raw:
        return "", "", "文件为空"
    if raw.startswith(_BINARY_PREFIXES):
        return "", "", "检测到 PDF/Office/图片等二进制格式，必须先提供文本版或粘贴关键内容"
    candidates = [("utf-8-sig", "utf-8-sig")]
    if normalize:
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            candidates.append(("utf-16", "utf-16"))
        candidates.append(("gb18030", "gb18030"))
    errors = []
    for label, enc in candidates:
        try:
            text = raw.decode(enc, errors="strict")
        except (UnicodeDecodeError, LookupError) as exc:
            errors.append("%s:%s" % (label, exc))
            continue
        bad = _text_corruption_reason(text)
        if bad:
            return "", label, bad
        if not text.strip():
            return "", label, "文件没有有效文本"
        return text, label, ""
    return "", "", ("不是可严格解码的 UTF-8 文本"
                    + ("；可用 requirement-record --source 规范化 GBK/UTF-16 文本" if not normalize else "")
                    + "（%s）" % " | ".join(errors[-2:]))


def _validate_requirement_document(path):
    """配置确认的需求入口必须是可复读的 UTF-8 文本；禁止 errors=replace 掩盖乱码。"""
    text, enc, err = _read_text_source(path, normalize=False)
    if err:
        return False, err
    marker = re.search(r"<!--\s*" + re.escape(REQ_SHA_MARKER) + r"\s*([0-9a-f]{64})\s*-->", text)
    if marker:
        body = text[marker.end():]
        # 记录器固定在 marker 后写一个正文换行；校验只去掉这一层封装，不改用户原文内部空白。
        body = body[1:] if body.startswith("\n") else body
        if body.endswith("\n"):
            body = body[:-1]
        actual = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if actual != marker.group(1):
            return False, "需求原文指纹不一致，文件写入后被改动或截断"
    return True, enc


def _configured_source_patterns(st):
    """仓库私有源码布局；config 字符串优先，defaults 支持字符串或正则数组。"""
    raw = ((st or {}).get("config", {}) or {}).get("源码路径", "")
    if raw:
        return ([x.strip() for x in raw.split(",") if x.strip()]
                if isinstance(raw, str) else list(raw) if isinstance(raw, list) else [])
    try:
        # utf-8-sig:团队手写 defaults 常带 BOM;解析失败必须可见——
        # 「源码路径」静默失效等于门禁口径悄悄变宽。
        v = json.load(open(DEFAULTS_PATH, encoding="utf-8-sig")).get("源码路径", [])
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v if isinstance(v, list) else []
    except FileNotFoundError:
        return []
    except Exception as e:
        print("⚠ %s 的「源码路径」解析失败,已忽略(请修复该 JSON): %s" % (DEFAULTS_PATH, e),
              file=sys.stderr)
        return []


def _matches_pattern(path, pattern):
    return source_paths.matches_pattern(path, pattern)


def _repo_rel_for_match(path):
    """目录类正则只能喂「项目根相对 + 正斜杠」路径。

    Edit gate 收到的是宿主给的绝对路径:直接拿去匹配 `(^|/)src/`,仓库祖先目录
    恰好叫 src/app/lib 时全仓所有文件都会被误判成源码(禁改步骤整体卡死且无出口);
    defaults 里 `^ut/` 这类锚定私有正则则反向永不命中。相对路径原样返回(去掉 ./ 前缀);
    项目根之外的绝对路径返回 None——目录模式对根外路径无意义(插件目录另有专门拦截)。
    不用 os.path.relpath:跨盘符抛 ValueError(Windows 军规3)。"""
    return source_paths.repo_relative_for_match(path, os.getcwd())


def _is_build_path(path):
    """识别会改变构建/依赖结果的入口；供源码范围和任务卡分类共用。"""
    return source_paths.is_build_path(path)


def _is_source_path(path, st=None, flow=None):
    """跨仓统一源码判定：扩展名/构建文件 + 通用目录 + 仓库私有路径，任一命中即算。

    Edit gate、Bash gate、令牌新鲜度和 UT 源码回流必须共用它，避免四套口径漂移。
    """
    normalized = norm(path).strip().strip('"\'')
    membership = os.path.isabs(normalized)
    known = source_paths.known_source_classification(
        normalized,
        project_root=os.getcwd(),
        require_membership=membership,
    )
    if known is not None:
        return known
    rules = list(
        (flow or FLOW or {}).get("source_patterns", []))
    rules.extend(_configured_source_patterns(st))
    return source_paths.is_source_path(
        normalized,
        rules,
        project_root=os.getcwd(),
        require_membership=membership,
    )


def _is_review(st):
    return (st.get("choices", {}) or {}).get("workflow") == "review"


def _ensure_review_base(st):
    """记录评审返工开始前的原 MR HEAD。

    新流程在 branch_create 离开前直接取 HEAD；旧版在途状态优先按进入 rf_triage 的
    history 时间反推，保证升级后不会把整个原需求 diff 当成本轮增量。
    """
    if not _is_review(st):
        return "", "当前不是评审意见处理流程"
    old = st.get("review_base_head", "")
    if old and argv_out(["git", "cat-file", "-t", old]) == "commit":
        return old, ""
    at = ""
    for h in st.get("history", []):
        if h.get("step") == "branch_create":
            at = h.get("at", "")
            break
    base = argv_out(["git", "rev-list", "-1", "--before=" + at, "HEAD"]) if at else ""
    if not base:
        review_doc = "docs/review/REVIEW-" + st.get("config", {}).get("单号", "") + ".md"
        added = argv_out([
            "git", "log", "--diff-filter=A", "-1", "--format=%H", "--", review_doc])
        if added:
            # --verify 必带(军规5):root commit 的 {added}^ 不存在时,裸 rev-parse 会把
            # 参数字面串回显到 stdout,伪 rev 一路传染成空 diff → 质量链静默全过。
            base = argv_out(["git", "rev-parse", "--verify", "--quiet", added + "^"])
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
    if not argv_out(["git", "rev-parse", "--verify", base]):
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


def _branch_adoption_requested(text):
    """Whether the user explicitly chose to keep working on the current branch."""
    value = re.sub(r"[（(]推荐[）)]", "", str(text or "")).strip()
    if re.search(
            r"(不要|不在|不想|拒绝|取消|改用其他|另开|新建|切到|切换到|"
            r"是否|能否|可以吗|怎么|如何|为什么|[?？])",
            value, re.I):
        return False
    branch = r"(?:当前|现有|现在|这个)分支"
    keep = r"(?:继续|沿用|保留|使用|开发|往下做)"
    return bool(
        re.search(branch + r"[^，。！？,;；]{0,12}" + keep, value, re.I)
        or re.search(keep + r"[^，。！？,;；]{0,12}" + branch, value, re.I)
    )


def _adopt_current_branch(st, ack):
    """Bind the explicitly chosen existing branch to this delivery round."""
    current = sh("git branch --show-current")
    head = argv_out(["git", "rev-parse", "--verify", "HEAD"])
    base = str((st.get("config", {}) or {}).get("基线分支", "") or "")
    base_head = argv_out(["git", "rev-parse", "--verify", base + "^{commit}"]) if base else ""
    if not current or not head:
        return False, "当前处于 detached HEAD 或 Git 状态不可读，不能登记为本单工作分支。"
    if not base or not base_head:
        return False, "配置中的基线分支不可解析，不能判断现有分支是否来自正确基线。"
    if current == base:
        return False, (
            "当前仍是基线分支 %s，不能把主干直接登记成本单工作分支。"
            "请创建约定分支，或先让用户选择一个非基线的现有工作分支。" % base
        )
    if argv_out(["git", "merge-base", base_head, head]) != base_head:
        return False, (
            "现有分支 %s 不包含基线 %s 的当前 HEAD，直接沿用会把无关历史带入本单。"
            "请先迁移/同步分支后重新让用户裁决。" % (current, base)
        )
    previous = str((st.get("config", {}) or {}).get("分支名", "") or "")
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    st.setdefault("config", {})["分支名"] = current
    st["branch_resolution"] = {
        "mode": "adopt-current",
        "branch": current,
        "head": head,
        "base": base,
        "base_head": base_head,
        "previous_branch": previous,
        "ack_sha256": hashlib.sha256(
            str(ack or "").encode("utf-8")).hexdigest(),
        "at": now,
    }
    return True, (
        "用户明确选择沿用现有分支；本单分支由 %s 调整为 %s，"
        "裁决时 HEAD=%s" % (previous or "(未配置)", current, head[:10])
    )


def ev_branch_ok(spec, st):
    want = st["config"].get("分支名", "")
    base = st["config"].get("基线分支", "")
    cur = sh("git branch --show-current")
    if not want:
        return False, "配置中无分支名(config_confirm 未 --set 分支名?)"
    if cur != want:
        return False, f"当前分支 {cur or '未知'} != 约定分支 {want}。请 git checkout -b {want}(已存在则 checkout;错误命名分支用 git branch -m 重命名)"
    if not base:
        return False, "配置中无基线分支，无法证明工作分支从正确位置切出"
    base_head = argv_out(["git", "rev-parse", "--verify", base + "^{commit}"])
    head = argv_out(["git", "rev-parse", "--verify", "HEAD"])
    if not base_head:
        return False, f"基线分支 {base} 不可解析；先 fetch/checkout 确认基线存在"
    if not head or head != base_head:
        resolution = st.get("branch_resolution") or {}
        if resolution.get("mode") == "adopt-current":
            if (resolution.get("branch") == cur
                    and resolution.get("head") == head
                    and resolution.get("base") == base
                    and resolution.get("base_head") == base_head):
                return True, ""
            return False, (
                "用户沿用现有分支的裁决已过期：裁决绑定 %s@%s、基线 %s，"
                "当前为 %s@%s、基线 HEAD %s。请展示变化后重新裁决，"
                "旧回答不能复用。"
                % (resolution.get("branch", "?"),
                   str(resolution.get("head", ""))[:10],
                   str(resolution.get("base_head", ""))[:10],
                   cur or "未知", head[:10] if head else "未知",
                   base_head[:10]))
        return False, (
            f"工作分支 {want} 的起点 {head[:10] if head else '未知'} != "
            f"基线 {base} 当前 HEAD {base_head[:10]}。branch_create 尚未开始实现，"
            "不能静默带入其他分支的提交。已有工作时先展示分支与提交差异，"
            "让用户选择迁移到约定分支或沿用当前非基线分支；选择沿用后按"
            "本步骤 current 输出的 goto 命令登记裁决。"
        )
    return True, ""


def ev_tasks_checked(spec, st):
    """实现清单全勾。清单从哪来由引擎统一裁决(v5=change.md 的"# 实现清单"节,
    legacy=tasks.md);宽松缩进的计数正则是本证据的历史语义,保持不变。"""
    cn = st["config"].get("CHANGE_NAME", "")
    if not cn:
        return False, "未找到本 change 的实现清单: CHANGE_NAME 未设置"
    from mae_flow_core import specengine
    try:
        label, txt = specengine.tasks_source(os.getcwd(), cn)
    except Exception as exc:  # 宽兜底:证据不 traceback,拒+指引可重试
        return False, "实现清单无法读取(%s): %s" % (type(exc).__name__, exc)
    if txt is None:
        return False, "未找到本 change 的实现清单: " + label
    n = len(re.findall(r"^\s*[-*]\s*\[\s\]", txt, re.M))
    return (n == 0, "" if n == 0 else f"{label} 还有 {n} 个未勾选任务")


def ev_spec_field(spec, st):
    """读本单交付登记字段作证据(由 `mae-flow spec` 子命令机器写入,并现场复核指针有效性)。

    v3 取代 yaml_field:数据源从 comet 的 .comet.yaml 换成 .mae-flow.json 的 spec 段——
    同一把锁、同一份 gate 保护,且登记时就校验过文件真实存在(比读外部 YAML 更可信)。
    spec: {"field": 名, "equals": 期望值} 或 {"field": 名}(非空即过)。"""
    field = spec["field"]
    data = _spec_data(st)
    val = str(data.get(field, "") or "")
    expected = spec.get("equals", spec.get("value"))
    if expected is not None:
        if val == expected:
            return True, ""
        return False, (f"交付登记 {field}={val or '(空)'},需要 {expected}"
                       "——按本步指引完成动作后用 mae-flow spec 登记,谎报无效")
    if val in ("", "null", "~"):
        return False, (f"交付登记 {field} 为空——本步产物尚未登记;"
                       f"完成后执行 mae-flow spec set {field} \"<路径>\"")
    # 指针类字段现场复核:登记后文件被删/改名不能继续算证据
    if field in SPEC_REGISTER_FIELDS and not os.path.isfile(val):
        return False, (f"交付登记 {field} 指向 {val},但该文件现在不存在(被删或改名);"
                       "重新生成产物并重新登记")
    return True, ""


# 轻量档的文件数升级阈值(与 hf_open/tw_open 步骤文档的升级条件一致)。
# 此前升级条件是纯提示词约束零机器锚点——模型不自查就静默滑过(审计定性)。
TIER_FILE_LIMITS = {"tweak": 5, "hotfix": 3}


def ev_tier_scope(spec, st):
    """轻量档范围硬校验:改动业务文件数超档位阈值时拒绝推进,呈用户裁决。

    出口两条(禁令必配出口):①升级工作流(hotfix 正规升级/goto design --force);
    ②用户确认确属轻量档 → accept-risk tier_scope(绑 HEAD,再改文件即失效)。
    full/review 不限。"""
    wf = (st.get("choices", {}) or {}).get("workflow", "")
    limit = TIER_FILE_LIMITS.get(wf)
    if not limit:
        return True, ""
    accepted, _why = _risk_acceptance("TIER_SCOPE", st)
    if accepted:
        return True, ""
    invalidated = ("已有 tier_scope 放行已失效(%s)。" % _why) if _why else ""
    files, err = _biz_changed_files(st)
    if err:
        return False, err
    if len(files) <= limit:
        return True, ""
    return False, (
        invalidated +
        "本单已改 %d 个业务文件,超过 %s 档升级阈值(%d):%s%s。这是步骤文档里的"
        "升级条件,现在由机器亲数。两条出路呈用户裁决:①升级工作流(展示原因,"
        "确认后按步骤指引正规升级/goto design --force);②确属轻量修改(如批量"
        "重命名)则 accept-risk tier_scope --reason --ack \"用户原话\" 继续,"
        "代码再变化即失效"
        % (len(files), wf, limit, "、".join(files[:6]),
           "…" if len(files) > 6 else ""))


def ev_spec_validate(spec, st):
    """规格结构校验作硬证据:调内置引擎对本 change 跑 validate。

    spec 可带 {"allow_empty": true}(hotfix/tweak 档):change 未声明任何规格
    变化时直接判过(轻量单允许无规格);一旦声明了规格条目/delta,格式必须过
    全套校验。v5 布局顺带拦骨架占位残留(占位进档案等于没写);查哪些前缀由
    {"placeholders": [...]} 配置,缺省只查「（待填」——方案节的「（待设计」
    属设计阶段,由 design 步的证据配置追加。布局混用(change.md 与旧四件套
    并存)在 has_delta/validate 里就会报错。"""
    cn = st["config"].get("CHANGE_NAME", "")
    if not cn:
        return False, "CHANGE_NAME 未设置,无法校验规格"
    from mae_flow_core import specengine
    # 宽兜底:证据函数抛裸异常会让 done 直接 traceback(check_evidence 无全局
    # 兜底)。核心原则是流畅易用不卡死——任何异常都转成"拒+可执行指引",
    # done 可重试、连拒两次自动亮 goto --force 用户裁决出口。
    try:
        need_validate = True
        if spec.get("allow_empty") and not specengine.has_delta(os.getcwd(), cn):
            need_validate = False
        if need_validate:
            ok, messages = specengine.validate(os.getcwd(), cn)
            if not ok:
                errors = [m for m in messages if m.startswith("[错误]")]
                shown = "; ".join(errors[:3]) + ("…" if len(errors) > 3 else "")
                return False, ("规格结构校验未通过: " + shown
                               + "。跑 spec validate 看全部并逐条修正")
        doc_path = os.path.join("openspec", "changes", cn, "change.md")
        if os.path.isfile(doc_path):
            txt = open(doc_path, encoding="utf-8").read()
            hit = [p for p in (spec.get("placeholders") or ["（待填"]) if p in txt]
            if hit:
                return False, ("change.md 残留「%s…」骨架占位;"
                               "把占位替换成实际内容后重试" % "、".join(hit))
        # v5 分档必须节接线(审计实锤:V5_TIER_REQUIRED 曾是零消费死常量,
        # "full=四节"合同在机器侧未接线,整节删除可静默过全部门禁)。
        workflow = (st.get("choices", {}) or {}).get("workflow", "")
        missing = specengine.check_required_sections(os.getcwd(), cn, workflow)
        if missing:
            return False, ("change.md 缺少 %s 档必须小节: %s;分档合同见 "
                           "spec instructions change"
                           % (workflow, "、".join(missing)))
    except specengine.SpecEngineError as exc:
        return False, "规格校验无法执行: " + str(exc)
    except Exception as exc:
        return False, ("规格校验异常(%s: %s);按报错修复对应文件(编码须 UTF-8)"
                       "后重试" % (type(exc).__name__, exc))
    return True, ""


def _unchanged_initial_dirty(path, st):
    """流程启动前已脏且指纹未变的文件不是本单变化，仍保留在状态中可审计。"""
    rel = norm(path).strip().strip('"')
    initial = set((st or {}).get("initial_dirty", []) or [])
    fingerprints = (st or {}).get("initial_dirty_fingerprints", {}) or {}
    return bool(rel in initial and fingerprints.get(rel) == _path_fingerprint(rel))


def _blocking_dirty_source_paths(st, flow=None):
    return [p for p in _dirty_paths()
            if _is_source_path(p, st, flow or FLOW)
            and not _unchanged_initial_dirty(p, st)]


def _unchanged_initial_dirty_source_paths(st, flow=None):
    return [p for p in _dirty_paths()
            if _is_source_path(p, st, flow or FLOW)
            and _unchanged_initial_dirty(p, st)]


def _source_changed_since(head, st=None):
    """令牌签发时 HEAD 之后,源码是否变化:已提交 diff + 工作区未提交改动。
    返回 (变更清单, 错误);基点不可解析(amend/rebase/GC)属错误,由调用方判拒——重签令牌即可恢复。"""
    if not re.fullmatch(r"[0-9a-f]{7,64}", head):
        return None, "令牌基点格式异常"
    cur = sh("git rev-parse --verify HEAD")
    if not cur:
        return None, "无法读取当前 HEAD（仓库可能已切走、损坏或不再是 Git 工作区）"
    changed = []
    if cur and cur != head:
        # cat-file 探基点存在性(不用 rev-parse ^{commit}:^ 在 Windows cmd 是转义符)
        if argv_out(["git", "cat-file", "-t", head]) != "commit":
            return None, "令牌基点 commit 不可解析(经历过 amend/rebase?)"
        # core.quotepath=false:否则非 ASCII 文件名被引号+八进制转义,pattern 匹配不到 = 漏检
        out = argv_out([
            "git", "-c", "core.quotepath=false",
            "diff", "--name-only", head, cur,
        ])
        changed += [f for f in out.splitlines() if f and _is_source_path(f, st)]
    # 校准实锤:令牌签发前就存在、内容此后未变的存量脏文件曾被算作"签发后
    # 变化",连锁封死任务卡/accept-risk/令牌复用(连裁决出口一起封)。init 已
    # 记 initial_dirty + 指纹,据此豁免:仅当该文件本单真动过(指纹变了)才算变化。
    for line in sh("git -c core.quotepath=false status --porcelain --untracked-files=all").splitlines():
        # 按空白切"状态 路径",不用列偏移:sh() 会 strip 首行前导空格(' M' → 'M'),偏移取路径会错位
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        f = parts[1].split(" -> ")[-1].strip().strip('"')
        if not f or not _is_source_path(f, st):
            continue
        if _unchanged_initial_dirty(f, st):
            continue  # 存量脏文件,本单未动,不算签发后变化
        changed.append(f + "(未提交)")
    return changed, ""


def _changed_paths_since_head(head):
    paths = []
    if head and argv_out(["git", "cat-file", "-t", head]) == "commit":
        paths.extend(argv_out([
            "git", "-c", "core.quotepath=false", "diff",
            "--name-only", "--no-renames", head, "HEAD",
        ]).splitlines())
    paths.extend(argv_out([
        "git", "-c", "core.quotepath=false", "diff",
        "--name-only", "--no-renames", "HEAD",
    ]).splitlines())
    paths.extend(_dirty_paths())
    return list(dict.fromkeys(norm(path) for path in paths if path))


def _source_fingerprints(paths, st=None, flow=None):
    result = {}
    for path in paths:
        if _is_source_path(path, st, flow or FLOW):
            result[path] = _review_path_fingerprint(path)
    return result


def _source_snapshot_since(head, st=None, flow=None):
    """Fingerprint committed, staged, unstaged and untracked source changes."""
    return _source_fingerprints(
        _changed_paths_since_head(head), st, flow)


def _checkpoint_candidate_path(path, st, flow=None):
    if _is_source_path(path, st, flow or FLOW):
        return True
    if _repo_path_identity(path) in _agent_written_paths():
        return True
    return _trusted_harness_commit_path(path, st)


def _checkpoint_delivery_snapshot(st, head, flow=None):
    """Fingerprint all reviewable delivery candidates, not just code suffixes."""
    result = {}
    for path in _changed_paths_since_head(head):
        if _unchanged_initial_dirty(path, st):
            continue
        if _checkpoint_candidate_path(path, st, flow):
            result[path] = _review_path_fingerprint(path)
    return result


def _checkpoint_worktree_snapshot(st, flow=None):
    """Return the exact uncommitted delivery snapshot shown in the IDE."""
    head = sh("git rev-parse --verify HEAD")
    return _checkpoint_delivery_snapshot(st, head, flow)


def _numstat_line_net(line, st=None, flow=None):
    fields = line.split("\t")
    if len(fields) != 3:
        return 0
    if not _is_source_path(fields[2], st, flow or FLOW):
        return 0
    try:
        added, deleted = int(fields[0]), int(fields[1])
    except ValueError:
        return 0
    return added - deleted


def _numstat_source_net(output, st=None, flow=None):
    return sum(
        _numstat_line_net(line, st, flow)
        for line in output.splitlines())


def _file_line_count(path):
    try:
        with open(path, "rb") as stream:
            return sum(1 for _line in stream)
    except OSError:
        return 0


def _untracked_source_net(st=None, flow=None):
    tracked = set(argv_out([
        "git", "ls-files", "--others", "--exclude-standard",
    ]).splitlines())
    return sum(
        _file_line_count(path) for path in tracked
        if _is_source_path(path, st, flow or FLOW))


def _working_source_net(head, st=None, flow=None):
    committed = argv_out([
        "git", "-c", "core.quotepath=false", "diff",
        "--numstat", head, "HEAD",
    ])
    working = argv_out([
        "git", "-c", "core.quotepath=false", "diff",
        "--numstat", "HEAD",
    ])
    return (
        _numstat_source_net(committed, st, flow)
        + _numstat_source_net(working, st, flow)
        + _untracked_source_net(st, flow))


def _snapshot_sha256(snapshot):
    body = json.dumps(
        snapshot or {}, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


RISK_AGENT_LABELS = {
    "COMPILE": "没有可验证的编译成功证据，代码可能无法构建",
    "CODECHECK": "CodeCheck 修复 Agent 没有合法令牌；本次将只保留首检结果，缺少专项修复结论",
    "CODECHECK_TOOL": "CodeCheck CLI 自动安装或执行失败，本次将缺少代码规范检查结果",
    "UT": "没有可验证的 UT 生成/运行通过证据，回归问题可能进入后续阶段",
    "STORY": "没有可验证的 STORY 专项 Agent 收尾证据",
    "GRILL": "需求追问 Agent 没有合法收尾，需求边界可能仍有遗漏",
    "ASKUSER": "宿主没有签发用户交互令牌；本次风险确认本身仍必须匹配用户真实原话",
    "UTRUN": "没有观测到 UT 命令真实调起",
    "TIER_SCOPE": "本单改动文件数超过所选交付档的升级阈值，继续按轻量档走会绕过设计与规格环节",
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
    # 校准实锤:history[-1] 不是"本步进入时间"——spec 登记/phase/accept-risk/
    # gate 放行都会 append history,open 步按法定顺序(问完用户再 spec phase
    # design)必然把刚签的 ASKUSER 令牌判成"本步之前",逼用户重新拍板。
    # 与 _risk_acceptance 同源用真实步骤转移时间;跨步复用由 token_step 拦、
    # 跨轮复用由令牌绑 HEAD 拦,收敛 entered 不开任何造假通道。
    entered = _step_entered_at(st)
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
    token_snapshot = tok.get("source_snapshot") if isinstance(tok, dict) else None
    if ts and ts >= entered:
        if token_step and token_step != st.get("current"):
            return blocked(f"{kind} 令牌属于步骤 {token_step}，当前是 {st.get('current')}。"
                           "每个步骤必须重新执行，不能复用上一关同一秒签发的令牌。")
        wanted = spec.get("statuses") or ([spec["status"]] if spec.get("status") else [])
        if wanted and status not in wanted:
            return blocked(f"{kind} 子 agent 虽已收尾,但结果为 {status or '旧令牌未记录状态'},"
                           f"本步只接受 {'/'.join(wanted)}。FAIL/BLOCKED/NEEDS_INPUT 是有效上报,"
                           "但不是质量通过证据;处理报告中的问题后重启 agent。")
        if head and isinstance(token_snapshot, dict):
            current_snapshot = _source_snapshot_since(head, st)
            if current_snapshot != token_snapshot:
                return blocked(
                    f"{kind} 证据已过期:令牌签发后的未提交代码快照已变化。"
                    "重新启动对应 agent 对当前工作区收尾；旧证据不能背书另一份 diff。")
        elif head:
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


def _source_files_for_diff(diff, st, include_tests=True):
    """指定 Git 范围内所有源码/构建入口变化，包含删除项。"""
    out = argv_out([
        "git", "-c", "core.quotepath=false", "diff", "--name-only", diff])
    files = [f for f in out.splitlines() if f and _is_source_path(f, st)]
    if not include_tests:
        files = [f for f in files if not _is_test_file(f, st)]
    return files, ""


def _changed_source_files(st, include_tests=True):
    """当前交付范围内所有源码/构建入口变化，不把语言范围写死成 C++/Java。"""
    diff, err = _scope_diff(st)
    if err:
        return None, err
    return _source_files_for_diff(diff, st, include_tests)


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


def ev_review_snapshot(spec, st):
    """用户确认只能背书进入检视节点时展示的那一版代码。

    检视期间若 HEAD 或源码工作区变化，旧展示立即失效，必须回到对应编码环节，
    重新提交、编译并生成新检视收据，不能确认 A 后让 B 继续。
    """
    sid = st.get("current", "")
    entered = (st.get("step_heads", {}) or {}).get(sid, "")
    current = sh("git rev-parse --verify HEAD")
    if not entered or argv_out(["git", "cat-file", "-t", entered]) != "commit":
        return False, f"缺少 {sid} 的检视入口 HEAD，无法确定用户看到的是哪版代码"
    if current != entered:
        return False, (
            f"检视期间 HEAD 已从 {entered[:10]} 变为 {current[:10] or '未知'}。"
            "旧展示已失效；回到对应编码环节，重新编译后再让用户检视。")
    base_step = spec.get("base_step", "")
    base = (st.get("step_heads", {}) or {}).get(base_step, "")
    if not base or argv_out(["git", "cat-file", "-t", base]) != "commit":
        return False, f"缺少 {base_step} 的入口 HEAD，无法生成本轮完整代码差异"
    if argv_out(["git", "merge-base", base, current]) != base:
        return False, (
            f"本轮检视基点 {base[:10]} 已不在当前 HEAD 历史上，可能发生了 rebase/reset。"
            "必须重新进入编码和编译环节建立可信范围。")
    dirty = _blocking_dirty_source_paths(st)
    if dirty:
        return False, (
            "用户检视期间源码/测试/构建文件又发生未提交变化: "
            + "、".join(dirty[:8])
            + "。旧编译和检视收据均已失效；先回到对应编码环节处理。")
    return True, ""


def _development_review(st):
    """Return the optional checkpoint state without migrating legacy deliveries.

    Absence is meaningful: an in-flight delivery created by an older release
    must keep its original build_review/tw_review/rf_review behavior.
    """
    data = st.get("development_review")
    return data if isinstance(data, dict) and data.get("version") == 1 else None


def _development_checkpoints_enabled(st):
    protocols = st.get("protocols") or {}
    return bool(
        isinstance(protocols, dict)
        and int(protocols.get("development_checkpoints", 0) or 0) >= 1)


def _task_structure_fingerprint(st):
    """Hash task identity/order while ignoring checkbox state and notes."""
    workflow = (st.get("choices", {}) or {}).get("workflow", "")
    lines = []
    if workflow == "review":
        path = os.path.join(
            "docs", "review",
            "REVIEW-" + str((st.get("config", {}) or {}).get("单号", "")) + ".md")
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            text = ""
        for raw in text.splitlines():
            if not raw.lstrip().startswith("|"):
                continue
            cells = [re.sub(r"\s+", " ", x.strip().strip("*`"))
                     for x in raw.strip().strip("|").split("|")]
            if (len(cells) >= 4 and cells[0] != "#"
                    and not set(cells[0]) <= {"-", ":"}
                    and cells[-1] == "修复(已确认)"):
                lines.append("|".join(cells[:-1]))
    else:
        change_name = str((st.get("config", {}) or {}).get("CHANGE_NAME", ""))
        try:
            from mae_flow_core import specengine
            _label, text = specengine.tasks_source(os.getcwd(), change_name)
        except Exception:
            text = ""
        for raw in (text or "").splitlines():
            match = re.match(r"^\s*[-*]\s*\[[ xX]\]\s*(.+?)\s*$", raw)
            if match:
                lines.append(re.sub(r"\s+", " ", match.group(1)).strip())
    body = "\n".join(lines)
    return hashlib.sha256(body.encode("utf-8")).hexdigest(), lines


def _checkpoint_current(st):
    return delivery_checkpoints.current_item(st)


def _checkpoint_expected_code_step(st):
    return delivery_checkpoints.expected_code_step(st)


def _checkpoint_review_pending(st):
    return delivery_checkpoints.review_pending(
        st, moonlight=_moonlight(st))


CHECKPOINT_LOCKED_STATUSES = delivery_checkpoints.LOCKED_STATUSES


def _final_review_item(st):
    return delivery_checkpoints.final_review_item(st)


def _checkpoint_locked_item(st):
    return delivery_checkpoints.locked_item(st)


def _checkpoint_review_locked(st):
    """Freeze reviewed code through exact commit and push verification."""
    return delivery_checkpoints.review_locked(
        st, moonlight=_moonlight(st))


def _review_before_commit(data):
    """New plans review worktree code; old in-flight plans retain their route."""
    return bool((data or {}).get("review_before_commit"))


def _upstream_snapshot():
    ref = argv_out([
        "git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    remote_head = argv_out(["git", "rev-parse", "--verify", "@{u}"])
    local_head = argv_out(["git", "rev-parse", "--verify", "HEAD"])
    return ref, remote_head, local_head


def _reset_range_reaches_upstream(base, head, remote_head):
    shared = argv_out(["git", "merge-base", head, remote_head])
    if not shared or shared == base:
        return False
    if argv_out(["git", "merge-base", base, shared]) != base:
        return False
    return True


def _upstream_contains_reset_commit(base, head):
    """Return the upstream ref when resetting base..head would drop pushed work."""
    ref, remote_head, _local_head = _upstream_snapshot()
    if not ref or not remote_head:
        return ""
    if head == base:
        return ""
    return ref if _reset_range_reaches_upstream(
        base, head, remote_head) else ""


def _checkpoint_review_lines(base, head, title, remote_ref=""):
    commits = argv_out([
        "git", "-c", "core.quotepath=false", "log", "--format=%h %s",
        base + ".." + head,
    ]).splitlines()
    files = argv_out([
        "git", "-c", "core.quotepath=false", "diff", "--name-status",
        base, head,
    ]).splitlines()
    stat = argv_out([
        "git", "-c", "core.quotepath=false", "diff", "--shortstat",
        base, head,
    ])
    lines = [
        "🔎 " + title,
        f"  范围: {base[:10]}..{head[:10]}",
    ]
    if remote_ref:
        lines.append(f"  远端收据: {remote_ref}@{head[:10]}")
    lines.append("  提交:")
    lines += ["    " + x for x in commits[:30]] or ["    （无提交）"]
    if len(commits) > 30:
        lines.append(f"    …另有 {len(commits) - 30} 个提交")
    lines.append("  文件:")
    lines += ["    " + x for x in files[:80]] or ["    （无文件差异）"]
    if len(files) > 80:
        lines.append(f"    …另有 {len(files) - 80} 个文件")
    if stat:
        lines.append("  统计: " + stat)
    lines.append(f"  完整差异命令: git diff {base} {head}")
    return lines


def _worktree_review_status(paths):
    if not paths:
        return [], ""
    status = argv_out([
        "git", "-c", "core.quotepath=false", "status", "--short",
        "--untracked-files=all", "--", *paths,
    ]).splitlines()
    stat = argv_out([
        "git", "-c", "core.quotepath=false", "diff",
        "--shortstat", "HEAD", "--", *paths,
    ])
    return status, stat


def _untracked_review_paths(paths):
    result = []
    for path in paths:
        tracked = argv_out([
            "git", "ls-files", "--error-unmatch", "--", path])
        if not tracked:
            result.append(path)
    return result


def _worktree_review_file_lines(status):
    lines = ["  文件:"]
    lines += ["    " + line for line in status[:80]]
    if not status:
        lines.append("    （无文件差异）")
    if len(status) > 80:
        lines.append("    …另有 %d 个文件" % (len(status) - 80))
    return lines


def _worktree_review_detail_lines(paths, stat, receipt):
    lines = []
    if stat:
        lines.append("  统计: " + stat)
    command = " ".join(shlex.quote(path) for path in paths)
    lines.append("  命令行复核: git diff HEAD -- " + command)
    untracked = _untracked_review_paths(paths)
    if untracked:
        lines.append("  未跟踪新文件也属于本收据，请在 IDE Source Control 中逐个打开: "
                     + "、".join(untracked))
    lines.append("  收据指纹: " + str(
        receipt.get("snapshot_sha256", ""))[:16])
    return lines


def _checkpoint_worktree_review_lines(item):
    receipt = item.get("receipt") or {}
    base = str(receipt.get("base", ""))
    paths = list((receipt.get("snapshot") or {}).keys())
    status, stat = _worktree_review_status(paths)
    lines = [
        "🔎 %s 用户代码检视（尚未提交）" % item.get("id"),
        "  对比基点: HEAD@%s" % base[:10],
        "  IDE 检视入口: Source Control / Local Changes；这里看到的未提交 diff "
        "就是确认后允许提交的代码。",
    ]
    lines += _worktree_review_file_lines(status)
    lines += _worktree_review_detail_lines(paths, stat, receipt)
    return lines


def _final_review_candidate_path(path, st):
    if _is_source_path(path, st, FLOW):
        return True
    identity = _repo_path_identity(path)
    if identity not in _agent_written_paths():
        return False
    low = norm(path).lower()
    return not low.endswith((".md", ".rst", ".adoc"))


def _final_delivery_snapshot(st, head):
    result = {}
    for path in _changed_paths_since_head(head):
        if _unchanged_initial_dirty(path, st):
            continue
        if _final_review_candidate_path(path, st):
            result[path] = _review_path_fingerprint(path)
    return result


def _final_review_delta(st):
    data = _development_review(st)
    if not data or _moonlight(st):
        return [], ""
    base = str(data.get("last_reviewed_head") or data.get("delivery_base") or "")
    if not base:
        return None, "缺少上次已检视代码基点"
    current = sh("git rev-parse --verify HEAD")
    if (argv_out(["git", "cat-file", "-t", base]) != "commit"
            or argv_out(["git", "merge-base", base, current]) != base):
        return None, (
            "上次已检视代码基点 %s 已不在当前 HEAD 历史上，可能发生了 "
            "rebase/reset；旧收据不能为改写后的提交历史背书" % base[:10])
    snapshot = _final_delivery_snapshot(st, base)
    dirty = set(_dirty_paths())
    changed = [
        path + ("(未提交)" if path in dirty else "")
        for path in snapshot
    ]
    return changed, ""


def ev_checkpoint_plan(spec, st):
    if _moonlight(st):
        return True, ""
    data = _development_review(st)
    if not data or data.get("status") != "plan_pending":
        return False, (
            "尚未生成开发检查点方案。先按本步指令执行 checkpoint plan --item ...，"
            "让用户看到具体批次后再选择开发节奏")
    if data.get("plan_step") != st.get("current"):
        return False, "检查点方案属于旧步骤，重新分析并生成本步方案"
    items = data.get("checkpoints") or []
    if not 1 <= len(items) <= 6:
        return False, "检查点数量必须为 1-6 个；小改可 1 个，常规任务建议 2-4 个"
    changed, err = _source_changed_since(data.get("plan_head", ""), st)
    if err:
        return False, "检查点方案基点无法核实:" + err
    if changed:
        return False, (
            "检查点方案呈现后代码已经变化: " + "、".join(changed[:5])
            + "。必须在写码前重新生成方案，不能确认旧划分")
    return True, ""


def ev_checkpoint_plan_complete(spec, st):
    """New deliveries honor their pace plan; legacy states remain untouched."""
    data = _development_review(st)
    if not data or _moonlight(st):
        return True, ""
    if data.get("status") != "active":
        return False, "开发节奏尚未完成用户确认"
    mode = data.get("mode")
    items = data.get("checkpoints") or []
    closed = (
        (lambda item: item.get("status") == "accepted")
        if mode == "staged" else
        (lambda item: item.get("status") in ("completed", "accepted"))
    )
    pending = [x.get("id", "?") for x in items if not closed(x)]
    if pending:
        if mode == "staged" and _review_before_commit(data):
            action = (
                "保持本批代码未提交，完成 compile-agent 后执行 checkpoint ready "
                "<CP编号>；用户检视确认后再精确提交、push")
        elif mode == "staged":
            action = "完成本批编译和 push 后 checkpoint status，等待用户检视"
        else:
            action = "完成本批编译后 checkpoint ready <CP编号>；连续模式不会停下来"
        return False, "检查点尚未闭环: %s。%s" % ("、".join(pending), action)
    return True, ""


def ev_final_review_clear(spec, st):
    """No final code delta may pass into irreversible archive/final push unseen."""
    data = _development_review(st)
    if not data or _moonlight(st):
        return True, ""
    changed, err = _final_review_delta(st)
    if err:
        return False, "最终检视基点无法核实:" + err
    if changed:
        return False, (
            "质量链后仍有未检视代码增量: " + "、".join(changed[:8])
            + "。执行 checkpoint final；所有普通模式都先检视本地增量，"
              "用户确认后才进入最终 push")
    return True, ""


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
        out = argv_out(["git", "status", "--porcelain", "--", p])
        if out:
            dirty.append(f"{p}({out.splitlines()[0][:2].strip()})")
    if not dirty:
        return True, ""
    return False, "以下产物未提交(或有未提交改动),先 git add/commit 再 done: " + "、".join(dirty)


def _archive_delivery_paths(st):
    """Return only the paths produced by this delivery's archive operation."""
    data = (st or {}).get("spec", {}) or {}
    paths = [
        re.sub(r"^(?:\./)+", "", norm(path))
        for path in data.get("archive_paths", []) or []
        if isinstance(path, str) and path.strip()
    ]
    if paths:
        return list(dict.fromkeys(paths))

    # Compatibility for an archive completed by a pre-upgrade in-flight state:
    # archived_to identifies the moved change. The exact merged specs were not
    # persisted then, so derive only currently dirty spec files and exclude
    # unchanged dirt that was already present when this delivery started.
    archive_name = str(data.get("archived_to", "") or "")
    if archive_name:
        paths.append("openspec/changes/archive/" + archive_name)
    paths.extend(
        path for path in _dirty_paths()
        if path.startswith("openspec/specs/")
        and not _unchanged_initial_dirty(path, st or {})
    )
    return list(dict.fromkeys(paths))


def ev_archive_paths_clean(spec, st):
    """Require this archive's exact outputs to be committed, not all OpenSpec."""
    paths = _archive_delivery_paths(st)
    if not paths:
        return False, (
            "缺少本次定稿的精确产物清单；重新执行 spec archive，"
            "或由维护人核对旧在途状态后再推进")
    dirty = []
    for path in paths:
        out = argv_out(["git", "status", "--porcelain", "--", path])
        if out:
            dirty.append(f"{path}({out.splitlines()[0][:2].strip()})")
    if not dirty:
        return True, ""
    return False, (
        "本次定稿产物尚未提交: " + "、".join(dirty)
        + "。只精确 git add 上述路径并提交；不要 git add openspec/，"
          "它可能卷入上一单遗留文件")


def _committed_delivery_paths(st):
    """List paths committed in this delivery's quality scope."""
    scope, err = _scope_diff(st)
    if err:
        return [], err
    try:
        result = subprocess.run(
            ["git", "-c", "core.quotepath=false", "diff", "--name-only",
             "--no-renames", scope, "--"],
            shell=False, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
    except Exception as exc:
        return [], str(exc)
    if result.returncode != 0:
        return [], (result.stderr or result.stdout or "git diff 失败").strip()
    changed = {
        re.sub(r"^(?:\./)+", "", norm(path))
        for path in result.stdout.splitlines() if path.strip()
    }
    return sorted(changed), ""


def _committed_initial_carryover(st):
    """Find unchanged pre-flow dirt that was committed into this delivery."""
    if not st or not st.get("initial_dirty"):
        return [], ""
    changed, err = _committed_delivery_paths(st)
    if err:
        return [], err
    changed = set(changed)
    written = _agent_written_paths()
    carried = [
        path for path in (st.get("initial_dirty", []) or [])
        if path in changed
        and _unchanged_initial_dirty(path, st)
        and _repo_path_identity(path) not in written
    ]
    return carried, ""


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
        return False, (
            "本地 HEAD 与远端上游不一致(未推送/推送失败/远端有新提交):"
            "先尝试普通 git push -u origin HEAD；若远端领先，执行 git fetch 后展示分叉，"
            "不要自动 rebase、reset 或 force-push（可能改写已检视检查点）")
    carried, carry_err = _committed_initial_carryover(st)
    if carry_err:
        return False, "无法核对是否夹带上一单遗留文件:" + carry_err
    if carried:
        return False, (
            "远端提交夹带了流程启动前已存在、且本单 Agent 未实际改写的文件: "
            + "、".join(carried[:8])
            + ("…" if len(carried) > 8 else "")
            + "。这通常是上一单选择“不上传”后遗留的文件。"
              "请用普通后续提交精确移除这些文件并重新 push；"
              "不要 amend/rebase/force-push 改写已检视历史。"
              "若本单确实需要它，先让 Agent 按本单需求实际修改并重新检视")
    committed_paths, committed_err = _committed_delivery_paths(st)
    if committed_err:
        return False, "无法核对已推送 OpenSpec 的归属:" + committed_err
    foreign_openspec = [
        path for path in committed_paths
        if path.startswith("openspec/")
        and not _trusted_harness_commit_path(path, st)
    ]
    if foreign_openspec:
        return False, (
            "远端提交含不属于当前 CHANGE_NAME/本次归档的 OpenSpec 文件: "
            + "、".join(foreign_openspec[:8])
            + ("…" if len(foreign_openspec) > 8 else "")
            + "。请用普通后续提交精确移除并重新 push；"
              "STORY 不入库时应移入 .mae-flow-work/story")
    current = set(_dirty_paths())
    initial = set(st.get("initial_dirty", []))
    if "initial_dirty" in st:
        changed_initial = set()
        fingerprints = st.get("initial_dirty_fingerprints", {}) or {}
        if fingerprints:
            changed_initial = {p for p in current & initial
                               if fingerprints.get(p) != _path_fingerprint(p)}
        changed_during_flow = (current - initial) | changed_initial
    else:
        # 旧在途状态没有初始化快照，只能从当前脏路径中再按来源缩小。
        changed_during_flow = current

    # 与提交前 Gate 使用同一来源口径：只有 Agent 通过文件工具直接写过的
    # 路径，以及 Mae-Flow 明确维护的交付产物，才可能属于本单提交范围。
    # IDE/CodeAgent/编译器在流程中生成的未证明路径仍留在工作区供审计，但
    # 不能仅凭“初始化后出现”就逼用户把它提交进 MR。
    written = _agent_written_paths()
    new_dirty = {
        p for p in changed_during_flow
        if (_repo_path_identity(p) in written
            or _trusted_harness_commit_path(p, st))
    }
    story_mode = str(st.get("config", {}).get("STORY入库", "")).lower()
    if any(x in story_mode for x in ("不生成", "不入库", "不提交", "no", "false")):
        story = "docs/story/STORY-" + st.get("config", {}).get("单号", "") + ".md"
        tracked = argv_out([
            "git", "ls-tree", "-r", "--name-only", "HEAD", "--", story])
        if tracked:
            return False, (f"STORY 已确认不入库，但 {story} 仍在当前提交中。"
                           "用 git rm --cached 精确移出索引并按单号提交修正；本地文件可以保留。")
        new_dirty = {p for p in new_dirty if not p.startswith("docs/story/")}
    if new_dirty:
        return False, (
            "仍有 Agent 实际写入或流程明确维护的交付候选未处理，远端不包含这些变化: "
            + "、".join(sorted(new_dirty)[:8])
            + "。逐个查看 diff：需要交付的精确提交，不需要的撤销修改；"
              "候选范围不代表必须全部提交。")
    return True, ""


def ev_commit_tagged(spec, st):
    dan = st["config"].get("单号", "")
    msg = sh("git log -1 --pretty=%s")
    if not msg:
        return False, "无法读取最新 commit"
    if re.match(r"^\[" + re.escape(dan) + r"\]\[(feat|fix)\]", msg):
        return True, ""
    # 晚拦截必须自带修复路径(核心哲学:错时机的拦截若不告诉怎么改,危害比
    # 不拦更大)。此兜底只在提交绕过了实时格式检查(-F/长参形态/子 agent
    # hook 未触发)时才会触发,修复=一条 amend,不动改动内容。
    return False, (f"最新 commit「{msg}」不符合 [{dan}][feat|fix]描述 格式。"
                   f"修复只需一条命令(不动已提交的改动内容):"
                   f"git commit --amend -m \"[{dan}][fix|feat]<原描述>\"")


def ev_commit_tagged_after_entry(spec, st):
    """不仅看最新提交格式，还要求提交确实发生在当前步骤之后。"""
    sid = st.get("current", "")
    base = (st.get("step_heads", {}) or {}).get(sid, "")
    if not base or argv_out(["git", "cat-file", "-t", base]) != "commit":
        return False, f"缺少 {sid} 的入口 HEAD，无法证明本步真的产生过提交"
    commits = argv_out(["git", "log", "--format=%H", base + "..HEAD"]).splitlines()
    if not commits:
        return False, "当前步骤之后没有新提交，不能拿上一步的提交冒充本步产出"
    return ev_commit_tagged(spec, st)


def _review_status_count(txt, status):
    """只统计评审意见表的数据行，不把模板说明中的合法值当真实裁决。"""
    # 只看意见清单的数据行。模板说明本身也会列出“修复(已确认)”这个合法值，
    # 全文搜关键词会把空模板误判成已有修复，导致没有代码可改时也被永久卡住。
    count = 0
    for line in txt.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [x.strip().strip("*`") for x in line.strip().strip("|").split("|")]
        if len(cells) < 4 or cells[0] == "#" or set(cells[0]) <= {"-", ":"}:
            continue
        if cells[-1] == status:
            count += 1
    return count


def _review_statuses(txt):
    """评审轮次/行号/意见原文 → 裁决；用于识别数量不变但意见身份被偷换。"""
    out = {}
    section = "未分节"
    for line in txt.splitlines():
        heading = re.match(r"^\s*##\s+(.+?)\s*$", line)
        if heading:
            section = re.sub(r"\s+", " ", heading.group(1)).strip()
            continue
        if not line.lstrip().startswith("|"):
            continue
        cells = [x.strip().strip("*`") for x in line.strip().strip("|").split("|")]
        if len(cells) < 4 or cells[0] == "#" or set(cells[0]) <= {"-", ":"}:
            continue
        base_identity = "%s / #%s / %s" % (
            section, cells[0], re.sub(r"\s+", " ", cells[1])[:40])
        identity, duplicate = base_identity, 2
        while identity in out:
            identity = "%s / 重复%d" % (base_identity, duplicate)
            duplicate += 1
        out[identity] = cells[-1]
    return out


def _review_has_confirmed_fix(txt):
    return _review_status_count(txt, "修复(已确认)") > 0


def ev_review_fix_committed(spec, st):
    """没有待修意见时允许空过；存在“修复(已确认)”则必须有本步骤的新提交。"""
    p = "docs/review/REVIEW-" + st.get("config", {}).get("单号", "") + ".md"
    try:
        txt = open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        return False, "评审裁决文档不存在: " + p
    # rf_triage 收尾时冻结「转规格轮次」数量。rf_fix 若把用户已经确认的
    # 「修复」翻案为「转规格轮次(已确认)」，必须在本步骤重新取得用户裁决，
    # 不能靠改文档里的终态文字单方面伪造“已确认”。旧版在途状态无快照时
    # fail-open，避免升级把已经进行中的评审轮永久卡死。
    baseline_rows = st.get("review_triage_statuses")
    current_rows = _review_statuses(txt)
    newly_transferred = []
    if isinstance(baseline_rows, dict):
        newly_transferred = [
            row_id for row_id, status in current_rows.items()
            if status == "转规格轮次(已确认)"
            and baseline_rows.get(row_id) != "转规格轮次(已确认)"
        ]
    else:
        # 旧状态只有计数快照，保留原有兼容语义。
        baseline = st.get("review_triage_transfer_count")
        transfers = _review_status_count(txt, "转规格轮次(已确认)")
        if isinstance(baseline, int) and transfers > baseline:
            newly_transferred = ["旧状态新增%d条" % (transfers - baseline)]
    if newly_transferred:
        ok, why = ev_agent_ran({"agent": "ASKUSER"}, st)
        if not ok:
            return False, (
                "rf_fix 把以下意见新改成了「转规格轮次(已确认)」: "
                + "、".join(newly_transferred[:8]) + "；"
                "但本步没有真实 AskUserQuestion 用户裁决。修复中改变既有裁决"
                "必须先向用户展示代码证据与行为影响，再由用户确认；" + why)
    if not _review_has_confirmed_fix(txt):
        return True, ""
    return ev_commit_tagged_after_entry(spec, st)


CODE_EXTS = (
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl", ".ipp", ".tpp",
    ".java", ".js", ".jsx", ".cjs", ".mjs",
    ".ts", ".tsx", ".cts", ".mts", ".py", ".pyi",
)
DEFAULT_TEST_PATS = [
    r"(^|/)(tests?|__tests__|spec|[^/]+[_-]tests?)/", r"(^|/)src/test/",
    r"(^|/)test_[^/]+\.py$",
    r"(_test|\.test|\.spec)\.(c|cc|cpp|cxx|h|hh|hpp|hxx|inl|ipp|tpp|py|go|rs|js|jsx|cjs|mjs|ts|tsx|cts|mts)$",
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
    out = argv_out([
        "git", "-c", "core.quotepath=false", "diff", "--name-only", diff])
    files = [f for f in out.splitlines()
             if f and f.lower().endswith(CODE_EXTS) and os.path.exists(f) and not _is_test_file(f, st)]
    return files, ""


# 覆盖口径(用户拍板):CodeCheck/UT 针对本次修改的函数,不背整个文件的存量债。
# "函数"用变更行±SLACK 窗口近似——函数级规则(超长/圈复杂度)的告警常报在
# 签名行,窗口外扩把"改动所在函数"的这类告警兜进来;纯存量行的告警滤除。
CODECHECK_LINE_SLACK = 3


def _diff_output(diff, files, cached=False):
    args = [
        "git", "-c", "core.quotepath=false",
        "diff", "-U0", "--no-renames",
    ]
    if cached:
        args.append("--cached")
    if diff:
        args.append(diff)
    args += ["--", *files]
    return argv_out(args)


def _diff_header_path(line):
    value = line[4:].strip()
    if value == "/dev/null":
        return ""
    if value.startswith("b/"):
        value = value[2:]
    return _decode_diff_path(value)


def _decode_diff_path(value):
    if not value.startswith('"') or not value.endswith('"'):
        return norm(value)
    try:
        return norm(bytes(
            value[1:-1], "utf-8").decode("unicode_escape"))
    except UnicodeError:
        return ""


def _diff_hunk_range(line):
    match = re.match(
        r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
    if not match:
        return set()
    start = int(match.group(1))
    count = int(
        match.group(2) if match.group(2) is not None else "1")
    return set(range(start, start + max(count, 1)))


def _record_changed_hunk(result, current, line):
    if current not in result or not line.startswith("@@ "):
        return
    result[current].update(_diff_hunk_range(line))


def _changed_lines_for_diff(diff, files, cached=False):
    """批量解析指定 Git diff 的 + 侧变更行，删除 hunk 锚定相邻行。"""
    result = {norm(path): set() for path in files}
    current = ""
    for line in _diff_output(diff, files, cached).splitlines():
        if line.startswith("+++ "):
            current = _diff_header_path(line)
            continue
        _record_changed_hunk(result, current, line)
    return result


def _changed_lines(st, files):
    """本单每文件的变更行集合(+侧,git diff -U0 解析)——范围过滤的唯一数据源。
    返回 ({norm(file): set(行号)}, err)。"""
    diff, err = _scope_diff(st)
    if err:
        return None, err
    return _changed_lines_for_diff(diff, files), ""


LIGHTCHECK_REPORT_PATH = os.path.join(
    ".mae-flow-work", "lightcheck", "latest.md")


def _lightcheck_tool_error(reason):
    return {
        "status": "TOOL_ERROR", "findings": [], "existing_debt": [],
        "skipped": [reason], "files": [], "functions_checked": 0,
        "duration_ms": 0,
    }


def _diff_baseline_commit(diff):
    """Resolve the left snapshot used to decide whether a warning is new."""
    if "..." in diff:
        left, right = diff.split("...", 1)
        return argv_out(["git", "merge-base", left, right or "HEAD"])
    if ".." in diff:
        return diff.split("..", 1)[0]
    return diff or "HEAD"


def _diff_current_commit(diff):
    if "..." in diff:
        return diff.split("...", 1)[1] or "HEAD"
    if ".." in diff:
        return diff.split("..", 1)[1] or "HEAD"
    return ""


def _git_object_spec(commit, path):
    return (":" + norm(path)
            if commit == ":"
            else "%s:%s" % (commit, norm(path)))


def _git_source_at(commit, path):
    if not commit:
        return None
    try:
        run = subprocess.run(
            ["git", "show", _git_object_spec(commit, path)],
            shell=False, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return run.stdout if run.returncode == 0 else None


def _cat_file_blob_size(header):
    if not header:
        return None
    if header.endswith(b" missing"):
        return None
    parts = header.rsplit(b" ", 2)
    if len(parts) != 3:
        return None
    if parts[-2] != b"blob":
        return None
    return _safe_int_bytes(parts[-1])


def _safe_int_bytes(value):
    try:
        return int(value)
    except ValueError:
        return None


def _read_cat_file_blob(stream):
    size = _cat_file_blob_size(stream.readline().rstrip(b"\n"))
    if size is None:
        return None
    source = stream.read(size).decode("utf-8", errors="replace")
    stream.read(1)
    return source


def _parse_cat_file_output(raw, files):
    stream = BytesIO(raw)
    return {
        path: _read_cat_file_blob(stream)
        for path in files
    }


def _fallback_git_sources(commit, paths):
    return {
        path: _git_source_at(commit, path)
        for path in paths
    }


def _cat_file_batch(commit, paths):
    payload = "".join(
        _git_object_spec(commit, path) + "\n" for path in paths).encode()
    try:
        run = subprocess.run(
            ["git", "cat-file", "--batch"], input=payload,
            capture_output=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return run.stdout if run.returncode == 0 else None


def _unsafe_batch_paths(paths):
    return any(
        "\n" in path or "\r" in path
        for path in paths)


def _batch_or_fallback_sources(commit, paths):
    if _unsafe_batch_paths(paths):
        return _fallback_git_sources(commit, paths)
    raw = _cat_file_batch(commit, paths)
    if raw is None:
        return _fallback_git_sources(commit, paths)
    return _parse_cat_file_output(raw, paths)


def _git_sources_at(commit, files):
    paths = list(dict.fromkeys(norm(path) for path in files))
    if not commit:
        return {path: None for path in paths}
    if not paths:
        return {}
    return _batch_or_fallback_sources(commit, paths)


def _save_lightcheck_result(result, scope):
    try:
        atomic_write_text(
            LIGHTCHECK_REPORT_PATH, render_markdown(result, scope))
        return norm(os.path.abspath(LIGHTCHECK_REPORT_PATH))
    except Exception as exc:
        # 前置检查的日志失败同样不能变成另一堵门。
        result.setdefault("skipped", []).append("报告写入失败: " + str(exc))
        return ""


def _lightcheck_code_files(files, require_worktree=True):
    return [
        norm(path) for path in files
        if norm(path).lower().endswith(CODE_EXTS)
        if not require_worktree or os.path.isfile(path)
    ]


def _lightcheck_diff_sources(diff, code_files):
    current_commit = _diff_current_commit(diff)
    if not current_commit:
        return None
    return _git_sources_at(current_commit, code_files)


def _available_snapshot_files(code_files, current_sources):
    if current_sources is None:
        return code_files
    return [
        path for path in code_files
        if current_sources.get(path) is not None
    ]


def _run_lightcheck_analysis(
        code_files, changed, baseline_sources, current_sources):
    return analyze_changed_with_timeout(
        os.getcwd(), code_files, changed,
        baseline_sources=baseline_sources,
        options={"current_sources": current_sources})


def _run_lightcheck_diff(diff, files, scope):
    code_files = _lightcheck_code_files(files, require_worktree=False)
    baseline = _diff_baseline_commit(diff)
    if code_files and not baseline:
        result = _lightcheck_tool_error(
            "无法解析检查基线，已自动放行")
        result["report_path"] = _save_lightcheck_result(result, scope)
        return result
    changed = _changed_lines_for_diff(diff, code_files)
    current_sources = _lightcheck_diff_sources(diff, code_files)
    code_files = _available_snapshot_files(code_files, current_sources)
    result = _run_lightcheck_analysis(
        code_files, changed, _git_sources_at(baseline, code_files),
        current_sources)
    result["report_path"] = _save_lightcheck_result(result, scope)
    return result


def _working_code_files(st, candidates=None):
    # 启动前未变化的用户现场必须排除；其余当前代码差异均可只读检查，
    # 这样 Edit/Write 与 Agent 经 Bash 实际改写两条路径都不会漏。
    if candidates is None:
        dirty = _blocking_dirty_source_paths(st, FLOW) if st else _dirty_paths()
    else:
        dirty = [
            path for path in candidates
            if not _unchanged_initial_dirty(path, st)
        ]
    return _lightcheck_code_files(dirty)


def _untracked_changed_lines(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as stream:
            count = len(stream.read().splitlines())
    except OSError:
        count = 0
    return set(range(1, count + 1))


def _working_lightcheck_inputs(files):
    tracked = set(argv_out([
        "git", "-c", "core.quotepath=false",
        "ls-files", "--", *files,
    ]).splitlines())
    tracked = {norm(path) for path in tracked}
    changed = _changed_lines_for_diff(
        "HEAD", [path for path in files if path in tracked])
    sources = _git_sources_at("HEAD", tracked)
    _add_untracked_lightcheck_inputs(
        files, tracked, changed, sources)
    return changed, sources


def _add_untracked_lightcheck_inputs(
        files, tracked, changed, sources):
    for path in files:
        if path not in tracked:
            changed[path] = _untracked_changed_lines(path)
            sources[path] = None


def _working_lightcheck_scope(st, candidates=None):
    """Inspect current-flow code dirt while preserving unchanged user dirt."""
    dirty = _working_code_files(st, candidates)
    changed, sources = _working_lightcheck_inputs(dirty)
    result = analyze_changed_with_timeout(
        os.getcwd(), dirty, changed, baseline_sources=sources)
    scope = ("提交前：本次提交候选代码"
             if candidates is not None
             else "提交前：本轮当前代码差异（排除未变化的启动前脏文件）")
    result["report_path"] = _save_lightcheck_result(
        result, scope)
    return result


def _read_worktree_sources(files):
    result = {}
    for path in files:
        try:
            with open(path, encoding="utf-8", errors="replace") as stream:
                result[path] = stream.read()
        except OSError:
            result[path] = None
    return result


def _eligible_pending_paths(st, snapshot):
    return [
        path for path in snapshot["paths"]
        if not _unchanged_initial_dirty(path, st)
    ]


def _partition_snapshot_files(code_files, working_paths):
    working, indexed = [], []
    for path in code_files:
        target = working if path in working_paths else indexed
        target.append(path)
    return working, indexed


def _pending_lightcheck_groups(st, snapshot):
    candidates = _eligible_pending_paths(st, snapshot)
    code_files = _lightcheck_code_files(
        candidates, require_worktree=False)
    working, indexed = _partition_snapshot_files(
        code_files, snapshot["working_paths"])
    return code_files, working, indexed


def _pending_lightcheck_inputs(working, indexed):
    changed = _changed_lines_for_diff("HEAD", working)
    changed.update(_changed_lines_for_diff(
        "HEAD", indexed, cached=True))
    current_sources = _git_sources_at(":", indexed)
    current_sources.update(_read_worktree_sources(working))
    return changed, current_sources


def _pending_lightcheck_scope(st, snapshot):
    code_files, working, indexed = _pending_lightcheck_groups(
        st, snapshot)
    changed, current_sources = _pending_lightcheck_inputs(
        working, indexed)
    code_files = _available_snapshot_files(
        code_files, current_sources)
    result = _run_lightcheck_analysis(
        code_files, changed, _git_sources_at("HEAD", code_files),
        current_sources)
    result["report_path"] = _save_lightcheck_result(
        result, "提交前：本次提交候选快照")
    return result


def _print_lightcheck_findings(findings, report):
    print("[mae-flow] ⚠ 轻量编码预检发现 %d 个本轮新触发问题（建议修复，不阻断）:"
          % len(findings), file=sys.stderr)
    for item in findings[:12]:
        function = (" " + item["function"]) if item.get("function") else ""
        print("  %s %s:%s%s — %s (%s > %s)" % (
            item["rule"], item["file"], item["line"], function,
            item["message"], item["actual"], item["limit"]),
            file=sys.stderr)
    if len(findings) > 12:
        print("  …其余 %d 项见报告" % (len(findings) - 12), file=sys.stderr)
    if report:
        print("  人类可读报告: " + report, file=sys.stderr)
    print("  请按项目 formatter/附近同类代码修正后再提交；"
          "最多修复并复查两轮，仍不确定则留给正式 CodeCheck，禁止扩大范围。",
          file=sys.stderr)


def _print_lightcheck_degraded(result, report):
    print("[mae-flow] 轻量编码预检 %s（建议层已自动放行，不替代正式 CodeCheck）"
          % result.get("status", "SKIPPED"))
    for reason in (result.get("skipped") or [])[:5]:
        print("  - " + reason)
    if report:
        print("[mae-flow] 报告: " + report)


def _print_lightcheck_empty(result, report):
    if result.get("status") != "CLEAN":
        _print_lightcheck_degraded(result, report)
        return
    print("[mae-flow] 轻量编码预检 CLEAN（建议项，不替代正式 CodeCheck）")
    if report:
        print("[mae-flow] 报告: " + report)


def _print_lightcheck_result(result, quiet=False):
    findings = result.get("findings", [])
    report = result.get("report_path", "")
    if findings:
        _print_lightcheck_findings(findings, report)
        return
    if not quiet:
        _print_lightcheck_empty(result, report)


def cmd_lightcheck(st, args):
    try:
        result = _working_lightcheck_scope(st or {})
    except Exception as exc:
        # 此命令的合同就是 fail-open；即使适配层自身有 bug 也只报告。
        result = _lightcheck_tool_error(
            "轻量检查异常: " + str(exc))
        result["report_path"] = _save_lightcheck_result(
            result, "提交前：异常安全降级")
    _print_lightcheck_result(result, quiet=bool(getattr(args, "quiet", False)))
    return 0


def _hunk_targets_for_diff(diff, files):
    """从指定 Git diff 提取函数级定位线索：新增行范围 + hunk 函数上下文。"""
    result = {}
    pattern = re.compile(
        r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@(?:\s*(.*))?$", re.M)
    for path in files:
        out = argv_out([
            "git", "-c", "core.quotepath=false",
            "diff", "-U0", diff, "--", path,
        ])
        targets = []
        for match in pattern.finditer(out):
            start = int(match.group(1))
            count = int(match.group(2) if match.group(2) is not None else "1")
            end = start + max(count, 1) - 1
            context = re.sub(r"\s+", " ", (match.group(3) or "").strip())
            if len(context) > 180:
                context = context[:177] + "..."
            targets.append({
                "start": start, "end": end, "context": context,
                "deletion_only": count == 0,
            })
        result[norm(path)] = targets
    return result


def _changed_hunk_targets(st, files):
    """提取完整流程 UT 的函数级定位线索。"""
    diff, err = _scope_diff(st)
    if err:
        return None, err
    return _hunk_targets_for_diff(diff, files), ""


def _looks_like_function_context(context):
    """只接受明确的方法/函数 hunk，避免把 Java class/namespace 整块当成本次函数。"""
    value = re.sub(r"\s+", " ", str(context or "").strip())
    if not value:
        return False
    if re.search(r"\b(class|struct|interface|enum|namespace|module)\b", value):
        return False
    return bool(
        ("(" in value and ")" in value)
        or re.search(r"\b(def|func|fn)\s+[A-Za-z_$][\w$]*", value)
    )


def _lexical_function_range(path, line_number):
    """Git 无函数驱动时的保守兜底，仅识别常见 Python 与花括号语言函数。"""
    try:
        with open(path, encoding="utf-8", errors="replace") as stream:
            source_lines = stream.read().splitlines()
    except OSError:
        return None
    if not source_lines or line_number < 1 or line_number > len(source_lines):
        return None
    low = path.lower()
    if low.endswith((".py", ".pyi")):
        for index in range(line_number - 1, -1, -1):
            match = re.match(
                r"^(\s*)(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(", source_lines[index])
            if not match:
                continue
            indent = len(match.group(1).replace("\t", "    "))
            end = len(source_lines)
            for cursor in range(index + 1, len(source_lines)):
                raw = source_lines[cursor]
                if not raw.strip():
                    continue
                current_indent = len(raw) - len(raw.lstrip(" \t"))
                if current_indent <= indent and not raw.lstrip().startswith(("#", "@")):
                    end = cursor
                    break
            if index + 1 <= line_number <= end:
                return {
                    "start": index + 1, "end": end,
                    "context": source_lines[index].strip()[:180],
                }
        return None
    if not low.endswith((
            ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx",
            ".java", ".js", ".jsx", ".ts", ".tsx")):
        return None
    control = re.compile(
        r"^(?:if|for|while|switch|catch|else|do|try|synchronized)\b")
    for index in range(line_number - 1, max(-1, line_number - 80), -1):
        header = source_lines[index].strip()
        if not header or control.match(header) or re.search(
                r"\b(class|struct|interface|enum|namespace|module)\b", header):
            continue
        if "(" not in header:
            continue
        joined = " ".join(
            part.strip() for part in source_lines[index:min(len(source_lines), index + 6)])
        before_brace = joined.split("{", 1)[0]
        if "{" not in joined or "(" not in before_brace or ")" not in before_brace:
            continue
        if control.match(before_brace.strip()) or before_brace.rstrip().endswith(";"):
            continue
        depth = 0
        opened = False
        for cursor in range(index, len(source_lines)):
            # 去掉常见字符串和 // 注释后再数括号；无法可靠解析时宁可不返回。
            code = re.sub(
                r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`',
                "", source_lines[cursor]).split("//", 1)[0]
            depth += code.count("{") - code.count("}")
            opened = opened or "{" in code
            if opened and depth == 0:
                end = cursor + 1
                if index + 1 <= line_number <= end:
                    return {
                        "start": index + 1, "end": end,
                        "context": before_brace.strip()[:180],
                    }
                break
            if opened and depth < 0:
                break
    return None


def _changed_function_ranges(st, files):
    """用 Git function-context 识别本次实际改到的函数新文件行范围。

    识别不可靠时返回空范围，调用方仍以变更行窗口 + 用户确认兜底，绝不把整文件
    自动算成本次修改。
    """
    diff, err = _scope_diff(st)
    if err:
        return None, err
    changed, err = _changed_lines(st, files)
    if err or changed is None:
        return None, err or "无法读取变更行"
    pattern = re.compile(
        r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@(?:\s*(.*))?$", re.M)
    result = {}
    for path in files:
        out = argv_out([
            "git", "-c", "core.quotepath=false", "diff",
            "--function-context", "--unified=0", diff, "--", path,
        ])
        ranges = []
        changed_lines = changed.get(norm(path), set())
        for line in sorted(changed_lines):
            fallback = _lexical_function_range(path, line)
            if fallback and not any(
                    item["start"] == fallback["start"] and item["end"] == fallback["end"]
                    for item in ranges):
                ranges.append(fallback)
        for match in pattern.finditer(out):
            start = int(match.group(1))
            count = int(match.group(2) if match.group(2) is not None else "1")
            context = re.sub(r"\s+", " ", (match.group(3) or "").strip())
            if count <= 0 or not _looks_like_function_context(context):
                continue
            end = start + count - 1
            hunk_changes = [
                line for line in changed_lines if start <= line <= end
                and not any(item["start"] <= line <= item["end"] for item in ranges)
            ]
            if not hunk_changes:
                continue
            ranges.append({"start": start, "end": end, "context": context[:180]})
        ranges.sort(key=lambda item: (item["start"], item["end"]))
        result[norm(path)] = ranges
    return result, ""


def _scope_classify_codecheck(result, st, files):
    """把告警预分类为“机器判定相关”和“待用户确认是否涉及”。

    返回 (filtered_result, excluded_pairs_or_None)。None = 无法分类——
    告警明细缺行号(纯计数输出/JSON 无行号)或明细与总数对不上时保守全算,
    宁可多报也不静默漏掉真告警。机器先认变更行±SLACK，再认同一变更函数；
    两者都无法证明的结果不能单方面定性为存量，必须交用户确认。"""
    pairs = result.get("pairs") or []
    if not pairs or result.get("total") != len(pairs) \
            or any(p[2] is None for p in pairs):
        return result, None
    changed, err = _changed_lines(st, files)
    if err or changed is None:
        return result, None
    function_ranges, range_err = _changed_function_ranges(st, files)
    if range_err or function_ranges is None:
        function_ranges = {}
    kept, excluded = [], []
    reasons = []
    for rule, wfile, line in pairs:
        window = changed.get(norm(wfile))
        if window is None:
            # 报告里的路径没还原成清单文件(多义 basename 等):保守保留
            kept.append((rule, wfile, line))
            reasons.append({
                "rule": rule, "file": wfile, "line": line,
                "reason": "报告路径无法映射，保守纳入",
            })
            continue
        if any(abs(line - c) <= CODECHECK_LINE_SLACK for c in window):
            kept.append((rule, wfile, line))
            reasons.append({
                "rule": rule, "file": wfile, "line": line,
                "reason": "命中本次变更行±%d" % CODECHECK_LINE_SLACK,
            })
        elif any(item["start"] <= line <= item["end"]
                 for item in function_ranges.get(norm(wfile), [])):
            target = next(
                item for item in function_ranges.get(norm(wfile), [])
                if item["start"] <= line <= item["end"])
            kept.append((rule, wfile, line))
            reasons.append({
                "rule": rule, "file": wfile, "line": line,
                "reason": "位于本次变更函数 %s（行%d-%d）"
                % (target["context"], target["start"], target["end"]),
            })
        else:
            excluded.append((rule, wfile, line))
    return {
        "total": len(kept), "pairs": kept,
        "commands": result.get("commands", []),
        "log_path": result.get("log_path", ""),
        "scope_reasons": reasons,
    }, excluded


def _scope_filter_codecheck(result, st, files):
    """旧调用口径兼容：返回过滤结果与窗口外数量。

    codecheck-scan 使用 _scope_classify_codecheck 保留逐条候选并要求用户确认；
    旧的现场复核只需要数量对账，继续走这个薄包装。
    """
    filtered, excluded = _scope_classify_codecheck(result, st, files)
    return filtered, (len(excluded) if excluded is not None else None)


def _render_warning_pairs(pairs):
    """任务卡里的告警清单渲染:规则|文件[|行号](旧状态里的二元组也兼容)。"""
    out = []
    for p in pairs:
        rule, file_name = p[0], p[1]
        line = p[2] if len(p) > 2 else None
        out.append("|".join([rule, file_name] + ([str(line)] if line is not None else [])))
    return "、".join(out)


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
    program = executable or "codecheck"
    base_argv = [program, "fullcheck", "-f", ",".join(batch)]
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


def _run_codecheck(files, st=None, phase="scan"):
    """执行 CodeCheck 并返回机器结果；scan、done 复核共用，避免两套解析口径漂移。"""
    log_state = st if isinstance(st, dict) else {}
    head = sh("git rev-parse --verify HEAD")
    log_path = append_codecheck_event(
        os.getcwd(), log_state, "run.started", {
            "phase": phase, "cwd": os.path.abspath(os.getcwd()),
            "head": head, "files": list(files), "file_count": len(files),
        })
    capability = ensure_codecheck(install=True)
    append_codecheck_event(
        os.getcwd(), log_state, "capability.checked", {
            "phase": phase,
            "available": bool(capability.get("available")),
            "path": capability.get("path", ""),
            "detail": capability.get("detail", ""),
            "installed": capability.get("installed"),
        })
    if not capability.get("available"):
        detail = str(capability.get("detail", "")).strip()[-1200:]
        append_codecheck_event(
            os.getcwd(), log_state, "run.failed", {
                "phase": phase, "kind": "capability-unavailable",
                "detail": detail,
            })
        return None, (
            "CodeCheck CLI 当前不可用。Mae-Flow 已按公司内网源尽力自动安装，但没有成功；"
            "这不会触发重复安装或派修复 Agent。"
            + (" 诊断: " + detail if detail else "")
            + "。普通模式请向用户展示风险后使用错误信息给出的恢复通道；"
            "月光宝盒模式记录为未完成质量项后继续。")
    executable = capability.get("path") or None
    # Windows 路走 shell=True:文件名里的 & ^ % 是 cmd 命令语义(a&b.c 会把 b 当命令跑),
    # 逗号会破坏 -f 的批次列表。这类文件名先拒绝,比"静默检错文件"或注入安全得多。
    risky = [f for f in files if re.search(r"[&|^%<>;,]", f)]
    if risky:
        append_codecheck_event(
            os.getcwd(), log_state, "run.failed", {
                "phase": phase, "kind": "unsafe-file-name", "files": risky,
            })
        return None, (
            "以下文件名含 cmd 元字符或逗号,无法安全传入 codecheck -f: "
            + "、".join(risky[:5])
            + "。请重命名文件或将其移出本次检查范围后重试。")
    total, pairs, commands = 0, [], []
    batches = _batches(files)
    for batch_index, batch in enumerate(batches, 1):
        launch, use_shell, cmd = _codecheck_launch(batch, executable=executable)
        commands.append(cmd)
        started = time.time()
        append_codecheck_event(
            os.getcwd(), log_state, "command.started", {
                "phase": phase, "batch": batch_index,
                "batch_count": len(batches), "files": batch,
                "command": cmd, "launch": launch,
                "shell": use_shell, "executable": executable or "",
            })
        try:
            r = subprocess.run(launch, shell=use_shell, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=900)
        except subprocess.TimeoutExpired as exc:
            append_codecheck_event(
                os.getcwd(), log_state, "command.failed", {
                    "phase": phase, "batch": batch_index,
                    "command": cmd, "kind": "timeout",
                    "timeout_seconds": 900,
                    "stdout": save_codecheck_artifact(
                        os.getcwd(), log_state,
                        "batch-%d-timeout-stdout" % batch_index,
                        getattr(exc, "stdout", "") or ""),
                    "stderr": save_codecheck_artifact(
                        os.getcwd(), log_state,
                        "batch-%d-timeout-stderr" % batch_index,
                        getattr(exc, "stderr", "") or ""),
                })
            return None, "codecheck 现场检查超时(>15min)——批次过大或服务异常"
        except OSError as e:
            append_codecheck_event(
                os.getcwd(), log_state, "command.failed", {
                    "phase": phase, "batch": batch_index,
                    "command": cmd, "kind": "launch-error",
                    "error": str(e),
                })
            return None, "codecheck CLI 无法启动: " + str(e)
        stdout, stderr = r.stdout or "", r.stderr or ""
        out = stdout + stderr
        stdout_artifact = save_codecheck_artifact(
            os.getcwd(), log_state,
            "batch-%d-stdout" % batch_index, stdout)
        stderr_artifact = save_codecheck_artifact(
            os.getcwd(), log_state,
            "batch-%d-stderr" % batch_index, stderr)
        rp = re.search(r"检查报告已保存到:\s*(.+)", out)
        rtxt = out
        report_path = ""
        if rp:
            report_path = rp.group(1).strip()
            try:
                with open(report_path, encoding="utf-8", errors="replace") as stream:
                    rtxt = stream.read()
            except OSError:
                pass
        report_artifact = (
            save_codecheck_artifact(
                os.getcwd(), log_state,
                "batch-%d-report" % batch_index, rtxt, ".md")
            if rtxt != out else None)
        count = _parse_codecheck_count(out, rtxt)
        json_pairs = []
        parsed_from = "console-or-report" if count is not None else ""
        parsed_json_path = ""
        parsed_json_artifact = None
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
                        parsed_from = "json"
                        parsed_json_path = os.path.abspath(jp)
                        try:
                            with open(jp, encoding="utf-8",
                                      errors="replace") as stream:
                                parsed_json_artifact = save_codecheck_artifact(
                                    os.getcwd(), log_state,
                                    "batch-%d-result-json" % batch_index,
                                    stream.read(), ".json")
                        except OSError:
                            pass
                        break
                except OSError:
                    continue
        append_codecheck_event(
            os.getcwd(), log_state, "command.completed", {
                "phase": phase, "batch": batch_index,
                "batch_count": len(batches), "command": cmd,
                "return_code": r.returncode,
                "duration_ms": int((time.time() - started) * 1000),
                "parsed_count": count, "parsed_from": parsed_from,
                "reported_path": report_path,
                "parsed_json_path": parsed_json_path,
                "parsed_json": parsed_json_artifact,
                "stdout": stdout_artifact, "stderr": stderr_artifact,
                "report": report_artifact,
            })
        if count is None:
            d = os.path.join(".mae-flow-work", "codecheck-diagnostics")
            os.makedirs(d, exist_ok=True)
            snap = os.path.join(d, time.strftime("%Y%m%d-%H%M%S") + ".txt")
            with open(snap, "w", encoding="utf-8") as f:
                f.write("COMMAND: " + cmd + "\nRETURN_CODE: " + str(r.returncode) + "\n\n" + out)
                if rtxt != out:
                    f.write("\n\n===== REPORT =====\n" + rtxt)
            append_codecheck_event(
                os.getcwd(), log_state, "run.failed", {
                    "phase": phase, "kind": "unparsed-output",
                    "batch": batch_index, "command": cmd,
                    "diagnostic": os.path.abspath(snap),
                })
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
        lns = re.findall(r"- \*\*(?:行号|位置|行)\*\*:\s*`?(\d+)", rtxt)
        if json_pairs:
            raw_pairs = json_pairs
        elif lns and len(lns) == len(rs) == len(fs):
            raw_pairs = [(r, f, int(ln)) for (r, f), ln in zip(zip(rs, fs), lns)]
        else:
            raw_pairs = [(r, f, None) for r, f in zip(rs, fs)]
        for rule, file_name, line in raw_pairs:
            matches = [x for x in batch if norm(x).lower() == norm(file_name).lower()
                       or os.path.basename(x).lower() == os.path.basename(file_name).lower()]
            pairs.append((rule, matches[0] if len(matches) == 1 else norm(file_name),
                          line))
    append_codecheck_event(
        os.getcwd(), log_state, "run.completed", {
            "phase": phase, "head": head, "total": total,
            "pairs": pairs, "commands": commands,
            "log_path": log_path or codecheck_log_path(os.getcwd(), log_state),
        })
    return {
        "total": total, "pairs": pairs, "commands": commands,
        "log_path": log_path or codecheck_log_path(os.getcwd(), log_state),
    }, ""


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
                # 行号:覆盖口径过滤(本次修改的函数)的依据;键名按已见格式宽兜底,
                # 取不到记 None(过滤层对 None 保守保留)。
                line = None
                for lk in ("line", "lineno", "linenumber", "startline",
                           "beginline", "linenum"):
                    try:
                        if low.get(lk) is not None:
                            line = int(low[lk])
                            break
                    except (TypeError, ValueError):
                        continue
                rows.append((str(uid), str(rule).split()[0],
                             norm(str(file_name)), line))
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(data)
    uniq = {}
    for uid, rule, file_name, line in rows:
        uniq[uid] = (rule, file_name, line)
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
        append_codecheck_event(
            os.getcwd(), st, "verify.empty", {
                "head": sh("git rev-parse --verify HEAD"),
                "reason": "no-business-code-files",
            })
        return True, ""
    # 校准实锤:零告警正常路上 fullcheck 必然跑两遍(scan 一遍+done 复核一遍,
    # 每次 done 重试再+1)。scan 是 harness 亲跑的真实动作、记录绑 HEAD+文件清单
    # 存于 gate 保护的状态文件——与 codecheck-record 同一信任模型。命中缓存
    # (同步骤∧首检 0 条∧文件清单一致∧源码零变化)直接判过,把 scan 已算出的
    # 结论真正用起来;agent 修复路径(scan.count>0)保持全量重跑,哲学不动。
    scan = (st.get("quality", {}) or {}).get("codecheck_scan", {})
    if (scan.get("step") == st.get("current") and scan.get("count") == 0
            and not scan.get("manual")
            and scan.get("files") == files and scan.get("head")):
        changed, cerr = _source_changed_since(scan.get("head"), st)
        if not cerr and not changed:
            append_codecheck_event(
                os.getcwd(), st, "verify.cache_reused", {
                    "kind": "clean-scan", "head": scan.get("head", ""),
                    "files": files, "count": 0,
                })
            return True, ""
    ex = "docs/codecheck-exempt-" + st["config"].get("单号", "") + ".md"
    # 豁免文件未提交是纯本地廉价事实，先报再跑昂贵 CLI；提交后复用下面绑定
    # HEAD+文件清单的复核缓存，不会因为一个台账问题反复 fullcheck。
    if os.path.exists(ex):
        dirty = argv_out(["git", "status", "--porcelain", "--", ex])
        if dirty:
            return False, f"豁免记录 {ex} 尚未提交；本地文件不能替远端 MR 背书，请精确提交后重试"

    verified = (st.get("quality", {}) or {}).get("codecheck_verify", {})
    use_verified = False
    if (verified.get("step") == st.get("current")
            and verified.get("files") == files and verified.get("head")):
        changed, verr = _source_changed_since(verified.get("head"), st)
        use_verified = not verr and not changed
    if use_verified:
        total = int(verified.get("count", 0))
        pairs = verified.get("pairs", []) or []
        append_codecheck_event(
            os.getcwd(), st, "verify.cache_reused", {
                "kind": "verification", "head": verified.get("head", ""),
                "files": files, "count": total, "pairs": pairs,
            })
    else:
        result, err = _run_codecheck(files, st, "harness-verify")
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
        # 与 codecheck-scan 同源同口径:复核也只数本次修改范围内的告警
        result, _stock = _scope_filter_codecheck(result, st, files)
        total, pairs = result["total"], result["pairs"]
        st.setdefault("quality", {})["codecheck_verify"] = {
            "step": st.get("current"), "head": sh("git rev-parse --verify HEAD"),
            "files": files, "count": total, "pairs": pairs,
            "log_path": result.get("log_path", ""),
            "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        append_codecheck_event(
            os.getcwd(), st, "verify.completed", {
                "head": st["quality"]["codecheck_verify"]["head"],
                "files": files, "count": total, "pairs": pairs,
            })
    if total == 0:
        return True, ""
    if not os.path.exists(ex):
        return False, (f"harness 现场复核实测遗留 {total} 条告警,且无豁免清单({ex})。"
                       "两条路:修掉重试;或经用户逐条裁决豁免(AskUserQuestion),把「规则ID + 文件 + 用户原话」"
                       f"逐行写入 {ex} 并 commit 后重试——口头豁免无效")
    extxt = open(ex, encoding="utf-8", errors="replace").read()
    bad = [f"{r}({f})" for r, f, _ln in pairs if not _exemption_text_has_pair(extxt, r, f)]
    if len(pairs) < total and bad == []:
        bad = [f"(另有 {total - len(pairs)} 条未解析出明细,无法核对豁免)"]
    if bad:
        return False, (f"实测遗留 {total} 条告警,以下未被豁免清单覆盖: " + "、".join(bad[:5])
                       + ("…" if len(bad) > 5 else "") + f"。修掉或补齐 {ex}(须用户裁决原话)后重试")
    approved = _approved_exemptions(st)
    unauthorized = [f"{r}({f})" for r, f, _ln in pairs
                    if _approval_key(r, f) not in approved and not _was_exempt_before_review(st, ex, r, f)]
    if unauthorized:
        return False, ("豁免文件覆盖了告警,但以下本轮豁免没有用户审批令牌: " + "、".join(unauthorized[:5])
                       + "。逐项 AskUserQuestion 后执行 mae-flow approve-exemption --rule <规则ID> "
                       "--file <文件> --reason <理由> --ack \"用户原话\"；手写豁免文件不再算授权")
    return True, ""


def ev_review_codecheck(spec, st):
    """统一规范检查协议：真实尝试一次；结果透明，但工具自身不成为硬阻塞源。"""
    scan = (st.get("quality", {}) or {}).get("codecheck_scan", {})
    files, err = _biz_changed_files(st)
    if err and scan.get("step") != st.get("current"):
        return False, err
    if files == []:
        # 文档、台账、测试和纯构建配置都不属于 CodeCheck 的业务代码输入。
        # 在证据层直接放行，避免弱模型仍照步骤说明生成一次空扫描。
        return True, ""
    accepted, _ = _risk_acceptance("CODECHECK_TOOL", st)
    if accepted:
        # CodeCheck is the one optional company CLI. A real user may explicitly
        # accept its absence after seeing the risk; otherwise an internal npm or
        # PATH outage would dead-lock the whole delivery.
        return True, ""
    if scan.get("step") != st.get("current"):
        return False, "尚未执行本步的机器首检。先运行 mae-flow codecheck-scan，禁止主会话自行修复"
    if scan.get("scope_pending"):
        return False, (
            "CodeCheck 仍有 %d 条机器准备排除的候选，尚未经用户确认是否涉及本次修改。"
            "按 codecheck-scan 输出使用 AskUserQuestion 展示候选，再执行 codecheck-scope；"
            "确认前不能忽略这些结果。"
            % len(scan.get("scope_candidates") or []))
    if scan.get("status") == "TOOL_ERROR":
        changed, err = _source_changed_since(scan.get("head", ""), st)
        if err:
            return False, "CodeCheck 诊断基点失效:" + err + "；重新执行 codecheck-scan"
        if changed:
            return False, ("CodeCheck 工具诊断后源码发生变化: " + "、".join(changed[:5])
                           + "。对新代码重新尝试一次 codecheck-scan")
        return True, ""
    if scan.get("count", 0) == 0:
        changed, err = _source_changed_since(scan.get("head", ""), st)
        if err:
            return False, "CodeCheck 首检基点失效:" + err + "；重新执行 codecheck-scan"
        if changed:
            return False, ("CodeCheck 首检为 0 后源码又发生变化: " + "、".join(changed[:5])
                           + "。旧首检不背新代码的书,重新执行 codecheck-scan")
    else:
        ok, why = ev_agent_ran(
            {"agent": "CODECHECK", "statuses": ["CLEAN", "REMAINING", "FAIL"]}, st)
        if not ok:
            return False, why
        try:
            token = json.load(open(
                STATE_PATH + ".tokens", encoding="utf-8")).get("CODECHECK", {})
        except Exception:
            token = {}
        if isinstance(token, dict) and token.get("status") == "FAIL":
            task = (st.get("agent_tasks", {}) or {}).get("CODECHECK", {})
            changed, err = _source_changed_since(task.get("head", ""), st)
            if err:
                return False, "CodeCheck FAIL 后无法核对源码状态:" + err
            if changed:
                return False, ("CodeCheck Agent 以 FAIL 收尾但留下了源码变化: "
                               + "、".join(changed[:5])
                               + "。先回退未验证改动，或完成编译并以 REMAINING/CLEAN 收尾。")
        # Agent 的最后一轮 fullcheck 已由 SubagentStop 绑定任务卡、源码和真实调用。
        # 不在 done 再跑第三遍；REMAINING/工具 FAIL 作为建议项进入交付报告。
        return True, ""
    return True, ""


def run_env_checks(force_all=False):
    """Compatibility view of self-contained runtime diagnostics."""
    checks = capability_diagnostics(os.getcwd(), include_codecheck=False)
    return [item["name"] for item in checks if not item["ok"]]


EVIDENCE = {"glob": ev_glob, "branch_ok": ev_branch_ok,
            "tasks_checked": ev_tasks_checked, "commit_tagged": ev_commit_tagged,
            "commit_tagged_after_entry": ev_commit_tagged_after_entry,
            "review_fix_committed": ev_review_fix_committed,
            "review_snapshot": ev_review_snapshot,
            "checkpoint_plan": ev_checkpoint_plan,
            "checkpoint_plan_complete": ev_checkpoint_plan_complete,
            "final_review_clear": ev_final_review_clear,
            "spec_field": ev_spec_field, "yaml_field": ev_spec_field,
            "spec_validate": ev_spec_validate, "tier_scope": ev_tier_scope,
            "pushed": ev_pushed, "agent_ran": ev_agent_ran,
            "content_free": ev_content_free, "clean_paths": ev_clean_paths,
            "archive_paths_clean": ev_archive_paths_clean,
            "codecheck_clean": ev_codecheck_clean, "glob_absent": ev_glob_absent,
            "review_agent_or_no_code": ev_review_agent_or_no_code,
            "agent_or_no_source": ev_agent_or_no_source,
            "review_codecheck": ev_review_codecheck}


def _evidence_failure_count(sid, success=False):
    """按步骤统计 done 证据连拒次数;成功推进即清零。与 _ack_failure 同一存储。"""
    key = "evidence:" + (sid or "")
    result = [0]

    def mutate(data):
        if not isinstance(data, dict):
            data = {}
        if success:
            data.pop(key, None)
            return data
        result[0] = int((data.get(key, {}) or {}).get("count", 0)) + 1
        data[key] = {"count": result[0],
                     "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        return data

    try:
        update_json(FAILURE_PATH, mutate, default={}, recover_corrupt=True)
    except Exception:
        return 1 if not success else 0
    return result[0]


def _ack_failure(st, reason="", success=False):
    """记录确认通道失败；只停止盲目重试，不制造不可恢复的锁。"""
    sid = (st or {}).get("current", "")
    key = "ack:" + sid
    result = [0]

    def mutate(data):
        if not isinstance(data, dict):
            data = {}
        if success:
            data.pop(key, None)
            return data
        previous = data.get(key, {})
        result[0] = int(previous.get("count", 0)) + 1
        data[key] = {
            "count": result[0],
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "reason": reason[:1000],
        }
        return data

    update_json(
        FAILURE_PATH, mutate, default={}, recover_corrupt=True)
    return result[0]


def _ack_candidates(text):
    """Extract exact user answers without treating prompt/options metadata as consent."""
    out = [text or ""]
    try:
        value = json.loads(text)
        answer_keys = {
            "answer", "answers", "response", "responses", "selected",
            "selection", "selectedoption", "selectedoptions", "result",
        }

        def walk(v, trusted=False):
            if isinstance(v, str) and trusted:
                out.append(v)
            elif isinstance(v, dict):
                for key, item in v.items():
                    normalized_key = re.sub(r"[^a-z]", "", str(key).lower())
                    walk(item, trusted or normalized_key in answer_keys)
            elif isinstance(v, list):
                for item in v:
                    walk(item, trusted)

        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, list):
            walk(value, trusted=True)
        else:
            walk(value)
    except Exception:
        pass
    return [re.sub(r"\s+", "", v) for v in out if re.sub(r"\s+", "", v)]


def _trusted_answer_candidates(text):
    """Return actual answer values, excluding question/option metadata."""
    candidates = _ack_candidates(text)
    try:
        parsed = json.loads(text)
    except Exception:
        return candidates
    if isinstance(parsed, str):
        return [re.sub(r"\s+", "", parsed)] if parsed.strip() else []
    raw = re.sub(r"\s+", "", text or "")
    return [value for value in candidates if value != raw]


def _all_ack_messages():
    try:
        msgs = json.loads(open(STATE_PATH + ".usermsg", encoding="utf-8").read() or "[]")
    except Exception:
        return []
    return msgs if isinstance(msgs, list) else []


def _ack_message_signature(item):
    payload = json.dumps({
        "id": item.get("id", ""),
        "step": item.get("step", ""),
        "at": item.get("at", ""),
        "text": item.get("text", ""),
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _ack_message_cursor():
    return [_ack_message_signature(item) for item in _all_ack_messages()]


def _current_ack_messages(st, extra_steps=()):
    msgs = _all_ack_messages()
    sid = st.get("current", "")
    entered = _step_entered_at(st)
    started = st.get("started", "")
    out = []
    for item in msgs:
        if (item.get("at", "") >= entered
                and (not item.get("step") or item.get("step") == sid)):
            out.append(item)
        elif (extra_steps and item.get("step") in extra_steps
              and item.get("at", "") >= started):
            # 一卡合一预答通道:配置确认卡合并收集的选择(交付方式/质询/STORY),
            # 供随后的选择步直接消费,免逐步重复提问;仍是本单内真实捕获的用户答案。
            out.append(item)
    return out


def _out_of_scope_ack_reason(st):
    """Explain captured-but-stale answers without blaming the Hook."""
    rows = _all_ack_messages()
    if not rows:
        return ""
    sid = st.get("current", "")
    entered = _step_entered_at(st)
    latest = rows[-1]
    old_step = str(latest.get("step", "") or "(未标步骤)")
    old_at = str(latest.get("at", "") or "?")
    if old_step != sid:
        return (
            "Hook 已捕获用户回复，但最新一条绑定在步骤 %s；当前已是 %s。"
            "步骤切换后旧回答按设计失效，不能再次授权新的 done/goto；"
            "请展示当前步骤需要的决定并取得一次新回复（旧回复时间 %s）。"
            % (old_step, sid, old_at)
        )
    if old_at < entered:
        return (
            "Hook 已捕获用户回复，但它早于当前步骤这一轮的进入时间 %s；"
            "旧轮回答按设计失效，不能为重进后的新一轮背书。"
            "请展示当前步骤需要的决定并取得一次新回复。"
            % entered
        )
    return (
        "Hook 已捕获用户回复，但其结构中没有当前命令可验真的答案字段。"
        "先执行 messages --full 查看原始回传；若按钮正文确实缺失，"
        "让用户发送当前页面要求的普通确认消息。"
    )


def _fresh_askuser(st):
    ok, _ = ev_agent_ran({"agent": "ASKUSER"}, st)
    return ok


def _is_positive_confirmation(value):
    compact = re.sub(r"[\s，。；;：:、!！]+", "", value or "")
    compact = re.sub(r"[（(]推荐[）)]", "", compact)
    if not compact or re.search(
            r"不确认|不同意|不是|不要|不能|没有|没法|拒绝|暂不|取消|"
            r"需要修改|需要调整|先别|等等|不对|有误|有问题|但是|不过|"
            r"什么意思|怎么|是否|能否|为什么|[?？]",
            compact, re.I):
        return False
    return (
        compact.lower() in {
            "确认", "确认并继续", "确认范围并继续", "确认定稿",
            "同意", "可以", "没问题", "继续", "按此执行", "以上正确",
            "无异议", "yes", "y", "ok",
        }
        or bool(re.match(
            r"^(?:确认|同意|可以|没问题|继续|按此|无异议)", compact, re.I))
    )


def _implicit_ack_verified(step, st):
    """Use a fresh button/plain-text answer directly; no second typed ACK."""
    expected = {
        re.sub(r"[\s，。；;：:、!！]+", "", str(value))
        for value in step.get("confirmation_answers", [])
        if str(value).strip()
    }
    rows = _current_ack_messages(st)
    for item in reversed(rows):
        for candidate in reversed(_trusted_answer_candidates(item.get("text", ""))):
            normalized = re.sub(r"[\s，。；;：:、!！]+", "", candidate)
            normalized = re.sub(r"[（(]推荐[）)]", "", normalized)
            if expected and normalized in expected:
                _ack_failure(st, success=True)
                return True, ""
            if _is_positive_confirmation(candidate):
                if expected:
                    continue
                _ack_failure(st, success=True)
                return True, ""
    wanted = " / ".join(step.get("confirmation_answers", []))
    why = (_out_of_scope_ack_reason(st) if not rows else "") or (
        "尚未捕获到本步骤的%s选择。正常情况下直接使用 AskUserQuestion 让用户点选即可，"
        "done 会自动读取结果，不要再要求用户补输“确认××”。"
        "只有宿主确实没有回传按钮结果时，才让用户发送一次页面上的确认选项。"
    ) % (("「" + wanted + "」") if wanted else "肯定")
    count = _ack_failure(st, why)
    return False, why + _ack_retry_guidance(count)


def _choice_verified(step, st, choice, ack_cursor=None):
    """Bind --choice to the answer when readable; trust a fresh UI token as fallback."""
    # 一卡合一:开场三个选择步同时接受配置确认卡期间捕获的真实答案。
    extra = (("config_confirm",)
             if st.get("current") in ("workflow_select", "grill_ask", "story_ask")
             else ())
    alias_rows = []
    for key, values in (step.get("choice_answers") or {}).items():
        for value in [key] + list(values or []):
            normalized = re.sub(r"[\s，。；;：:、!！]+", "", str(value))
            normalized = re.sub(r"[（(]推荐[）)]", "", normalized)
            if normalized:
                alias_rows.append((key, normalized.lower()))

    rows = _current_ack_messages(st, extra_steps=extra)
    if ack_cursor is not None:
        cursor = set(ack_cursor or [])
        rows = [item for item in rows
                if _ack_message_signature(item) not in cursor]
    readable = []
    for item in rows:
        readable.extend(_trusted_answer_candidates(item.get("text", "")))
    for candidate in reversed(readable):
        normalized = re.sub(r"[\s，。；;：:、!！]+", "", candidate)
        normalized = re.sub(r"[（(]推荐[）)]", "", normalized).lower()
        # 全等,或"标签开头+补充说明"(按钮文案常带括号注释)。禁止全文子串搜索:
        # 「这次不是 hotfix,走完整开发」会命中 hotfix、消息里出现 docs/review/ 路径
        # 会命中 review——把用户的合法回答误判成 Agent 替用户改选。
        # 纯 ASCII 代号(full/hotfix/tweak/review)只认全等,防叙述句里的英文词误触。
        matches = [
            (key, alias) for key, alias in alias_rows
            if normalized == alias
            or (not re.fullmatch(r"[a-z0-9_-]+", alias)
                and normalized.startswith(alias))
        ]
        if not matches:
            continue
        longest = max(len(alias) for _, alias in matches)
        keys = {key for key, alias in matches if len(alias) == longest}
        if len(keys) == 1:
            selected = next(iter(keys))
            if selected == choice:
                _ack_failure(st, success=True)
                return True, ""
            return False, (
                "用户点选的是「%s」，但 Agent 准备提交 --choice %s。"
                "请按按钮真实结果执行，禁止替用户改选。" % (candidate, choice)
            )

    if ack_cursor is None and _fresh_askuser(st):
        # Some CodeAgent builds emit the interaction token but omit the selected label.
        # The UI interaction is still stronger evidence than forcing the user to type it again.
        _ack_failure(st, success=True)
        return True, ""
    scope_why = _out_of_scope_ack_reason(st) if not rows else ""
    if scope_why:
        return False, scope_why
    return False, (
        "没有检测到本步骤的真实选项回答。请用 AskUserQuestion 展示固定选项；"
        "用户点选后直接执行 done --choice %s，不需要再输入确认句。" % choice
    )


def _ack_retry_guidance(count):
    if count < 2:
        return ""
    return (
        " 同一确认自动校验已连续失败 %d 次，现停止重复执行同一条命令。"
        "流程没有锁死，也不需要 exit/init：先运行 messages 查看实际捕获答案；"
        "若结构化选择未回传，让用户发送一条当前页面要求的普通确认消息，再原样提交。"
    ) % count


def _ack_verified(st, ack, exact=True):
    """ack 必须来自当前步骤之后的真实用户输入；旧步骤的“可以”不能循环使用。

    如果宿主拿不到 AskUserQuestion 的应答正文，用户再发一条普通消息即可恢复；不允许静默降级为
    “模型自己写一句 --ack 也算用户确认”。
    """
    msgs = _current_ack_messages(st)
    if not msgs:
        why = _out_of_scope_ack_reason(st) or (
            "harness 尚未记录到任何用户回复。先执行 doctor 检查 UserPromptSubmit 输入，"
            "不要重复执行相同 done，也无需退出重开。")
        count = _ack_failure(st, why)
        return False, why + _ack_retry_guidance(count)

    def nt(s):
        return re.sub(r"\s+", "", s or "")

    na = nt(ack)
    actual = [v for m in msgs for v in _ack_candidates(m.get("text", ""))]
    matched = any((na == v if exact else na in v) for v in actual) if na else False
    if matched:
        _ack_failure(st, success=True)
        return True, ""
    why = ("--ack 与当前步骤开始后的用户真实输入不匹配。"
           "ack 必须是用户回复/选项的原文复制；先执行 messages 核对实际捕获答案，"
           "不要再次执行相同命令。")
    count = _ack_failure(st, why)
    return False, why + _ack_retry_guidance(count)


def _requirement_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _config_sha256(config, requirement_sha=""):
    payload = json.dumps(
        {"config": config or {}, "requirement_sha256": requirement_sha},
        ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_full_config_confirmation(value):
    compact = re.sub(r"[\s，。；;：:、!！]+", "", value or "")
    if not compact or re.search(
            r"不确认|不是|不要|不能|没有|没法|否认|拒绝|暂不|修改|调整|"
            r"不对|有误|有问题|什么意思|怎么|是否|能否|为什么|[?？]",
            compact):
        return False
    return (
        compact in (
            re.sub(r"\s+", "", CONFIG_CONFIRM_ACK),
            "全部正确",
            "以上配置全部正确",
            "所有配置都正确",
        )
        or bool(re.search(r"确认(?:以上|全部|所有).{0,4}配置", compact))
    )


def _config_ack_verified(st, ack, config_sha, review_id):
    """Verify one final confirmation bound to the exact reviewed config."""
    current_rows = _current_ack_messages(st)
    messages = [
        item for item in current_rows
        if item.get("config_review_sha256") == config_sha
        and item.get("config_review_id") == review_id
    ]
    normalized_ack = re.sub(r"\s+", "", ack or "")
    matched = False
    for item in messages:
        for candidate in _trusted_answer_candidates(item.get("text", "")):
            same_answer = (
                normalized_ack == candidate if normalized_ack else True)
            if same_answer and _is_full_config_confirmation(candidate):
                matched = True
                break
        if matched:
            break
    if matched:
        _ack_failure(st, success=True)
        return True, ""

    if normalized_ack and not _is_full_config_confirmation(normalized_ack):
        why = (
            "配置确认必须针对完整配置，不能用“确认 master”等单项回答给整份配置背书。"
            "请展示 config-review 输出后，只询问一次“是否确认以上全部配置”。"
        )
    elif not messages and not current_rows and _out_of_scope_ack_reason(st):
        why = _out_of_scope_ack_reason(st)
    elif not messages:
        why = (
            "没有捕获到与当前配置确认单绑定的用户回复。AskUserQuestion 的应答可能未被宿主回传；"
            "无需退出或重新初始化，让用户发送一条普通消息“%s”即可恢复。"
            % CONFIG_CONFIRM_ACK
        )
    else:
        why = (
            "当前配置确认单之后没有肯定的完整配置选择。用户在 AskUserQuestion 点选后可直接 done，"
            "不需要再手动输入或由 Agent 拼接 --ack。"
        )
    count = _ack_failure(st, why)
    return False, why + _ack_retry_guidance(count)


def check_evidence(step, st):
    return workflow_completion.evidence_failures(
        step, st, EVIDENCE)


# ---------------- 步骤展示 ----------------

def perms_line(step):
    allow, forbid = [], []
    (allow if step.get("allow_source_edit") else forbid).append("修改源码")
    (allow if step.get("allow_specs_write") else forbid).append("写 openspec/specs/ 真相源")
    return "允许: " + ("、".join(allow) or "仅本步指令内动作") + ";禁止: " + "、".join(forbid + ["编辑 .comet.yaml"])


# mae-flow 步骤 ↔ comet phase 合法区间(阶段互锁哨兵;未列出的步骤不检查)
# 依据 comet 0.3 语义:comet-design 收尾自带 guard design --apply → build;build 收尾 apply → verify
SPEC_REGISTER_FIELDS = ("design_doc", "plan", "verification_report")
SPEC_PHASES = ("open", "design", "build", "verify", "archive", "archived")


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
    if old and argv_out(["git", "cat-file", "-t", old]) == "commit":
        return old, ""
    entered_at = ""
    for h in reversed(st.get("history", [])):
        result = str(h.get("result", ""))
        if result == "goto:" + sid or _resolved_next(flow, st, h.get("step", "")) == sid:
            entered_at = h.get("at", "")
            break
    if not entered_at:
        return "", f"历史中找不到进入 {sid} 的转换记录"
    base = argv_out(["git", "rev-list", "-1", "--before=" + entered_at, "HEAD"])
    if not base or argv_out(["git", "cat-file", "-t", base]) != "commit":
        return "", f"无法按进入时间 {entered_at} 解析安全基点"
    st.setdefault("step_heads", {})[sid] = base
    st.setdefault("migrations", []).append({
        "type": "recover-step-head", "step": sid, "head": base,
        "from_history_at": entered_at, "at": time.strftime("%Y-%m-%d %H:%M:%S")})
    save_state(st)
    return base, ""


def _with_lightcheck_prompt(sid, text):
    if sid not in (
            "build", "rf_fix", "tw_change", "verify_ponytail",
            "verify_ut", "rf_ut", "tw_ut"):
        return text
    prompt = (
        "\n\n──── 轻量编码预防（建议层，不新增门禁） ────\n"
        "写每个函数时主动控制：正式入参≤5（Python self/cls 不计）、"
        "有效代码行≤50（空行/纯注释/仅括号分隔行不计）、McCabe 圈复杂度≤5、"
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
    txt = open(md, encoding="utf-8").read().rstrip()
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
            die("插件内嵌能力包损坏，当前步骤不能可靠执行: %s。"
                "请升级/重装 Mae-Flow；流程状态尚未推进。" % exc, 2)
    return subst(_with_lightcheck_prompt(sid, txt), st)


def _review_receipt_lines(st, step):
    """生成编译后人工检视收据；只展示机器解析出的本轮精确 Git 范围。"""
    evidence = next(
        (item for item in step.get("evidence", [])
         if item.get("type") == "review_snapshot"), {})
    base_step = evidence.get("base_step", "")
    base = (st.get("step_heads", {}) or {}).get(base_step, "")
    head = sh("git rev-parse --verify HEAD")
    if (not base or not head
            or argv_out(["git", "cat-file", "-t", base]) != "commit"):
        return ["❌ 无法生成本轮检视收据：缺少可信 Git 基点；done 会安全拒绝。"]
    commits = argv_out([
        "git", "-c", "core.quotepath=false", "log", "--format=%h %s",
        base + ".." + head,
    ]).splitlines()
    files = argv_out([
        "git", "-c", "core.quotepath=false", "diff", "--name-status",
        base, head,
    ]).splitlines()
    stat = argv_out([
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
        return json.load(open(DEFAULTS_PATH, encoding="utf-8-sig")), ""
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
    checkpoint_state = _development_review(st)
    if checkpoint_state and checkpoint_state.get("status") == "active":
        mode_label = ("分阶段先检视、后提交并 push"
                      if checkpoint_state.get("mode") == "staged"
                      else "一次完成、最终统一检视")
        print("🧭 开发节奏: " + mode_label)
        current_checkpoint = _checkpoint_current(st)
        if sid == _checkpoint_expected_code_step(st) and current_checkpoint:
            print("   当前检查点: %s [%s] %s" % (
                current_checkpoint.get("id"),
                current_checkpoint.get("status"),
                current_checkpoint.get("title")))
            if current_checkpoint.get("status") == "push_pending":
                if _review_before_commit(checkpoint_state):
                    print("   用户检视过的精确提交待推送；普通 push 后执行 checkpoint status 验真。")
                else:
                    print("   编译已通过；完成普通 push 后执行 checkpoint status 冻结远端检视收据。")
            elif current_checkpoint.get("status") == "commit_pending":
                base = str((current_checkpoint.get("receipt") or {}).get(
                    "base", ""))
                if sh("git rev-parse --verify HEAD") == base:
                    add, commit = _checkpoint_commit_command(
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
            elif current_checkpoint.get("status") == "review_pending":
                if _review_before_commit(checkpoint_state):
                    print("\n".join(_checkpoint_worktree_review_lines(
                        current_checkpoint)))
                else:
                    receipt = current_checkpoint.get("receipt") or {}
                    print("\n".join(_checkpoint_review_lines(
                        receipt.get("base", ""), receipt.get("head", ""),
                        "%s 等待用户检视" % current_checkpoint.get("id"),
                        receipt.get("remote_ref", ""))))
                _print_checkpoint_decisions(final=False)
        elif (sid == _checkpoint_expected_code_step(st)
              and (checkpoint_state.get("final_rework") or {}).get("status")
              == "coding"):
            print("   当前是最终检视返工，不新增或重开原 CP。按本步骤提交修改并走正常编译/质量链，"
                  "不要再执行 checkpoint ready；回到 delivery_review 后会重新展示完整增量。")
        if sid == "delivery_review":
            final = _final_review_active(checkpoint_state)
            if final:
                _show_final_review_receipt(st, checkpoint_state, final)
            else:
                changed, review_err = _final_review_delta(st)
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
    if sid == "config_confirm" and not _moonlight(st):
        print("⚠ 本步先收集配置值，再由 config-review 生成完整确认单。"
              "只有确认单后的最终回答能推进；基线分支、单号等局部回答不能代替整单确认。")
    elif step.get("user_ack") and not _moonlight(st):
        print("⚠ 本步有真实用户决策:用 AskUserQuestion 呈现固定选项，用户点选后同轮直接 done。"
              "按钮结果由 harness 自动读取，不要再要求用户手动输入“确认××”；"
              "只有宿主确实不回传按钮结果时才退回一次纯文本选择。")
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
                      "候选值;缺项时只询问取值，最后随完整配置确认单一次确认")
            print(f"──── 仓库预设({DEFAULTS_PATH},{suffix}) ────")
            for k, v in show.items():
                print(f"  {k} = {v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)}")
    print("──── 完成后执行 ────")
    if sid == "config_confirm" and not _moonlight(st):
        review = st.get("config_review") or {}
        if review.get("sha256"):
            _print_config_review(review, step)
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


# ---------------- 命令 ----------------

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
        die("开启新流程前无法清理旧辅助状态，继续会造成证据或消息串单："
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
        die("独立任务状态损坏：%s。它不会拦普通开发；可执行 action cancel 归档坏现场。" % err, 2)
    if action and expired:
        _archive_action(action, "expired", "独立任务超过 24 小时自动失效")
        return None
    return action


def _save_action(action):
    try:
        core_save_action(action)
    except StateStoreError as exc:
        die("独立任务状态存在并发更新或不可读，拒绝覆盖：" + str(exc)
            + "。重新执行 action status 后继续。", 2)


def _git_local_runtime_ignore():
    """独立任务不改团队 .gitignore，只把本机运行现场加入当前仓的本地排除。"""
    path = sh("git rev-parse --git-path info/exclude")
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
        die("独立任务在归档前发生并发更新或状态不可读：" + str(exc)
            + "。重新执行 action status 后继续。", 2)


def _standalone_config(terminal_state=None):
    """独立任务只继承项目运行方式，不继承单号、步骤、令牌或质量结论。"""
    merged = {}
    candidates = []
    if os.path.isfile(STATE_PATH + ".last"):
        candidates.append(STATE_PATH + ".last")
    if os.path.isfile(EXIT_PATH):
        try:
            rec = json.load(open(EXIT_PATH, encoding="utf-8"))
            saved = os.path.join(rec.get("snapshot", ""), STATE_PATH)
            if os.path.isfile(saved):
                candidates.append(saved)
        except Exception:
            pass
    for path in candidates:
        try:
            cfg = json.load(open(path, encoding="utf-8")).get("config", {}) or {}
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
        defaults = json.load(open(DEFAULTS_PATH, encoding="utf-8-sig")) if os.path.isfile(DEFAULTS_PATH) else {}
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
        values = [p for p in _dirty_paths() if _is_source_path(p, st or {}, FLOW or {})]
    out = []
    root = os.path.abspath(os.getcwd())
    for value in values:
        path = os.path.abspath(value)
        try:
            rel = norm(os.path.relpath(path, root))
        except ValueError:
            die("独立任务文件必须位于当前项目内：" + value, 2)
        if rel == ".." or rel.startswith("../"):
            die("独立任务文件必须位于当前项目内：" + value, 2)
        if not os.path.exists(path):
            die("独立任务文件不存在：" + value, 2)
        if rel not in out:
            out.append(rel)
    return out


def _action_target_files(values, kind, config, flow):
    """Turn explicit/inferred paths into the frozen scope shown to the user."""
    source_files = [p for p in values if _is_source_path(p, {}, flow)]
    if kind == "codecheck":
        return [p for p in source_files
                if p.lower().endswith(CODE_EXTS)
                and not _is_test_file(p, {"config": config})]
    if kind == "ut":
        business = [p for p in source_files
                    if not _is_build_path(p)
                    and not _is_test_file(p, {"config": config})]
        if not business:
            die("独立 UT 范围至少要包含一个被测业务文件；"
                "空范围、只有测试文件或只有构建文件都不能启动。"
                "请先定位被测源码，再用 --files 明确传入。", 2)
        return source_files
    return values


def _action_scope_ack_verified(action, ack):
    """Scope approval must come from a user event after the proposal was saved."""
    if re.sub(r"\s+", "", ack or "") != re.sub(r"\s+", "", ACTION_SCOPE_ACK):
        return False, "确认命令必须原样使用用户选项「%s」" % ACTION_SCOPE_ACK
    proposed = float(action.get("scope_proposed_epoch", 0) or 0)
    for message in reversed(action.get("user_messages", []) or []):
        if float(message.get("epoch", 0) or 0) + 0.001 < proposed:
            continue
        candidates = _ack_candidates(str(message.get("text", "")))
        if re.sub(r"\s+", "", ACTION_SCOPE_ACK) in candidates:
            return True, ""
    return False, (
        "没有捕获到范围展示后的用户确认。请使用 AskUserQuestion 让用户选择「确认以上范围」；"
        "工具应答未被宿主回传时，让用户再发送一条纯文本“确认以上范围”，不要由 Agent 代答。")


def _print_action_scope(action, inferred):
    print("[mae-flow] 独立 %s 待确认执行范围（尚未运行工具、尚未派子 Agent）：" %
          action.get("kind", "").upper())
    print("范围来源：" + ("当前工作区改动自动推导" if inferred else "用户点名/Agent 定位后传入"))
    for index, path in enumerate(action.get("files", []), 1):
        suffix = "（测试文件）" if _is_test_file(
            path, {"config": action.get("config", {})}) else "（被测/业务文件）"
        print("  %d. %s%s" % (index, path, suffix))
    print("现在必须用 AskUserQuestion 让用户二选一：")
    print("  - 确认以上范围")
    print("  - 需要调整范围")
    print("用户确认后执行：")
    print('python "%s" action confirm-scope --ack "%s"' %
          (os.path.abspath(__file__), ACTION_SCOPE_ACK))
    print("若用户要求调整，执行 action cancel 后按新范围重新 action start；禁止自行扩大文件清单。")


def _action_request(action, request="", source=""):
    work = _action_dir(action)
    os.makedirs(work, exist_ok=True)
    sources = []
    if source:
        src = os.path.abspath(source)
        text, _, err = _read_text_source(src, normalize=True)
        if err:
            die("独立任务输入材料不可读：" + err, 2)
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
    head = sh("git rev-parse --verify HEAD")
    sid = "standalone_" + action["kind"]
    files = action.get("files", [])
    groups = _task_file_groups(files, {"config": config})
    scan = action.get("quality", {}).get("codecheck_scan", {})
    lines = [
        f"# Mae-Flow Standalone {label} TASK CARD",
        "本文件由 harness 生成。运行模式是独立任务：不启动完整交付流程，不得自行扩大范围。",
        f"独立任务ID: {action['id']}",
        f"运行模式: standalone",
        f"当前步骤: {sid}",
        f"项目根: {os.path.abspath(os.getcwd())}",
        f"任务卡基点 HEAD: {head}",
        f"提交策略: 禁止提交（保留工作区改动给用户检查）",
        f"任务说明: {action.get('request', '') or '按任务卡文件范围完成本项工作'}",
        f"本次子任务范围: {'、'.join(files) if files else action.get('request', '用户描述范围')}",
        f"编译方式: {config.get('编译方式', '')}",
        f"UT生成方式: {config.get('UT生成方式', '')}",
        f"UT运行命令: {config.get('UT运行命令', '')}",
    ]
    if stage:
        lines.append("质询检查阶段: " + stage)
    lines.append("需求/规格依据:")
    sources = action.get("sources", [])
    lines.extend("- " + os.path.abspath(x) for x in sources)
    if not sources:
        lines.append("- 用户未提供独立文档；以任务说明和点名代码为依据，不得发明业务要求")
    lines.append("任务相关文件（独立任务只允许使用以下冻结范围）:")
    _append_task_files(lines, "被测/业务源码", groups["business"])
    _append_task_files(lines, "测试文件", groups["tests"])
    _append_task_files(lines, "构建/依赖文件", groups["build"])
    if label in ("UT", "CODECHECK"):
        execution_files = groups["business"] or groups["tests"] or groups["build"]
        _append_execution_context(lines, execution_files, label)
    if label == "CODECHECK":
        lines += [
            f"Harness首检告警数: {scan.get('count', '未执行')}",
            "Harness首检文件: " + "、".join(scan.get("files", [])),
            "Harness首检告警(规则|文件): "
            + _render_warning_pairs(scan.get("pairs", [])),
            "职责:仅处理首检范围内业务代码告警；修复后按配置编译并重新 fullcheck；禁止自动豁免。",
        ]
    elif label == "UT":
        standalone_targets = _hunk_targets_for_diff(
            action.get("base_head", "HEAD"), groups["business"])
        lines.append("UT覆盖目标（硬边界，不等于整个文件）:")
        for business_file in groups["business"]:
            targets = standalone_targets.get(norm(business_file), [])
            if not targets:
                lines.append("- %s | 当前工作区无可定位 diff；只覆盖任务说明点名的函数/行为，"
                             "若任务说明也未点明则 NEEDS_INPUT，禁止给整个文件补存量覆盖"
                             % business_file)
            for target in targets:
                span = ("%d" % target["start"] if target["start"] == target["end"]
                        else "%d-%d" % (target["start"], target["end"]))
                context = target.get("context") or "按该行附近确认所属函数/行为"
                lines.append("- %s | 行 %s | %s" % (
                    business_file, span, context))
        lines += [
            "职责:仅新增/修改测试代码；按配置调用 UT 生成能力并真实运行测试；"
            "覆盖对象仅限上面的函数/行为与任务说明，禁止扩成整个文件；"
            "疑似源码问题完成自查后上报，禁止自行改被测源码。",
            "独立任务默认不 commit；PASS 不以 commit 为条件，但测试必须真实全绿。",
        ]
    elif label == "GRILL":
        lines += [
            "职责:只读审查需求材料、代码勘察笔记和当前澄清文档，寻找遗漏的需求决策分支；"
            "禁止替用户拍板、禁止修改任何文件。",
        ]
    body = "\n".join(lines).rstrip() + "\n"
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    body += f"TASK_CARD_SHA256: {digest}\n"
    work = _action_dir(action)
    os.makedirs(work, exist_ok=True)
    suffix = ("-" + stage) if stage else ""
    path = os.path.join(work, f"{label.lower()}{suffix}-task.md")
    atomic_write_text(path, body)
    initial = {
        p: _path_fingerprint(p)
        for p in _dirty_paths()
        if _is_source_path(p, {}, FLOW or {})
    }
    action.setdefault("agent_tasks", {})[label] = {
        "step": sid, "path": path, "sha256": digest, "head": head,
        "scope": action.get("request", ""), "allowed_files": scan.get("files", []) if label == "CODECHECK" else [],
        "task_files": files,
        "execution_roots": [root for root, _reason in _task_execution_roots(
            groups["business"] or groups["tests"] or groups["build"])[0]],
        "initial_source_fingerprints": initial, "standalone": True, "stage": stage,
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
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
              % norm(codecheck_log_path(os.getcwd(), action)))
    print("启动 %s 时只传这一句:\n读取并严格执行任务卡 \"%s\"；"
          "最终报告必须原样带 TASK_CARD_SHA256: %s" % (agent, path, digest))
    return path


def cmd_action_start(flow, st, args):
    terminal_state = bool(
        st and flow.get("steps", {}).get(
            st.get("current", ""), {}).get("terminal"))
    if st is not None and not terminal_state:
        die("当前有完整交付流程正在运行，不能叠加独立任务。"
            "若确定只做单项工作，先发送 `/mae-flow:mae-flow exit`，退出后重试。", 2)
    current = _load_action()
    if current:
        die("已有独立任务 %s(%s) 未收尾。它不会拦普通开发；"
            "继续用 action status，放弃用 action cancel。" % (
                current.get("id", "?"), current.get("kind", "?")), 2)
    kind = args.kind
    defaults = _standalone_config(st if terminal_state else None)
    config = {
        "编译方式": args.build or defaults.get("编译方式", ""),
        "UT生成方式": args.generator or defaults.get("UT生成方式", ""),
        "UT运行命令": args.ut_command or defaults.get("UT运行命令", ""),
        "测试路径": defaults.get("测试路径", ""),
    }
    if kind == "ut":
        missing = [k for k in ("UT生成方式", "UT运行命令") if not config.get(k)]
        if missing:
            die("独立 UT 缺少 %s。先从项目实际能力确认后，用 --generator/--ut-command 传入；"
                "禁止让 Agent 猜。" % "、".join(missing), 2)
    if kind == "codecheck" and not args.check_only and not config.get("编译方式"):
        die("独立 CodeCheck 修复模式缺少编译方式。用 --build 传入项目真实编译方式；"
            "如果只想看报告，使用 --check-only。", 2)
    if kind == "grill" and not (args.request or args.source):
        die("独立质询必须提供 --request 用户需求原话或 --source 需求文本路径。", 2)
    raw_files = _action_files(args.files)
    inferred_scope = not bool(args.files)
    if kind in ("ut", "codecheck"):
        scoped_files = _action_target_files(raw_files, kind, config, flow)
        if not scoped_files:
            label = "CodeCheck" if kind == "codecheck" else "UT"
            die("独立 %s 没有可执行的业务代码范围。请先定位文件，再用 --files 明确指定；"
                "不会自动扩大到全仓。" % label, 2)
    else:
        scoped_files = raw_files
    if terminal_state:
        # end 只是一份待归档的完成记录，不应冒充“在途流程”阻断独立任务。
        # 在所有参数/范围校验通过后再归档，避免一次无效 action start 改变状态。
        _clear_auxiliary_state()
        _append_history(st, outcome="已完成后开启独立任务")
        os.replace(STATE_PATH, STATE_PATH + ".last")
        print("[mae-flow] 上一单已交付完成并归档为 .mae-flow.json.last；"
              "现在启动独立任务，无需 exit。")
    _git_local_runtime_ignore()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    # 同一秒内取消后重开同类任务也必须使用全新目录，避免旧任务卡/报告混入新现场。
    nonce = hashlib.sha256(("%s:%s" % (time.time_ns(), os.getpid())).encode()).hexdigest()[:8]
    action_id = f"{stamp}-{nonce}-{kind}"
    action = {
        "version": 1, "id": action_id, "kind": kind,
        "status": ("awaiting_scope_confirmation"
                   if kind in ("ut", "codecheck") else "active"),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "expires_epoch": time.time() + 24 * 3600,
        "work_dir": os.path.abspath(os.path.join(".mae-flow-work", "standalone", action_id)),
        "request": (args.request or "").strip(), "config": config,
        "check_only": bool(args.check_only),
        "base_head": sh("git rev-parse --verify HEAD"),
        "commit_policy": "forbid", "tokens": {}, "rejections": {}, "quality": {},
    }
    action["sources"] = _action_request(action, args.request or "", args.source or "")
    action["files"] = scoped_files
    if kind in ("ut", "codecheck"):
        action["scope_source"] = "dirty-worktree" if inferred_scope else "explicit"
        action["scope_proposed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        action["scope_proposed_epoch"] = time.time()
        _save_action(action)
        _print_action_scope(action, inferred_scope)
        return
    _save_action(action)
    work = _action_dir(action)
    prep = os.path.join(work, "grill-prep.md")
    clarification = os.path.join(work, "clarifications.md")
    action["grill"] = {"prep": prep, "clarifications": clarification, "questions_answered": 0}
    _save_action(action)
    print("[mae-flow] 独立需求质询已开启，不会进入设计或编码。")
    print("先定向阅读需求与相关代码，把八维检查和候选问题写入：%s" % prep)
    print("备课工作表必须按模板结构填写(hook 会校验章节,自由发挥会被打回):%s"
          % os.path.abspath(os.path.join(HERE, "..", "skills", "mae-flow",
                                         "assets", "GRILL-PREP-TEMPLATE.md")))
    print("随后一次只问用户一个问题，每次回答后先检查模糊词、新名词、矛盾和衍生边界，"
          "答案增量写入：%s" % clarification)
    print("备课完成后执行 action critic --stage prep --document \"%s\" 做第一次对抗检查。"
          % prep)


def cmd_action_confirm_scope(flow, args):
    action = _load_action()
    if not action or action.get("kind") not in ("ut", "codecheck"):
        die("当前没有等待范围确认的独立 UT/CodeCheck 任务。", 2)
    if action.get("status") != "awaiting_scope_confirmation":
        die("当前独立任务已经确认过范围，不能重复确认或改写范围。", 2)
    ok, why = _action_scope_ack_verified(action, args.ack)
    if not ok:
        die("独立任务范围确认验真失败：" + why, 2)
    # 确认与执行可能跨会话；再次验证冻结路径仍存在且仍属于允许类型。
    files = _action_files(action.get("files", []))
    files = _action_target_files(
        files, action["kind"], action.get("config", {}), flow)
    if files != action.get("files", []):
        die("确认后的文件范围与展示内容不一致，已拒绝执行；取消后重新发起。", 2)
    action["status"] = "active"
    action["scope_confirmed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    action["scope_confirmed_ack"] = args.ack
    _save_action(action)
    if action["kind"] == "codecheck":
        append_codecheck_event(
            os.getcwd(), action, "standalone.scope_confirmed", {
                "head": action.get("base_head", ""),
                "files": files,
                "ack": args.ack,
            })
        result, err = _run_codecheck(files, action, "standalone-scan")
        if err:
            # 独立模式也遵循建议型语义：工具版本/协议不可识别不等于代码失败。
            # 保存真实诊断后正常结束，避免同一不可靠插件把用户拖进重跑循环。
            report = os.path.join(_action_dir(action), "codecheck-report.md")
            atomic_write_text(
                report,
                "# 独立 CodeCheck 结果\n\n"
                "状态：工具不可用或输出无法解析（建议项，不代表代码失败）\n\n"
                "检查文件：\n%s\n\n"
                "原始诊断：\n```\n%s\n```\n"
                % ("\n".join("- `" + x + "`" for x in files), err))
            action["quality"]["codecheck_scan"] = {
                "step": "standalone_codecheck", "head": action["base_head"],
                "count": None, "status": "TOOL_ERROR", "files": files,
                "pairs": [], "commands": [], "error": err,
                "log_path": codecheck_log_path(os.getcwd(), action),
                "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            append_codecheck_event(
                os.getcwd(), action, "standalone.scan_failed", {
                    "head": action.get("base_head", ""),
                    "files": files, "error": err,
                })
            _save_action(action)
            work = _archive_action(
                action, "tool-error",
                "CodeCheck 已真实尝试；工具不可用或输出无法解析，按建议项结束")
            print("[mae-flow] ⚠ 独立 CodeCheck 已真实尝试，但工具不可用或输出无法解析。")
            print("诊断已保留在 %s；本任务按建议项结束，不派修复 Agent，也不要求重跑。"
                  % norm(os.path.join(work, "codecheck-report.md")))
            print("[mae-flow] CodeCheck 详细日志: %s"
                  % norm(os.path.join(work, "codecheck-debug.md")))
            print("未启动完整流程，也没有修改或提交代码。")
            return
        scan = {
            "step": "standalone_codecheck", "head": action["base_head"],
            "count": result["total"], "files": files, "pairs": result["pairs"],
            "commands": result["commands"], "log_path": result.get("log_path", ""),
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        action["quality"]["codecheck_scan"] = scan
        _save_action(action)
        if result["total"] == 0 or action.get("check_only"):
            report = os.path.join(_action_dir(action), "codecheck-report.md")
            atomic_write_text(
                report,
                "# 独立 CodeCheck 结果\n\n检查文件：%d\n\n告警：%d\n\n命令：\n%s\n"
                % (len(files), result["total"],
                   "\n".join("- `" + x + "`" for x in result["commands"])))
            outcome = "clean" if result["total"] == 0 else "check-only"
            append_codecheck_event(
                os.getcwd(), action, "standalone.scan_completed", {
                    "head": action.get("base_head", ""),
                    "files": files, "count": result["total"],
                    "commands": result["commands"], "outcome": outcome,
                })
            work = _archive_action(action, outcome, "机器首检完成")
            print("[mae-flow] 独立 CodeCheck 已完成：%d 条告警。报告：%s"
                  % (result["total"], norm(report)))
            print("[mae-flow] CodeCheck 详细日志: %s"
                  % norm(os.path.join(work, "codecheck-debug.md")))
            print("未启动完整流程，也没有修改或提交代码。")
            return
        append_codecheck_event(
            os.getcwd(), action, "standalone.scan_completed", {
                "head": action.get("base_head", ""),
                "files": files, "count": result["total"],
                "pairs": result["pairs"], "commands": result["commands"],
                "outcome": "repair-required",
            })
        print("[mae-flow] 首检发现 %d 条告警，开始专项修复。" % result["total"])
        print("[mae-flow] CodeCheck 详细日志: %s"
              % norm(codecheck_log_path(os.getcwd(), action)))
        return _action_task_card(action, "codecheck")
    return _action_task_card(action, "ut")


def cmd_action_critic(args):
    action = _load_action()
    if not action or action.get("kind") != "grill":
        die("当前没有独立 Grill 任务。", 2)
    document = os.path.abspath(args.document or "")
    if not os.path.isfile(document):
        die("质询检查材料不存在：" + (args.document or "(空)"), 2)
    action.setdefault("grill", {})["last_critic_document"] = document
    action["grill"]["last_critic_stage"] = args.stage
    if args.stage == "prep":
        # 双查承诺的前半:final 会覆盖 last_critic_stage,prep 是否跑过需单独留痕
        action["grill"]["prep_critic_done"] = True
    if document not in action.setdefault("sources", []):
        action["sources"].append(document)
    return _action_task_card(action, "grill", args.stage)


def cmd_action_status():
    action = _load_action()
    if not action:
        print("[mae-flow] 当前没有独立任务；普通开发完全不受 mae-flow 接管。")
        return
    print(json.dumps(action, ensure_ascii=False, indent=2))


def cmd_action_finish(args):
    action = _load_action()
    if not action:
        die("当前没有独立任务。", 2)
    kind = action.get("kind")
    if kind == "grill":
        report = os.path.abspath(args.report or action.get("grill", {}).get("clarifications", ""))
        if not os.path.isfile(report):
            die("独立质询结果文档不存在；用 --report 指定最终澄清文档。", 2)
        text, _, err = _read_text_source(report, normalize=False)
        if err:
            die("独立质询结果不可读：" + err, 2)
        if re.search(r"\{\{[^}]+\}\}|待确认|TODO|TBD", text, re.I):
            die("澄清文档仍有待确认项，不能宣称质询完成。继续追问或把未决项明确列为用户决定暂缓。", 2)
        if not (action.get("grill", {}) or {}).get("prep_critic_done"):
            die("备课后的第一轮对抗检查(prep critic)没有执行过——双查是独立质询的质量承诺,"
                "不能只做收尾那次。先 action critic --stage prep --document <备课文件>,"
                "补齐它找出的缺口后再收尾。", 2)
        grill_token = (action.get("tokens", {}) or {}).get("GRILL", {})
        if not grill_token or (action.get("agent_tasks", {}).get("GRILL", {}) or {}).get("stage") != "final":
            die("收尾前还没有执行 final 对抗检查。先 action critic --stage final --document <澄清文档>；"
                "它只找遗漏，不会阻塞普通开发。", 2)
        work = _archive_action(action, "completed", "独立需求质询完成")
        print("[mae-flow] 独立需求质询已完成：%s" % report)
        if grill_token.get("status") == "GAPS":
            print("⚠ final critic 仍报告潜在遗漏，已保留在 %s；这是风险提示，不会卡住后续开发。"
                  % grill_token.get("report_path", work))
        print("没有启动完整交付流程，也没有自动进入设计或编码。")
        return
    label = kind.upper()
    token = (action.get("tokens", {}) or {}).get(label, {})
    if not token:
        rejection = (action.get("rejections", {}) or {}).get(label, {})
        detail = rejection.get("reason", "尚未收到专项 Agent 的合法收尾")
        die(detail + "。继续修正 Agent 报告，或执行 action cancel 结束独立任务；"
            "无论哪种情况都不会拦普通开发。", 2)
    report = token.get("report_path", "")
    work = _archive_action(action, "completed", "%s/%s" % (label, token.get("status", "")))
    print("[mae-flow] 独立 %s 已结束，结果：%s" % (label, token.get("status", "?")))
    print("报告：" + (norm(report) if report else norm(work)))
    if token.get("status") not in ("PASS", "CLEAN", "CLEAR"):
        print("⚠ 结果包含失败、待确认或遗留项；已如实保留，但不会自动豁免，也不会卡住普通开发。")
    print("本任务没有自动提交或推送代码。")


def cmd_action_cancel():
    action, err, _ = core_load_action()
    if err:
        work = core_archive_corrupt_action()
        print("[mae-flow] 独立任务状态已损坏，但取消成功；坏现场保存在 %s。"
              "普通开发从未被它拦截。原因：%s" % (norm(work or "无"), err))
        return
    if not action:
        print("[mae-flow] 当前没有独立任务，无需取消。")
        return
    work = _archive_action(action, "cancelled", "用户取消独立任务")
    print("[mae-flow] 独立任务已取消，现场保留在 %s；代码未回滚，普通开发继续放行。" % norm(work))


def _captured_user_messages(st):
    return _current_ack_messages(st or {})


def cmd_messages(st, args):
    """Show stable IDs and trusted answer fields instead of question metadata."""
    rows = _captured_user_messages(st)
    message_id = getattr(args, "id", None)
    if message_id:
        rows = [item for item in rows if item.get("id") == message_id]
    if not rows:
        if message_id:
            old = [
                item for item in _all_ack_messages()
                if item.get("id") == message_id
            ]
            if old:
                die(
                    "消息 ID %s 已被 Hook 捕获，但它属于步骤 %s，当前是 %s；"
                    "旧步骤消息不能跨步骤复用。"
                    % (message_id, old[-1].get("step", "(未标步骤)"),
                       st.get("current", "")),
                    2)
            die("用户消息中不存在 ID %s；请先执行 messages 查看当前可用 ID。"
                % message_id, 2)
        why = _out_of_scope_ack_reason(st)
        if why:
            die("当前步骤没有可复用的用户消息。" + why, 2)
        die("尚未捕获到任何用户消息。检查 UserPromptSubmit hook；"
            "不要重复执行同一条确认命令；AskUserQuestion 不回传时，"
            "让用户发送当前页面要求的普通确认消息即可恢复。", 2)
    print("[mae-flow] 当前步骤捕获到的用户消息（需求落盘请使用左侧 ID）:")
    for m in rows:
        text = re.sub(r"\s+", " ", m.get("text", "")).strip()
        health = _text_corruption_reason(m.get("text", ""))
        preview = text if getattr(args, "full", False) else text[:100]
        print("  %s  %s  %s%s" % (
            m.get("id", "(旧记录无ID)"), m.get("at", "?"), preview,
            ("  ❌疑似乱码:" + health) if health else ""))
        extracted = [
            value for value in _ack_candidates(m.get("text", ""))
            if value != re.sub(r"\s+", "", m.get("text", ""))
        ]
        if extracted:
            print("    提取答案: " + " | ".join(extracted))
        if m.get("config_review_sha256"):
            print("    绑定配置: 收据 %s / 指纹 %s" % (
                m.get("config_review_id", "?"),
                m["config_review_sha256"][:12]))


def cmd_direct_messages(args):
    """Show Direct-mode prompts/answers that may authorize a safe re-entry."""
    rec = _read_exit_record()
    rows = list(rec.get("direct_messages", []) or [])
    if getattr(args, "id", None):
        rows = [item for item in rows if item.get("id") == args.id]
    if not rows:
        die("退出后尚未捕获到用户消息。让用户直接发送恢复 Mae-Flow、"
            "执行 /mae-flow:mae-flow review-fix 或开启另一流程的真实请求；"
            "不要让 Agent 自行生成授权，也不要移动 .mae-flow.json.exited。", 2)
    print("[mae-flow] Direct 模式捕获到的用户消息：")
    for m in rows:
        text = re.sub(r"\s+", " ", str(m.get("text", "") or "")).strip()
        preview = text if getattr(args, "full", False) else text[:100]
        print("  %s  %s  %s" % (
            m.get("id", "(旧记录无ID)"), m.get("at", "?"), preview))
        extracted = _trusted_answer_candidates(str(m.get("text", "") or ""))
        compact_raw = re.sub(r"\s+", "", str(m.get("text", "") or ""))
        extracted = [value for value in extracted if value != compact_raw]
        if extracted:
            print("    提取答案: " + " | ".join(extracted))
    if any(not item.get("id") for item in rows):
        print("旧记录没有消息 ID：请直接重新发送一次明确的恢复/换单请求，"
              "Hook 会生成 ID；不需要再点一轮“确认”。")
    print("恢复原流程：init --message-id <ID>")
    print("保留旧现场并开启另一流程：init --new --message-id <ID>")


def cmd_requirement_record(st, args):
    """从 Hook 捕获原文或已有文本文件生成统一 UTF-8 需求入口，并做写后回读校验。"""
    if (st or {}).get("current") != "config_confirm":
        die("requirement-record 只允许在配置确认阶段使用，避免后续偷偷更换需求依据。", 2)
    ticket = (args.ticket or (st.get("config", {}) or {}).get("单号", "")).strip()
    if not re.fullmatch(r"(?:REQ|DTS)\w+", ticket):
        die("--ticket 必须是有效的 REQ/DTS 单号。", 2)
    if bool(args.message_id) == bool(args.source):
        die("必须且只能选择 --message-id <messages输出的ID> 或 --source <文本文件>。", 2)

    source_desc = ""
    if args.message_id:
        rows = _captured_user_messages(st)
        matches = [m for m in rows if m.get("id") == args.message_id]
        if not matches:
            die("当前步骤不存在消息 ID %s。先执行 messages 查看；"
                "不要把中文原文复制进 shell 参数。" % args.message_id, 2)
        text = matches[-1].get("text", "")
        bad = _text_corruption_reason(text)
        if bad:
            die("捕获的用户原话疑似已经乱码：" + bad
                + "。不要落盘；执行 doctor 检查 Hook 输入编码，或 `/mae-flow:mae-flow exit` 退出。", 2)
        source_desc = "用户消息 " + args.message_id
    else:
        src = os.path.abspath(args.source)
        text, enc, err = _read_text_source(src, normalize=True)
        if err:
            die("需求材料无法安全转成文本：" + err, 2)
        source_desc = "%s（原编码 %s）" % (norm(src), enc)

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    path = os.path.join("docs", "req", "REQ-" + ticket + ".md")
    if os.path.exists(path) and not args.replace:
        die("目标已存在：%s。先查看内容；确认旧文件确实错误后加 --replace，禁止静默覆盖。" % path, 2)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    content = (
        "# 用户提供的原始需求\n\n"
        "来源：%s\n\n"
        "<!-- %s %s -->\n"
        "%s\n" % (source_desc, REQ_SHA_MARKER, digest, text)
    )
    atomic_write_text(path, content)
    ok, why = _validate_requirement_document(path)
    if not ok:
        die("需求文件写后回读校验失败：" + why + "。文件保留供诊断，禁止进入下一阶段。", 2)
    print("[mae-flow] 需求原文已确定性写入 UTF-8 并通过指纹回读：%s" % norm(path))
    print("来源：%s" % source_desc)
    print("正文 SHA256：%s" % digest)
    print("请展示该文件全文让用户核对；确认后将「需求文档」配置为上述路径。")


def _reopen_spec_archive(st):
    """把交付阶段从 archive 退回 verify（源码返工时验证结论必须重做）。

    v3:阶段是自家状态里的一个字段,回退就是改它 + 作废验证结论——不再需要调外部
    引擎的 archive-reopen 转换(那条链在纯内嵌项目上曾必死:只找 .cac/.claude 旧脚本)。"""
    data = _spec_data(st)
    if data.get("phase") != "archive":
        return True, ""
    data["phase"] = "verify"
    data.pop("verify_result", None)
    data.pop("verified_at", None)
    st.setdefault("history", []).append(
        {"step": st.get("current", ""), "result": "spec:archive-reopen",
         "note": "源码返工,验证结论作废", "at": time.strftime("%Y-%m-%d %H:%M:%S")})
    return True, ""


def _explicit_direct_reentry(text):
    """Whether captured user text explicitly asks Mae-Flow to take control again."""
    return _direct_reentry_decision(text) == "allow"


def _looks_like_control_question(value):
    return bool(re.search(
        r"(是什么|什么意思|怎么(?:用|恢复|开启|进入|接回)?|如何|能不能|"
        r"可以吗|是否|要不要|会不会|会怎样|有什么影响|[?？])",
        value, re.I))


def _targeted_flow_denial(value):
    """Reject only negation aimed at workflow control, not business wording."""
    target = r"(?:mae[- ]?flow|review-fix|这个工作流|原流程|月光宝盒|moonlight)"
    negative = r"(?:不确认|不要|不想|不再|不用|暂不|暂时不要|先别|别|拒绝|取消|停止|关闭|退出)"
    control = r"(?:重新)?(?:恢复|启用|接回|进入|使用|执行|开启|启动|切回|继续使用|用)"
    return bool(
        re.search(negative + r"\s*" + control + r"?\s*" + target, value, re.I)
        or re.search(target + r"[^，。！？,;；]{0,12}" + negative
                     + r"\s*" + control, value, re.I)
        or re.search(target + r"\s*(?:不要了|不用了|先别了?|取消|停止|关闭|退出)",
                     value, re.I)
    )


def _moonlight_activation_decision(text):
    """Return allow/deny/neutral for an unattended-mode activation request."""
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    lower = value.lower()
    command = re.match(r"^/mae-flow(?::mae-flow)?(?:\s+([^\s]+))?", lower)
    if command:
        action = (command.group(1) or "").strip()
        return "allow" if action in ("moonlight", "月光宝盒") else "neutral"
    if not re.search(r"月光宝盒|moonlight", value, re.I):
        return "neutral"
    if _targeted_flow_denial(value):
        return "deny"
    activation = bool(
        re.search(
            r"(?:开启|启动|启用|进入|切换到?|使用|用|继续|恢复)\s*(?:一下|这个)?\s*"
            r"(?:月光宝盒|moonlight)",
            value, re.I)
        or re.search(
            r"(?:月光宝盒|moonlight)(?:模式)?\s*(?:开启|启动|启用|继续|运行|接着|恢复)",
            value, re.I)
    )
    strong = bool(re.search(
        r"(?:请|帮我|直接|立即|马上|务必)\s*"
        r"(?:开启|启动|启用|进入|切换到?|使用|用|继续|恢复)\s*"
        r"(?:一下|这个)?\s*(?:月光宝盒|moonlight)",
        value, re.I))
    if _looks_like_control_question(value) and not strong:
        return "neutral"
    return "allow" if activation else "neutral"


def _direct_reentry_decision(text):
    """Return allow/deny/neutral for a captured Direct-mode user message."""
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    lower = value.lower()
    command = re.match(r"^/mae-flow(?::mae-flow)?(?:\s+([^\s]+))?", lower)
    if command:
        action = (command.group(1) or "").strip()
        # 独立 ut/codecheck/grill/story/chain/help 不应重新启用完整流程；
        # review-fix、月光宝盒和无参数完整入口都是明确的重新接管意图。
        return ("allow" if action in ("", "review-fix", "moonlight", "月光宝盒")
                else "neutral")
    # 否定只在明确指向流程控制时生效。业务请求里的“不要用长度判断”
    # 不应反过来否定开头已经明确发起的 review-fix。
    if _targeted_flow_denial(value):
        return "deny"
    if "review-fix" in lower:
        # 兼容宿主去掉 slash 前缀后只留下 action + 参数的形态，但“review-fix
        # 是什么/怎么用”只是咨询，不能因包含关键词就恢复门禁。
        asks_only = _looks_like_control_question(value)
        directs_action = bool(re.search(
            r"(请|帮我|执行|开启|进入|使用|处理|修复|调整|改成|改为|方案.{0,12}变)",
            value, re.I))
        strong_directive = bool(re.search(
            r"(?:(?:请(?!问|告诉|说明|介绍)|帮我|直接|立即|马上|务必)\s*"
            r"(?:执行|开启|进入|使用|用|处理|修复|调整|改成|改为)|"
            r"(?:处理|修复|调整)一下|改成|改为)",
            value, re.I))
        if asks_only and not strong_directive:
            return "neutral"
        return ("allow" if re.match(r"^review-fix(?:\s|$)", lower)
                or directs_action else "neutral")
    moonlight = _moonlight_activation_decision(value)
    if moonlight != "neutral":
        return moonlight
    names_flow = (
        "mae-flow" in lower or "mae flow" in lower or "这个工作流" in value
        or bool(re.search(r"(?:原|之前|先前)流程", value))
        or bool(re.fullmatch(r"(?:确认)?重新启用(?:流程)?", value))
    )
    action = bool(re.search(
        r"重新(?:使用|启用|进入|接回)?|恢复|接回|继续使用|确认重新|切回",
        value, re.I))
    strong_directive = bool(re.search(
        r"(?:请(?!问|告诉|说明|介绍)|帮我|直接|立即|马上|务必)\s*"
        r"(?:重新)?(?:恢复|启用|接回|进入|切回|继续使用)",
        value, re.I))
    if _looks_like_control_question(value) and not strong_directive:
        return "neutral"
    return "allow" if names_flow and action else "neutral"


def _direct_message_decision(text):
    """Classify only trusted answer fields from one captured message."""
    decisions = [
        _direct_reentry_decision(candidate)
        for candidate in _trusted_answer_candidates(str(text or ""))
    ]
    if "deny" in decisions:
        return "deny"
    if "allow" in decisions:
        return "allow"
    return "neutral"


def _direct_reentry_authorization(rec, ack="", message_id=""):
    """Resolve a real Direct-mode user message and verify explicit re-entry intent."""
    all_rows = list((rec or {}).get("direct_messages", []) or [])
    rows = list(enumerate(all_rows))
    if message_id:
        rows = [(index, row) for index, row in rows
                if row.get("id") == message_id]
        if not rows:
            return "", "退出记录中不存在消息 ID %s" % message_id
    needle = re.sub(r"\s+", "", ack or "")
    matched_without_intent = False
    for index, row in reversed(rows):
        text = str(row.get("text", "") or "")
        candidates = _trusted_answer_candidates(text)
        for candidate in candidates:
            if message_id or (needle and needle == candidate):
                decision = _direct_reentry_decision(candidate)
                if decision == "allow":
                    later_decisions = [
                        _direct_message_decision(item.get("text", ""))
                        for item in all_rows[index + 1:]
                    ]
                    later_decisive = [
                        item for item in later_decisions if item != "neutral"
                    ]
                    if later_decisive and later_decisive[-1] == "deny":
                        return "", (
                            "该授权之后用户又明确表示不要恢复/启用 Mae-Flow；"
                            "旧消息 ID 已撤销，请以最新用户意图为准")
                    return text, ""
                matched_without_intent = True
    if matched_without_intent:
        return "", ("对应用户消息没有明确要求恢复/重新启用 Mae-Flow；"
                    "普通改码请求不能被 Agent 解释成重新接管")
    if message_id:
        return "", "消息 ID %s 没有可验证的用户答案" % message_id
    return "", ("--ack 必须与 Direct 模式捕获到的完整用户原话或按钮答案精确一致")


def _read_exit_record():
    try:
        rec = json.load(open(EXIT_PATH, encoding="utf-8"))
        return rec if isinstance(rec, dict) else {}
    except Exception:
        return {}


def _exit_snapshot_path(rec):
    dst = str((rec or {}).get("snapshot", "") or "")
    return dst, (os.path.join(dst, STATE_PATH) if dst else "")


def _preserve_exit_pointer(rec):
    """Archive the latest pointer, including Direct-mode authorization messages."""
    dst, _saved = _exit_snapshot_path(rec)
    recovery = (dst if dst and os.path.isdir(dst)
                else _unique_exit_dir({"config": {"单号": "restarted"}}))
    os.makedirs(recovery, exist_ok=True)
    target = os.path.join(recovery, "exit-record.json")
    if rec:
        atomic_write_json(target, rec)
    elif not os.path.isfile(target):
        # 损坏指针无法结构化保存时保留原始字节，避免 doctor/冲突收敛丢现场。
        shutil.copy2(EXIT_PATH, target)
    return recovery


def _resume_direct_mode(ack="", message_id=""):
    """恢复退出前现场；直接开发期间若改过源码，只回退到必要的质量链入口。"""
    if not os.path.exists(EXIT_PATH):
        return None
    rec = _read_exit_record()
    _authorized, auth_why = _direct_reentry_authorization(
        rec, ack=ack, message_id=message_id)
    if not _authorized:
        die("当前项目处于普通开发模式，重新启用会恢复门禁，但授权验真失败："
            + auth_why
            + "。先执行 messages 查看真实消息 ID，再使用 "
              "init --message-id <ID>；恢复原流程不要加 --new，开启另一流程加 --new。"
              "禁止移动、重命名或复制 .mae-flow.json.exited——它只是退出指针，"
              "真正状态位于其 snapshot 指向的目录。", 2)
    dst, saved_state = _exit_snapshot_path(rec)
    if not saved_state or not os.path.isfile(saved_state):
        die("退出现场缺少状态快照，不能自动恢复：%s。退出标记仍保留，请交维护人处理。" %
            (saved_state or "(无 snapshot)")
            + " 如用户明确要放弃旧现场开启另一流程，执行 "
              "init --new --message-id <messages输出的ID>；"
              "禁止把 .mae-flow.json.exited 改名成 .mae-flow.json。", 2)
    try:
        st = json.load(open(saved_state, encoding="utf-8"))
    except Exception as exc:
        die("退出状态快照不可解析，不能自动恢复：%s" % exc, 2)

    current_branch = sh("git branch --show-current")
    recorded_branch = str(rec.get("branch", "") or "")
    if recorded_branch and current_branch != recorded_branch:
        die("退出前流程位于分支 %s，当前分支是 %s，不能把旧断点恢复到错误分支。"
            "要续原流程请先 git checkout %s；要保留旧现场开启另一流程则使用 "
            "init --new --message-id <ID>。退出指针尚未消费。"
            % (recorded_branch, current_branch or "(detached/不可读)", recorded_branch), 2)

    changed, err = _source_changed_since(rec.get("head", ""), st)
    if err:
        die("无法判断退出期间的源码变化，不能安全恢复：" + err, 2)
    source_changed = any(_is_source_path(
        p[:-len("(未提交)")] if p.endswith("(未提交)") else p, st)
        for p in (changed or []))
    if source_changed:
        review_state = _development_review(st)
        if review_state:
            item = _checkpoint_current(st)
            if item and item.get("status") in (
                    "push_pending", "review_pending", "commit_pending",
                    "commit_recovery", "reset_pending"):
                item["status"] = "coding"
                for key in ("receipt", "head", "compile_head",
                            "compile_task_sha256"):
                    item.pop(key, None)
            review_state.pop("final_review", None)
    old_step = st.get("current", "")
    workflow = (st.get("choices", {}) or {}).get("workflow", "")
    target = old_step
    if source_changed:
        if workflow == "review" and old_step in (
                "rf_compile", "rf_codecheck", "rf_ut",
                "delivery_review", "push", "end"):
            target = "rf_compile"
        elif workflow == "tweak" and old_step in (
                "tw_compile", "tw_codecheck", "tw_ut", "tw_verify",
                "delivery_review", "archive_confirm", "archive", "push", "end"):
            target = "tw_compile"
        elif old_step in ("verify_ponytail", "verify_post_ponytail_compile", "verify_recompile",
                          "verify_codecheck", "verify_ut", "verify_comet",
                          "delivery_review", "archive_confirm", "archive", "push", "end"):
            if _spec_phase(st) == "archive":
                ok, why = _reopen_spec_archive(st)
                if not ok:
                    die("源码已变化且交付处于定稿阶段，但正规回退失败；尚未重新启用：" + why, 2)
            target = "verify_recompile"

    for path in _state_sidecars():
        if os.path.exists(path):
            os.remove(path)
    st.pop("unlock", None)
    st.pop("agent_tasks", None)
    st.pop("quality", None)
    st.pop("risk_acceptances", None)
    # 接回的是普通交互模式:退出快照可能带着月光宝盒标记(夜跑中途 exit)。
    # 不清掉的话恢复后每次 AskUserQuestion 都被 hook 硬拦,用户毫无提示。
    # 想继续无人值守应重新明确执行 moonlight on。
    if (st.get("moonlight") or {}).get("enabled"):
        st.pop("moonlight", None)
        print("[mae-flow] 退出前处于月光宝盒模式,已随恢复切回普通交互;"
              "需要继续无人值守请重新执行 moonlight on。")
    st["current"] = target
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    st.setdefault("history", []).append({"step": old_step, "result": "resumed:" + target,
                                          "note": "direct-source-changed" if source_changed else "no-source-change",
                                          "at": now})
    if target != old_step:
        st.setdefault("step_heads", {})[target] = rec.get("head", "")
    dst = _preserve_exit_pointer(rec)
    save_state(st)
    remove_with_retry(EXIT_PATH)
    print("[mae-flow] 已重新启用流程，退出现场仍保留在 %s；旧 agent/CodeCheck 令牌已清空。"
          % (dst or ".mae-flow-work/exited/"))
    if target != old_step:
        print("检测到退出期间改过源码：%s → %s，重新执行后续质量链。" % (old_step, target))
    return st


def _start_new_from_direct(flow, ack="", message_id=""):
    """Keep the exited snapshot for audit and deliberately start another flow."""
    if not os.path.exists(EXIT_PATH):
        die("当前没有已退出流程，init --new 无需使用；直接执行 init。", 2)
    rec = _read_exit_record()
    _authorized, auth_why = _direct_reentry_authorization(
        rec, ack=ack, message_id=message_id)
    if not _authorized:
        die("开启另一流程的授权验真失败：" + auth_why
            + "。先执行 messages，再用 init --new --message-id <ID>。"
              "禁止手工移动 .mae-flow.json.exited。", 2)

    # 先完成可能失败的环境前检和旧辅助状态清理，再消费退出指针。任何失败都仍
    # 保持 Direct 模式，用户可原样重试，不留下半初始化现场。
    try:
        prepare_project(os.getcwd())
    except CapabilityError as exc:
        die("插件运行时预检失败，旧退出现场和指针均未改动：%s。"
            "解决环境问题后原样重试 init --new。" % exc, 2)
    _clear_auxiliary_state()

    dst, saved_state = _exit_snapshot_path(rec)
    dst = _preserve_exit_pointer(rec)
    previous = None
    if saved_state and os.path.isfile(saved_state):
        try:
            previous = json.load(open(saved_state, encoding="utf-8"))
        except Exception:
            previous = None
    if previous:
        sid = previous.get("current", "")
        terminal = bool(flow.get("steps", {}).get(sid, {}).get("terminal"))
        _append_history(
            previous,
            outcome=("已完成后开启新流程" if terminal else
                     "用户保留退出现场并开启另一流程"))
        if terminal:
            # 终态换单仍维持 .last 语义，review-fix 可继承上一轮配置。
            atomic_write_json(STATE_PATH + ".last", previous)
    # 根指针由 cmd_init 在新主状态成功写盘后再消费；中途任何异常都会继续
    # 保持 Direct 模式，避免“旧现场还在但恢复入口消失”的半完成状态。
    return previous, dst


def _terminal_rollover_message(st, message_id="", ack=""):
    """Select a fresh terminal Slash request to carry into the next round."""
    rows = [
        item for item in _captured_user_messages(st)
        if item.get("step") == st.get("current")
    ]
    if message_id:
        rows = [item for item in rows if item.get("id") == message_id]
        if not rows:
            die("终态换轮找不到消息 ID %s。无需 exit/goto/skip；执行 messages "
                "查看本条 Slash 命令 ID，或直接执行 init 自动开启下一轮。"
                % message_id, 2)
    elif ack:
        needle = re.sub(r"\s+", "", ack)
        rows = [
            item for item in rows
            if needle in _trusted_answer_candidates(
                str(item.get("text", "") or ""))
        ]
        if not rows:
            die("终态换轮的 --ack 与本步骤用户原话不匹配。无需退出；"
                "直接执行 init 即可自动归档上一单并开启下一轮。", 2)
    else:
        cutoff = time.time() - 600
        rows = [
            item for item in rows
            if float(item.get("epoch", 0) or 0) >= cutoff
            and _direct_reentry_decision(
                str(item.get("text", "") or "")) == "allow"
        ]
    if not rows:
        return None
    row = dict(rows[-1])
    if _direct_reentry_decision(
            str(row.get("text", "") or "")) != "allow":
        die("消息没有明确要求开启 Mae-Flow 新轮次。终态门禁已解除，"
            "普通开发请求不应被 Agent 擅自解释成 init。", 2)
    return row


def cmd_init(flow, args):
    action = _load_action()
    if action:
        die("独立任务 %s(%s) 尚未收尾。先 action finish 或 action cancel；"
            "独立任务不会自动升级成完整流程。" % (
                action.get("id", "?"), action.get("kind", "?")), 2)
    live_before = load_state()
    has_exit = os.path.exists(EXIT_PATH)
    new_exit_snapshot = ""
    terminal_live = bool(
        live_before and flow.get("steps", {}).get(
            live_before.get("current", ""), {}).get("terminal"))
    rollover_message = (
        _terminal_rollover_message(
            live_before, getattr(args, "message_id", "") or "",
            args.ack or "")
        if terminal_live else None
    )
    if (not live_before and not has_exit
            and (getattr(args, "message_id", None) or args.ack)):
        die("当前没有退出指针，--message-id/--ack 已失效，不能悄悄改成新建流程。"
            "若确实要开启全新流程，请去掉这两个参数后执行 init；"
            "若原本要恢复旧现场，请先用 doctor 查明退出指针为何不存在。", 2)
    if getattr(args, "new", False) and live_before and not terminal_live:
        die("当前仍有完整流程状态，init --new 不会覆盖它。先查看 current/status；"
            "确需放弃时走 /mae-flow:mae-flow exit 留存现场，再用 Direct 模式的 messages + "
            "init --new --message-id。禁止删除或改名状态文件。", 2)
    if getattr(args, "new", False) and terminal_live:
        print("[mae-flow] 当前已是交付终态；已将 init --new 归一化为终态换轮。"
              "无需 exit/goto/skip，上一单会自动归档为 .mae-flow.json.last。")
    if getattr(args, "new", False) and not terminal_live:
        _previous, new_exit_snapshot = _start_new_from_direct(
            flow, args.ack or "", getattr(args, "message_id", "") or "")
    elif not live_before:
        resumed = _resume_direct_mode(
            args.ack or "", getattr(args, "message_id", "") or "")
        if resumed is not None:
            # 退出现场本身已经终态时，“重新启用”不能只恢复到 end 然后原地
            # 返回；继续走下面既有终态滚动逻辑，自动备份 .last 并开启下一轮。
            if not flow["steps"].get(resumed.get("current"), {}).get("terminal"):
                print_current(flow, resumed)
                return
    old = load_state()
    # --new 在终态只是兼容性别名，并没有经过 Direct 的预检/清理路径；
    # 仍须像普通终态 init 一样执行 prepare_project。
    prepared = bool(getattr(args, "new", False) and not terminal_live)
    auxiliary_cleared = prepared
    if old:
        sid = old.get("current")
        if flow["steps"].get(sid, {}).get("terminal"):
            if not prepared:
                try:
                    prepare_project(os.getcwd())
                except CapabilityError as exc:
                    die("插件运行时预检失败，上一单状态和退出指针均未改动：%s" % exc, 2)
                prepared = True
            _clear_auxiliary_state()
            auxiliary_cleared = True
            _append_history(old)
            if os.path.exists(EXIT_PATH):
                # FLOW 与 EXIT 冲突时有效主状态优先。终态 init 已获开启下一轮授权，
                # 消费陈旧退出指针前仍把它留到过程区，绝不让旧 snapshot 覆盖主状态。
                stale = _preserve_exit_pointer(_read_exit_record())
                remove_with_retry(EXIT_PATH)
                print("[mae-flow] 已收敛陈旧退出指针，旧记录保留在 %s。"
                      % norm(stale))
            os.replace(STATE_PATH, STATE_PATH + ".last")
            print(f"[mae-flow] 上一单({old.get('config', {}).get('单号', '?')})已交付完成,"
                  f"旧状态备份为 {STATE_PATH}.last,开启新流程。")
        else:
            die(f"流程已存在(进行中,当前步骤 {sid}),查看用 status。"
                "不要删除或改名状态文件；确要放弃并开启另一流程，先执行 /mae-flow:mae-flow exit "
                "留存现场，再按 Direct 模式 messages 输出使用 init --new。", 2)
    if not prepared:
        try:
            prepare_project(os.getcwd())
        except CapabilityError as exc:
            die("插件运行时预检失败，尚未创建流程状态，因此不会拦截普通开发: %s" % exc, 2)
    if not auxiliary_cleared:
        _clear_auxiliary_state()
    _gitignore()
    dirty = _dirty_paths()
    st = {"current": flow["start"], "config": {}, "choices": {},
          "protocols": {"development_checkpoints": 1},
          "history": [], "started": time.strftime("%Y-%m-%d %H:%M:%S"),
          "initial_dirty": dirty,
          "initial_dirty_fingerprints": {p: _path_fingerprint(p) for p in dirty}}
    atomic_write_json(AGENT_WRITES_PATH, {"paths": {}})
    save_state(st)
    if rollover_message:
        carried = dict(rollover_message)
        carried["carried_from_step"] = carried.get("step", "end")
        carried["step"] = st["current"]
        carried.pop("config_review_sha256", None)
        carried.pop("config_review_id", None)
        atomic_write_json(STATE_PATH + ".usermsg", [carried])
        print("[mae-flow] 已把本条 Slash 请求带入新轮，可通过 messages 查看原文。")
    if new_exit_snapshot and os.path.exists(EXIT_PATH):
        remove_with_retry(EXIT_PATH)
        print("[mae-flow] 已按用户明确授权开启另一流程；旧退出现场继续保留在 %s。"
              % norm(new_exit_snapshot))
    print("[mae-flow] 流程已初始化；内置规格引擎已就绪，未创建项目级 Skill。")
    print_current(flow, st)


def _capability_arguments(args):
    values = list(getattr(args, "arguments", []) or [])
    return values[1:] if values[:1] == ["--"] else values


def cmd_capability(args):
    action = args.capability_action
    if action == "status":
        checks = capability_diagnostics(
            os.getcwd(), include_codecheck=bool(args.codecheck))
        for check in checks:
            print("%s %s — %s" % (
                "✅" if check["ok"] else "❌",
                check["name"], check["detail"]))
        if not all(item["ok"] for item in checks
                   if item["name"] != "CodeCheck"):
            sys.exit(2)
        return
    if action == "prepare":
        try:
            result = prepare_project(os.getcwd())
        except CapabilityError as exc:
            die("插件运行时预检失败: " + str(exc), 2)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if action == "codecheck":
        result = ensure_codecheck(install=bool(args.install))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["available"]:
            sys.exit(2)
        return
    try:
        if action == "openspec":
            arguments = _capability_arguments(args)
            sub = next((a for a in arguments if a and not a.startswith("-")), "")
            # archive 是不可逆动作(delta 合并进真相源+移动 change 目录),必须钉在
            # archive 步:透传通道曾是真相源写保护之外的第三条未设防写路,
            # verify 链任意步一条命令即可绕过用户定稿确认。
            if sub == "archive":
                st_now = None
                try:
                    st_now = load_state()
                except Exception:
                    st_now = None
                if st_now is not None and st_now.get("current") != "archive":
                    die("规格定稿(archive)只能在 archive 步执行:它把规格合并进真相源并移动"
                        "变更目录,不可逆;绕过验证链与 archive_confirm 用户确认等于伪造交付状态。"
                        "当前步骤 %s;先完成验证链并经用户确认定稿。"
                        % st_now.get("current", "?"), 2)
            if sub == "init":
                die("openspec init 由插件统一执行:手动 init 可能生成 AI 工具目录污染仓库。"
                    "需要重建规格配置时执行 capability prepare。", 2)
            result = run_openspec(arguments, cwd=os.getcwd())
        else:
            comet_action = action.replace("comet-", "")
            result = run_comet(
                comet_action, _capability_arguments(args), cwd=os.getcwd())
    except CapabilityError as exc:
        die("内嵌能力执行失败: " + str(exc), 2)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode:
        sys.exit(result.returncode)


def _gitignore():
    gi = ".gitignore"
    # .mae-flow.json* 含 .tmp 原子写中间件与 .last 交付备份;历史账本单列(pattern 不覆盖)
    lines = [".mae-flow.json*", EXIT_PATH, HISTORY_PATH, ".mae-flow-work/"]
    # errors=replace:用户仓的 .gitignore 可能是 GBK 注释,严格解码会让 init 直接
    # 崩 traceback(且报错看不出和 .gitignore 有关);替换字符只影响去重判断,无害。
    txt = (open(gi, encoding="utf-8", errors="replace").read()
           if os.path.exists(gi) else "")
    existing = {
        line.strip() for line in txt.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    add = [line for line in lines if line not in existing]
    if add:
        open(gi, "a", encoding="utf-8").write(
            ("\n" if txt and not txt.endswith("\n") else "") + "\n".join(add) + "\n")
    _gitattributes()


def _gitattributes():
    """openspec/ 锁 LF:comet 的 bash 侧读 .comet.yaml 不剥 \\r,Windows autocrlf
    检出会让 comet 读到 "pass\\r" 全线报 Invalid,而 mae-flow 侧证据解析对 \\r 免疫
    ——症状是「done 说证据满足、comet 命令全报错」的双状态机分裂。"""
    ga = ".gitattributes"
    line = "openspec/** text eol=lf"
    try:
        txt = (open(ga, encoding="utf-8", errors="replace").read()
               if os.path.exists(ga) else "")
        existing = {
            item.strip() for item in txt.splitlines()
            if item.strip() and not item.lstrip().startswith("#")
        }
        if line in existing:
            return
        open(ga, "a", encoding="utf-8", newline="\n").write(
            ("\n" if txt and not txt.endswith("\n") else "")
            + "# mae-flow: comet 状态文件必须 LF(CRLF 检出会造成阶段状态读取分裂)\n"
            + line + "\n")
    except OSError as exc:
        print("[mae-flow] ⚠ 无法写 .gitattributes(%s);Windows autocrlf 环境请手动加入: %s"
              % (exc, line), file=sys.stderr)


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
            die("无法记录评审意见处理基点 HEAD,拒绝进入本轮修改。", 2)
        st["review_base_head"] = base
    # 兼容旧版已经停在 rf_verify 的在途单：按 history 自动恢复返工前 HEAD。
    if sid == "rf_verify" and st.get("choices", {}).get("workflow") == "review":
        _, err = _ensure_review_base(st)
        if err:
            die(err, 2)
    if sid == "rf_triage":
        review_doc = "docs/review/REVIEW-" + st.get("config", {}).get("单号", "") + ".md"
        try:
            review_text = open(review_doc, encoding="utf-8", errors="replace").read()
        except OSError as exc:
            die("无法冻结评审裁决快照:" + str(exc), 2)
        st["review_triage_statuses"] = _review_statuses(review_text)
        st["review_triage_transfer_count"] = _review_status_count(
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
        die(f"月光旁路步骤 {exc.step_id} 缺少可解析的 moonlight_choice/next，拒绝卡死流程。", 2)
    if _moonlight(st) and sid == "push":
        _moonlight_resolve_kind(st, "push")
        ml = _moonlight_data(st)
        ml["pushed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        ml["pushed_head"] = sh("git rev-parse --verify HEAD")
    st["current"] = nxt
    if nxt:
        st.setdefault("step_heads", {})[nxt] = sh("git rev-parse --verify HEAD")
    save_state(st)
    if _moonlight(st) and nxt == "moonlight_review":
        _write_moonlight_report(flow, st)
    print(f"[mae-flow] {sid} {tag} → 进入 {nxt}\n")
    print_current(flow, st)


def _validated_pending_config(step, st, set_values):
    """Build and fully validate a candidate without touching confirmed config."""
    sid = st["current"]
    # 配置先在内存候选副本里完成全部校验；任何一步失败都不污染已确认状态。
    # 旧实现遇到需求路径不存在会先 save_state，导致下一轮继续携带半套/乱码配置。
    pending_config = dict(st.get("config", {}) or {})
    allowed_sets = _allowed_set_keys(step)
    for kv in set_values or []:
        if "=" not in kv:
            die(f"--set 需为 k=v 形式: {kv}")
        k, v = kv.split("=", 1)
        if k not in allowed_sets:
            die(f"当前步骤 {sid} 不允许写配置项「{k}」。已确认配置不能在后续步骤偷偷改写；"
                "确需调整请经用户确认 goto config_confirm 后修改。", 2)
        bad = _validate_config_value(k, v)
        if bad:
            die(f"{k}「{v}」不合法:{bad}。", 2)
        pending_config[k] = v
    if pending_config.get("单号") and not pending_config.get("单号类型"):
        pending_config["单号类型"] = "feat" if pending_config["单号"].startswith("REQ") else "fix"
    # 需求文档:单号与需求完全解耦(单号只管 git 命名,需求只管做什么),内容对不对只有用户能判定,
    # 机器只拦"路径是假的"这一种硬错;"拿对文档"靠 config_confirm 的单独确认(展示摘录给用户核实)
    new_keys = [kv.split("=", 1)[0] for kv in (set_values or []) if "=" in kv]
    doc = pending_config.get("需求文档", "")
    if "需求文档" in new_keys and not os.path.exists(doc):
        die(f"需求文档「{doc}」不存在——路径必须真实可读。"
            "用户口述/粘贴的需求须先原文照录落盘(如 docs/req/REQ-<单号>.md)并经用户确认,再以该路径 --set。", 2)
    if doc and ("需求文档" in new_keys or sid == "config_confirm"):
        ok, why = _validate_requirement_document(doc)
        if not ok:
            die(f"需求文档「{doc}」未通过严格文本校验:{why}。"
                "不要让用户重复说“我确认”，确认无法修复坏文件；"
                "用户口述用 messages + requirement-record --message-id，"
                "已有 GBK/UTF-16 文本用 requirement-record --source 规范化。", 2)
    if step.get("require_sets"):
        missing = [k for k in step["require_sets"] if not pending_config.get(k)]
        if missing:
            remedy = ("用 --set 补齐；月光模式禁止询问用户，只能从本轮需求原话、仓库预设、"
                      "当前分支和代码事实中保守取得，不能编造"
                      if _moonlight(st) else "用 --set 补齐;缺失项应询问用户")
            die("配置缺失,禁止推进: " + "、".join(missing) + "(" + remedy + ")", 2)
        if "基线分支" in step["require_sets"]:
            derived_branch = "{基线分支}_{工号}_{单号}".format(**pending_config)
            bad = _validate_config_value("分支名", derived_branch)
            if bad:
                die("脚本按基线分支、工号和单号生成的分支名「%s」不合法:%s。"
                    "请修正组成字段后重新确认，不能带着非法 ref 进入后续步骤。"
                    % (derived_branch, bad), 2)
            supplied_branch = pending_config.get("分支名", "")
            if supplied_branch and supplied_branch != derived_branch:
                die(
                    "分支名无需 Agent 拼接，脚本按基线分支、工号和单号确定生成。"
                    "收到的分支名「%s」与应为的「%s」不一致；删除该 --set 后重试。"
                    % (supplied_branch, derived_branch), 2)
            pending_config["分支名"] = derived_branch
    return pending_config


def _config_review_excerpt(path):
    try:
        text = open(path, encoding="utf-8").read()
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
        die("config-review 只用于配置确认阶段。其他步骤的已确认配置不能偷偷改写。", 2)
    if _moonlight(st):
        die("月光宝盒不询问用户，不需要 config-review；按 current 指令保守补齐配置后直接 done。", 2)
    step = flow["steps"]["config_confirm"]
    pending = _validated_pending_config(step, st, args.set or [])
    requirement_sha = _requirement_sha256(pending.get("需求文档", ""))
    digest = _config_sha256(pending, requirement_sha)
    review_id = hashlib.sha256(
        (digest + "\0" + str(time.time_ns())).encode("utf-8")).hexdigest()[:16]
    st["config_review"] = {
        "step": "config_confirm",
        "id": review_id,
        "sha256": digest,
        "config": pending,
        "requirement_sha256": requirement_sha,
        "head": sh("git rev-parse --verify HEAD"),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_state(st)
    _ack_failure(st, success=True)

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


def _activate_checkpoint_plan(st, mode):
    data = _development_review(st)
    head = sh("git rev-parse --verify HEAD")
    data.update({
        "status": "active",
        "mode": mode,
        "delivery_base": head,
        "last_reviewed_head": head,
        "current_index": 0,
        "configured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    no_code = bool(data.get("no_code_plan"))
    for index, item in enumerate(data.get("checkpoints") or []):
        for key in ("head", "compile_head", "compile_task_sha256",
                    "receipt", "accepted_head", "completed_head"):
            item.pop(key, None)
        item["status"] = (
            ("accepted" if mode == "staged" else "completed")
            if no_code else "coding")
        item["attempt"] = 1
        item["fixed_base"] = head if index == 0 else ""
        if no_code:
            item["completed_head"] = head
            if mode == "staged":
                item["accepted_head"] = head
    if no_code:
        data["current_index"] = len(data.get("checkpoints") or [])


def cmd_checkpoint_plan(st, args):
    if st.get("current") not in PACE_STEPS:
        die("checkpoint plan 只允许在开发节奏确认步骤执行；先按 current 完成方案/范围分析。", 2)
    if _moonlight(st):
        die("月光宝盒不需要人工开发节奏方案；状态机会自动旁路本步骤。", 2)
    items = [re.sub(r"\s+", " ", str(x or "")).strip()
             for x in (args.item or [])]
    if not 1 <= len(items) <= 6 or any(len(x) < 2 for x in items):
        die("检查点必须给出 1-6 个非空 --item；小改可 1 个，常规任务建议 2-4 个。", 2)
    if len(set(items)) != len(items):
        die("检查点标题/范围不能重复；请写出各批次可区分的业务边界。", 2)
    dirty = _blocking_dirty_source_paths(st, FLOW)
    if dirty:
        die("开发节奏必须在写第一行代码前确认；当前已有本轮未提交源码: "
            + "、".join(dirty[:8]) + "。先归因并处理，再重新生成方案。", 2)
    task_sha, task_lines = _task_structure_fingerprint(st)
    head = sh("git rev-parse --verify HEAD")
    checkpoints = [
        {"id": "CP%d" % (i + 1), "title": title, "status": "planned"}
        for i, title in enumerate(items)
    ]
    plan_body = json.dumps({
        "head": head, "task_sha256": task_sha,
        "items": [{"id": x["id"], "title": x["title"]} for x in checkpoints],
    }, ensure_ascii=False, sort_keys=True)
    st["development_review"] = {
        "version": 1,
        # New deliveries freeze the uncommitted IDE diff first.  The explicit
        # flag preserves old in-flight version-1 states on their proven route.
        "review_before_commit": True,
        "status": "plan_pending",
        "plan_step": st.get("current"),
        "plan_head": head,
        "plan_sha256": hashlib.sha256(plan_body.encode("utf-8")).hexdigest(),
        "task_structure_sha256": task_sha,
        "task_count": len(task_lines),
        "ack_cursor": _ack_message_cursor(),
        "no_code_plan": (
            (st.get("choices", {}) or {}).get("workflow") == "review"
            and not task_lines),
        "checkpoints": checkpoints,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_state(st)
    print("[mae-flow] 开发检查点方案（确认前尚未开始写码）")
    print("  代码基点: " + head[:10])
    print("  实现/评审任务数: %d（勾选状态和备注不计入结构指纹）" % len(task_lines))
    for item in checkpoints:
        print("  %s — %s" % (item["id"], item["title"]))
    print("\n用 AskUserQuestion 提供三个固定选项：")
    print("  - 按检查点分阶段开发、检视确认后提交并推送")
    print("  - 一次完成全部代码，最终统一检视")
    print("  - 调整检查点划分")
    print("用户点选后执行 done --choice staged|continuous|adjust；"
          "月光宝盒不会进入此确认。")


def _checkpoint_plan_drift(st):
    data = _development_review(st) or {}
    current_sha, _ = _task_structure_fingerprint(st)
    planned = str(data.get("task_structure_sha256", ""))
    return bool(planned and current_sha != planned)


def _checkpoint_source_fresh(head, st):
    changed, err = _source_changed_since(head, st)
    if err:
        return False, "代码基点无法核实:" + err
    if changed:
        return False, "代码发生变化:" + "、".join(changed[:8])
    return True, ""


def _print_checkpoint_decisions(final=False):
    print("\n展示完整 diff、关键风险和自验证方式后，用 AskUserQuestion 提供：")
    print("  - " + CHECKPOINT_CONTINUE_ACK)
    print("  - " + CHECKPOINT_REVISE_ACK)
    if not final:
        print("  - " + CHECKPOINT_CONTINUOUS_ACK)
    print("点选后执行 checkpoint decide continue|revise"
          + ("" if final else "|continuous") + ' --ack "用户选择原文"。')


def cmd_checkpoint_ready(flow, st, args):
    data = _development_review(st)
    if not data or data.get("status") != "active":
        die("当前没有已确认的开发检查点方案；旧版在途流程继续按原有 review 节点执行。", 2)
    if _moonlight(st):
        die("月光宝盒不执行人工检查点；继续按当前质量链无人值守推进。", 2)
    expected_step = _checkpoint_expected_code_step(st)
    if st.get("current") != expected_step:
        die("checkpoint ready 只允许在本工作流编码步骤 %s 执行；当前为 %s。"
            % (expected_step or "(未知)", st.get("current")), 2)
    item = _checkpoint_current(st)
    if not item or item.get("id") != args.checkpoint_id:
        die("当前应处理 %s，不是 %s。先执行 checkpoint status 查看计划。"
            % ((item or {}).get("id", "无剩余检查点"), args.checkpoint_id), 2)
    if item.get("status") not in ("coding",):
        die("%s 当前状态为 %s，不能重复 ready；执行 checkpoint status 查看下一步。"
            % (item["id"], item.get("status", "未知")), 2)
    base = str(item.get("fixed_base") or data.get("delivery_base") or "")
    head = sh("git rev-parse --verify HEAD")
    if (not base or argv_out(["git", "cat-file", "-t", base]) != "commit"
            or argv_out(["git", "merge-base", base, head]) != base):
        die("检查点固定基点不在当前历史上，可能发生 rebase/reset；"
            "不能用改写后的历史冒充原检查点。", 2)
    mode = data.get("mode")
    precommit_review = mode == "staged" and _review_before_commit(data)
    if precommit_review:
        if head != base:
            die("%s 使用“先检视、后提交”，但固定基点之后已经产生提交。"
                "旧提交不能冒充 IDE 未提交 diff；保留现场并让用户决定如何归因，"
                "不要 amend/reset 自动改写历史。" % item["id"], 2)
        snapshot = _checkpoint_worktree_snapshot(st, flow)
        if not snapshot:
            die("%s 没有本轮未提交交付差异；空批次应调整或合并，"
                "不要制造空检视。" % item["id"], 2)
        source_paths = [
            path for path in snapshot
            if _is_source_path(path, st, flow)
        ]
        task = (st.get("agent_tasks", {}) or {}).get("COMPILE", {})
        if source_paths:
            if (task.get("checkpoint") != item["id"]
                    or not task.get("precommit_review")):
                die("最后一次编译任务没有绑定当前未提交检查点 %s。先执行 agent-task "
                    "compile --checkpoint %s --scope \"<本批模块/任务>\"，"
                    "再启动 compile-agent。" % (item["id"], item["id"]), 2)
            ok, why = ev_agent_ran(
                {"agent": "COMPILE", "statuses": ["OK"]}, st)
            if not ok:
                die("检查点编译证据不足:" + why, 2)
        # compile-agent may have made an allowed compile fix.  Freeze the exact
        # post-build worktree that its token just proved, not the task input.
        snapshot = _checkpoint_worktree_snapshot(st, flow)
        receipt = {
            "base": head,
            "snapshot": snapshot,
            "snapshot_sha256": _snapshot_sha256(snapshot),
            "ack_cursor": _ack_message_cursor(),
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        item.update({
            "compile_head": head,
            "compile_task_sha256": (
                task.get("sha256", "") if source_paths else ""),
            "compile_skipped_no_source": not source_paths,
            "head": head,
            "receipt": receipt,
            "status": "review_pending",
            "task_structure_drift": _checkpoint_plan_drift(st),
            "closed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        save_state(st)
        print("\n".join(_checkpoint_worktree_review_lines(item)))
        if item.get("task_structure_drift"):
            print("⚠ 实现清单结构在开发中发生变化，请重点核对新增/删除任务是否仍符合确认范围。")
        _print_checkpoint_decisions(final=False)
        return
    dirty = _blocking_dirty_source_paths(st, flow)
    if dirty:
        die("检查点编译收尾前仍有未提交源码/测试/构建文件: "
            + "、".join(dirty[:8]) + "。只精确提交本批应入库文件后重试。", 2)
    if not argv_out(["git", "log", "-1", "--format=%H", base + ".." + head]):
        die("%s 自固定基点后没有新提交；空批次应调整/合并检查点，不制造空检视。"
            % item["id"], 2)
    ok, why = ev_commit_tagged({}, st)
    if not ok:
        die("检查点最新提交格式不合规:" + why, 2)
    source_files = [
        path for path in argv_out([
            "git", "-c", "core.quotepath=false", "diff", "--name-only",
            base, head]).splitlines()
        if path and _is_source_path(path, st, flow)
    ]
    task = (st.get("agent_tasks", {}) or {}).get("COMPILE", {})
    if source_files:
        if task.get("checkpoint") != item["id"]:
            die("最后一次编译任务没有绑定当前检查点 %s。先执行 agent-task compile "
                "--checkpoint %s --scope \"<本批模块/任务>\"，再启动 compile-agent。"
                % (item["id"], item["id"]), 2)
        ok, why = ev_agent_ran({"agent": "COMPILE", "statuses": ["OK"]}, st)
        if not ok:
            die("检查点编译证据不足:" + why, 2)
    item.update({
        # ev_agent_ran has just proved the token still covers current source.
        # The task-card head predates compile-agent fixes, so freezing it here
        # would falsely treat the agent's own committed repair as post-compile.
        "compile_head": head,
        "compile_task_sha256": task.get("sha256", "") if source_files else "",
        "compile_skipped_no_source": not source_files,
        "head": head,
        "task_structure_drift": _checkpoint_plan_drift(st),
        "closed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    if mode == "continuous":
        item["status"] = "completed"
        item["completed_head"] = head
        data["current_index"] = int(data.get("current_index", 0)) + 1
        nxt = _checkpoint_current(st)
        if nxt:
            nxt["fixed_base"] = head
        save_state(st)
        print("[mae-flow] %s 已编译并记录范围 %s..%s；连续模式不 push、不等待，直接进入%s。"
              % (item["id"], base[:10], head[:10],
                 (" " + nxt["id"]) if nxt else "编码收尾"))
        if item.get("task_structure_drift"):
            print("⚠ 实现清单结构较确认时有变化，最终检视会显式标注；"
                  "若业务边界发生实质变化，应主动呈用户调整计划。")
        return
    item["status"] = "push_pending"
    save_state(st)
    print("[mae-flow] %s 编译通过，已冻结候选范围 %s..%s。现在小步推送："
          % (item["id"], base[:10], head[:10]))
    print("  git push -u origin HEAD")
    print("推送成功后执行 checkpoint status；系统会核对真实上游 HEAD 后才开始检视。")


def _refresh_staged_checkpoint(st, item):
    fresh, why = _checkpoint_source_fresh(item.get("compile_head", ""), st)
    if not fresh:
        item["status"] = "coding"
        item.pop("receipt", None)
        return False, "编译后" + why + "；已回到当前批次，重新提交并编译"
    head = sh("git rev-parse --verify HEAD")
    # 文档提交不会使编译证据失效，但远端/检视收据必须冻结真实 HEAD。
    item["head"] = head
    ref, remote_head, local_head = _upstream_snapshot()
    if not ref:
        return False, "当前分支没有上游；执行 git push -u origin HEAD"
    if remote_head != local_head:
        return False, (
            "本地与上游不一致（本地 %s，%s=%s）。执行普通 git push；"
            "若远端领先，禁止自动 rebase/force-push，先展示分叉。"
            % (local_head[:10], ref, remote_head[:10] if remote_head else "未知"))
    item["status"] = "review_pending"
    item["receipt"] = {
        "base": item.get("fixed_base", ""),
        "head": local_head,
        "remote_ref": ref,
        "remote_head": remote_head,
        "ack_cursor": _ack_message_cursor(),
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    return True, ""


def _reviewed_snapshot_current(st, item):
    receipt = item.get("receipt") or {}
    base = str(receipt.get("base", ""))
    if receipt.get("scope") == "final":
        return _final_delivery_snapshot(st, base)
    return _checkpoint_delivery_snapshot(st, base)


def _reviewed_worktree_fresh(st, item):
    receipt = item.get("receipt") or {}
    base = str(receipt.get("base", ""))
    if sh("git rev-parse --verify HEAD") != base:
        return False, "HEAD 已变化"
    if _reviewed_snapshot_current(st, item) != (receipt.get("snapshot") or {}):
        return False, "未提交 diff 已变化"
    return True, ""


def _checkpoint_commit_command(st, item):
    paths = list(((item.get("receipt") or {}).get("snapshot") or {}).keys())
    add = "git add -- " + " ".join(shlex.quote(path) for path in paths)
    cfg = st.get("config", {}) or {}
    message = "[%s][%s]%s" % (
        cfg.get("单号", ""), cfg.get("单号类型", ""),
        item.get("title", "检查点代码"))
    return add, 'git commit -m %s' % shlex.quote(message)


def _accept_pushed_checkpoint(st, data, item, head):
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    item["status"] = "accepted"
    item["accepted_head"] = head
    item["accepted_at"] = now
    data["last_reviewed_head"] = head
    data["current_index"] = int(data.get("current_index", 0)) + 1
    nxt = _checkpoint_current(st)
    if nxt:
        nxt["fixed_base"] = head
    st.setdefault("history", []).append({
        "step": st.get("current"), "result": "checkpoint:accept:" + item["id"],
        "note": CHECKPOINT_CONTINUE_ACK, "at": now})
    return nxt


def _reviewed_commit_head_error(st, item, head):
    receipt = item.get("receipt") or {}
    base = str(receipt.get("base", ""))
    if head == base:
        add, commit = _checkpoint_commit_command(st, item)
        return "用户已确认，但检视代码尚未提交。依次执行:\n  %s\n  %s" % (
            add, commit)
    if argv_out(["git", "merge-base", base, head]) != base:
        return "提交历史已改写，旧检视收据失效；禁止自动 reset/rebase"
    return ""


def _reviewed_commit_snapshot_error(st, item):
    receipt = item.get("receipt") or {}
    if _reviewed_snapshot_current(st, item) != (receipt.get("snapshot") or {}):
        return (
            "提交后的代码不等于用户检视快照；拒绝继续。保留现场并展示差异，"
            "不要自动 amend/reset")
    return ""


def _commit_path_set_error(expected, actual):
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    details = []
    if missing:
        details.append("漏掉 " + "、".join(missing[:8]))
    if extra:
        details.append("夹带 " + "、".join(extra[:8]))
    return "提交文件集合不等于检视收据：" + "；".join(details)


def _commit_count_error(count):
    shown = count if count else "不可核实"
    return "每个检视检查点必须对应 1 个精确提交，当前产生 %s 个" % shown


def _reviewed_commit_paths_error(item):
    receipt = item.get("receipt", {})
    base = str(receipt.get("base", ""))
    expected = set(receipt.get("snapshot", {}).keys())
    actual = set(argv_out([
        "git", "-c", "core.quotepath=false", "diff",
        "--name-only", "--no-renames", base, "HEAD",
    ]).splitlines())
    if actual != expected:
        return _commit_path_set_error(expected, actual)
    count = argv_out(["git", "rev-list", "--count", base + "..HEAD"])
    if count != "1":
        return _commit_count_error(count)
    return ""


def _reviewed_commit_dirty_error(item):
    receipt = item.get("receipt") or {}
    reviewed = set((receipt.get("snapshot") or {}).keys())
    dirty_reviewed = sorted(reviewed.intersection(_dirty_paths()))
    if dirty_reviewed:
        return "用户已检视文件仍有未提交变化: " + "、".join(
            dirty_reviewed[:8])
    return ""


def _verify_reviewed_checkpoint_commit(st, item):
    head = sh("git rev-parse --verify HEAD")
    errors = [
        _reviewed_commit_head_error(st, item, head),
        _reviewed_commit_snapshot_error(st, item),
        _reviewed_commit_paths_error(item),
        _reviewed_commit_dirty_error(item),
    ]
    for error in errors:
        if error:
            return "", error
    ok, why = ev_commit_tagged({}, st)
    if not ok:
        return "", "检视后提交格式不合规:" + why
    return head, ""


def _complete_continuous_checkpoint(data, item, head):
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    data["mode"] = "continuous"
    item["status"] = "completed"
    item["completed_head"] = head
    item["closed_at"] = now
    data["current_index"] = int(data.get("current_index", 0)) + 1
    nxt = _checkpoint_current({"development_review": data})
    if nxt:
        nxt["fixed_base"] = head
    return (
        "已切换为一次完成模式；当前内部提交将在质量链后与剩余代码统一检视。"
        + (("进入 " + nxt["id"]) if nxt else "全部检查点已完成"))


def _checkpoint_already_pushed():
    ref, remote_head, local_head = _upstream_snapshot()
    return bool(ref and remote_head == local_head), local_head


def _accepted_checkpoint_message(item, nxt):
    suffix = ("进入 " + nxt["id"]) if nxt else "全部计划检查点已完成"
    return "%s 的检视快照、精确提交和已存在的远端 push 均已核对。%s" % (
        item["id"], suffix)


def _refresh_reviewed_checkpoint_commit(st, data, item):
    head, why = _verify_reviewed_checkpoint_commit(st, item)
    if not head:
        return False, why
    item["head"] = head
    item["committed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if item.pop("after_commit_continuous", False):
        return True, _complete_continuous_checkpoint(data, item, head)
    pushed, remote_head = _checkpoint_already_pushed()
    if pushed and remote_head == head:
        nxt = _accept_pushed_checkpoint(st, data, item, head)
        return True, _accepted_checkpoint_message(item, nxt)
    item["status"] = "push_pending"
    return True, (
        "检视确认后的精确提交已核对。现在执行 git push -u origin HEAD；"
        "成功后再执行 checkpoint status。")


def _reviewed_push_local_error(st, item):
    receipt = item.get("receipt") or {}
    head = str(item.get("head", ""))
    if sh("git rev-parse --verify HEAD") != head:
        return "检视后待推送 HEAD 已变化；旧收据不能背书新提交"
    if _reviewed_snapshot_current(st, item) != (receipt.get("snapshot") or {}):
        return "待推送代码不再等于用户检视快照；拒绝继续"
    return ""


def _reviewed_push_remote_error(item):
    head = str(item.get("head", ""))
    ref, remote_head, local_head = _upstream_snapshot()
    if not ref:
        return "当前分支没有上游；执行 git push -u origin HEAD"
    if remote_head != local_head or local_head != head:
        return (
            "本地与上游不一致（本地 %s，%s=%s）。执行普通 git push；"
            "远端领先时禁止自动 rebase/force-push，先展示分叉。"
            % (local_head[:10], ref, remote_head[:10] if remote_head else "未知"))
    return ""


def _verify_reviewed_checkpoint_push(st, item):
    errors = [
        _reviewed_push_local_error(st, item),
        _reviewed_push_remote_error(item),
    ]
    for error in errors:
        if error:
            return "", error
    head = str(item.get("head", ""))
    return head, ""


def _refresh_reviewed_checkpoint_push(st, data, item):
    head, why = _verify_reviewed_checkpoint_push(st, item)
    if not head:
        return False, why
    nxt = _accept_pushed_checkpoint(st, data, item, head)
    return True, "%s 已确认、精确提交并推送。%s" % (
        item["id"], ("进入 " + nxt["id"]) if nxt else "全部计划检查点已完成")


def _refresh_pending_checkpoint_commit(st, data, item):
    ok, why = _refresh_reviewed_checkpoint_commit(st, data, item)
    base = str((item.get("receipt") or {}).get("base", ""))
    if not ok and sh("git rev-parse --verify HEAD") == base:
        print("[mae-flow] " + why)
        return
    if not ok:
        item["status"] = "commit_recovery"
        item["verification_error"] = why
        item.setdefault("receipt", {})["ack_cursor"] = _ack_message_cursor()
        save_state(st)
        print("[mae-flow] 提交核验失败，已禁止 push，现场保持不变："
              + why)
        print("把失败原因和真实 git diff 展示给用户，让用户选择「需要调整代码」；"
              "随后执行 checkpoint decide revise --ack \"需要调整代码\"。")
        return
    save_state(st)
    print("[mae-flow] " + why)


def _refresh_pending_checkpoint_reset(st, item):
    base = str((item.get("receipt") or {}).get("base", ""))
    if sh("git rev-parse --verify HEAD") != base:
        die("恢复尚未完成；执行 git reset --mixed %s，"
            "它只撤销未推送的错误检查点提交并保留工作区内容。" % base, 2)
    item["status"] = "coding"
    item["attempt"] = int(item.get("attempt", 1)) + 1
    for key in ("receipt", "head", "compile_head",
                "compile_task_sha256", "verification_error"):
        item.pop(key, None)
    _invalidate_quality_for_rework(st)
    save_state(st)
    print("[mae-flow] 错误提交已安全拆回工作区，检查点返回 coding；"
          "调整代码后重新生成编译任务和检视收据。")


def _refresh_pending_checkpoint_push(st, data, item):
    ok, why = _refresh_reviewed_checkpoint_push(st, data, item)
    save_state(st)
    if not ok:
        die(why, 2)
    print("[mae-flow] " + why)


def _refresh_precommit_checkpoint_status(st, data, item):
    status = item.get("status")
    if status == "commit_pending":
        _refresh_pending_checkpoint_commit(st, data, item)
        return True
    if status == "reset_pending":
        _refresh_pending_checkpoint_reset(st, item)
        return True
    if status == "push_pending":
        _refresh_pending_checkpoint_push(st, data, item)
        return True
    return False


def _refresh_checkpoint_status(st, data, item):
    if _review_before_commit(data):
        return _refresh_precommit_checkpoint_status(st, data, item)
    if data.get("mode") == "staged" and item.get("status") == "push_pending":
        ok, why = _refresh_staged_checkpoint(st, item)
        save_state(st)
        if not ok:
            die(why, 2)
    return False


def _show_pending_checkpoint_review(st, data, item):
    if _review_before_commit(data):
        fresh, why = _reviewed_worktree_fresh(st, item)
        if not fresh:
            die("检查点收据已失效:" + why
                + "；选择调整后重新编译并生成收据。", 2)
        print("\n".join(_checkpoint_worktree_review_lines(item)))
    else:
        receipt = item.get("receipt") or {}
        print("\n".join(_checkpoint_review_lines(
            receipt.get("base", ""), receipt.get("head", ""),
            "%s 用户代码检视" % item.get("id"),
            receipt.get("remote_ref", ""))))
    if item.get("task_structure_drift"):
        print("⚠ 实现清单结构在开发中发生变化，请重点核对新增/删除任务是否仍符合确认范围。")
    _print_checkpoint_decisions(final=False)


def _show_coding_checkpoint(data, item):
    if data.get("mode") == "staged" and _review_before_commit(data):
        print("当前正在编码 %s；保持代码未提交，绑定本批 compile-agent 通过后执行 "
              "checkpoint ready %s。" % (item["id"], item["id"]))
        return
    print("当前正在编码 %s；完成提交和绑定本批的 compile-agent 后执行 checkpoint ready %s。"
          % (item["id"], item["id"]))


def _show_checkpoint_review(st, data, item):
    if item.get("status") == "review_pending":
        _show_pending_checkpoint_review(st, data, item)
    elif item.get("status") == "coding":
        _show_coding_checkpoint(data, item)


def _final_drifted_checkpoints(data):
    return [
        item.get("id", "?") for item in data.get("checkpoints") or []
        if item.get("task_structure_drift")
    ]


def _show_final_review_mode(data):
    mode = data.get("mode")
    if mode == "continuous":
        print("  模式说明:中途策略是不 push；确认最终整体代码后才进入正式 push。")
    elif mode == "staged":
        print("  模式说明:最终质量增量确认后才进入正式 push；"
              "若已被外部工具提前推送会明确告警。")


def _show_final_review_context(data):
    drifted = _final_drifted_checkpoints(data)
    if drifted:
        print("⚠ 开发期间实现/评审任务结构曾偏离编码前方案（%s）；"
              "请额外核对新增、删除或重排的任务仍符合需求边界。"
              % "、".join(drifted))
    _show_final_review_mode(data)


def _show_final_pending_review(data, final):
    base = str(final.get("base", ""))
    head = str(final.get("head", ""))
    if base != head:
        print("\n".join(_checkpoint_review_lines(
            base, head, "最终未检视代码增量",
            final.get("remote_ref", ""))))
    receipt = final.get("receipt") or {}
    if receipt.get("snapshot"):
        print("\n".join(_checkpoint_worktree_review_lines({
            "id": "最终增量", "receipt": receipt,
        })))
    if final.get("remote_ref"):
        print("⚠ 当前本地 HEAD 已经存在于上游；仍须完成检视，"
              "但不要再次 push 或改写远端历史。")
    _show_final_review_context(data)
    _print_checkpoint_decisions(final=True)


def _show_final_pending_commit(st, final):
    add, commit = _checkpoint_commit_command(st, final)
    print("最终未提交增量已经用户确认；只允许提交该检视快照：")
    print("  " + add)
    print("  " + commit)
    print("提交后执行 checkpoint status 核验；核验通过后会回流完整质量链。")


def _show_final_commit_recovery(final):
    print("最终增量提交核验失败，push 已冻结："
          + str(final.get("verification_error", "未知原因")))
    print("展示真实差异并让用户选择「需要调整代码」，"
          "再执行 checkpoint decide revise。")


def _show_final_reset_pending(final):
    base = str(((final.get("receipt") or {}).get("base", "")))
    print("用户已授权拆回错误的最终增量提交；执行 git reset --mixed "
          + base + "，随后 checkpoint status。")


def _show_legacy_final_push_pending():
    print("检测到旧版“先 push、后最终检视”的在途状态；执行 checkpoint status "
          "会原地迁移为本地先检视，不需要先 push。")


def _show_final_review_receipt(st, data, final):
    handlers = {
        "review_pending": lambda: _show_final_pending_review(data, final),
        "commit_pending": lambda: _show_final_pending_commit(st, final),
        "commit_recovery": lambda: _show_final_commit_recovery(final),
        "reset_pending": lambda: _show_final_reset_pending(final),
        "push_pending": _show_legacy_final_push_pending,
    }
    handler = handlers.get(final.get("status"))
    if handler:
        handler()


def _final_review_active(data):
    final = (data or {}).get("final_review")
    if not isinstance(final, dict):
        return None
    return final if final.get("status") in CHECKPOINT_LOCKED_STATUSES else None


def _final_rework_target(flow, st):
    workflow = (st.get("choices", {}) or {}).get("workflow", "")
    target = CHECKPOINT_CODE_STEPS.get(workflow, "")
    if not target:
        die("无法确定返工编码入口，workflow=" + (workflow or "未设置"), 2)
    return target


def _activate_final_rework(flow, st, data, final, context=None):
    context = context or {}
    target = _final_rework_target(flow, st)
    reopened, reopen_why = _reopen_spec_archive(st)
    if not reopened:
        die("最终检视返工无法回退规格验证阶段:" + reopen_why, 2)
    reviewed_head = context.get("reviewed_head", "")
    if reviewed_head:
        data["last_reviewed_head"] = reviewed_head
    data.pop("final_review", None)
    data["final_rework"] = {
        "status": "coding",
        "base": final.get("base", ""),
        "rejected_head": final.get("head", ""),
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    st["current"] = target
    st.setdefault("step_heads", {})[target] = (
        context.get("step_base") or sh("git rev-parse --verify HEAD"))
    _invalidate_quality_for_rework(st)
    st.setdefault("history", []).append({
        "step": "delivery_review",
        "result": "checkpoint:rework-final",
        "note": context.get("note", ""),
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    save_state(st)
    return target


def _final_commit_recovery(st, final, why):
    final["status"] = "commit_recovery"
    final["verification_error"] = why
    final["ack_cursor"] = _ack_message_cursor()
    save_state(st)
    print("[mae-flow] 最终增量提交核验失败，已禁止 push，现场保持不变："
          + why)
    print("展示真实差异，让用户选择「需要调整代码」后执行 "
          "checkpoint decide revise。")


def _handle_missing_final_commit(st, final, why):
    base = str((final.get("receipt") or {}).get("base", ""))
    if sh("git rev-parse --verify HEAD") == base:
        print("[mae-flow] " + why)
        return
    _final_commit_recovery(st, final, why)


def _finish_final_commit(st, data, final, head):
    final["head"] = head
    final["status"] = "accepted"
    final["accepted_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if final.get("requires_quality_rerun"):
        commit_base = str((final.get("receipt") or {}).get("base", ""))
        target = _activate_final_rework(
            FLOW, st, data, final, {
                "note": "用户检视后的最终工作区提交已核对，重新执行完整质量链",
                "reviewed_head": head,
                "step_base": commit_base,
            })
        print("[mae-flow] 用户检视后的精确提交已核对；为防止未验证代码直达 push，"
              "已回到 %s 重新执行编译和完整质量链。" % target)
        return
    data["last_reviewed_head"] = head
    save_state(st)
    print("[mae-flow] 最终检视提交已核对；执行 done 进入规格定稿/最终 push。")


def _refresh_final_pending_commit(st, data, final):
    head, why = _verify_reviewed_checkpoint_commit(st, final)
    if not head:
        _handle_missing_final_commit(st, final, why)
        return
    _finish_final_commit(st, data, final, head)


def _refresh_final_pending_reset(st, data, final):
    base = str((final.get("receipt") or {}).get("base", ""))
    if sh("git rev-parse --verify HEAD") != base:
        die("恢复尚未完成；执行 git reset --mixed %s。该命令保留工作区内容。"
            % base, 2)
    target = _activate_final_rework(
        FLOW, st, data, final, {
            "note": "错误的最终增量提交已拆回工作区，重新执行完整质量链",
        })
    print("[mae-flow] 错误提交已拆回工作区并保留文件内容；已回到 %s，"
          "调整后重新编译、检查和检视。" % target)


def _migrate_legacy_final_push_pending(st, final):
    head = str(final.get("head") or sh("git rev-parse --verify HEAD"))
    if sh("git rev-parse --verify HEAD") != head:
        die("旧版最终 push 状态的 HEAD 已变化，不能自动迁移旧收据；"
            "先展示历史差异让用户决定。", 2)
    ref, remote_head, _local_head = _upstream_snapshot()
    final["status"] = "review_pending"
    final["head"] = head
    final["remote_ref"] = ref if remote_head == head else ""
    final["remote_head"] = remote_head if remote_head == head else ""
    final["ack_cursor"] = _ack_message_cursor()
    save_state(st)
    print("[mae-flow] 旧版最终状态已迁移为“本地先检视”；"
          "不再要求先 push。")


def _refresh_final_review_status(st, data, final):
    status = final.get("status")
    if status == "commit_pending":
        _refresh_final_pending_commit(st, data, final)
        return True
    if status == "reset_pending":
        _refresh_final_pending_reset(st, data, final)
        return True
    if status == "push_pending":
        _migrate_legacy_final_push_pending(st, final)
        _show_final_review_receipt(st, data, final)
        return True
    return False


def cmd_checkpoint_status(st):
    data = _development_review(st)
    if not data:
        print("[mae-flow] 当前是旧版在途流程，没有检查点子状态；继续按 current 的既有步骤执行。")
        return
    print("[mae-flow] 开发节奏: %s；计划状态: %s"
          % (data.get("mode", "待确认"), data.get("status", "未知")))
    for item in data.get("checkpoints") or []:
        print("  %s [%s] %s" % (
            item.get("id"), item.get("status"), item.get("title")))
    item = _checkpoint_current(st)
    if not item:
        final = _final_review_active(data)
        if final:
            if _refresh_final_review_status(st, data, final):
                return
            _show_final_review_receipt(st, data, final)
            return
        print("全部计划检查点已闭环；继续当前主流程。")
        return
    if _refresh_checkpoint_status(st, data, item):
        return
    _show_checkpoint_review(st, data, item)


def cmd_checkpoint_final(st):
    if st.get("current") != "delivery_review":
        die("checkpoint final 只允许在最终代码增量检视步骤执行；"
            "中间批次使用 checkpoint ready/status。", 2)
    data = _development_review(st)
    if not data or _moonlight(st):
        print("[mae-flow] 当前无需检查点式最终检视；直接按 current 执行 done。")
        return
    active = _final_review_active(data)
    if active:
        if active.get("status") == "push_pending":
            _migrate_legacy_final_push_pending(st, active)
        _show_final_review_receipt(st, data, active)
        return
    changed, err = _final_review_delta(st)
    if err:
        die("最终检视基点无法核实:" + err, 2)
    if not changed:
        print("[mae-flow] 最后已检视代码版本之后没有源码/测试/构建变化；"
              "无需重复确认，直接执行 done。")
        return
    base = str(data.get("last_reviewed_head") or data.get("delivery_base") or "")
    head = sh("git rev-parse --verify HEAD")
    worktree_snapshot = _final_delivery_snapshot(st, head)
    receipt = {}
    if worktree_snapshot:
        receipt = {
            "base": head,
            "snapshot": worktree_snapshot,
            "snapshot_sha256": _snapshot_sha256(worktree_snapshot),
            "scope": "final",
        }
    ref, remote_head, _local_head = _upstream_snapshot()
    remote_ref = ref if remote_head == head else ""
    data["final_review"] = {
        "status": "review_pending", "base": base, "head": head,
        "title": "最终检视增量",
        "remote_ref": remote_ref,
        "remote_head": remote_head if remote_ref else "",
        "changed": changed,
        "receipt": receipt,
        "requires_commit": bool(worktree_snapshot),
        "requires_quality_rerun": bool(worktree_snapshot),
        "ack_cursor": _ack_message_cursor(),
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_state(st)
    final = data["final_review"]
    _show_final_review_receipt(st, data, final)


def _checkpoint_ack(st, ack, expected, receipt):
    if ack != expected:
        return False, "选择原文必须精确为「%s」，不能用近义词代答" % expected
    cursor = set((receipt or {}).get("ack_cursor") or [])
    fresh = [
        item for item in _current_ack_messages(st)
        if _ack_message_signature(item) not in cursor
    ]
    normalized = re.sub(r"\s+", "", expected)
    if any(
            normalized in _ack_candidates(item.get("text", ""))
            for item in fresh):
        _ack_failure(st, success=True)
        return True, ""
    why = (
        "没有捕获到本次检视收据呈现之后的新用户选择。"
        "同一编码步骤内上一批的“继续”不能复用到当前批次；"
        "请展示当前收据并重新取得一次选项回答")
    count = _ack_failure(st, why)
    return False, why + _ack_retry_guidance(count)


def _invalidate_quality_for_rework(st):
    st.pop("unlock", None)
    st.pop("risk_acceptances", None)
    st.pop("agent_tasks", None)
    st.pop("quality", None)
    for kind in ("COMPILE", "CODECHECK", "UT"):
        _drop_agent_token(kind)


def cmd_checkpoint_decide(flow, st, args):
    data = _development_review(st)
    if not data or _moonlight(st):
        die("当前没有等待用户裁决的普通模式检查点。", 2)
    expected = {
        "continue": CHECKPOINT_CONTINUE_ACK,
        "revise": CHECKPOINT_REVISE_ACK,
        "continuous": CHECKPOINT_CONTINUOUS_ACK,
    }[args.choice]
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    final = data.get("final_review") or {}
    if st.get("current") == "delivery_review" and final.get("status") == "review_pending":
        ok, why = _checkpoint_ack(st, args.ack, expected, final)
        if not ok:
            die("检查点用户裁决验真失败:" + why, 2)
        if args.choice == "continuous":
            die("最终检视已经是统一收尾，不能再切换为连续模式。", 2)
        if args.choice == "revise":
            target = _activate_final_rework(
                flow, st, data, final, {"note": args.ack})
            print("[mae-flow] 用户要求调整最终代码，已回到 %s。修复提交后必须重新走编译和质量链；"
                  "已检视基点不前移，最终会展示完整修复组合。" % target)
            print_current(flow, st)
            return
        receipt_head = final.get("head", "")
        if sh("git rev-parse --verify HEAD") != receipt_head:
            die("最终检视期间 HEAD 已变化，旧确认不能背书新版本；先选择调整并重新验证。", 2)
        if final.get("remote_ref"):
            ref, remote_head, local_head = _upstream_snapshot()
            if ref != final.get("remote_ref") or remote_head != local_head:
                die("远端检查点在检视期间发生变化，拒绝确认旧远端收据。", 2)
        if final.get("requires_commit"):
            fresh, why = _reviewed_worktree_fresh(st, final)
            if not fresh:
                die("最终检视收据已失效:" + why, 2)
            final["status"] = "commit_pending"
            final["confirmed_at"] = now
            st.setdefault("history", []).append({
                "step": "delivery_review",
                "result": "checkpoint:confirmed-final-worktree",
                "note": args.ack,
                "at": now,
            })
            save_state(st)
            _show_final_review_receipt(st, data, final)
            return
        dirty_after_receipt = _final_delivery_snapshot(st, receipt_head)
        if dirty_after_receipt:
            die("最终检视收据已失效:检视期间又出现交付代码变化："
                + "、".join(list(dirty_after_receipt)[:8]), 2)
        data["last_reviewed_head"] = receipt_head
        final["status"] = "accepted"
        final["accepted_at"] = now
        data.pop("final_rework", None)
        st.setdefault("history", []).append({
            "step": "delivery_review", "result": "checkpoint:accept-final",
            "note": args.ack, "at": now})
        save_state(st)
        print("[mae-flow] 最终代码增量已确认。执行 done 进入规格定稿/最终 push。")
        return

    if (st.get("current") == "delivery_review"
            and final.get("status") == "commit_recovery"):
        if args.choice != "revise":
            die("错误的最终增量提交不能直接放行；只能选择「需要调整代码」。", 2)
        ok, why = _checkpoint_ack(
            st, args.ack, CHECKPOINT_REVISE_ACK, final)
        if not ok:
            die("最终提交恢复裁决验真失败:" + why, 2)
        base = str((final.get("receipt") or {}).get("base", ""))
        head = sh("git rev-parse --verify HEAD")
        pushed_ref = _upstream_contains_reset_commit(base, head)
        if pushed_ref:
            die("待拆回的最终增量提交已经存在于上游 %s，不能自动改写远端历史。"
                "请让用户决定追加纠正提交、另开分支或由管理员处理；"
                "禁止 force-push。" % pushed_ref, 2)
        final["status"] = "reset_pending"
        final["recovery_ack"] = args.ack
        save_state(st)
        print("[mae-flow] 用户已选择调整。执行：")
        print("  git reset --mixed " + base)
        print("完成后执行 checkpoint status；文件内容会保留并回到完整质量链。")
        return

    item = _checkpoint_current(st)
    if item and item.get("status") == "commit_recovery":
        if args.choice != "revise":
            die("错误提交不能用“继续”放行；只能让用户选择「需要调整代码」后安全拆回工作区。", 2)
        ok, why = _checkpoint_ack(
            st, args.ack, CHECKPOINT_REVISE_ACK, item.get("receipt") or {})
        if not ok:
            die("检查点恢复裁决验真失败:" + why, 2)
        base = str((item.get("receipt") or {}).get("base", ""))
        head = sh("git rev-parse --verify HEAD")
        pushed_ref = _upstream_contains_reset_commit(base, head)
        if pushed_ref:
            die("错误提交已经存在于上游 %s，不能自动改写远端历史。"
                "请让用户决定追加纠正提交、另开分支或由仓库管理员处理；"
                "当前继续冻结，禁止 force-push。" % pushed_ref, 2)
        item["status"] = "reset_pending"
        item["recovery_ack"] = args.ack
        save_state(st)
        print("[mae-flow] 用户已选择调整。执行：")
        print("  git reset --mixed " + base)
        print("该命令只撤销尚未推送的错误检查点提交，文件内容保留在工作区；"
              "完成后执行 checkpoint status 返回 coding。")
        return
    if not item or item.get("status") != "review_pending":
        die("当前没有处于 review_pending 的中间检查点；执行 checkpoint status 查看。", 2)
    ok, why = _checkpoint_ack(st, args.ack, expected, item.get("receipt") or {})
    if not ok:
        die("检查点用户裁决验真失败:" + why, 2)
    if args.choice == "revise":
        item["status"] = "coding"
        item["attempt"] = int(item.get("attempt", 1)) + 1
        for key in ("receipt", "head", "compile_head", "compile_task_sha256"):
            item.pop(key, None)
        _invalidate_quality_for_rework(st)
        st.setdefault("history", []).append({
            "step": st.get("current"), "result": "checkpoint:revise:" + item["id"],
            "note": args.ack, "at": now})
        save_state(st)
        print("[mae-flow] %s 返回修改；固定基点仍为 %s，修复后会重新展示整批组合差异。"
              % (item["id"], str(item.get("fixed_base", ""))[:10]))
        return
    if _review_before_commit(data):
        fresh, fresh_why = _reviewed_worktree_fresh(st, item)
        if not fresh:
            die("检查点收据已失效:" + fresh_why
                + "；旧确认不能背书另一份未提交 diff。", 2)
        item["status"] = "commit_pending"
        item["confirmed_at"] = now
        item["after_commit_continuous"] = args.choice == "continuous"
        st.setdefault("history", []).append({
            "step": st.get("current"),
            "result": "checkpoint:confirmed-worktree:" + item["id"],
            "note": args.ack, "at": now})
        save_state(st)
        add, commit = _checkpoint_commit_command(st, item)
        if args.choice == "continuous":
            print("[mae-flow] 用户选择后续统一检视；当前工作区快照已冻结，"
                  "先形成可追踪的内部检查点提交，之后不 push、不再停顿。")
        else:
            print("[mae-flow] 用户已确认未提交 diff。现在只提交刚才检视过的精确文件：")
        print("  " + add)
        print("  " + commit)
        print("提交成功后执行 checkpoint status；系统会逐文件核对提交内容与检视快照，"
              + ("然后进入连续开发。" if args.choice == "continuous"
                 else "相等后才允许小步 push。"))
        return
    if args.choice == "continuous":
        fresh, fresh_why = _checkpoint_source_fresh(
            item.get("compile_head", ""), st)
        if not fresh:
            die("切换一次完成模式前，当前批编译收据已失效:"
                + fresh_why + "。先选择调整并重新编译。", 2)
        completed_head = sh("git rev-parse --verify HEAD")
        data["mode"] = "continuous"
        item["status"] = "completed"
        item["completed_head"] = completed_head
        item["closed_at"] = now
        item.pop("receipt", None)
        data["current_index"] = int(data.get("current_index", 0)) + 1
        nxt = _checkpoint_current(st)
        if nxt:
            nxt["fixed_base"] = completed_head
        st.setdefault("history", []).append({
            "step": st.get("current"), "result": "checkpoint:switch-continuous",
            "note": args.ack, "at": now})
        save_state(st)
        print("[mae-flow] 已切换为一次完成模式。当前批的有效编译结果已保留，"
              "但不会冒充用户已检视；%s质量链结束后从上一个已确认 HEAD 统一检视。"
              % (("进入 " + nxt["id"] + "，") if nxt else "全部检查点已完成，"))
        return
    receipt = item.get("receipt") or {}
    receipt_head = receipt.get("head", "")
    if sh("git rev-parse --verify HEAD") != receipt_head:
        die("检视期间 HEAD 已变化；旧远端收据失效，选择调整后重新编译、push、检视。", 2)
    fresh, why = _checkpoint_source_fresh(receipt_head, st)
    if not fresh:
        die("检查点收据已失效:" + why, 2)
    ref, remote_head, local_head = _upstream_snapshot()
    if (ref != receipt.get("remote_ref") or remote_head != receipt_head
            or local_head != receipt_head):
        die("检视期间本地或远端分支发生变化；拒绝确认旧收据。", 2)
    item["status"] = "accepted"
    item["accepted_head"] = receipt_head
    item["accepted_at"] = now
    data["last_reviewed_head"] = receipt_head
    data["current_index"] = int(data.get("current_index", 0)) + 1
    nxt = _checkpoint_current(st)
    if nxt:
        nxt["fixed_base"] = receipt_head
    st.setdefault("history", []).append({
        "step": st.get("current"), "result": "checkpoint:accept:" + item["id"],
        "note": args.ack, "at": now})
    save_state(st)
    print("[mae-flow] %s 已确认并冻结远端收据。%s"
          % (item["id"], ("进入 " + nxt["id"]) if nxt else "全部计划检查点已完成"))


def cmd_checkpoint(flow, st, args):
    action = args.checkpoint_action
    if action == "plan":
        return cmd_checkpoint_plan(st, args)
    if action == "status":
        return cmd_checkpoint_status(st)
    if action == "ready":
        return cmd_checkpoint_ready(flow, st, args)
    if action == "final":
        return cmd_checkpoint_final(st)
    if action == "decide":
        return cmd_checkpoint_decide(flow, st, args)
    die("未知 checkpoint 动作: " + str(action), 2)


def _done_handle_legacy_pace(flow, st, sid, step):
    if (sid in PACE_STEPS and not _development_checkpoints_enabled(st)
            and not _development_review(st)):
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        target = _next_from_step(step, st, "continuous")
        st.setdefault("history", []).append({
            "step": sid, "result": "legacy:skipped-development-pace",
            "note": "旧版在途状态恢复升级前路径", "at": now})
        st["current"] = target
        st.setdefault("step_heads", {})[target] = sh(
            "git rev-parse --verify HEAD")
        save_state(st)
        print("[mae-flow] 检测到升级前在途状态；本单不追加开发节奏确认，"
              "已按原流程进入 %s。\n" % target)
        print_current(flow, st)
        return True
    return False

def _done_pending_config(step, st, args, sid):
    review = st.get("config_review") if sid == "config_confirm" else None
    if sid != "config_confirm" or _moonlight(st):
        return _validated_pending_config(step, st, args.set or [])
    if not isinstance(review, dict) or not review.get("sha256"):
        die(
            "尚未生成完整配置确认单。先按 current 输出执行 config-review --set ...；"
            "脚本会校验并展示全部配置，再让用户只做一次最终确认。"
            "不要直接拿基线分支、单号等局部回答调用 done。", 2)
    if args.set:
        pending_config = _validated_pending_config(step, st, args.set)
        current_requirement_sha = _requirement_sha256(
            pending_config.get("需求文档", ""))
        if _config_sha256(
                pending_config, current_requirement_sha) != review.get("sha256"):
            die(
                "done 携带的配置与用户看到的确认单不一致。禁止确认 A、提交 B；"
                "请用新配置重新执行 config-review。", 2)
    else:
        review_state = dict(st)
        review_state["config"] = dict(review.get("config") or {})
        pending_config = _validated_pending_config(step, review_state, [])
        current_requirement_sha = _requirement_sha256(
            pending_config.get("需求文档", ""))
        if _config_sha256(
                pending_config,
                current_requirement_sha) != review.get("sha256"):
            die("配置或需求文档在呈现后发生变化，旧确认单已自动失效。"
                "重新执行 config-review 即可恢复，无需退出流程。", 2)
    ok, why = _config_ack_verified(
        st, args.ack or "", review.get("sha256"), review.get("id", ""))
    if not ok:
        die(why, 2)
    return pending_config

def _done_validate_choice_and_ack(step, st, args, sid):
    error = workflow_completion.choice_error(step, args.choice)
    if error:
        die(error, 2)
    if (sid == "config_confirm" or not step.get("user_ack")
            or _moonlight(st)):
        return
    if step.get("choice_key"):
        pace_state = _development_review(st) if sid in PACE_STEPS else None
        ok, why = _choice_verified(
            step, st, args.choice,
            (pace_state or {}).get("ack_cursor")
            if pace_state else None)
    elif step.get("confirmation_answers"):
        ok, why = _implicit_ack_verified(step, st)
    elif args.ack:
        ok, why = _ack_verified(st, args.ack)
    else:
        ok, why = _implicit_ack_verified(step, st)
    if not ok:
        die(why, 2)

def _done_commit_inputs(step, st, args, sid, pending_config):
    for key, value in workflow_completion.choice_config(step, args.choice).items():
        bad = _validate_config_value(key, value)
        if bad:
            die(f"流程定义为选择 {args.choice} 配置的 {key}「{value}」不合法:{bad}。"
                "请维护人修正 flow.json，拒绝写入半套状态。", 2)
        pending_config[key] = value
    st["config"] = pending_config
    if sid == "config_confirm":
        st.pop("config_review", None)
        st.pop("branch_resolution", None)
    if step.get("choice_key"):
        st["choices"][step["choice_key"]] = args.choice

def _done_guard_branch(st, sid):
    if sid == "story":
        _canonicalize_story_output(
            st.get("config", {}).get("单号", ""), st)
    want = st.get("config", {}).get("分支名", "")
    if sid not in ("config_confirm", "workflow_select", "branch_create") and want:
        cur = sh("git branch --show-current")
        if cur != want:
            _done_save_die(
                st, f"当前分支 {cur or '未知'} != 本单约定分支 {want}。先切回正确分支，禁止在别的分支推进。")

def _done_save_die(st, message):
    save_state(st)
    die(message, 2)

def _done_transition_to_recheck(flow, st, sid, target, changed, note, message,
                                clear_unlock=False):
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    st["history"].append({"step": sid, "result": "source-recheck:" + target,
                          "note": note + "、".join(changed[:10]), "at": now})
    st["current"] = target
    st.setdefault("step_heads", {})[target] = sh("git rev-parse --verify HEAD")
    if clear_unlock:
        st.pop("unlock", None)
    for kind in ("COMPILE", "CODECHECK", "UT"):
        (st.get("agent_tasks", {}) or {}).pop(kind, None)
    (st.get("quality", {}) or {}).pop("codecheck_scan", None)
    (st.get("quality", {}) or {}).pop("codecheck_verify", None)
    save_state(st)
    print(message)
    print_current(flow, st)
    return True

def _done_source_change(flow, st, sid, step):
    source_next = step.get("source_change_next")
    if not source_next:
        return False
    _, migrate_err = _ensure_step_entry_head(flow, st, sid)
    if migrate_err:
        _done_save_die(
            st, "无法恢复步骤入口 HEAD:" + migrate_err + "。拒绝猜测源码是否变化。")
    changed, why = _source_changed_since(
        (st.get("step_heads", {}) or {}).get(sid, ""), st)
    if why:
        _done_save_die(st, "无法核对本步源码变化:" + why)
    if not changed:
        return False
    dirty = [x for x in changed if x.endswith("(未提交)")]
    if dirty:
        _done_save_die(st, "本步改过源码，但仍有未提交改动: " + "、".join(dirty[:5])
                       + "。先按单号格式精确提交，再 done；否则下一步任务卡看不到这些文件。")
    ok, commit_why = ev_commit_tagged_after_entry({}, st)
    if not ok:
        _done_save_die(st, "源码变化尚未形成可追踪的本步提交:" + commit_why)
    return _done_transition_to_recheck(
        flow, st, sid, source_next, changed, "本步修改源码:",
        f"[mae-flow] {sid} 修改了源码，自动进入 {source_next} 重新编译；主会话不要自行编译。\n")

def _done_source_recheck(flow, st, sid, step):
    recheck = step.get("source_change_recheck")
    if not recheck:
        return False
    _, migrate_err = _ensure_step_entry_head(flow, st, sid)
    if migrate_err:
        _done_save_die(st, "无法恢复 UT 步骤入口 HEAD:" + migrate_err
                       + "。为避免漏掉编译/CodeCheck，拒绝向后推进；请交维护人核对历史。")
    changed, why = _business_source_changed_since_step(st, sid)
    if why:
        _done_save_die(st, "无法核对 UT 步骤内是否修改过被测源码:" + why
                       + "。为避免漏掉编译/CodeCheck，拒绝向后推进；请交维护人恢复步骤入口基点。")
    if not changed:
        return False
    ul = st.get("unlock") or {}
    if ul.get("scope") != "source" or ul.get("step") != sid:
        _done_save_die(st, "UT 步骤内检测到未经 unlock source 用户裁决的被测源码变更: "
                       + "、".join(changed[:5]) + ("…" if len(changed) > 5 else "")
                       + "。这是越权修改，不能靠补跑验证洗白；先呈报变更和 UT 自查结论，由用户裁决后再处理。")
    dirty = [x for x in changed if x.endswith("(未提交)")]
    if dirty:
        _done_save_die(st, "用户虽已解锁源码修复，但这些源码仍未提交: "
                       + "、".join(dirty[:5])
                       + "。先按单号格式精确提交，再 done；否则回流任务卡无法覆盖真实改动。")
    ok, commit_why = ev_commit_tagged_after_entry({}, st)
    if not ok:
        _done_save_die(st, "UT 暴露的源码修复尚未形成可追踪提交:" + commit_why)
    return _done_transition_to_recheck(
        flow, st, sid, recheck, changed, "UT 裁决后修改被测源码:",
        f"[mae-flow] UT 阶段经用户裁决修改了被测源码，自动回流到 {recheck}。"
        "必须重新经过编译、CodeCheck 与 UT；禁止直接推送。\n", clear_unlock=True)

def _done_require_evidence(step, st, args, sid):
    fails = check_evidence(step, st)
    if not fails:
        _evidence_failure_count(sid, success=True)
        return
    save_state(st)
    count = _evidence_failure_count(sid)
    target = (_next_from_step(step, st, args.choice or "")
              if count >= 2 and not _moonlight(st) else "")
    die(workflow_completion.evidence_error(
        fails, count, _moonlight(st), target,
        os.path.abspath(sys.argv[0])), 2)

def _done_adjust_checkpoint(flow, st, sid):
    st.pop("development_review", None)
    st.get("choices", {}).pop("development_pace", None)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    st.setdefault("history", []).append({
        "step": sid, "result": "checkpoint-plan:adjust",
        "note": "用户要求调整检查点划分", "at": now})
    st.setdefault("step_heads", {})[sid] = sh("git rev-parse --verify HEAD")
    save_state(st)
    print("[mae-flow] 用户选择调整检查点；旧方案已失效，代码仍未解锁。"
          "结合用户意见重新执行 checkpoint plan --item ...。")
    print_current(flow, st)

def _done_finalize(flow, st, args, sid, step):
    for event in workflow_completion.completion_events(
            sid, step, st, args.choice, args.ack or ""):
        if event.kind == "adjust_checkpoint":
            _done_adjust_checkpoint(flow, st, sid)
            return
        if event.kind == "activate_checkpoint":
            _activate_checkpoint_plan(st, event.value)
        elif event.kind == "resolve_moonlight":
            _moonlight_resolve_kind(st, event.value)
        elif event.kind == "localize_story":
            _localize_story(event.value)
        elif event.kind == "advance":
            advance(flow, st, sid, step, "done", event.note)

def cmd_done(flow, st, args):
    sid = st["current"]
    step = flow["steps"][sid]
    if step.get("terminal"):
        die("流程已在终态。")
    if _done_handle_legacy_pace(flow, st, sid, step):
        return
    if sid == "moonlight_review":
        die("月光宝盒已推送并等待早晨处理。请执行 moonlight report、moonlight repair 或 moonlight finalize，"
            "不能用 done 跳过报告闭环。", 2)
    args.choice = workflow_completion.resolve_choice(step, st, args.choice)
    pending_config = _done_pending_config(step, st, args, sid)
    _done_validate_choice_and_ack(step, st, args, sid)
    _done_commit_inputs(step, st, args, sid, pending_config)
    _done_guard_branch(st, sid)
    if (_done_source_change(flow, st, sid, step)
            or _done_source_recheck(flow, st, sid, step)):
        return
    _done_require_evidence(step, st, args, sid)
    _done_finalize(flow, st, args, sid, step)


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
            kinds.add("CODECHECK_TOOL")
        elif typ in ("agent_ran", "agent_or_no_source", "review_agent_or_no_code") and spec.get("agent"):
            kinds.add(str(spec["agent"]).upper())
    return kinds


def cmd_accept_risk(flow, st, args):
    """用户有意识地只放行当前步骤某个 Agent 令牌；不跳过同一步的其他机器证据。"""
    sid = st["current"]
    step = flow["steps"][sid]
    kind = args.agent.upper()
    required = _step_agent_kinds(step)
    # TIER_SCOPE 不是 Agent 令牌:它放行的是本步的档位范围硬校验(升级阈值),
    # 仅在挂了 tier_scope 证据的步骤可用。
    if kind == "TIER_SCOPE":
        if not any(e.get("type") == "tier_scope"
                   for e in step.get("evidence", [])):
            die(f"当前步骤 {sid} 没有档位范围校验,不需要 tier_scope 放行。", 2)
    elif kind not in required:
        die(f"当前步骤 {sid} 不需要 {kind} 令牌，不能预先或跨步骤放行。"
            + ("本步可放行: " + "、".join(sorted(required)) if required else "本步没有可风险放行的 Agent 令牌。"), 2)
    if not args.reason:
        die("accept-risk 必须 --reason 写清具体风险，不能只写『继续』。", 2)
    if not args.ack:
        die("accept-risk 必须携带用户明确承担风险的原话:--ack \"用户原话\"。", 2)
    ok, why = _ack_verified(st, args.ack, exact=True)
    if not ok:
        die("accept-risk 授权验真失败:" + why, 2)
    dirty = _blocking_dirty_source_paths(st, flow)
    if dirty:
        die("风险确认必须绑定稳定代码版本，但仍有未提交源码/测试/构建文件: " + "、".join(dirty[:8])
            + "。先按本单规范提交，再向用户展示风险并重新确认。", 2)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    inherited_dirty = _unchanged_initial_dirty_source_paths(st, flow)
    task = (st.get("agent_tasks", {}) or {}).get(kind, {})
    rec = {"step": sid, "head": sh("git rev-parse --verify HEAD"), "at": now,
           "task_sha256": task.get("sha256", ""), "reason": args.reason, "ack": args.ack,
           "unchanged_initial_dirty": inherited_dirty}
    st.setdefault("risk_acceptances", {})[kind] = rec
    st.setdefault("history", []).append(
        {"step": sid, "result": "accept-risk:" + kind, "note": args.reason, "at": now})
    save_state(st)
    print(f"[mae-flow] 用户已确认承担 {kind} 令牌缺失风险；仅放行当前步骤 {sid}、当前代码版本。")
    print("风险: " + args.reason)
    if inherited_dirty:
        print("审计:以下流程启动前已脏文件指纹未变，不算本单变化: "
              + "、".join(inherited_dirty[:8]))
    print("其他机器证据不会跳过；源码/测试变化、任务卡变化或进入下一步后，本次放行自动失效。现在重新执行 done。")


WORKFLOW_LABELS = {"full": "完整开发", "hotfix": "已定位问题修复",
                   "tweak": "局部修改", "review": "处理评审意见"}


def _workflow_chain(flow, wf):
    """按交付方式线性展开步骤链(可选询问步取"做"分支展示完整形态)。"""
    return workflow_transitions.workflow_chain(flow, wf)


def cmd_steps(flow, st, args):
    """工作流全景:每条交付方式背后的完整步骤链、每步卡什么、哪些环节可裁。

    透明化诉求:用户选档/裁剪前先看得见全貌;质量门禁步骤不在可裁白名单。"""
    current = st.get("current") if st else None
    active_wf = (st.get("choices", {}) or {}).get("workflow") if st else None
    ask_labels = {"grill_ask": "需求质询", "grill": "需求质询",
                  "story_ask": "STORY", "story": "STORY"}
    for wf in ("full", "hotfix", "tweak", "review"):
        marker = "(本单)" if wf == active_wf else ""
        print("\n═══ %s(%s)%s ═══" % (WORKFLOW_LABELS[wf], wf, marker))
        for sid in _workflow_chain(flow, wf):
            step = flow["steps"][sid]
            tags = []
            if sid in ("grill_ask", "story_ask"):
                tags.append("可选环节:%s(流程内询问决定)" % ask_labels[sid])
            elif sid in ("grill", "story"):
                tags.append("随「%s」询问可选" % ask_labels[sid])
            if step.get("user_ack"):
                tags.append("用户确认")
            evidence = sorted({e.get("type", "?")
                               for e in step.get("evidence", [])})
            here = "▶" if (wf == active_wf and sid == current) else " "
            print(" %s %-28s %s%s" % (
                here, sid + " " + step.get("title", ""),
                ("[" + "、".join(tags) + "] ") if tags else "",
                ("证据:" + ",".join(evidence)) if evidence else "(无硬证据)"))
    print("\n可选环节(需求质询/STORY)由流程内询问逐单决定;其余步骤为流程完整性"
          "的一部分,不提供配置级裁剪。")


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
        values = ([x.strip() for x in raw.split(",") if x.strip()]
                  if isinstance(raw, str) else list(raw) if isinstance(raw, list) else [])
    else:
        try:
            raw = json.load(open(DEFAULTS_PATH, encoding="utf-8-sig")).get("测试路径", [])
            values = ([x.strip() for x in raw.split(",") if x.strip()]
                      if isinstance(raw, str) else list(raw) if isinstance(raw, list) else [])
        except Exception:
            values = []
    valid = []
    for value in values:
        pattern = str(value).strip()
        if not pattern:
            continue
        try:
            re.compile(pattern)
        except re.error as exc:
            print("⚠ 测试路径正则「%s」无效，已按 fail-closed 忽略并保留内置测试边界: %s"
                  % (pattern, exc), file=sys.stderr)
            continue
        valid.append(pattern)
    return valid


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


GATE_STRIKES_PATH = STATE_PATH + ".gate-strikes"
GATE_PERMITS_PATH = STATE_PATH + ".gate-permits"
GATE_STRIKE_LIMIT = 3


def _gate_block_id(rule, subject):
    return hashlib.sha256((rule + "\n" + norm(subject)).encode(
        "utf-8", errors="replace")).hexdigest()[:10]


def _gate_die(st, sid, rule, subject, msg):
    """裁决类拦截的统一出口:break-glass 一次性放行令 + 三振熔断。

    gate 的误报不可能降到零(静态文本判断动态行为),兜底纪律是:
    ①有效放行令 → 消费后放过本条规则,其余规则继续检查;
    ②同一规则同步骤连拦 ≥GATE_STRIKE_LIMIT 次 → 报错升级,附本次动作的放行令
      签发指引——出口不提前广告,卡死的那一刻自己出现;
    ③月光模式改为指向 blocked/defer 留痕(夜里没有用户消息,放行令天然签不出来);
    ④每次三振与放行都留痕:兜底机制同时是误报采集器(doctor 展示)。
    绝对类规则(密钥/危险命令/状态文件/伪造通道)不走这里,没有放行令——
    用户在真实终端手动执行就是它们的逃生口。"""
    bid = _gate_block_id(rule, subject)
    try:
        permits = json.load(open(GATE_PERMITS_PATH, encoding="utf-8"))
    except FileNotFoundError:
        permits = {}
    except Exception:
        # 实测:放行令存储损坏是唯一"用户说了不算"的场景,且曾全静默——
        # 当场隔离坏文件并明示,重新 allow 一步即恢复(同意原话仍可验真)。
        permits = {}
        try:
            os.replace(GATE_PERMITS_PATH, GATE_PERMITS_PATH + ".corrupt."
                       + time.strftime("%Y%m%d-%H%M%S"))
            print("[mae-flow] ⚠ 放行令存储损坏,已隔离;若刚签发过放行令,"
                  "重新执行同一条 allow 命令即可重签。", file=sys.stderr)
        except OSError:
            pass
    rec = permits.get(bid)
    if rec and not rec.get("used") and rec.get("step") == sid:
        head = sh("git rev-parse --verify HEAD")
        if rec.get("head") and rec.get("head") != head:
            # 实测:HEAD 变化后放行令静默作废,拦截消息与普通三振无差别,
            # Agent 会误判"放行没生效"盲目循环——显式说明作废原因与恢复路。
            msg = ("已有放行令 %s 因代码版本变化作废(签发于 %s)。需重新征得"
                   "用户同意后 allow 重签。" % (bid, rec.get("head", "")[:8])
                   ) + msg
        if not rec.get("head") or rec.get("head") == head:
            def consume(data):
                entry = (data or {}).get(bid) or {}
                entry["used"] = True
                entry["used_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                data[bid] = entry
                return data
            try:
                update_json(GATE_PERMITS_PATH, consume, default={}, recover_corrupt=True)
            except Exception:
                pass
            try:
                st.setdefault("history", []).append({
                    "step": sid, "result": "gate:allowed-by-user",
                    "note": rule + " " + bid,
                    "at": time.strftime("%Y-%m-%d %H:%M:%S")})
                save_state(st)
            except Exception:
                pass
            print("[mae-flow] 用户放行令 %s 生效(一次性,已作废):规则 %s 放过此动作,"
                  "其余规则继续检查。" % (bid, rule), file=sys.stderr)
            return
    count = 1
    try:
        def bump(data):
            data = data or {}
            counts = data.setdefault("counts", {})
            entry = counts.get(rule) or {}
            if entry.get("step") != sid:
                entry = {"step": sid, "count": 0}
            entry["count"] = int(entry.get("count", 0) or 0) + 1
            entry["last_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            counts[rule] = entry
            recent = data.setdefault("recent", {})
            recent[bid] = {"rule": rule, "step": sid, "sample": subject[:200],
                           "at": entry["last_at"]}
            while len(recent) > 20:
                oldest = min(recent, key=lambda k: recent[k].get("at", ""))
                recent.pop(oldest, None)
            return data
        data = update_json(GATE_STRIKES_PATH, bump, default={}, recover_corrupt=True)
        count = int(((data or {}).get("counts", {}).get(rule) or {}).get("count", 1) or 1)
    except Exception:
        count = 1
    if count >= GATE_STRIKE_LIMIT:
        if _moonlight(st or {}):
            msg += ("\n⚠ 本规则已在本步骤连续拦截 %d 次,可能是误拦。月光宝盒无人值守中"
                    "不可放行:这属于客观阻塞,按 current 给出的 moonlight blocked"
                    "(质量步骤用 defer)留痕停止,把拦截编号 %s 写进 reason,早晨由用户裁决。"
                    % (count, bid))
        else:
            msg += ("\n⚠ 本规则已在本步骤连续拦截 %d 次,可能是误拦。停止再试写法变体;"
                    "若你确认该动作正当且必要:把动作原文和拦截原因展示给用户,用户同意后执行 "
                    "python \"%s\" allow %s --ack \"用户同意原话\"。"
                    "放行只对这一个动作生效一次,绑定当前代码版本,用后即废;其余规则不受影响。"
                    "若动作确属违规,回到 current 指引换正规路径。"
                    % (count, os.path.abspath(sys.argv[0]), bid))
    die(msg, 2)


def cmd_spec(flow, st, args):
    """交付登记与阶段推进(v3 取代 comet-state)。

    设计要点(比被取代者更硬):
    - 指针字段登记时**现场校验文件真实存在**,写不进不存在的路径;
    - `verify_result` 不可直写——它只能由 verify-pass 转换产生,而转换要求验证报告
      已登记且真实存在。这封掉了 comet 时代 `set verify_result pass` 的伪造通道;
    - 阶段推进只接受合法序,乱跳报错;所有动作写 history 留痕。"""
    if st is None:
        die("流程未初始化;先执行 init。", 2)
    action = args.spec_action
    data = _spec_data(st)
    cn = (st.get("config", {}) or {}).get("CHANGE_NAME", "")
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    from mae_flow_core import specengine

    if action == "show":
        out = {"change": cn, **data}
        # 已归档单的 change 目录已移走,查产物必然报"不存在"——成功之后
        # 看到报错违背流畅原则,改报归档去向。
        if cn and str(data.get("phase", "")) == "archived":
            out["note"] = "已归档: openspec/changes/archive/%s" % (
                data.get("archived_to", "?"))
        elif cn:
            try:
                out["artifacts"] = specengine.status(os.getcwd(), cn)
            except Exception as exc:
                out["artifacts_error"] = str(exc)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    # v5:新单一律四合一 change.md,档位跟随交付方式(review 不建单,缺省按 full)。
    workflow = (st.get("choices", {}) or {}).get("workflow", "")
    tier = workflow if workflow in ("full", "hotfix", "tweak") else "full"
    if action == "new":
        name = (args.value or cn or "").strip()
        if not name:
            die("需要变更目录名:spec new <英文短名>。", 2)
        try:
            specengine.ensure_config(os.getcwd())
            info = specengine.new_change(os.getcwd(), name, tier=tier)
        except specengine.SpecEngineError as exc:
            die("创建变更目录失败: " + str(exc), 2)
        # dogfood 实测:spec init 要求 CHANGE_NAME 已记录,而记录动作(done --set)
        # 排在 init 之后,真实链路要撞两次墙才绕通。new 是真实动作、目录名就是
        # 事实,创建成功即顺手登记(为空才写;done --set 同值幂等,权威不变)。
        # 注意:登记+吞并 init 的全部内存变更做完后【单次】save_state——
        # save_versioned_json 保存后会 clear+deepcopy 重建 st,先前取出的
        # data 引用即成孤儿,连续两次 save 的第二次会静默写空(实测踩雷)。
        registered = not cn
        if registered:
            st["config"]["CHANGE_NAME"] = name
            st.setdefault("history", []).append(
                {"step": st["current"], "result": "spec:new", "note": name,
                 "at": now})
        elif cn != name:
            print("[mae-flow] ⚠ 已登记 CHANGE_NAME=%s 与新目录 %s 不一致;"
                  "一仓一单,请确认没有开重复单。" % (cn, name), file=sys.stderr)
        # new 吞并 init(优化实测:init 只剩可推导字段,独立存在只制造
        # "init 先于登记"类顺序撞墙)。幂等守卫:已初始化过则不重置 phase。
        inited = (not data.get("initialized_at")) and (not cn or cn == name)
        if inited:
            data.update({"change": name, "phase": "open",
                         "workflow": workflow, "initialized_at": now})
            st.setdefault("history", []).append(
                {"step": st["current"], "result": "spec:init", "note": name,
                 "at": now})
        if registered or inited:
            save_state(st)
        # stdout 是 spec new 的 JSON 契约面,提示一律走 stderr
        if registered:
            print("[mae-flow] CHANGE_NAME=%s 已随创建自动登记(done 无需重复 --set)。"
                  % name, file=sys.stderr)
        if inited:
            print("[mae-flow] 交付登记已随创建初始化:change=%s phase=open"
                  % name, file=sys.stderr)
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return
    if action == "instructions":
        artifact = args.value or ""
        if not cn:
            die("先记录 CHANGE_NAME(done --set CHANGE_NAME=<英文短名>)。", 2)
        try:
            print(specengine.instructions(os.getcwd(), artifact, cn, tier=tier),
                  end="")
        except specengine.SpecEngineError as exc:
            die("获取产物格式指令失败: " + str(exc), 2)
        return
    if action == "validate":
        if not cn:
            die("先记录 CHANGE_NAME。", 2)
        try:
            ok, messages = specengine.validate(os.getcwd(), cn)
        except specengine.SpecEngineError as exc:
            die("规格校验无法执行: " + str(exc), 2)
        for line in messages:
            print(line)
        if not ok:
            die("规格结构校验未通过:按上面的错误逐条修正后重跑(当步修比定稿时爆便宜得多)。", 2)
        print("[mae-flow] 规格结构校验通过。")
        return
    if action == "archive":
        if not cn:
            die("先记录 CHANGE_NAME。", 2)
        if _spec_phase(st) != "archive":
            die("规格定稿只能在定稿阶段执行(当前阶段 %s):先完成验证并通过 spec verify-pass。"
                % (_spec_phase(st) or "未初始化"), 2)
        try:
            info = specengine.archive(os.getcwd(), cn)
        except specengine.SpecEngineError as exc:
            die("规格定稿失败(现场保持原样,可修正后直接重跑): " + str(exc), 2)
        data["phase"] = "archived"
        data["archived_to"] = info.get("archive_name", "")
        archived_path = norm(os.path.relpath(
            info.get("archived_to", ""), os.getcwd()))
        data["archive_paths"] = list(dict.fromkeys(
            ["openspec/changes/" + cn, archived_path] + [
                re.sub(r"^(?:\./)+", "", norm(path))
                for path in info.get("merged", []) or []
            ]))
        data["archived_at"] = now
        st.setdefault("history", []).append(
            {"step": st["current"], "result": "spec:archived",
             "note": info.get("archive_name", ""), "at": now})
        save_state(st)
        for warn in info.get("warnings", []) or []:
            print("⚠ " + str(warn), file=sys.stderr)
        print("[mae-flow] 规格已定稿:合并进真相源 %s;变更目录已移动到 %s。"
              % ("、".join(info.get("merged", [])) or "(无规格变更)",
                 info.get("archive_name", "")))
        print("[mae-flow] 本次只需精确提交: "
              + "、".join(data["archive_paths"]))
        print("禁止 git add openspec/；该宽路径可能卷入其他单遗留文件。")
        print("统计: " + json.dumps(info.get("totals", {}), ensure_ascii=False))
        return
    if action == "init":
        if not cn:
            die("先用 done --set CHANGE_NAME=<英文短名> 记录变更目录名。", 2)
        # spec new 已自动初始化,本命令保留为在途兼容的幂等别名——重复 init
        # 不得把已推进的 phase 重置回 open(旧实现的隐性坑,顺手关闭)。
        if data.get("initialized_at"):
            print("[mae-flow] 交付登记已存在:change=%s phase=%s(幂等,未改动)"
                  % (data.get("change", cn), data.get("phase", "?")))
            return
        data.update({"change": cn, "phase": "open", "workflow":
                     (st.get("choices", {}) or {}).get("workflow", ""),
                     "initialized_at": now})
        st.setdefault("history", []).append(
            {"step": st["current"], "result": "spec:init", "note": cn, "at": now})
        save_state(st)
        print("[mae-flow] 交付登记已初始化:change=%s phase=open" % cn)
        return
    if action == "set":
        field, value = args.field, (args.value or "").strip()
        if field not in SPEC_REGISTER_FIELDS:
            die("只能登记这些产物指针: %s。阶段与验证结论由 phase/verify-pass 转换产生,"
                "不接受直写(直写等于伪造机器结论)。" % "、".join(SPEC_REGISTER_FIELDS), 2)
        if not value:
            die("登记值不能为空。", 2)
        if not os.path.isfile(value):
            die("登记失败:%s 不存在。先真实产出该文件再登记(登记不是承诺,是事实)。" % value, 2)
        data[field] = norm(value)
        st.setdefault("history", []).append(
            {"step": st["current"], "result": "spec:set:" + field, "note": value, "at": now})
        save_state(st)
        print("[mae-flow] 已登记 %s = %s" % (field, norm(value)))
        return
    if action == "phase":
        target = args.value or ""
        if target not in SPEC_PHASES:
            die("阶段只能是: %s" % "、".join(SPEC_PHASES), 2)
        cur = _spec_phase(st) or "open"
        order = list(SPEC_PHASES)
        # 轻量单快进:hotfix/tweak 不经 design/build 步骤,phase 停在 open,而
        # 防跳跃墙的报错本来就教模型机械连打三条——仪式改由机器代劳。
        # 逐格推进逐格留痕,审计轨迹与手动三连逐字等价;full 单不放行
        # (它的 design/build 推进各自绑在对应步骤的 done 证据里)。
        wf = (st.get("choices", {}) or {}).get("workflow", "")
        if target == "verify" and cur == "open" and wf in ("hotfix", "tweak"):
            for p in ("design", "build", "verify"):
                data["phase"] = p
                st.setdefault("history", []).append(
                    {"step": st["current"], "result": "spec:phase:" + p,
                     "at": now})
            save_state(st)
            print("[mae-flow] 交付阶段(轻量单快进):open → design → build → verify")
            return
        if order.index(target) < order.index(cur):
            die("阶段不能回退(%s → %s)。需要回流请走 goto --force --ack 由用户裁决。"
                % (cur, target), 2)
        if order.index(target) - order.index(cur) > 1:
            # dogfood 实测:hotfix/tweak 单不经 design/build 步骤,阶段停在 open,
            # verify 步一条 phase verify 会撞这堵墙——报错必须给出路(核心原则)。
            # 审计实锤两修:①链止步 verify(archive/archived 由 verify-pass/
            # spec archive 产生,列进链会引导绕过三重校验并推进死胡同);
            # ②命令用本脚本真实路径(字面量 mae-flow.py 相对路径照抄必失败)。
            script = norm(os.path.abspath(sys.argv[0]))
            stop = min(order.index(target), order.index("verify"))
            chain = " && ".join(
                'python "%s" spec phase %s' % (script, p)
                for p in order[order.index(cur) + 1:stop + 1])
            tail = ("(verify 之后由 spec verify-pass 与 spec archive 推进,"
                    "不可用 phase 直达)" if order.index(target) > order.index("verify")
                    else "")
            die("阶段不能跳跃(%s → %s):中间阶段的产物与证据会被绕过。"
                "轻量单(hotfix/tweak)不经 design/build 步骤但阶段仍需逐级推进,"
                "依序执行:%s%s" % (cur, target, chain, tail), 2)
        if target == "archive":
            die("archive 阶段由 spec verify-pass 在三重校验(阶段在 verify+报告"
                "存在+清单全勾)通过后写入,不接受直接推进(直推会绕过验证)。", 2)
        if target == "archived":
            die("archived 由 spec archive 动作在真实完成定稿后写入,不接受直接推进。", 2)
        data["phase"] = target
        st.setdefault("history", []).append(
            {"step": st["current"], "result": "spec:phase:" + target, "at": now})
        save_state(st)
        print("[mae-flow] 交付阶段:%s → %s" % (cur, target))
        return
    if action == "verify-pass":
        # --report 合并"登记+判定"两连(优化实测:set verification_report 全仓
        # 只在 verify-pass 前一行出现,拆开只制造"忘登记"撞墙)。校验与 history
        # 与逐条执行完全一致;verify_result 不可直写的封印不动。
        report_arg = (getattr(args, "report", "") or "").strip()
        if report_arg:
            if not os.path.isfile(report_arg):
                die("登记失败:%s 不存在。先真实产出验证报告再登记。" % report_arg, 2)
            data["verification_report"] = norm(report_arg)
            st.setdefault("history", []).append(
                {"step": st["current"], "result": "spec:set:verification_report",
                 "note": report_arg, "at": now})
        cur = _spec_phase(st)
        if cur != "verify":
            die("verify-pass 只能在验证阶段执行(当前阶段 %s):没进入验证就宣布验证通过"
                "等于跳过实现与检查。先按步骤指引把阶段推进到 verify。" % (cur or "未初始化"), 2)
        report = str(data.get("verification_report", "") or "")
        if not report or not os.path.isfile(report):
            die("verify-pass 要求先登记真实存在的验证报告:"
                "mae-flow spec set verification_report \"<路径>\"。"
                "验证结论不能凭口头产生。", 2)
        # 校准实锤:0 字节报告与零任务清单曾可满足"三重硬校验"——空产物
        # 不能证明任何事。
        try:
            if os.path.getsize(report) == 0:
                die("验证报告 %s 是空文件——空报告不能证明验证发生过;"
                    "写入真实验证结论后重试。" % report, 2)
        except OSError:
            pass
        try:
            _label, tasks_txt = specengine.tasks_source(os.getcwd(), cn)
        except specengine.SpecEngineError as exc:
            die("实现清单无法读取:" + str(exc), 2)
        if not re.search(r"^\s*[-*]\s*\[[ xX]\]", tasks_txt or "", re.M):
            die("实现清单没有任何任务条目(空清单不能证明实现完成):"
                "至少列出本单真实完成的任务并勾选后重试。", 2)
        ok, why = ev_tasks_checked({}, st)
        if not ok:
            die("verify-pass 前实现清单仍有未完成项:" + why, 2)
        data["verify_result"] = "pass"
        data["branch_status"] = "handled"
        data["verified_at"] = now
        data["phase"] = "archive"
        st.setdefault("history", []).append(
            {"step": st["current"], "result": "spec:verify-pass", "note": report, "at": now})
        save_state(st)
        print("[mae-flow] 规格符合性已通过:verify_result=pass,阶段 verify → archive。")
        return
    die("未知的 spec 动作: " + str(action), 2)


def cmd_allow(flow, st, args):
    """break-glass:为一次被误拦的动作签发单次放行令(用户裁决,强验真)。"""
    if st is None:
        die("流程未启用,gate 本来就不拦,无需放行令。", 2)
    bid = (args.block_id or "").strip()
    try:
        recent = (json.load(open(GATE_STRIKES_PATH, encoding="utf-8")) or {}).get("recent", {})
    except Exception:
        recent = {}
    rec = recent.get(bid)
    if not rec:
        listing = "\n".join(
            "  %s  %s  %s" % (k, v.get("rule", "?"), (v.get("sample", "") or "")[:60])
            for k, v in sorted(recent.items(), key=lambda kv: kv[1].get("at", ""),
                               reverse=True)[:5])
        die("未找到拦截编号 %s 的记录。最近的拦截:\n%s\n请使用报错里给出的编号,不要自行构造。"
            % (bid or "(空)", listing or "  (无)"), 2)
    if rec.get("step") != st.get("current"):
        die("拦截编号 %s 属于步骤 %s,当前步骤是 %s;放行令只能在拦截发生的步骤签发。"
            % (bid, rec.get("step", "?"), st.get("current", "?")), 2)
    ok, why = _ack_verified(st, args.ack or "", exact=True)
    if not ok:
        die("放行令签发验真失败:" + why
            + "。必须先把动作原文和拦截原因展示给用户,取得用户明确同意的原话。", 2)
    head = sh("git rev-parse --verify HEAD")

    def issue(data):
        data = data or {}
        data[bid] = {"rule": rec.get("rule", ""), "step": st.get("current", ""),
                     "head": head, "sample": rec.get("sample", ""),
                     "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                     "ack": (args.ack or "")[:200], "used": False}
        return data
    update_json(GATE_PERMITS_PATH, issue, default={}, recover_corrupt=True)
    st.setdefault("history", []).append({
        "step": st.get("current", ""), "result": "gate:allow-issued",
        "note": rec.get("rule", "") + " " + bid,
        "at": time.strftime("%Y-%m-%d %H:%M:%S")})
    save_state(st)
    print("[mae-flow] 已签发一次性放行令 %s(规则 %s):仅对该动作生效一次,"
          "绑定当前代码版本与步骤,用后即废、代码变化即废。请原样重试刚才被拦的那个动作。"
          % (bid, rec.get("rule", "")))


# Bash 命令里能落盘的动作(cmd/PowerShell/git-bash 常见写法都算)。
# 强证据:动词语义就是"写/删这个文件",命中即按写盘处理。
WRITEISH_STRONG = (r"(sed\s+-i|perl\s+-i|git\s+apply|Set-Content|Out-File|Add-Content"
                   r"|\brm\s+|(?<![\w-])del\s+)")
# 弱启发:cp/mv/tee/patch 的源码参数可能只是"读源码写别处"(cp src/a.c /tmp)。
# 命中只软提醒不硬拦——bash 写检测定位是软提醒层(MAINTAINERS 3.3),真正门槛在
# done 证据。历史最高频误报:裸 `>` 把 `2>&1` 只读命令判成写盘、`\bpatch\b`
# 命中 git format-patch;重定向改为解析真实落盘目标(_redirect_targets)。
WRITEISH_WEAK = (r"(\btee\s+|\bcp\s+|\bmv\s+|(?<![\w-])copy\s+|(?<![\w-])move\s+"
                 r"|(?<![\w-])patch\b)")


def _advisory_lightcheck_before_commit(st, snapshot):
    """Check exact commit candidates; any timeout/crash remains non-blocking."""
    try:
        result = _pending_lightcheck_scope(st, snapshot)
    except BaseException as exc:
        result = _lightcheck_tool_error(
            "提交前轻量检查启动失败，已自动放行: " + str(exc))
        result["report_path"] = _save_lightcheck_result(
            result, "提交前：异常安全降级")
    _print_lightcheck_result(result, quiet=True)


def _redirect_targets(c):
    """提取 >/>> 的真实落盘目标。fd 复制(2>&1)与空设备不算写文件。

    校准实锤:目标带引号(`> "src/a.c"`,Windows 习惯写法)曾整体逃逸捕获,
    源码保护与 specs 真相源双拦全部短路——引号形态必须同样捕获。"""
    out = []
    for m in re.finditer(
            r"""\d*>{1,2}\s*(?:"([^"]+)"|'([^']+)'|([^\s;|&<>'"]+))""", c):
        t = (m.group(1) or m.group(2) or m.group(3) or "").strip()
        if not t or t.lower() in ("/dev/null", "nul"):
            continue
        out.append(t)
    return out


def _gate_edit(flow, st, sid, step, intent, jdie):
    p = intent.subject
    rel = _repo_rel_for_match(p)
    pm = rel if rel is not None else p
    if p.lower().endswith((".comet.yaml", ".openspec.yaml")):
        die("禁止手动编辑 comet/openspec 状态文件(.comet.yaml/.openspec.yaml),它们由 comet-state 维护(黑名单#4)。", 2)
    if re.search(r"\.mae-flow\.json(?:\.[\w-]+)*$|\.mae-flow-history\.jsonl$|\.mae-flow-need-reload$"
                 r"|(^|/)\.mae-flow-work/moonlight-report\.md$", p, re.I):
        die("流程状态/令牌/历史账本/待重启标记/月光宝盒报告由 mae-flow 与 hook 维护,禁止直接编辑或删除。"
            "待重启标记只能靠**重启会话**清除(SessionStart 自动删),不许手动绕过——绕过 = skill 没加载就往下走。", 2)
    if re.search(r"(^|/)\.mae-flow-defaults\.json$", p, re.I):
        die("流程运行期间禁止修改 .mae-flow-defaults.json:它决定源码/测试路径的判定口径,"
            "改它等于改门禁规则。团队预设请在流程外走正常评审提交。", 2)
    if re.search(r"(^|/)\.env(\.[\w.-]+)?$", p, re.I) and not re.search(
            r"\.env\.(example|sample|template|dist|defaults)$", p, re.I):
        die(".env 类密钥文件禁止写入(凭据保护);确需修改请用户手动操作。", 2)
    if sid == "config_confirm" and re.search(r"(^|/)docs/req/", pm, re.I):
        jdie("edit-docs-req",
             "配置确认阶段禁止 Agent 直接写 docs/req（Windows shell/编辑工具编码不可作为需求真相源）。"
             "用户口述先执行 mae-flow messages，再用 requirement-record --message-id；"
             "已有文本用 requirement-record --source。")
    plugin_root = norm(os.path.abspath(os.path.join(HERE, ".."))).lower()
    if norm(os.path.abspath(p)).lower().startswith(plugin_root + "/"):
        die("禁止修改插件自身(flow/steps/hooks/scripts):流程规则不是交付改动的对象。", 2)
    if re.search(flow["specs_truth"], pm, re.I) and not step.get("allow_specs_write"):
        jdie("edit-specs",
             f"openspec/specs/ 为真相源,当前步骤 {sid or '未初始化'} 禁止写入(黑名单#3)。")
    if _is_source_path(p, st, flow):
        if _checkpoint_review_locked(st):
            item = _checkpoint_locked_item(st) or {}
            jdie(
                "edit-checkpoint-review",
                "检查点 %s 的检视快照已经冻结，Agent 不能继续改源码。"
                "用户选择“需要调整代码”后执行 checkpoint decide revise，"
                "状态回到 coding 才能修改。"
                % item.get("id", item.get("title", "最终检视")))
        if not step.get("allow_source_edit"):
            jdie("edit-source",
                 f"当前步骤 {sid}({step.get('title','')})禁止修改源码;先 mae-flow current 查看该做什么。")
        tp = _effective_test_patterns(st) if step.get("tests_only") else []
        ul = (st or {}).get("unlock") or {}
        unlocked = ul.get("scope") == "source" and ul.get("step") == sid
        if tp and not unlocked and not any(re.search(t, pm, re.I) for t in tp):
            jdie("edit-tests-only",
                 f"当前步骤 {sid} 仅允许写测试路径(当前生效规则: {'|'.join(tp)})。"
                 "UT 暴露的疑似源码缺陷不是死路:自查确认后带报告呈用户裁决,用户判定确为代码缺陷时执行 "
                 "mae-flow unlock source --reason <裁决结论> --ack \"用户原话\" 解锁本步修复;"
                 "禁止未经用户裁决自行改源码。")
    sys.exit(0)


def _gate_commit_candidates(c, st, jdie):
    candidate_snapshot = _pending_commit_candidates(c)
    item = _checkpoint_locked_item(st) or {}
    receipt = item.get("receipt") or {}
    if item.get("status") == "commit_pending" and receipt.get("snapshot"):
        expected = set((receipt.get("snapshot") or {}).keys())
        actual = set(candidate_snapshot.get("paths") or [])
        current = _reviewed_snapshot_current(st, item)
        if current != (receipt.get("snapshot") or {}):
            jdie(
                "bash-checkpoint-reviewed-snapshot",
                "检视后的未提交代码已经变化，禁止拿旧确认提交新 diff。"
                "保留现场并重新进入调整、编译和检视。")
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            detail = []
            if missing:
                detail.append("漏掉 " + "、".join(missing[:8]))
            if extra:
                detail.append("夹带 " + "、".join(extra[:8]))
            jdie(
                "bash-checkpoint-reviewed-files",
                "本次 commit 必须精确等于用户刚检视的文件；"
                + "；".join(detail)
                + "。按 checkpoint status 输出的精确 git add/commit 执行。")
    (inherited, foreign_openspec, strong_artifacts,
     unproven_paths, artifact_hints) = _pending_commit_files(
         c, st, candidate_snapshot)
    if inherited:
        shown = "、".join(inherited[:8])
        more = "…" if len(inherited) > 8 else ""
        jdie(
            "bash-cross-delivery-carryover",
            "提交前检测到流程启动前已经存在、内容至今未变，且本单 Agent "
            "没有实际改写的文件: " + shown + more
            + "。它们属于上一单/用户现场，不能因为本次暂存而变成本单交付。"
              "执行 git restore --staged -- <上述路径> 只移出暂存区；"
              "若本单确实需要某文件，让 Agent 按本单需求实际修改并检视后再提交。")
    if foreign_openspec:
        shown = "、".join(foreign_openspec[:8])
        more = "…" if len(foreign_openspec) > 8 else ""
        jdie(
            "bash-foreign-openspec",
            "提交前检测到不属于当前 CHANGE_NAME 或本次定稿产物的 OpenSpec "
            "文件: " + shown + more
            + "。请从暂存区移除；STORY 只能写到 docs/story/STORY-<单号>.md，"
              "选择不入库后由流程移入 .mae-flow-work/story。")
    if strong_artifacts:
        shown = "、".join(strong_artifacts[:8])
        more = "…" if len(strong_artifacts) > 8 else ""
        jdie(
            "bash-build-artifacts",
            "提交前检测到既非 Agent 直接改写、又属于本次新增的高置信临时编译产物: "
            + shown + more
            + "。这些文件通常不应进入 MR。若已暂存，执行 "
              "git restore --staged -- <上述路径>（只移出暂存区，不删除本地文件），"
              "并把对应规则加入项目 .gitignore 后再提交；若命令是 git add && git commit，"
              "从 git add 清单中移除这些路径。")
    if unproven_paths:
        print(
            "[mae-flow] ⚠ 提交提示:以下文件不在 Agent 通过 Write/Edit/MultiEdit "
            "实际改写的候选范围内，可能是编译、格式化或生成命令的副作用；"
            "也可能是必要的移动/删除，因此本次不阻断。请逐个确认: "
            + "、".join(unproven_paths[:8])
            + ("…" if len(unproven_paths) > 8 else ""),
            file=sys.stderr)
    if artifact_hints:
        print(
            "[mae-flow] ⚠ 产物提示:以下候选位于常见输出目录或具有编译产物特征；"
            "即使 Agent 直接写过，也不代表必须提交，请结合 git diff 确认: "
            + "、".join(artifact_hints[:8])
            + ("…" if len(artifact_hints) > 8 else ""),
            file=sys.stderr)
    _advisory_lightcheck_before_commit(st, candidate_snapshot)


def _gate_bash_writes(flow, st, sid, step, intent, jdie):
    c = intent.subject
    toks = intent.tokens
    redirects = _redirect_targets(c)
    strong_write = bool(re.search(WRITEISH_STRONG, c, re.I))
    weak_write = bool(re.search(WRITEISH_WEAK, c, re.I))
    writeish = strong_write or weak_write or bool(redirects)
    if writeish and any(t.lower().endswith((".comet.yaml", ".openspec.yaml"))
                        for t in toks):
        die("comet/openspec 状态文件禁止经 Bash 改写:它们由 comet-state 维护(黑名单#4),"
            "直写等同伪造阶段/验证证据。", 2)
    if re.search(r"COMET_FORCE_PHASE", c, re.I):
        die("COMET_FORCE_PHASE 属于已退役的外部阶段引擎逃生口,本流程不再使用;"
            "阶段由 mae-flow spec 管理,异常先执行 mae-flow doctor。", 2)
    if re.search(r"runtime/vendor/(comet|openspec|superpowers|ponytail)/\S*\.(sh|mjs|js)\b"
                 r"|runtime/bin/openspec\b", c, re.I):
        die("禁止直接执行插件内嵌脚本:绕过 capability 包装会丢失内嵌 OpenSpec 路由等环境,"
            "退落到机器全局版本(版本锁失效)。请使用 current 给出的 capability 命令。", 2)
    if re.search(r"(?:^|[;&|(])\s*openspec\b", c):
        die("禁止调用机器全局 openspec CLI:schema 与归档语义锁定在内嵌 1.6.0,全局版本随"
            "上游发布漂移(版本锁失效);init 还会交互式生成工具目录污染仓库。"
            "请使用 current 给出的 capability openspec 命令。", 2)
    if (sid == "config_confirm" and writeish
            and guard_intent.hits_path(intent, r"(^|/)docs/req/")):
        jdie("bash-docs-req",
             "配置确认阶段禁止经 Bash/PowerShell/重定向写 docs/req。"
             "统一使用 mae-flow requirement-record 确定性写 UTF-8 并回读校验。")
    if writeish and guard_intent.hits_path(
            intent, r"\.mae-flow(\.json|-history\.jsonl|-need-reload|-defaults\.json)"
            r"|\.mae-flow-work/moonlight-report\.md"):
        die("流程状态/历史账本/待重启标记/仓库预设/月光宝盒报告由 mae-flow 维护,禁止经 Bash 改写/删除"
            "(待重启标记只能靠重启会话清;仓库预设决定门禁口径,流程外走正常评审提交)。", 2)
    if (writeish and guard_intent.hits_path(intent, flow["specs_truth"])
            and not step.get("allow_specs_write")):
        jdie("bash-specs",
             f"openspec/specs/ 为真相源,当前步骤 {sid or '未初始化'} 禁止经 Bash 写入(黑名单#3)。")
    source_toks = [t for t in toks if _is_source_path(t, st, flow)]
    redirect_sources = [t for t in redirects if _is_source_path(t, st, flow)]
    offenders = list(dict.fromkeys(
        redirect_sources + (source_toks if strong_write else [])))
    if offenders:
        if _checkpoint_review_locked(st):
            item = _checkpoint_current(st) or {}
            jdie(
                "bash-checkpoint-review-source",
                "检查点 %s 的检视快照已经冻结，禁止经 Bash 改源码。"
                "先由用户选择继续或调整。" % item.get("id", "?"))
        if not step.get("allow_source_edit"):
            jdie("bash-source",
                 f"当前步骤 {sid} 禁止经 Bash 写源码文件(命中: {'、'.join(offenders[:3])});"
                 "先 mae-flow current 查看该做什么。")
        tp = _effective_test_patterns(st) if step.get("tests_only") else []
        ul = (st or {}).get("unlock") or {}
        if tp and not (ul.get("scope") == "source" and ul.get("step") == sid):
            bad = [t2 for t2 in offenders
                   if not any(re.search(t, (_repo_rel_for_match(t2) or t2), re.I)
                              for t in tp)]
            if bad:
                jdie("bash-tests-only",
                     f"当前步骤 {sid} 仅允许写测试路径(当前生效规则: {'|'.join(tp)});"
                     f"命中非测试源码: {'、'.join(bad[:3])}。经用户裁决确为代码缺陷时用 unlock source 解锁。")
    elif weak_write and source_toks and not step.get("allow_source_edit"):
        print(f"[mae-flow] ⚠ 软提醒:命令含 cp/mv/tee/patch 且提及源码路径({source_toks[0]})。"
              "当前步骤禁止写源码;若该命令确实会修改源码请勿执行。"
              "启发式不拦截(误报率高),真正校验在 done 证据层。", file=sys.stderr)
    sys.exit(0)


def cmd_gate(flow, st, args):
    # 全局安装只是提供能力，不代表用户授权接管当前仓库。没有状态时必须 fail-open；
    # 真正启用流程只认 init 创建的 .mae-flow.json。
    if st is None:
        sys.exit(0)
    sid = st["current"] if st else None
    step = flow["steps"].get(sid, {}) if st else {}
    # end 状态保留在主文件中是为了报告与下一单滚动，不代表流程门禁仍活跃。
    # Hook 主路由已整体旁路；这里再做一次 CLI 级防御，避免旧 Hook、手工 gate
    # 调用或并发终态迁移继续拦截普通开发。
    if step.get("terminal"):
        sys.exit(0)

    intent = guard_intent.parse_intent(args.what, args.arg)

    def jdie(rule, msg):
        # 裁决类规则统一走 break-glass 出口(放行令+三振熔断);绝对类仍用裸 die
        _gate_die(st, sid, rule, intent.subject, msg)
    # NTFS 不区分大小写:所有路径匹配一律 re.I
    if args.what == "edit":
        return _gate_edit(flow, st, sid, step, intent, jdie)
    if args.what == "bash":
        c = intent.subject
        # 按 token 匹配路径类 pattern:整串匹配时 `(^|/)src/` 对空格后的相对路径
        # (如 `sed -i ... src/main.c`)永远不命中
        toks = intent.tokens

        def hits_path(pat):
            return guard_intent.hits_path(intent, pat)

        # Edit/Write 之外，模型也可能用 python -c、node -e 等任意解释器直接碰状态文件。
        # 与其穷举所有写法，不如禁止 Bash 直接引用这些内部文件；读取统一走 status/current/doctor。
        if hits_path(r"(^|/)(\.mae-flow\.json(?:\.[\w-]+)*|\.mae-flow-history\.jsonl|\.mae-flow-need-reload"
                     r"|\.mae-flow-work/moonlight-report\.md)$"):
            die("流程状态、令牌、历史账本、待重启标记和月光宝盒报告禁止经 Bash 直接访问；"
                "查看请用 mae-flow status/current/doctor/moonlight report，修改只能走对应子命令。", 2)

        if intent.branch and st:
            name = intent.branch.name
            creating = intent.branch.creating
            want = st["config"].get("分支名", "")
            base = st["config"].get("基线分支", "")
            # branch_create 的第一步就是从基线切出约定分支；此时 checkout/switch
            # 基线必须放行，创建出来后仍只允许约定分支。其他步骤保持原有严格口径。
            baseline_checkout = (
                sid == "branch_create" and not creating and base and name == base)
            if name and want and name != want and not baseline_checkout:
                jdie("bash-branch-name",
                     f"分支名 {name} 不符合约定 {want}(内部流程建议的 feature/xx 命名一律拒绝)。")
        if (_checkpoint_review_locked(st)
                and re.search(r"(?:^|[\s;&|(])git\s+commit\b", c, re.I)):
            item = _checkpoint_locked_item(st) or {}
            if item.get("status") != "commit_pending":
                jdie(
                    "bash-checkpoint-review-commit",
                    "检查点 %s 的检视收据已冻结，当前状态 %s 不允许新增提交。"
                    "等待检视时先取得用户裁决；待推送时只允许 push。"
                    % (item.get("id", item.get("title", "最终检视")),
                       item.get("status", "?")))
        if (_checkpoint_review_locked(st)
                and re.search(r"(?:^|[\s;&|(])git\s+push\b", c, re.I)):
            item = _checkpoint_locked_item(st) or {}
            if item.get("status") != "push_pending":
                jdie(
                    "bash-checkpoint-push-before-verify",
                    "检查点 %s 当前为 %s；提交内容尚未通过 checkpoint status "
                    "核验，禁止提前 push 或把 commit/push 合成一条命令。"
                    % (item.get("id", item.get("title", "最终检视")),
                       item.get("status", "?")))
        if re.search(r"git\s+add\s+(-A\b|--all\b|\.(\s|$))", c):
            die("禁止宽提交(git add -A / --all / .):会把无关文件与不入库产物卷进交付分支"
                "(实战:STORY 选了不入库仍被卷进 MR)。git add 必须精确到文件/明确的产物目录。", 2)
        m = re.search(r"git\s+commit\b.*?(?:-m|--message[= ])\s*"
                      r"(?:\"([^\"]*)\"|'([^']*)'|(\S+))", c)
        if m and st:
            msg = m.group(1) or m.group(2) or m.group(3) or ""
            dan = st["config"].get("单号", "")
            if dan and not re.match(r"^\[" + re.escape(dan) + r"\]\[(feat|fix)\]", msg):
                jdie("bash-commit-format",
                     f"commit message「{msg}」不符合 [{dan}][feat|fix]描述 格式。")
            # 分支校验在提交这一刻做——拦截时机 = 错误发生时机。原来只在 done 时查,
            # 站错分支提交一整步才发现,返工要 cherry-pick;现在错的那一笔就进不去。
            want = st["config"].get("分支名", "")
            if want and sid not in ("config_confirm", "workflow_select", "branch_create"):
                cur_branch = sh("git branch --show-current")
                if cur_branch and cur_branch != want:
                    jdie("bash-commit-branch",
                         f"提交前拦截:当前分支 {cur_branch} != 本单约定分支 {want}。"
                         f"先 git checkout {want} 再提交;在错分支上积累提交,done 时才发现要整步返工。")
        if re.search(r"(?:^|[\s;&|(])git\s+commit\b", c, re.I):
            _gate_commit_candidates(c, st, jdie)
        if re.search(r"git\s+push\b.*(--force|-f\b)", c) or re.search(r"git\s+push\b.*\s\+\S+", c):
            die("禁止 force push(含 +refspec 形式)。", 2)
        if re.search(r"dispatch\.py", c):
            die("hook 分发器(dispatch.py)由 harness 自动调用,禁止手动执行——这是伪造 agent 收尾令牌的通道。", 2)
        if re.search(r"mae-flow\.py[^;&|]*\bexit\b[^;&|]*--interactive\b", c, re.I):
            die("exit --interactive 是 Hook/ack 全坏时给用户的真实终端逃生口，"
                "Agent 的 Bash 禁止调用或代答；把完整命令展示给用户手动执行。", 2)
        add_paths, _add_force = _git_add_pathspecs(c)
        if any(re.sub(r"/+$", "", path) == "openspec" for path in add_paths):
            jdie(
                "bash-wide-openspec-add",
                "禁止整目录 git add openspec/：它会把其他单遗留的 change/STORY "
                "一起卷入提交。open/design 只 add 当前 "
                "openspec/changes/{CHANGE_NAME}；archive 只 add spec archive "
                "输出的本次精确产物清单。")
        # 动词必须命令位锚定且只看它自己的参数:旧写法 `(mkdir|md|new-item)\b` 左侧
        # 不锚定,`git add openspec/changes/x/proposal.md` 里 "proposal.md" 的结尾
        # 也命中 "md"——提交规格文件被判成"手动创建",而 clean_paths 证据又要求
        # 必须提交,门禁与证据互锁卡死(实战黑事件)。
        m_mk = re.search(r"(?:^|[\s;&|(])(?:mkdir|md|new-item)\b"
                         r"((?:\s+(?:-\S+|\"[^\"]*\"|'[^']*'|[^\s;|&]+))*)", c, re.I)
        if m_mk and any(re.search(r"(^|/)openspec/", t, re.I)
                        for t in re.split(r"""[\s;|&()<>'"]+""", m_mk.group(1) or "")
                        if t and not t.startswith("-")):
            jdie("bash-mkdir-openspec",
                 "禁止手动创建 openspec 目录：change 必须由 `mae-flow spec new` 创建，"
                 "它会在建目录的同时登记当前单与阶段；手搓空目录没有状态登记，"
                 "后续证据校验会失败。先执行 current，并照本步骤给出的 spec 命令处理。")
        if re.search(r"\bcomet\s+init\b", c):
            die("禁止执行全局 comet init：它会初始化无关平台并污染项目。"
                "Mae-Flow 已内嵌所需运行时，执行 current 给出的 capability 命令即可，无需人工初始化。", 2)
        # 危险命令 denylist(社区共识高信号项;普通目录的 rm -r 不拦,只拦毁灭性目标)
        if re.search(r"(curl|wget|iwr|invoke-webrequest)[^|&;]*\|\s*(sudo\s+)?(sh|bash|zsh|iex|powershell)", c, re.I):
            die("危险命令拦截:管道执行远程脚本(供应链风险)。确需执行请用户手动运行。", 2)
        if re.search(r"git\s+clean\s+-\S*[xX]", c):
            die("危险命令拦截:git clean -x 会删除 ignore 文件(含 mae-flow 状态与令牌)。", 2)
        # 全树不可逆清除(校准实锤:未提交工作区也是磁盘上唯一的现场,一条
        # reset --hard 蒸发;而系统报错话术恰在诱导"回退改动"类命令)。
        # 裁决类 jdie:精确到文件的回退照常放行,全树清除三振后有放行令出口。
        if st and (re.search(r"git\s+reset\s+(-\S+\s+)*--hard\b", c)
                   or re.search(r"git\s+(checkout|restore)\s+(--\s+)?"
                                r"(\.|:/)(\s|$)", c)):
            jdie("bash-wipe-worktree",
                 "全树不可逆清除拦截(git reset --hard / checkout -- .):未提交的"
                 "工作区改动会全部蒸发。回退越权改动请精确到文件:"
                 "git checkout HEAD -- <文件>;确需全树清除,把风险展示给用户裁决。")
        # 毁灭目标只查 rm/rd 自己的命令段(校准实锤:整条命令 token 混查会把
        # `rm -rf build && cmake -S . -B build` 的「.」算到 rm 头上——重建编译
        # 的最高频惯用法被绝对拦且无出路;真阳性的毁灭 token 天然在 rm 段内)。
        for target in guard_intent.recursive_delete_targets(intent):
            die(f"危险命令拦截:对「{target}」的递归删除。确需执行请用户手动运行。", 2)
        if st and re.search(r"git\s+worktree\s+add", c):
            jdie("bash-worktree",
                 "本流程约定 branch 隔离,worktree 会使 mae-flow 状态机失联(新目录无状态文件,gate 全拦)。"
                 "若是为并行另一单开工作区:请用户手动建 worktree 并在新目录另起会话独立 init,本流程内不执行该命令。")
        return _gate_bash_writes(flow, st, sid, step, intent, jdie)
    die("gate 用法: gate edit <路径> | gate bash <命令>")


def _task_scope(st, diff_override=""):
    if diff_override:
        diff, err = diff_override, ""
    else:
        diff, err = _scope_diff(st)
        if err:
            return "", [], err
    out = argv_out([
        "git", "-c", "core.quotepath=false", "diff", "--name-status", diff])
    return diff, [x for x in out.splitlines() if x.strip()], ""


def _task_file_groups(files, st):
    """把子任务范围拆成业务源码、测试、构建三组；文档根本不应传进来。"""
    groups = {"business": [], "tests": [], "build": []}
    for path in files:
        if _is_build_path(path):
            key = "build"
        elif _is_test_file(path, st):
            key = "tests"
        else:
            key = "business"
        if path not in groups[key]:
            groups[key].append(path)
    return groups


def _build_root_marker(directory):
    """返回目录中的显式构建入口；只读一层，避免为了定位模块递归扫大仓。"""
    try:
        names = os.listdir(directory)
    except OSError:
        return ""
    for name in sorted(names, key=str.lower):
        low = name.lower()
        full = os.path.join(directory, name)
        if (os.path.isfile(full)
                and (low in SOURCE_FILENAMES
                or (low.startswith("requirements") and low.endswith(".txt"))
                or low.endswith(BUILD_DESCRIPTOR_EXTS))):
            return name
    return ""


def _execution_root_for_file(path):
    """从相关代码向上找最近构建根；找不到时只回退到源码目录，绝不猜仓库根。"""
    repo = os.path.abspath(os.getcwd())
    absolute = os.path.abspath(path)
    directory = absolute if os.path.isdir(absolute) else os.path.dirname(absolute)
    if _is_build_path(path):
        rel = norm(os.path.relpath(directory, repo))
        return (rel if rel != "." else "."), "变更文件本身是构建入口"
    current = directory
    while current == repo or current.startswith(repo + os.sep):
        marker = _build_root_marker(current)
        if marker:
            rel = norm(os.path.relpath(current, repo))
            return (rel if rel != "." else "."), "检测到 " + marker
        if current == repo:
            break
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    if directory != repo and directory.startswith(repo + os.sep):
        return norm(os.path.relpath(directory, repo)), "未找到构建入口，按相关源码所在目录定位"
    return "", "未找到可证明的模块目录"


def _task_execution_roots(files):
    """生成去重的模块执行目录和依据，供任务卡阻止根目录意外全量构建。"""
    roots = []
    seen = set()
    unresolved = []
    for path in files:
        root, reason = _execution_root_for_file(path)
        if not root:
            unresolved.append(path)
            continue
        if root not in seen:
            roots.append((root, reason))
            seen.add(root)
    return roots, unresolved


def _append_task_files(lines, title, files):
    lines.append(title + ":")
    if files:
        lines.extend("- " + path for path in files)
    else:
        lines.append("- （无）")


def _append_execution_context(lines, files, kind):
    """把代码范围翻译成 Agent 可直接使用的 cwd；CodeCheck 扫描仍固定在项目根。"""
    roots, unresolved = _task_execution_roots(files)
    label = "修复后编译执行目录" if kind == "CODECHECK" else "编译/UT执行目录"
    lines.append(label + ":")
    for root, reason in roots:
        lines.append("- %s（%s）" % (root, reason))
    if unresolved:
        lines.append("- 未确定（相关文件: %s）" % "、".join(unresolved))
    if not roots:
        lines.append("- 未确定")
    if len(roots) > 1:
        lines.append("执行目录策略: 涉及多个模块，按上述目录分别定向验证；"
                     "禁止退回项目根执行一次全仓构建来代替分模块验证。")
    elif unresolved:
        lines.append("执行目录策略: 无法确定模块目录时按 NEEDS_INPUT/FAIL 如实上报；"
                     "禁止默认在项目根执行全量构建。")
    else:
        lines.append("执行目录策略: 从上述目录执行任务卡配置的编译/UT入口；"
                     "不得自行扩大为项目根全量构建。")


def _requirement_sources(st):
    out = []
    doc = st.get("config", {}).get("需求文档", "")
    if doc and os.path.exists(doc):
        out.append(os.path.abspath(doc))
    cn = st.get("config", {}).get("CHANGE_NAME", "")
    if cn:
        # 双布局:v5 的规格在 change.md 规格条目节,legacy 在 specs/<域>/spec.md;
        # 归档后两者都随目录进 archive。审计实锤:漏掉 change.md 时,v5 单的
        # COMPILE/CODECHECK/UT 任务卡「需求/规格依据」永远缺规格。
        pats = [f"openspec/changes/{cn}/change.md",
                f"openspec/changes/{cn}/specs/*/spec.md",
                f"openspec/changes/archive/*{cn}*/change.md",
                f"openspec/changes/archive/*{cn}*/specs/*/spec.md",
                f"openspec/archive/*{cn}*/change.md",
                f"openspec/archive/*{cn}*/specs/*/spec.md"]
        for p in pats:
            out.extend(os.path.abspath(x) for x in globmod.glob(p))
    return list(dict.fromkeys(out))

def _store_agent_task(flow, st, args, context):
    kind = context["kind"]
    sid = context["sid"]
    document = context["document"]
    digest = document.digest()
    body = document.sealed_body()
    directory = os.path.abspath(os.path.join(
        ".mae-flow-work", "agent-tasks"))
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{sid}-{kind.lower()}.md")
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(body)
    lightcheck_result = context["lightcheck_result"]
    st.setdefault("agent_tasks", {})[kind] = quality_task_cards.task_record(
        step=sid, path=path, digest=digest, head=context["task_head"],
        scope=args.scope or "", checkpoint=context["checkpoint_id"],
        precommit_review=context["precommit_review"],
        initial_compile_net=(
            _working_source_net(context["task_head"], st, flow)
            if context["precommit_review"] else 0),
        source_snapshot=(
            _source_snapshot_since(context["task_head"], st, flow)
            if context["precommit_review"] else {}),
        allowed_files=(
            context["scan"].get("files", [])
            if kind == "CODECHECK" else []),
        task_files=context["task_files"],
        execution_roots=[
            root for root, _reason in _task_execution_roots(
                context["execution_files"])[0]],
        lightcheck=({
            "status": lightcheck_result.get("status"),
            "findings": len(lightcheck_result.get("findings") or []),
            "report_path": lightcheck_result.get("report_path", ""),
        } if lightcheck_result is not None else {}),
        ut_targets=context["ut_targets"] if kind == "UT" else {},
        unchanged_initial_dirty=context["inherited_dirty"],
        at=time.strftime("%Y-%m-%d %H:%M:%S"))
    if kind == "CODECHECK":
        append_codecheck_event(
            os.getcwd(), st, "agent.task_created", {
                "task_path": os.path.abspath(path),
                "task_sha256": digest,
                "head": context["task_head"],
                "allowed_files": context["scan"].get("files", []),
                "scan_count": context["scan"].get("count"),
                "scope": args.scope or "",
            })
    save_state(st)
    print(f"[mae-flow] {kind} 任务卡已生成: {path}")
    if kind == "COMPILE" and lightcheck_result is not None:
        _print_lightcheck_result(lightcheck_result, quiet=True)
    if kind == "CODECHECK":
        print("[mae-flow] CodeCheck 详细日志: %s"
              % norm(codecheck_log_path(os.getcwd(), st)))
    print(f"启动对应专项 agent 时只传这一句:\n读取并严格执行任务卡 \"{path}\"；最终报告必须原样带 TASK_CARD_SHA256: {digest}")

def cmd_agent_task(flow, st, args):
    """由代码生成完整子 Agent 任务卡，主模型不再临时拼参数。"""
    kind = args.kind.upper()
    sid = st["current"]
    checkpoint_id = str(getattr(args, "checkpoint", "") or "")
    task_diff_override = ""
    precommit_review = False
    (st.get("risk_acceptances", {}) or {}).pop(kind, None)  # 新任务卡=新证据轮次，旧风险确认作废
    if not quality_task_cards.task_allowed(kind, sid):
        die(f"当前步骤 {sid} 不允许生成 {kind} 任务卡；先执行 current,禁止提前派发。", 2)
    if checkpoint_id:
        if kind != "COMPILE":
            die("--checkpoint 只用于 compile 任务卡。", 2)
        item = _checkpoint_current(st)
        review_state = _development_review(st) or {}
        if (not item
                and (review_state.get("final_rework") or {}).get("status")
                == "coding"):
            die("当前是最终检视返工，原检查点已闭环；不要传 --checkpoint，"
                "按本步骤正常生成编译任务卡并重走质量链。", 2)
        if (not item or item.get("id") != checkpoint_id
                or sid != _checkpoint_expected_code_step(st)):
            die("检查点编译目标不匹配：当前应为 %s@%s，收到 %s@%s。"
                % ((item or {}).get("id", "无"), _checkpoint_expected_code_step(st),
                   checkpoint_id, sid), 2)
        if item.get("status") != "coding":
            die("检查点 %s 当前状态为 %s，不能重复生成编译任务卡。"
                % (checkpoint_id, item.get("status", "未知")), 2)
        checkpoint_base = item.get("fixed_base", "")
        precommit_review = bool(
            review_state.get("mode") == "staged"
            and _review_before_commit(review_state))
        if precommit_review:
            current_head = sh("git rev-parse --verify HEAD")
            if current_head != checkpoint_base:
                die("当前检查点采用先检视后提交，但 HEAD 已偏离固定基点。"
                    "禁止拿已提交代码伪装成 IDE 未提交差异；保留现场让用户归因。", 2)
            task_diff_override = "HEAD"
        elif checkpoint_base and argv_out(
                ["git", "cat-file", "-t", checkpoint_base]) == "commit":
            task_diff_override = checkpoint_base + "..HEAD"
    dirty_source = _blocking_dirty_source_paths(st, flow)
    inherited_dirty = _unchanged_initial_dirty_source_paths(st, flow)
    if dirty_source and not precommit_review:
        die("生成任务卡前仍有未提交源码/测试/构建文件: " + "、".join(dirty_source[:8])
            + "。任务卡只信 Git 可追踪范围；先按单号格式精确提交，或回退不属于本单的改动。", 2)
    if precommit_review:
        checkpoint_snapshot = _checkpoint_worktree_snapshot(st, flow)
        source_files = [
            path for path in checkpoint_snapshot
            if _is_source_path(path, st, flow)
        ]
        if not source_files:
            die("当前检查点只有配置、资源、文档或夹具等非代码交付差异，"
                "无需生成空编译任务卡；直接执行 checkpoint ready %s，"
                "流程会跳过编译并进入未提交 diff 检视。" % checkpoint_id, 2)
        diff = "HEAD"
        changes = argv_out([
            "git", "-c", "core.quotepath=false", "status", "--short",
            "--untracked-files=all", "--", *source_files,
        ]).splitlines()
    else:
        diff, changes, err = _task_scope(st, task_diff_override)
        if err:
            die(err, 2)
        source_files, source_err = (
            _source_files_for_diff(diff, st) if diff
            else (None, "无法计算任务卡 Git 范围"))
        if source_err:
            die(source_err, 2)
    if kind in ("COMPILE", "UT") and not source_files:
        die("本轮只有文档/台账等非代码变更，无需生成 %s 任务卡；直接 done。"
            "Harness 在证据层会自动放行，不要启动专项 Agent。" % kind, 2)
    lightcheck_result = None
    if kind == "COMPILE":
        try:
            lightcheck_result = (
                _working_lightcheck_scope(st, source_files)
                if precommit_review else
                _run_lightcheck_diff(
                    diff, source_files,
                    "编译前兜底：" + (checkpoint_id or sid)))
        except Exception as exc:
            lightcheck_result = _lightcheck_tool_error(
                "编译前轻量检查异常，已自动放行: " + str(exc))
            lightcheck_result["report_path"] = _save_lightcheck_result(
                lightcheck_result, "编译前：异常安全降级")
    ut_targets = {}
    if kind == "CODECHECK":
        scan = (st.get("quality", {}) or {}).get("codecheck_scan", {})
        if scan.get("step") != sid:
            die("先执行 codecheck-scan 冻结首检结果，再生成 CODECHECK 任务卡。", 2)
        if scan.get("scope_pending"):
            die("CodeCheck 仍有机器准备排除的候选，必须先让用户确认是否涉及本次修改，"
                "再按 scan 输出执行 codecheck-scope；禁止先派修复 Agent。", 2)
        if scan.get("status") == "TOOL_ERROR":
            die("CodeCheck 工具本轮已真实尝试但不可用/不可解析；这是建议项留痕，"
                "不派修复 Agent，直接 done。", 2)
        if scan.get("count", 0) == 0:
            die("机器首检为 0 告警，不应派 codecheck-fix-agent；直接 done。", 2)
        if not scan.get("files"):
            die("CodeCheck 首检没有业务代码文件却记录了告警，状态自相矛盾；"
                "重新执行 codecheck-scan，禁止把文档或全仓当修复范围。", 2)
        changed, why = _source_changed_since(scan.get("head", ""), st)
        if why:
            die("CodeCheck 首检基点失效:" + why + "；重新执行 codecheck-scan", 2)
        if changed:
            die("首检后、修复 Agent 启动前源码已变化: " + "、".join(changed[:5])
                + "。禁止主会话先修再补手续；回退这些改动后重扫。", 2)
    scan = (st.get("quality", {}) or {}).get("codecheck_scan", {})
    task_files = list(scan.get("files", [])) if kind == "CODECHECK" else list(source_files)
    groups = _task_file_groups(task_files, st)
    cfg = st.get("config", {})
    task_head = sh("git rev-parse --verify HEAD")
    lines = quality_task_cards.TaskCardDocument([
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
        f"开发检查点: {checkpoint_id or '无（主流程质量节点）'}",
        f"编译方式: {cfg.get('编译方式', '')}",
        f"UT生成方式: {cfg.get('UT生成方式', '')}",
        f"UT运行命令: {cfg.get('UT运行命令', '')}",
        "需求/规格依据:",
    ])
    if precommit_review:
        lines += [
            "检视/提交策略: 当前是分阶段“先检视、后提交”检查点。",
            "任务卡范围是当前未提交工作区（含 staged/unstaged/untracked）；"
            "允许为真实编译错误修复业务源码，但禁止 git commit、git push。",
            "编译成功后保留全部代码为未提交状态，由主流程冻结快照并让用户在 IDE 检视；"
            "用户确认后才会精确提交。",
        ]
    if inherited_dirty:
        lines.append("流程启动前已脏但指纹未变(不属于本任务,保持可见): "
                     + "、".join(inherited_dirty))
    sources = _requirement_sources(st)
    lines.extend("- " + x for x in sources)
    if not sources:
        if kind == "UT":
            lines.append("- （未找到；UT agent 必须 FAIL，禁止对着实现猜测试）")
        else:
            lines.append("- （未找到；本任务不据此扩大代码范围）")
    lines.append("任务相关文件（已排除 Markdown、规格历史、评审记录和其他过程文档）:")
    _append_task_files(lines, "被测/业务源码", groups["business"])
    _append_task_files(lines, "测试文件", groups["tests"])
    _append_task_files(lines, "构建/依赖文件", groups["build"])
    ignored_count = max(0, len(changes) - len(task_files))
    lines.append("未传给子 Agent 的非任务变更: %d 项" % ignored_count)
    execution_files = (task_files if kind == "COMPILE"
                       else (groups["business"] or groups["tests"] or groups["build"]))
    _append_execution_context(lines, execution_files, kind)
    if kind == "COMPILE" and lightcheck_result is not None:
        lines += [
            "Mae-Flow轻量编码预检: %s（%d 个本轮新触发建议；"
            "不替代正式 CodeCheck，不是编译门禁）" % (
                lightcheck_result.get("status", "UNKNOWN"),
                len(lightcheck_result.get("findings") or [])),
            "轻量预检报告: "
            + (lightcheck_result.get("report_path") or "报告写入失败，已自动放行"),
            "边界:compile-agent 不得为了轻量建议扩大职责；只处理真实编译错误。"
            "主会话在后续写码时按建议预防/修正。",
        ]
    # compound 沉淀统一在任务卡装载:一处注入,主流程/评审/小改三条质量链全部受益
    # (原先只有主流程 build/verify 的步骤文引用,rf/tw 的 agent 拿不到踩坑经验)。
    notes_path = os.path.join("docs", "delivery-notes.md")
    if os.path.isfile(notes_path):
        try:
            note_lines = [l.rstrip() for l in open(
                notes_path, encoding="utf-8", errors="replace").read().splitlines()
                if l.strip()][:40]
        except OSError:
            note_lines = []
        if note_lines:
            lines.append("本仓沉淀经验(按需参考;与本任务卡指令冲突时以任务卡为准):")
            lines.extend("- " + x.lstrip("- ") for x in note_lines)
    if kind == "CODECHECK":
        lines += [f"Harness首检告警数: {scan.get('count', '未执行')}",
                  "用户已确认不涉及本次修改的告警数: "
                  + (str(scan.get("stock_excluded"))
                     if isinstance(scan.get("stock_excluded"), int)
                     else "无法区分（本轮按 raw 全量计入）"),
                  "Harness首检分批数: %d（复验保持相同文件分批，禁止漏批或只跑最后一批）"
                  % max(1, len(scan.get("commands") or [])),
                  "Harness首检文件（仅是 CLI 扫描输入，不代表整文件都可修）: "
                  + "、".join(scan.get("files", [])),
                  "Harness首检告警(规则|文件): " + _render_warning_pairs(scan.get("pairs", [])),
                  "CodeCheck修复目标（硬边界，仅以下告警）:"]
        reason_rows = scan.get("scope_reasons") or []
        for pair in scan.get("pairs", []):
            rule, warning_file = pair[0], pair[1]
            warning_line = pair[2] if len(pair) > 2 else None
            reason = next((
                item.get("reason", "") for item in reason_rows
                if item.get("rule") == rule and item.get("file") == warning_file
                and item.get("line") == warning_line
            ), "缺少可细分行号/归属信息，按 Harness 保守纳入")
            lines.append("- %s | %s:%s | %s" % (
                rule, warning_file,
                warning_line if warning_line is not None else "?", reason))
        lines.append("职责:只修上列精确告警；即使同一文件还有其他告警也不得顺手处理。"
                     "主会话不得代修；修复后按任务卡编译方式验证并复验。")
    elif kind == "UT":
        # 覆盖口径(用户拍板):测试对象=本次修改的函数,不为文件中未修改的
        # 存量函数补测——范围蔓延等于每单背整个文件的测试债。
        ut_targets, target_err = _changed_hunk_targets(st, groups["business"])
        if target_err:
            die("无法计算 UT 函数级范围：" + target_err, 2)
        lines.append("UT覆盖目标（硬边界，不等于整个文件）:")
        if groups["business"]:
            for business_file in groups["business"]:
                targets = ut_targets.get(norm(business_file), [])
                if not targets:
                    lines.append("- %s | 无新增行范围（删除/重命名场景）；"
                                 "只验证本次移除或迁移行为，不给其他存量函数补测"
                                 % business_file)
                    continue
                for target in targets:
                    span = ("删除位置" if target.get("deletion_only")
                            else ("%d" % target["start"]
                                  if target["start"] == target["end"]
                                  else "%d-%d" % (target["start"], target["end"])))
                    context = target.get("context") or "Git 未识别函数名，按该行附近确认所属函数/行为"
                    suffix = ("（纯删除 hunk；只验证本次移除或迁移行为）"
                              if target.get("deletion_only") else "")
                    lines.append("- %s | 行 %s | %s%s" % (
                        business_file, span, context, suffix))
        else:
            lines.append("- 本轮无业务源码修改；只验证已变更测试/构建入口，"
                         "禁止为任意存量业务函数新增覆盖")
        lines += ["职责:只对任务卡范围补/改测试；**测试对象=本次修改的函数/行为"
                  "(上面硬边界所在函数)+规格条目 EARS 条目,禁止为文件中未修改的"
                  "存量函数补测**；必须调用任务卡指定的 Mae-Flow 自带"
                  " AutoUT/java-autout Skill（或明确配置的既有写法），并真实执行测试。"
                  "写“随生成方式自带”时由对应 Skill 根据项目决定实际命令，并在 EXECUTED_UT 如实报告。",
                  "评审意见处理不修改规格，测试依据使用上面列出的既有需求/规格。"]
    else:
        lines += ["职责:严格按任务卡的编译方式执行；配置为 build-fix 时必须调用 Mae-Flow"
                  " 插件自带的 build-fix Skill，禁止自己猜命令。"]
    _store_agent_task(flow, st, args, {
        "kind": kind, "sid": sid, "document": lines,
        "task_head": task_head, "checkpoint_id": checkpoint_id,
        "precommit_review": precommit_review, "scan": scan,
        "task_files": task_files, "execution_files": execution_files,
        "lightcheck_result": lightcheck_result, "ut_targets": ut_targets,
        "inherited_dirty": inherited_dirty,
    })

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
    # 兼容升级前已在途、尚未把过程目录写进 .gitignore 的项目；只改本机
    # info/exclude，避免诊断日志被后续宽范围操作意外带入提交。
    _git_local_runtime_ignore()
    append_codecheck_event(
        os.getcwd(), st, "scan.requested", {
            "head": sh("git rev-parse --verify HEAD"),
            "files": files, "file_count": len(files),
        })
    if files:
        result, err = _run_codecheck(files, st, "harness-scan")
    else:
        log_path = append_codecheck_event(
            os.getcwd(), st, "scan.empty", {
                "head": sh("git rev-parse --verify HEAD"),
                "reason": "no-business-code-files",
            })
        result, err = ({
            "total": 0, "pairs": [], "commands": [],
            "log_path": log_path or codecheck_log_path(os.getcwd(), st),
        }, "")
    if err:
        # CodeCheck 是辅助规范工具，不是编译器或测试器。它的版本、输出协议和
        # 可用性都不稳定；真实尝试一次后把诊断绑定当前源码即可，不让工具故障
        # 把交付流程永久封死，也不要求用户为同一工具问题反复确认。
        head = sh("git rev-parse --verify HEAD")
        st.setdefault("quality", {})["codecheck_scan"] = {
            "step": sid, "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "head": head, "count": None, "status": "TOOL_ERROR",
            "files": files, "pairs": [], "commands": [], "error": err,
            "log_path": codecheck_log_path(os.getcwd(), st),
        }
        append_codecheck_event(
            os.getcwd(), st, "scan.tool_error", {
                "head": head, "files": files, "error": err,
            })
        st["quality"].pop("codecheck_verify", None)
        _drop_agent_token("CODECHECK")
        (st.get("agent_tasks", {}) or {}).pop("CODECHECK", None)
        save_state(st)
        print("[mae-flow] ⚠ CodeCheck 已真实尝试但工具不可用或输出无法解析；"
              "诊断已绑定当前 HEAD，本轮按建议项留痕，不派修复 Agent，也不重复长跑。",
              file=sys.stderr)
        print(err, file=sys.stderr)
        print("[mae-flow] CodeCheck 详细日志: %s"
              % norm(codecheck_log_path(os.getcwd(), st)))
        print("直接 done；源码若变化，当前诊断会失效并要求重新尝试。")
        return
    # 机器只做预分类：变更行±3 内直接计入，窗口外不能再自动定性为
    # “存量债”。逐条保留为候选，交用户确认是否与本次修改有关。
    excluded_pairs = None
    if files:
        result, excluded_pairs = _scope_classify_codecheck(result, st, files)
    candidates = [
        {"id": "W%d" % (i + 1), "rule": pair[0], "file": pair[1],
         "line": pair[2],
         "reason": "未命中本次变更行或机器可识别的变更函数，需确认是否存在间接影响"}
        for i, pair in enumerate(excluded_pairs or [])
    ]
    if candidates and _moonlight(st):
        # 月光宝盒禁止询问用户；此时不能沿用旧逻辑自动排除，也不能卡住无人值守链。
        # 最保守的安全选择是把全部候选计入本次修复范围，宁可多报、不能漏报。
        result["pairs"] = list(result.get("pairs") or []) + [
            (item["rule"], item["file"], item["line"]) for item in candidates
        ]
        result["scope_reasons"] = list(result.get("scope_reasons") or []) + [{
            "rule": item["rule"], "file": item["file"], "line": item["line"],
            "reason": "月光模式无法人工裁决，保守纳入",
        } for item in candidates]
        result["total"] = len(result["pairs"])
        print("[mae-flow] 🌙 月光模式无法进行用户范围裁决；%d 条疑似范围外告警"
              "已保守全部计入本次修复范围。" % len(candidates))
        candidates = []
        excluded_pairs = []
    st.setdefault("quality", {})["codecheck_scan"] = {
        "step": sid, "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "head": sh("git rev-parse --verify HEAD"), "count": result["total"],
        "files": files, "pairs": result["pairs"], "commands": result["commands"],
        "scope_reasons": result.get("scope_reasons", []),
        "log_path": result.get("log_path", codecheck_log_path(os.getcwd(), st)),
        "raw_count": result["total"] + len(candidates),
        "scope_candidates": candidates,
        "scope_pending": bool(candidates),
        "stock_excluded": (0 if excluded_pairs is not None else None)}
    append_codecheck_event(
        os.getcwd(), st, "scan.completed", {
            "head": st["quality"]["codecheck_scan"]["head"],
            "files": files,
            "raw_count": st["quality"]["codecheck_scan"]["raw_count"],
            "kept_count": result["total"],
            "kept_pairs": result["pairs"],
            "scope_reasons": result.get("scope_reasons", []),
            "scope_candidates": candidates,
            "scope_pending": bool(candidates),
            "moonlight": _moonlight(st),
        })
    st["quality"].pop("codecheck_verify", None)
    if result.get("pairs"):
        print("[mae-flow] 机器已直接计入本次修改的告警:")
        for i, pair in enumerate(result["pairs"], 1):
            print("  A%d | %s | %s:%s" % (
                i, pair[0], pair[1], pair[2] if pair[2] is not None else "?"))
    if candidates:
        print("[mae-flow] ⚠ 机器按变更行±%d/变更函数预分类出 %d 条“归属不确定”告警；"
              "它们尚未被排除，必须先让用户确认是否涉及本次修改。"
              % (CODECHECK_LINE_SLACK, len(candidates)))
        for item in candidates:
            print("  %s | %s | %s:%s | %s" % (
                item["id"], item["rule"], item["file"], item["line"],
                item["reason"]))
        print("用 AskUserQuestion 分批展示上述候选，让用户选择“涉及本次修改”的编号。")
        print("确认后执行以下二选一命令（--ack 必须复制用户确认原话）：")
        print('  python "%s" codecheck-scope --include W1,W3 --ack "<用户原话>"'
              % os.path.abspath(sys.argv[0]))
        print('  python "%s" codecheck-scope --none --ack "<用户原话>"'
              % os.path.abspath(sys.argv[0]))
        print("在 codecheck-scope 完成前，禁止生成修复任务卡，也不能 done。")
    elif excluded_pairs is None and result["total"]:
        print("[mae-flow] ⚠ 本轮告警明细缺行号,无法区分存量与本单修改,"
              "已保守全算。", file=sys.stderr)
    # 每次重扫都是新一轮；旧 Agent 令牌不能替新告警背书。
    _drop_agent_token("CODECHECK")
    (st.get("agent_tasks", {}) or {}).pop("CODECHECK", None)
    save_state(st)
    print(f"[mae-flow] CodeCheck 首检完成:业务文件 {len(files)} 个,告警 {result['total']} 条。")
    print("[mae-flow] CodeCheck 详细日志: %s"
          % norm(result.get("log_path") or codecheck_log_path(os.getcwd(), st)))
    if candidates:
        print("先完成用户范围确认；此时显示的告警数仅为机器明确相关部分。")
    elif result["total"]:
        print("禁止主会话修复。下一步执行 agent-task codecheck 生成完整任务卡，再启动 codecheck-fix-agent。")
    else:
        print("零告警，不派修复 agent；直接 done（期间源码若变化，证据会过期并要求重扫）。")


def cmd_codecheck_scope(flow, st, args):
    """把机器准备排除的 CodeCheck 结果交给用户裁定是否涉及本次修改。"""
    if st["current"] not in ("verify_codecheck", "tw_codecheck", "rf_codecheck"):
        die("codecheck-scope 只能在规范检查步骤使用。", 2)
    scan = (st.get("quality", {}) or {}).get("codecheck_scan", {})
    if scan.get("step") != st["current"]:
        die("尚无本步骤的 codecheck-scan 结果；先执行首检。", 2)
    candidates = scan.get("scope_candidates") or []
    if not candidates:
        die("本轮没有需要用户判断的疑似范围外告警，不需要 codecheck-scope。", 2)
    if not scan.get("scope_pending"):
        die("本轮 CodeCheck 涉及范围已经确认；代码未变化时直接按 current 继续。", 2)
    changed, why = _source_changed_since(scan.get("head", ""), st)
    if why:
        die("CodeCheck 首检基点失效:" + why + "；重新执行 codecheck-scan。", 2)
    if changed:
        die("首检后源码发生变化: " + "、".join(changed[:5])
            + "。旧候选不再代表当前代码，重新执行 codecheck-scan。", 2)
    include = {
        value.upper()
        for value in re.split(r"[\s,，、]+", args.include or "")
        if value.strip()
    }
    if bool(include) == bool(args.none):
        die("codecheck-scope 必须二选一：--include W1,W3 或 --none。", 2)
    valid = {str(item.get("id", "")).upper() for item in candidates}
    unknown = sorted(include - valid)
    if unknown:
        die("未知候选编号: " + "、".join(unknown)
            + "；只能从本轮输出的 " + "、".join(sorted(valid)) + " 中选择。", 2)
    if not args.ack:
        die("codecheck-scope 必须携带用户确认原话 --ack。", 2)
    ok, why = _ack_verified(st, args.ack)
    if not ok:
        die("CodeCheck 涉及范围确认验真失败:" + why, 2)
    ack_upper = str(args.ack).upper()
    if include:
        missing = sorted(
            item for item in include
            if not re.search(r"(?<![A-Z0-9])" + re.escape(item)
                             + r"(?![A-Z0-9])", ack_upper))
        if missing:
            die("--include 中的 " + "、".join(missing)
                + " 没有出现在用户确认原话里。必须让用户看到编号并明确选择，"
                  "不能由 Agent 根据自己的判断补选。", 2)
    elif not re.search(r"(?:均|都|全部).{0,4}不涉及|没有.{0,4}涉及|无.{0,4}涉及",
                       args.ack):
        die("--none 必须对应用户明确表示“全部/均不涉及本次修改”的原话，"
            "普通的“确认/继续”不能替代范围裁决。", 2)
    selected = [
        (item.get("rule", ""), item.get("file", ""), item.get("line"))
        for item in candidates if str(item.get("id", "")).upper() in include
    ]
    original = list(scan.get("pairs") or [])
    scan["pairs"] = original + selected
    scan["scope_reasons"] = list(scan.get("scope_reasons") or []) + [{
        "rule": item.get("rule", ""), "file": item.get("file", ""),
        "line": item.get("line"), "reason": "用户确认涉及本次修改（%s）" % item.get("id", ""),
    } for item in candidates if str(item.get("id", "")).upper() in include]
    scan["count"] = len(scan["pairs"])
    scan["stock_excluded"] = len(candidates) - len(selected)
    scan["scope_pending"] = False
    scan["scope_review"] = {
        "head": scan.get("head", ""), "included": sorted(include),
        "ack": args.ack, "at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    append_codecheck_event(
        os.getcwd(), st, "scope.decided", {
            "head": scan.get("head", ""),
            "candidates": candidates,
            "included": sorted(include),
            "excluded": [
                item.get("id") for item in candidates
                if str(item.get("id", "")).upper() not in include
            ],
            "ack": args.ack,
            "final_count": scan["count"],
            "stock_excluded": scan["stock_excluded"],
        })
    st["quality"].pop("codecheck_verify", None)
    _drop_agent_token("CODECHECK")
    (st.get("agent_tasks", {}) or {}).pop("CODECHECK", None)
    save_state(st)
    if include:
        print("[mae-flow] 用户确认以下候选涉及本次修改: "
              + "、".join(sorted(include)) + "；已加入本轮修复范围。")
    else:
        print("[mae-flow] 用户确认疑似范围外候选均不涉及本次修改。")
    print("最终本轮告警 %d 条，用户确认不涉及 %d 条。"
          % (scan["count"], scan["stock_excluded"]))
    print("[mae-flow] CodeCheck 详细日志: %s"
          % norm(scan.get("log_path") or codecheck_log_path(os.getcwd(), st)))
    if scan["count"]:
        print("现在执行 agent-task codecheck 生成任务卡并启动修复 Agent。")
    else:
        print("最终范围为 0 条，可直接 done。")


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
        "count": args.count, "at": rec["at"], "manual": True,
        "log_path": codecheck_log_path(os.getcwd(), st)}
    append_codecheck_event(
        os.getcwd(), st, "manual.result_recorded", {
            "head": head, "files": files, "count": args.count,
            "diagnostic": diag, "diagnostic_sha256": digest,
            "reason": args.reason, "ack": args.ack,
        })
    st["quality"].pop("codecheck_verify", None)
    _drop_agent_token("CODECHECK")
    (st.get("agent_tasks", {}) or {}).pop("CODECHECK", None)
    save_state(st)
    print(f"[mae-flow] 已记录人工核对结果: {args.count} 条，绑定 HEAD {head[:12]} 与诊断 SHA256 {digest[:12]}。")
    print("[mae-flow] CodeCheck 详细日志: %s"
          % norm(codecheck_log_path(os.getcwd(), st)))
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
    append_codecheck_event(
        os.getcwd(), st, "exemption.approved", {
            "head": sh("git rev-parse --verify HEAD"),
            "rule": rule, "file": file_name,
            "reason": args.reason, "ack": args.ack,
            "record_file": os.path.abspath(ex),
        })
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


def _story_source_candidates(ticket):
    """Find dirty STORY output for this ticket, including a wrong directory."""
    canonical = "docs/story/STORY-" + ticket + ".md"
    if os.path.isfile(canonical):
        return [canonical]
    candidates = []
    for path in _dirty_paths():
        if not os.path.isfile(path) or not _is_story_document(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as stream:
                sample = stream.read(65536)
        except OSError:
            sample = ""
        if ticket.casefold() in (path + "\n" + sample).casefold():
            candidates.append(path)
    return list(dict.fromkeys(candidates))


def _unstage_uncommitted_story(path):
    """Remove a newly added STORY from the index without deleting its content."""
    staged = argv_out(
        ["git", "diff", "--cached", "--name-only", "--", path])
    if not staged:
        return
    restored = subprocess.run(
        ["git", "restore", "--staged", "--", path],
        shell=False, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=30,
    )
    if restored.returncode != 0:
        die(
            f"{path} 已暂存但无法安全移出暂存区:"
            + (restored.stderr or restored.stdout).strip()
            + "。先执行 git restore --staged -- " + path + " 后重试。", 2)


def _canonicalize_story_output(ticket, st=None):
    """Move one wrong-path STORY to the canonical location before validation."""
    canonical = "docs/story/STORY-" + ticket + ".md"
    if os.path.isfile(canonical):
        return canonical
    candidates = _story_source_candidates(ticket)
    if st is not None:
        written = _agent_written_paths()
        candidates = [
            path for path in candidates
            if (not _unchanged_initial_dirty(path, st)
                or _repo_path_identity(path) in written)
        ]
    if len(candidates) > 1:
        die(
            "发现多个本单 STORY 输出且都不在标准路径: "
            + "、".join(candidates)
            + "。拒绝猜测，请先合并为 " + canonical + "。", 2)
    if not candidates:
        return ""
    src = candidates[0]
    tracked_in_head = argv_out(
        ["git", "ls-tree", "-r", "--name-only", "HEAD", "--", src])
    if tracked_in_head:
        die(
            f"STORY 被写到错误路径且已经提交: {src}。"
            "请用普通后续提交把它迁移到 " + canonical
            + "，不能靠工作区移动掩盖已提交事实。", 2)
    _unstage_uncommitted_story(src)
    os.makedirs(os.path.dirname(canonical), exist_ok=True)
    os.replace(src, canonical)
    print(f"[mae-flow] ⚠ STORY 输出路径已自动纠正: {src} → {canonical}")
    return canonical


def _localize_story(ticket):
    """Move a not-for-commit STORY out of the delivery tree deterministically."""
    reason = _validate_config_value("单号", ticket)
    if reason:
        die("STORY 本地化失败:" + reason, 2)
    candidates = _story_source_candidates(ticket)
    canonical = "docs/story/STORY-" + ticket + ".md"
    if not candidates:
        print("[mae-flow] 用户选择 STORY 不入库；未发现本次生成的 STORY 文件，"
              "无需清理。")
        return ""
    if len(candidates) > 1:
        die(
            "发现多个与本单匹配的 STORY，无法安全猜测该保留哪一份: "
            + "、".join(candidates)
            + "。先合并为 " + canonical + " 后重跑 story-localize。", 2)
    src = candidates[0]
    tracked_in_head = argv_out(
        ["git", "ls-tree", "-r", "--name-only", "HEAD", "--", src])
    if tracked_in_head:
        die(
            f"用户选择 STORY 不入库，但 {src} 已存在于 HEAD。"
            "不能仅移动本地文件掩盖已提交事实；请用普通后续提交精确删除它，"
            "再重跑本命令。", 2)
    _unstage_uncommitted_story(src)
    _git_local_runtime_ignore()
    dst_dir = os.path.join(".mae-flow-work", "story")
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, os.path.basename(canonical))
    if os.path.exists(dst):
        stem, ext = os.path.splitext(os.path.basename(canonical))
        number = 2
        while os.path.exists(os.path.join(dst_dir, f"{stem}-{number}{ext}")):
            number += 1
        dst = os.path.join(dst_dir, f"{stem}-{number}{ext}")
    os.replace(src, dst)
    if src != canonical:
        print(f"[mae-flow] ⚠ STORY 曾被写到错误目录 {src}，已一并纠正。")
    print(f"[mae-flow] STORY 不入库，已移入 Git 本地排除的过程区: {norm(dst)}")
    return norm(dst)


def cmd_story_localize(args):
    """Cleanup command for standalone `/mae-flow:mae-flow story`."""
    return _localize_story((args.ticket or "").strip())


def cmd_envcheck(flow, args):
    checks = capability_diagnostics(os.getcwd(), include_codecheck=True)
    for item in checks:
        print(("✅ " if item["ok"] else "❌ ") + item["name"] + ": " + item["detail"])
    # CodeCheck is optional and is installed only when first used; its absence
    # does not make the plugin itself unusable.
    required_failed = [x for x in checks if not x["ok"] and x["name"] != "CodeCheck"]
    if required_failed:
        sys.exit(2)


def cmd_doctor(flow, st, args):
    sid = st["current"]
    step = flow["steps"][sid]
    print(f"项目根(状态文件所在): {os.getcwd()}")
    runtime = resolve_runtime(os.getcwd())
    print("✅ 运行模式: " + runtime.mode)
    if runtime.conflicts:
        print("⚠ 状态冲突: " + "、".join(runtime.conflicts)
              + "（完整流程具有唯一控制权，陈旧标记不会绕过当前门禁）")
        if "flow_and_action" in runtime.conflicts:
            print("   清理方式: 确认独立任务不再需要后执行 action cancel")
        if "flow_and_exit" in runtime.conflicts:
            print("   清理方式: 当前完整流程可正常继续；下次正常 exit/init 会重建退出标记")
    for error in runtime.errors:
        print("⚠ 非主控状态不可读: " + error)
    print(f"当前步骤: {sid} — {step['title']}")
    cur = sh("git branch --show-current")
    want = st["config"].get("分支名", "(未设置)")
    print(("✅" if cur == want else "❌") + f" 分支: 当前 {cur or '未知'} / 约定 {want}")
    cn = st["config"].get("CHANGE_NAME", "")
    # v3 后阶段真相源在 .mae-flow.json 的 spec 段;产物按布局探测
    # (v5=change.md,legacy=.openspec.yaml/四件套)。审计实锤:旧实现查
    # .comet.yaml,对 v3 之后的每张健康单都误报 ❌。
    if cn:
        cdir = f"openspec/changes/{cn}"
        ph = str(_spec_data(st).get("phase", "") or "?")
        if os.path.isfile(cdir + "/change.md"):
            print(f"✅ change: {cn}(v5 四合一),phase={ph}")
        elif os.path.isdir(cdir):
            print(f"✅ change: {cn}(旧布局在途),phase={ph}")
        elif ph == "archived" or globmod.glob(
                f"openspec/changes/archive/*{cn}*"):
            print(f"✅ change: {cn} 已归档,phase={ph}")
        else:
            print(f"❌ change: {cn} 目录不存在且未见归档(phase={ph})")
    else:
        print("⚠ change: CHANGE_NAME 未设置(open 之前属正常)")
    nac = _active_change_count()
    print(("✅" if nac <= 1 else "❌") + f" 活跃 change 数: {nac}" + ("(僵尸在场!comet 会抽错人,清理见下)" if nac > 1 else ""))
    guards = [p for p in comet_guard_paths(os.getcwd()) if os.path.isfile(p)]
    try:
        compat = bool(guards) and all(
            COMET_COMPAT_BEGIN in open(p, encoding="utf-8", errors="strict").read()
            for p in guards)
    except Exception:
        compat = False
    print(("✅" if compat else "⚠") + " 直接开发逃生兼容: "
          + ("Comet Hook 已识别退出标记" if compat else
             "未确认（不阻止当前流程；exit 会再次尽力修复，且永不因此拒绝退出）"))
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
    print(("✅ 插件运行时: 完整" if not ef else
           "❌ 插件运行时不完整: " + "、".join(ef)))
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
        captured = json.loads(open(STATE_PATH + ".usermsg", encoding="utf-8").read() or "[]")
        n = len(captured)
        print(f"✅ ack 验真存储: {n} 条用户输入" if n else
              "❌ ack 验真存储: 空(确认步骤会拒绝推进；请让用户发送一条普通消息后重试)")
        if captured:
            last = captured[-1]
            health = _text_corruption_reason(last.get("text", ""))
            print(("❌" if health else "✅") + " 最近用户输入: id=%s step=%s encoding=%s sha256=%s%s" % (
                last.get("id", "旧记录无ID"), last.get("step", "?"),
                last.get("input_encoding", "旧记录未知"),
                (last.get("sha256", "") or "?")[:12],
                (" 疑似乱码=" + health) if health else ""))
    except Exception:
        print("❌ ack 验真存储: 不存在(确认步骤会拒绝推进；检查 UserPromptSubmit hook，"
              "临时恢复方式是让用户发送普通确认消息后重试)")
    try:
        failures = json.load(open(FAILURE_PATH, encoding="utf-8")) if os.path.exists(FAILURE_PATH) else {}
        rec = failures.get("ack:" + sid, {})
        if rec:
            print(("❌" if int(rec.get("count", 0)) >= 2 else "⚠")
                  + " 当前确认自动校验失败: %s 次（%s）。流程未锁死；正确的新回复仍可恢复" % (
                      rec.get("count", 0), rec.get("reason", "")[:160]))
    except Exception:
        pass
    try:
        tok = json.loads(open(STATE_PATH + ".tokens", encoding="utf-8").read()).get("UTRUN", "")
        uts = tok.get("at") if isinstance(tok, dict) else tok
        print(("✅" if uts else "⚠") + f" UTRUN 令牌(UT 命令真实调起): {uts or '未记录(尚未跑 UT,或 PostToolUse-Bash 未触发)'}")
    except Exception:
        print("⚠ UTRUN 令牌: 无令牌文件")
    try:
        strikes = json.load(open(GATE_STRIKES_PATH, encoding="utf-8")) if os.path.exists(GATE_STRIKES_PATH) else {}
        hot = [(r, e) for r, e in (strikes.get("counts", {}) or {}).items()
               if int(e.get("count", 0) or 0) >= GATE_STRIKE_LIMIT]
        for rule, entry in hot:
            print("⚠ 疑似误拦: 规则 %s 在步骤 %s 连拦 %s 次(最近 %s)。"
                  "确属正当动作可用报错中的 allow 放行令;反复出现请把本行报给维护者修规则。"
                  % (rule, entry.get("step", "?"), entry.get("count"), entry.get("last_at", "?")))
    except Exception:
        pass


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
    atomic_write_text(MOONLIGHT_REPORT_PATH, text)
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
    atomic_write_json(AGENT_WRITES_PATH, {"paths": {}})
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
    decision = _moonlight_activation_decision(text)
    if decision != "allow":
        return False, (
            "捕获的用户原话没有明确要求开启月光宝盒"
            + ("，且表达了拒绝/关闭意图。" if decision == "deny"
               else "；咨询、介绍或仅提到名称都不算授权。")), ""
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


def _moonlight_blocked(flow, st, args):
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
        "id": delivery_moonlight.issue_id(len(issues)), "step": sid, "kind": "blocker",
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


def _moonlight_push_failed(flow, st, args):
    if st.get("current") != "push":
        die("moonlight push-failed 只允许在 push 步骤使用。", 2)
    reason = (args.reason or "").strip()
    if len(reason) < 12:
        die("push-failed 必须记录错误原文和已经尝试的处理。", 2)
    ml = _moonlight_data(st)
    issues = ml.setdefault("issues", [])
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    issue = {
        "id": delivery_moonlight.issue_id(len(issues)), "step": "push", "kind": "push",
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


def _moonlight_unlock_source(flow, st, args):
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


def _moonlight_finalize(flow, st, args):
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
    target = delivery_moonlight.finalize_target(st)
    st.setdefault("history", []).append({
        "step": "moonlight_review", "result": "moonlight:finalize",
        "note": ("带遗留确认" if issues else "晨间检查完成"),
        "at": ml["finalized_at"]})
    st["current"] = target
    st.setdefault("step_heads", {})[target] = sh("git rev-parse --verify HEAD")
    save_state(st)
    _write_moonlight_report(flow, st)
    print("[mae-flow] 月光宝盒晨间检查已结束。"
          + ("评审意见处理已完成。" if target == "end" else
             "已恢复普通模式并进入规格定稿；定稿提交后还要再次 push。"))
    print_current(flow, st)


def cmd_moonlight(flow, st, args):
    action = args.action
    if action in ("on", "continue"):
        if not args.ack:
            die("开启月光宝盒必须携带用户原话: --ack \"用户要求无人值守开发的原话\"。", 2)
        resumed_from_direct = False
        authorized_preinit = False
        activation_request = ""
        if os.path.exists(EXIT_PATH) and st is None:
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
            # 与 init 同一套前检:启动瞬间是无人值守唯一有人在场的时刻。跳过它,
            # node/git 缺失这类环境炸弹会留到凌晨 open 步才爆,整夜产出为零。
            try:
                prepare_project(os.getcwd())
            except CapabilityError as exc:
                die("插件运行时预检失败,月光宝盒未开启、未创建流程状态: %s。"
                    "请现在解决环境问题后重新发起。" % exc, 2)
            st = _new_state()
            save_state(st)
        # 一键入口允许 --ack 取本轮用户消息中的“月光宝盒/moonlight”短语，
        # 避免把整段需求塞进 shell；仍必须命中当前步骤后的真实用户输入。
        if not resumed_from_direct and not authorized_preinit:
            ok, why = _ack_verified(st, args.ack, exact=False)
            if not ok:
                die("月光宝盒授权验真失败:" + why, 2)
            activation_request = _moonlight_request_from_messages(st, args.ack)
            decision = _moonlight_activation_decision(activation_request)
            if decision != "allow":
                die("月光宝盒授权验真失败:用户原话没有明确要求开启无人值守模式"
                    + ("，且表达了拒绝/关闭意图。" if decision == "deny"
                       else "；咨询、介绍或仅提到名称都不算授权。"), 2)
        if flow["steps"].get(st.get("current", ""), {}).get("terminal"):
            # 上一单已交付完成:必须像 init 一样换单滚动。否则月光在终态(安全停点)上
            # 启用,整夜什么都不发生;授权已在旧状态的消息上验真通过,滚动后直接开新单。
            try:
                prepare_project(os.getcwd())
            except CapabilityError as exc:
                die("插件运行时预检失败，上一单状态仍保持可用：%s" % exc, 2)
            _clear_auxiliary_state()
            _append_history(st)
            os.replace(STATE_PATH, STATE_PATH + ".last")
            st = _new_state()
            save_state(st)
            print(f"[mae-flow] 上一单已完成,旧状态备份为 {STATE_PATH}.last;月光宝盒在新单上开启。")
        ml = _moonlight_data(st)
        if not ml.get("enabled"):
            st.pop("config_review", None)
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
                    "id": delivery_moonlight.issue_id(len(issues)), "step": "archive",
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
            # off 是拆掉全部夜间约束(Ask 拦截+Stop 防线)的开关,必须与 on 对称地
            # 要求用户原话——夜里没有用户消息,Agent 无法自行关闭后收工;
            # 早晨用户说一句"关闭月光宝盒"即可通过。
            if not args.ack:
                die("关闭月光宝盒需要 --ack \"用户要求关闭/恢复交互的原话\"。"
                    "无人值守运行中不允许 Agent 自行关闭;质量问题走 moonlight defer,"
                    "客观阻塞走 moonlight blocked。", 2)
            ok, why = _ack_verified(st, args.ack, exact=False)
            if not ok:
                die("月光宝盒关闭授权验真失败:" + why, 2)
            _moonlight_data(st)["enabled"] = False
            _moonlight_data(st)["disabled_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            st.setdefault("history", []).append({
                "step": st["current"], "result": "moonlight:off", "note": "恢复普通交互模式",
                "at": time.strftime("%Y-%m-%d %H:%M:%S")})
            save_state(st)
            _write_moonlight_report(flow, st)
        print("[mae-flow] 月光宝盒已关闭，当前断点保留；后续恢复普通确认和严格门禁。")
        print_current(flow, st)
        return
    if action in ("repair", "finalize") and st.get("current") == "moonlight_review":
        # 晨间入口不依赖 enabled 标记:off 之后 done 在 moonlight_review 仍会指向
        # repair/finalize,若这里再要求"已开启"就形成互相踢皮球,用户没有出路。
        pass
    elif not _moonlight(st):
        die("当前未开启月光宝盒。", 2)
    if action == "blocked":
        return _moonlight_blocked(flow, st, args)
    if action == "push-failed":
        return _moonlight_push_failed(flow, st, args)
    if action == "unlock-source":
        return _moonlight_unlock_source(flow, st, args)
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
        dirty = _blocking_dirty_source_paths(st, flow)
        if dirty:
            die("带遗留推进前必须先提交当前有效源码/测试/构建改动，否则 push 会漏文件: "
                + "、".join(dirty[:8]), 2)
        ml = _moonlight_data(st)
        issues = ml.setdefault("issues", [])
        issue_id = delivery_moonlight.issue_id(len(issues))
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
        # defer 必须复用 done 的源码回流纪律:UT 步内(经 unlock-source)改过被测源码后
        # defer,旧写法直达 next——被修改的源码从未重新编译/CodeCheck 就被推送。
        # 检测到步内源码变更时,遗留照记,去向改为对应质量链回流入口。
        recheck = flow["steps"].get(sid, {}).get("source_change_recheck")
        if recheck:
            _, migrate_err = _ensure_step_entry_head(flow, st, sid)
            changed, why = ([], migrate_err)
            if not migrate_err:
                changed, why = _business_source_changed_since_step(st, sid)
            if why:
                die("defer 前无法核对本步是否修改过被测源码:" + why
                    + "。为避免推送未复验的源码,拒绝直接推进;先解决核对问题或走 moonlight blocked。", 2)
            if changed:
                st["history"].append({
                    "step": sid, "result": "source-recheck:" + recheck,
                    "note": ("defer 时检测到步内源码变更(unlock=%s):"
                             % ("有" if (st.get("unlock") or {}).get("step") == sid else "无"))
                            + "、".join(changed[:10]),
                    "at": time.strftime("%Y-%m-%d %H:%M:%S")})
                st["current"] = recheck
                st.setdefault("step_heads", {})[recheck] = sh("git rev-parse --verify HEAD")
                st.pop("unlock", None)
                for k2 in ("COMPILE", "CODECHECK", "UT"):
                    (st.get("agent_tasks", {}) or {}).pop(k2, None)
                (st.get("quality", {}) or {}).pop("codecheck_scan", None)
                (st.get("quality", {}) or {}).pop("codecheck_verify", None)
                save_state(st)
                _write_moonlight_report(flow, st)
                print(f"[mae-flow] 遗留已登记,但本步修改过被测源码,自动回流 {recheck} "
                      "重新编译/CodeCheck/UT;不重新验证不得推送。")
                print_current(flow, st)
                return
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
        # Old reports may still contain an environment issue. Keep it visible,
        # but plugin-owned capabilities no longer have a setup repair phase.
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
        return _moonlight_finalize(flow, st, args)
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
    """Backward-compatible no-op for scripts written before embedded runtime."""
    print("[mae-flow] 能力随插件直接加载，不再需要 reload。执行 current 继续。")


def _prepare_spec_for_goto(st, target):
    """Synchronize the embedded spec phase when a user-approved goto rewinds work."""
    if target not in ("open", "design"):
        return True, ""
    data = _spec_data(st)
    phase = _spec_phase(st)
    if not phase:
        return False, (
            "尚未初始化本单交付登记，不能直接 goto %s。"
            "请先回到对应的 open 步创建变更记录。" % target
        )
    if phase == "archived":
        return False, (
            "本单规格已经完成不可逆定稿，不能在同一轮 goto %s 回写。"
            "请开启新的修订轮次。" % target
        )
    desired = "open" if target == "open" else "design"
    if target == "open":
        clear = (
            "design_doc", "plan", "verification_report",
            "verify_result", "verified_at", "archived_to", "archived_at",
        )
    else:
        clear = (
            "design_doc", "plan", "verification_report",
            "verify_result", "verified_at",
        )
    removed = [key for key in clear if key in data]
    for key in clear:
        data.pop(key, None)
    previous = phase
    data["phase"] = desired
    workflow = (st.get("choices", {}) or {}).get("workflow", "")
    if workflow:
        data["workflow"] = workflow
    if previous == desired and not removed:
        return True, ""
    detail = "规格阶段 %s → %s" % (previous, desired)
    if removed:
        detail += "，作废下游登记 " + "、".join(removed)
    return True, detail


def cmd_goto(flow, st, args):
    if not args.force:
        die("goto 是人工修复通道,必须 --force。")
    if not args.ack:
        die("goto 是**人工**修复通道,必须携带用户明确授权:--ack \"用户原话\"。"
            "证据不足该修证据/重跑 agent,禁止用 goto 绕过关卡——绕过 = 最严重违规。", 2)
    if args.step not in flow["steps"]:
        die("未知步骤: " + args.step)
    source = st.get("current", "")
    branch_context = source == "branch_create" or args.step == "branch_create"
    branch_adoption = branch_context and _branch_adoption_requested(args.ack)
    if args.step == source and not branch_adoption:
        die("当前已经在步骤 %s；同一步 goto 不会修复任何证据，反而会让本步旧授权失效。"
            "请按 current 的补救指引处理。若是在 branch_create 明确沿用现有分支，"
            "用户原话必须包含“沿用/在当前（现有）分支继续”。" % source, 2)
    ok, why = _ack_verified(st, args.ack)
    if not ok:
        die("goto 授权验真失败:" + why, 2)
    notes = []
    if branch_adoption:
        adopted, detail = _adopt_current_branch(st, args.ack)
        if not adopted:
            die("沿用现有分支失败:" + detail, 2)
        notes.append(detail)
    elif args.step == "branch_create":
        # A fresh branch attempt must not inherit a previous branch exception.
        st.pop("branch_resolution", None)
    if source == "branch_create" and args.step != "branch_create":
        branch_ok, branch_why = ev_branch_ok({}, st)
        if not branch_ok:
            die(
                "goto 不能只跳过 branch_create：后续提交和推进仍会校验本单分支。"
                + branch_why
                + " 若用户决定保留现有非基线分支，请让原话明确包含"
                  "“在现有分支上继续”，再执行本次 goto；系统会同步登记分支裁决。",
                2)
    workflow = (st.get("choices", {}) or {}).get("workflow", "")
    if args.step == "design" and workflow in ("hotfix", "tweak"):
        st.setdefault("choices", {})["workflow"] = "full"
        notes.append("工作流 %s → full（进入方案设计即完成升级）" % workflow)
    spec_ok, spec_note = _prepare_spec_for_goto(st, args.step)
    if not spec_ok:
        die("goto 转移准备失败:" + spec_note, 2)
    if spec_note:
        notes.append(spec_note)
    if args.step == "config_confirm":
        st.pop("branch_resolution", None)
    if args.step in {
            "config_confirm", "workflow_select", "branch_create", "grill_ask",
            "grill", "open", "design", "story_ask", "story",
            "hf_open", "tw_open", "rf_triage",
            "build_pace", "tw_pace", "rf_pace"}:
        st.pop("development_review", None)
    if args.step in PACE_STEPS:
        st.setdefault("protocols", {})["development_checkpoints"] = 1
    st.pop("unlock", None)   # 跳转同样使解锁失效
    st.pop("risk_acceptances", None)
    st.pop("config_review", None)
    st["history"].append({"step": st["current"], "result": "goto:" + args.step,
                          "note": "；".join(notes) if notes else "manual",
                          "at": time.strftime("%Y-%m-%d %H:%M:%S")})
    st["current"] = args.step
    st.setdefault("step_heads", {})[args.step] = sh("git rev-parse --verify HEAD")
    save_state(st)
    for note in notes:
        print("[mae-flow] goto 同步处理：" + note)
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
    """保留现场并解除项目接管；确认链损坏时仍必须有独立出口。"""
    if flow.get("steps", {}).get(st.get("current", ""), {}).get("terminal"):
        # end 已经由 Hook 全面旁路，保留主状态是为了报告和下一单 init 自动
        # 滚动。终态再转 Direct 不增加自由，只会让下一次启动多一道 message-id
        # 授权；即使 Agent 忽略 Hook 提示又调用裸 CLI，也必须幂等成功。
        print("[mae-flow] 流程已经完成且 Hook 门禁已解除，无需再次退出；"
              "终态记录会保留给 current/status/report 和下一单自动滚动。"
              "不要执行 exit --interactive。")
        return
    ack = args.ack or ""
    reason = args.reason or ""
    auth = "ack"

    intent_arg = getattr(args, "intent", None)
    interactive = bool(getattr(args, "interactive", False))
    # Hook 级退出受 12 秒看门狗约束，不能先跑可能很慢的 git status 预览；
    # 用户已经通过本条明确命令授权，退出后完整现场仍会落盘。
    if not intent_arg:
        _print_exit_preview(flow, st)
    if intent_arg:
        try:
            intent = json.load(open(EXIT_INTENT_PATH, encoding="utf-8"))
        except Exception as exc:
            die("退出事件凭据不可读或已消费：%s。不要循环重试；"
                "用户可在真实终端执行 exit --interactive。" % exc, 2)
        valid = (
            intent.get("id") == intent_arg
            and intent.get("step") == st.get("current")
            and time.time() - float(intent.get("epoch", 0)) <= 30
            and intent.get("sha256") == hashlib.sha256(
                str(intent.get("text", "")).encode("utf-8")).hexdigest()
        )
        try:
            os.remove(EXIT_INTENT_PATH)
        except OSError:
            pass
        if not valid:
            die("退出事件凭据已过期、步骤不符或内容损坏。重新发送 `/mae-flow:mae-flow exit`，"
                "或在真实终端执行 exit --interactive；不要再次要求用户说“我确认”。", 2)
        ack = str(intent.get("text", ""))
        reason = reason or "用户通过明确退出指令切换为普通开发"
        auth = "userprompt-hook"
    elif interactive:
        if not sys.stdin.isatty():
            die("exit --interactive 只允许用户在真实交互终端执行，Agent/Bash 管道不能代答。"
                "请把命令原样展示给用户手动运行。", 2)
        print("\n这是紧急逃生通道。请输入大写 EXIT 确认保留现场并解除 mae-flow 门禁：",
              end=" ", flush=True)
        if input().strip() != "EXIT":
            die("输入不匹配，未退出。", 2)
        ack = "TTY:EXIT"
        reason = reason or "用户通过真实终端紧急退出"
        auth = "interactive-tty"
    elif not ack:
        print("\n直接发送 `/mae-flow:mae-flow exit` 即可退出，UserPromptSubmit Hook 会把该用户事件作为授权，"
              "不再要求二次确认。")
        print("若 Hook 已损坏，请用户在真实终端手动执行：")
        print('python "%s" exit --interactive --reason "切换为普通开发"'
              % os.path.abspath(sys.argv[0]))
        return

    if auth == "ack":
        if not reason:
            die("exit 必须 --reason 记录为什么退出。也可让用户直接发送 `/mae-flow:mae-flow exit`。", 2)
        ok, why = _ack_verified(st, ack, exact=True)
        if not ok:
            die("exit 对话授权验真失败:" + why
                + "。不要让用户重复确认；请直接发送 `/mae-flow:mae-flow exit`，"
                "或在真实终端执行 exit --interactive。", 2)

    # 兼容补丁尽力完成，但绝不能反过来把逃生通道卡死。退出标记仍会原子落盘；
    # 未发现 Comet Hook 通常表示它尚未初始化或没有项目级拦截。
    found, patched, errors = ensure_direct_mode_compat(os.getcwd())
    compat_warnings = list(errors)
    if _active_change_count() > 0 and not found:
        compat_warnings.append(
            "存在在建规格但未发现旧版项目级 Comet Hook（新版本内嵌运行时下属正常现象）；"
            "若退出后仍被其他旧插件拦截，请更新或移除旧插件，不要运行 setup")

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    sid = st.get("current", "")
    st.pop("unlock", None)
    st.setdefault("history", []).append(
        {"step": sid, "result": "exited", "note": reason, "at": now})
    save_state(st)
    if auth != "userprompt-hook":
        _append_history(st, outcome="用户主动退出")

    snapshot = _unique_exit_dir(st)
    copied = _snapshot_state_files(snapshot)
    record = {
        "version": 1,
        "status": "exited",
        "at": now,
        "reason": reason,
        "ack": ack,
        "authorization": auth,
        "step": sid,
        "title": (flow.get("steps", {}).get(sid, {}) or {}).get("title", ""),
        "ticket": (st.get("config", {}) or {}).get("单号", ""),
        "workflow": (st.get("choices", {}) or {}).get("workflow", ""),
        "head": sh("git rev-parse --verify HEAD"),
        "branch": sh("git branch --show-current"),
        "dirty_paths": ([] if auth == "userprompt-hook" else _dirty_paths()),
        "dirty_paths_deferred": auth == "userprompt-hook",
        "snapshot": norm(snapshot),
        "comet_guard_paths": [norm(p) for p in found],
        "compat_warnings": compat_warnings,
    }
    _write_json_atomic(os.path.join(snapshot, "exit-record.json"), record)
    _clear_broken_exit_marker()
    save_versioned_json(EXIT_PATH, record, "exit")
    cleanup_errors = []
    state_removed = True
    for src, _ in copied:
        try:
            remove_with_retry(src)
        except OSError as exc:
            cleanup_errors.append("%s: %s" % (src, exc))
            if os.path.basename(src) == STATE_PATH:
                state_removed = False
    if not state_removed:
        # 运行模式裁决是「完整流程优先于退出标记」:主状态还在=门禁仍然生效。
        # 此时宣布"退出标记已生效"是谎报,用户会以为退了却继续被拦。
        die("退出未生效:主状态文件 %s 未能删除(可能被杀软/编辑器占用),完整流程门禁仍在。"
            "请关闭占用后重新发送 /mae-flow:mae-flow exit;现场已保存到 %s。清理失败明细: %s"
            % (STATE_PATH, norm(snapshot), "；".join(cleanup_errors)), 2)

    print("\n[mae-flow] 已退出流程。代码、提交和文档均已保留；流程现场已保存到 " + norm(snapshot))
    if patched:
        print("已让项目阶段门禁识别直接开发模式：" + "、".join(norm(p) for p in patched))
    if cleanup_errors:
        print("⚠ 部分附属状态文件未清理(退出已生效,不影响普通开发)：" + "；".join(cleanup_errors),
              file=sys.stderr)
    if compat_warnings:
        print("⚠ 退出兼容提示：" + "；".join(compat_warnings), file=sys.stderr)
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
    print("用户明确要求恢复或开启评审修复时，先执行 messages 取得真实消息 ID："
          "恢复原断点用 init --message-id <ID>；保留旧现场开启另一流程用 "
          "init --new --message-id <ID>。不同单并行时再另开 worktree。")


def cmd_runtime_doctor(runtime, args, state_error=""):
    """No-state diagnostic path: auxiliary corruption must never deadlock repair."""
    print("项目根(状态文件所在): " + os.getcwd())
    print("❌ 运行模式: corrupt（Hook 已 fail-open，普通改码不受阻）")
    for error in runtime.errors:
        print("   - " + error)
    if os.path.isfile(STATE_PATH):
        print("完整流程状态损坏。发送 `/mae-flow:mae-flow exit` 可保存坏现场并退出；"
              "Hook 同时损坏时由用户在真实终端执行 exit --interactive。")
        if getattr(args, "repair_state", False):
            die("完整流程状态包含唯一断点，doctor 不会自动覆盖。"
                "请使用独立 exit 逃生链保存现场。", 2)
        return
    if os.path.isfile(ACTION_PATH):
        print("独立任务控制指针损坏；普通开发已放行。"
              "可执行 doctor --repair-state 保存坏文件并清理指针。")
        if getattr(args, "repair_state", False):
            return cmd_action_cancel()
        return
    if os.path.isfile(EXIT_PATH):
        print("退出标记损坏；普通开发已放行，但重新接回流程前需要修复。"
              "可执行 doctor --repair-state 保存坏文件并重建退出标记。")
        if not getattr(args, "repair_state", False):
            return
        stamp = time.strftime("%Y%m%d-%H%M%S")
        base = os.path.abspath(os.path.join(
            ".mae-flow-work", "state-recovery", stamp))
        recovery, suffix = base, 2
        while os.path.exists(recovery):
            recovery, suffix = base + "-" + str(suffix), suffix + 1
        os.makedirs(recovery, exist_ok=False)
        bad = os.path.join(recovery, os.path.basename(EXIT_PATH) + ".bad")
        shutil.move(EXIT_PATH, bad)
        record = {
            "status": "exited",
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "reason": "doctor 修复损坏退出标记",
            "snapshot": "",
            "recovered_bad_marker": norm(bad),
        }
        _clear_broken_exit_marker()
        save_versioned_json(EXIT_PATH, record, "exit")
        print("[mae-flow] 损坏退出标记已保存到 %s，并重建普通开发模式标记。" % norm(bad))
        return
    print("未找到可识别的 Mae-Flow 标记；可按未初始化项目处理。")


def cmd_exit_corrupt_state(args, state_error):
    """状态 JSON 已坏时的独立逃生口；不能要求先修好状态才能退出。"""
    intent_arg = getattr(args, "intent", None)
    interactive = bool(getattr(args, "interactive", False))
    ack, auth = "", ""
    if intent_arg:
        try:
            intent = json.load(open(EXIT_INTENT_PATH, encoding="utf-8"))
            valid = (
                intent.get("id") == intent_arg
                and intent.get("step") == "__corrupt_state__"
                and time.time() - float(intent.get("epoch", 0)) <= 30
                and intent.get("sha256") == hashlib.sha256(
                    str(intent.get("text", "")).encode("utf-8")).hexdigest()
            )
        except Exception:
            valid, intent = False, {}
        try:
            os.remove(EXIT_INTENT_PATH)
        except OSError:
            pass
        if not valid:
            die("流程状态已损坏，退出事件凭据也不可用。请在真实终端执行 exit --interactive。", 2)
        ack, auth = str(intent.get("text", "")), "userprompt-hook-corrupt-state"
    elif interactive:
        if not sys.stdin.isatty():
            die("状态已损坏；exit --interactive 只能由用户在真实终端执行。", 2)
        print("[mae-flow] 状态 JSON 已损坏（%s）。输入大写 EXIT 保留坏文件并解除门禁：" % state_error,
              end=" ", flush=True)
        if input().strip() != "EXIT":
            die("输入不匹配，未退出。", 2)
        ack, auth = "TTY:EXIT", "interactive-tty-corrupt-state"
    else:
        die("流程状态已损坏，普通 ack 无法可靠验真。请重新发送 `/mae-flow:mae-flow exit`；"
            "若 Hook 也异常，在真实终端执行 exit --interactive。原状态不会删除。", 2)

    found, patched, errors = ensure_direct_mode_compat(os.getcwd())
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    snapshot = _unique_exit_dir({"config": {"单号": "corrupt-state"}})
    copied = _snapshot_state_files(snapshot)
    record = {
        "version": 1, "status": "exited", "at": now,
        "reason": getattr(args, "reason", None) or "流程状态损坏后紧急退出",
        "ack": ack, "authorization": auth, "step": "__corrupt_state__",
        "state_error": str(state_error), "head": sh("git rev-parse --verify HEAD"),
        "branch": sh("git branch --show-current"), "snapshot": norm(snapshot),
        "comet_guard_paths": [norm(p) for p in found], "compat_warnings": errors,
    }
    _write_json_atomic(os.path.join(snapshot, "exit-record.json"), record)
    _clear_broken_exit_marker()
    save_versioned_json(EXIT_PATH, record, "exit")
    leftovers = []
    for src, _ in copied:
        try:
            remove_with_retry(src)
        except OSError:
            leftovers.append(src)
    print("[mae-flow] 状态虽已损坏，但逃生成功；坏状态完整保存在 %s。现在按普通开发处理。"
          % norm(snapshot))
    if leftovers:
        # 损坏态 Hook 本就 fail-open,残留只影响提示横幅;但必须让用户知道文件还在。
        print("⚠ 以下坏状态文件被占用未能删除(不拦普通开发,稍后可手动清理): "
              + "、".join(norm(p) for p in leftovers), file=sys.stderr)
    if patched:
        print("已同步放行项目阶段门禁：" + "、".join(norm(p) for p in patched))
    if errors:
        print("⚠ 兼容提示：" + "；".join(errors), file=sys.stderr)


_COMMAND_UNHANDLED = object()


def _dispatch_action(flow, state, args):
    route = command_dispatch.action_route(args.action)
    if route is None:
        return _COMMAND_UNHANDLED
    return command_dispatch.invoke(
        route, globals(), flow=flow, state=state, args=args)


def _dispatch_story_localize(flow, state, runtime, args):
    if runtime.mode == RuntimeMode.STANDALONE:
        die("当前有 UT/CodeCheck/Grill 独立任务正在运行，"
            "先 finish/cancel 后再整理 STORY。", 2)
    if (
        state is not None
        and not flow.get("steps", {}).get(
            state.get("current", ""), {}).get("terminal")
    ):
        die("完整流程中的 STORY 不入库由 story 步 done 自动处理，"
            "无需手工执行 story-localize。", 2)
    return cmd_story_localize(args)


def _dispatch_init(flow, runtime, args):
    if runtime.mode == RuntimeMode.STANDALONE:
        die("当前有独立任务正在运行，不能同时初始化完整流程。"
            "先执行 action finish 或 action cancel。", 2)
    return cmd_init(flow, args)


def _dispatch_moonlight_start(flow, state, runtime, args):
    if runtime.mode == RuntimeMode.STANDALONE:
        die("当前有独立任务正在运行，不能叠加月光宝盒。"
            "先执行 action finish 或 action cancel。", 2)
    return cmd_moonlight(flow, state, args)


def _dispatch_global_command(flow, state, runtime, args):
    if args.cmd == "envcheck":
        return cmd_envcheck(flow, args)
    if args.cmd == "steps":
        return cmd_steps(flow, state, args)
    if args.cmd == "capability":
        return cmd_capability(args)
    if args.cmd == "template":
        return cmd_template(flow, args)
    if args.cmd == "story-localize":
        return _dispatch_story_localize(flow, state, runtime, args)
    if args.cmd == "init":
        return _dispatch_init(flow, runtime, args)
    if args.cmd == "moonlight" and args.action in ("on", "continue"):
        return _dispatch_moonlight_start(
            flow, state, runtime, args)
    if args.cmd == "lightcheck":
        return cmd_lightcheck(state, args)
    if args.cmd == "gate":
        return cmd_gate(flow, state, args)
    if args.cmd == "action":
        return _dispatch_action(flow, state, args)
    if args.cmd == "report" and args.all:
        return cmd_report_all()   # 账本聚合是无状态命令,不要求存在在途单
    return _COMMAND_UNHANDLED


def _dispatch_runtime_mode(runtime, args):
    if runtime.mode == RuntimeMode.DIRECT:
        if args.cmd == "messages":
            return cmd_direct_messages(args)
        if args.cmd in ("current", "status", "doctor", "exit"):
            return print_direct_mode_status()
        die("当前项目已退出 mae-flow，普通开发不需要执行流程命令。"
            "若用户明确要重新进入流程，先执行 messages，再按输出使用 init；"
            "旧质量证据不会复用。禁止移动或改名 .mae-flow.json.exited。", 2)
    if runtime.mode == RuntimeMode.STANDALONE:
        if args.cmd in ("current", "status", "doctor"):
            return cmd_action_status()
        die("当前只运行独立任务，不存在可推进的完整交付步骤。"
            "执行 action status 查看，或 action finish/action cancel 结束。", 2)
    if runtime.mode == RuntimeMode.CORRUPT and args.cmd in ("current", "status", "doctor"):
        return cmd_runtime_doctor(runtime, args)
    return _COMMAND_UNHANDLED


def _dispatch_flow_command(flow, state, args):
    if state is None:
        die("流程未初始化,先执行 init。")
    route = command_dispatch.flow_route(args.cmd)
    if route is None:
        return _COMMAND_UNHANDLED
    return command_dispatch.invoke(
        route, globals(), flow=flow, state=state, args=args)


def _load_dispatch_state(runtime, args):
    try:
        return load_state(), _COMMAND_UNHANDLED
    except Exception as state_error:
        if args.cmd == "exit":
            return None, cmd_exit_corrupt_state(args, state_error)
        if args.cmd == "doctor":
            return None, cmd_runtime_doctor(runtime, args, state_error)
        die("流程状态文件损坏，不能安全判断当前步骤：%s。不要删除或手改状态；"
            "用户可直接发送 `/mae-flow:mae-flow exit`，Hook 会保存坏文件并退出；"
            "Hook 也异常时在真实终端执行 exit --interactive。" % state_error, 2)


def main():
    args = parse_args()

    root, _ = find_project_root()
    if root != os.getcwd():
        os.chdir(root)
        if args.cmd != "gate":   # gate 保持输出纯净(stderr 会回传模型)
            print(f"[mae-flow] 调用目录非项目根,已定位到: {root}", file=sys.stderr)

    global FLOW
    flow = load_flow()
    FLOW = flow
    runtime = resolve_runtime(os.getcwd())
    state, state_result = _load_dispatch_state(runtime, args)
    if state_result is not _COMMAND_UNHANDLED:
        return state_result

    result = _dispatch_global_command(flow, state, runtime, args)
    if result is not _COMMAND_UNHANDLED:
        return result
    result = _dispatch_runtime_mode(runtime, args)
    if result is not _COMMAND_UNHANDLED:
        return result
    return _dispatch_flow_command(flow, state, args)


if __name__ == "__main__":
    main()
