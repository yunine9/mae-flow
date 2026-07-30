"""CLI responsibilities extracted from the historical entrypoint."""

from .shared import (
    BashGateContext, BashWriteContext, EditGateContext, HERE, OwnershipFacts,
    WRITEISH_STRONG, WRITEISH_WEAK, decide_bash_write, decide_commit_branch,
    decide_compile_task_commit, decide_edit, decide_ownership,
    decide_post_commit, decide_pre_commit, git_intent, guard_intent, os, re,
    replace, sys,
)
from .wiring import api

def _advisory_lightcheck_before_commit(st, snapshot):
    """Check exact commit candidates; any timeout/crash remains non-blocking."""
    try:
        result = api._pending_lightcheck_scope(st, snapshot)
    except BaseException as exc:
        result = api._lightcheck_tool_error(
            "提交前轻量检查启动失败，已自动放行: " + str(exc))
        result["report_path"] = api._save_lightcheck_result(
            result, "提交前：异常安全降级")
    api._print_lightcheck_result(result, quiet=True)

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
    rel = api._repo_rel_for_match(p)
    pm = rel if rel is not None else p
    plugin_root = api.norm(os.path.abspath(os.path.join(HERE, ".."))).lower()
    item = api._checkpoint_locked_item(st) or {}
    patterns = (
        tuple(api._effective_test_patterns(st))
        if step.get("tests_only") else ())
    unlock = (st or {}).get("unlock") or {}
    decision = decide_edit(EditGateContext(
        path=p,
        match_path=pm,
        step=sid or "",
        step_title=step.get("title", ""),
        inside_plugin=api.norm(os.path.abspath(p)).lower().startswith(
            plugin_root + "/"),
        specs_truth=flow["specs_truth"],
        allow_specs_write=bool(step.get("allow_specs_write")),
        is_source=api._is_source_path(p, st, flow),
        checkpoint_locked=api._checkpoint_review_locked(st),
        checkpoint_label=item.get(
            "id", item.get("title", "最终检视")),
        allow_source_edit=bool(step.get("allow_source_edit")),
        tests_only_patterns=patterns,
        source_unlocked=(
            unlock.get("scope") == "source"
            and unlock.get("step") == sid),
    ))
    if decision.kind == "absolute":
        api.die(decision.message, 2)
    if decision.kind == "block":
        jdie(decision.rule, decision.message)
    sys.exit(0)


def _compile_candidate_groups(candidate_snapshot, compile_side_effects):
    staged_paths = {
        api._repo_path_identity(path)
        for path in candidate_snapshot.get("staged_paths", ())
    }
    command_paths = {
        api._repo_path_identity(path)
        for path in candidate_snapshot.get("working_paths", ())
    }
    return (
        tuple(
            path for path in compile_side_effects
            if api._repo_path_identity(path) in staged_paths
        ),
        tuple(
            path for path in compile_side_effects
            if api._repo_path_identity(path) in command_paths
        ),
    )


def _enforce_commit_ownership(decision, jdie):
    if decision.block:
        if decision.block.rule in {
                "bash-compile-side-effects",
                "bash-build-artifacts",
                "bash-checkpoint-reviewed-snapshot",
                "bash-checkpoint-reviewed-files"}:
            # Integrity/provenance hard blocks are not user-decision permits.
            # Keep their recovery local and write no strike/permit state.
            api.die(decision.block.message, 2)
        jdie(decision.block.rule, decision.block.message)
    for message in decision.advisories:
        print(message, file=sys.stderr)


def _gate_compile_task_window(st):
    tokens = api._agent_token_data()
    decision = decide_compile_task_commit(
        st.get("current", ""),
        (st.get("agent_tasks", {}) or {}).get("COMPILE"),
        (tokens if isinstance(tokens, dict) else {}).get("COMPILE"),
    )
    if decision:
        api.die(decision.message, 2)


def _gate_commit_candidates(c, st, jdie):
    candidate_snapshot = api._pending_commit_candidates(c)
    item = api._checkpoint_locked_item(st) or {}
    receipt = item.get("receipt") or {}
    review_required = (
        item.get("status") == "commit_pending"
        and bool(receipt.get("snapshot")))
    (inherited, foreign_openspec, compile_side_effects, strong_artifacts,
     unproven_paths, artifact_hints) = api._pending_commit_files(
         c, st, candidate_snapshot)
    (staged_compile_side_effects, command_compile_side_effects) = (
        _compile_candidate_groups(candidate_snapshot, compile_side_effects))
    decision = decide_ownership(OwnershipFacts(
        review_required=review_required,
        expected_snapshot=receipt.get("snapshot") or {},
        current_snapshot=(
            api._reviewed_snapshot_current(st, item)
            if review_required else {}),
        candidate_paths=tuple(candidate_snapshot.get("paths") or []),
        inherited=tuple(inherited),
        foreign_openspec=tuple(foreign_openspec),
        compile_side_effects=tuple(compile_side_effects),
        staged_compile_side_effects=staged_compile_side_effects,
        command_compile_side_effects=command_compile_side_effects,
        strong_artifacts=tuple(strong_artifacts),
        unproven_paths=tuple(unproven_paths),
        artifact_hints=tuple(artifact_hints),
    ))
    _enforce_commit_ownership(decision, jdie)
    _advisory_lightcheck_before_commit(st, candidate_snapshot)

def _gate_bash_writes(flow, st, sid, step, intent, jdie):
    c = intent.subject
    toks = intent.tokens
    redirects = _redirect_targets(c)
    strong_write = bool(re.search(WRITEISH_STRONG, c, re.I))
    weak_write = bool(re.search(WRITEISH_WEAK, c, re.I))
    writeish = strong_write or weak_write or bool(redirects)
    source_toks = [t for t in toks if api._is_source_path(t, st, flow)]
    redirect_sources = [t for t in redirects if api._is_source_path(t, st, flow)]
    offenders = list(dict.fromkeys(
        redirect_sources + (source_toks if strong_write else [])))
    patterns = (
        tuple(api._effective_test_patterns(st))
        if step.get("tests_only") else ())
    unlock = (st or {}).get("unlock") or {}
    source_unlocked = (
        unlock.get("scope") == "source"
        and unlock.get("step") == sid)
    bad = [
        path for path in offenders
        if not any(re.search(
            pattern, (api._repo_rel_for_match(path) or path), re.I)
            for pattern in patterns)
    ] if patterns and not source_unlocked else []
    item = api._checkpoint_current(st) or {}
    decision = decide_bash_write(BashWriteContext(
        command=c,
        tokens=tuple(toks),
        writeish=writeish,
        strong_write=strong_write,
        weak_write=weak_write,
        hits_requirement=guard_intent.hits_path(
            intent, r"(^|/)docs/req/"),
        hits_internal_state=guard_intent.hits_path(
            intent,
            r"\.mae-flow(\.json|-history\.jsonl|-need-reload|-defaults\.json)"
            r"|\.mae-flow-work/moonlight-report\.md"),
        hits_specs_truth=guard_intent.hits_path(
            intent, flow["specs_truth"]),
        step=sid or "",
        allow_specs_write=bool(step.get("allow_specs_write")),
        offenders=tuple(offenders),
        source_tokens=tuple(source_toks),
        checkpoint_locked=api._checkpoint_review_locked(st),
        checkpoint_label=item.get("id", "?"),
        allow_source_edit=bool(step.get("allow_source_edit")),
        tests_only_patterns=patterns,
        source_unlocked=source_unlocked,
        bad_test_sources=tuple(bad),
    ))
    if decision.kind == "absolute":
        api.die(decision.message, 2)
    if decision.kind == "block":
        jdie(decision.rule, decision.message)
    if decision.kind == "advisory":
        print(decision.message, file=sys.stderr)
    sys.exit(0)


def _git_actions_preflight(command):
    wrapped_git = git_intent.wrapped_git_mutations(command)
    if wrapped_git:
        api.die(
            "Agent Bash 禁止用 Python/PowerShell/cmd/sh 等解释器或子进程"
            "换壳执行 git add/commit/push 来绕过 Hook。检测到: "
            + "、".join(wrapped_git)
            + "。保留现场并直接使用可见的 git 命令，让 Gate 正常裁决；"
            "若是用户本人决定在外部终端操作，应把命令和风险交给用户，"
            "不得由 Agent 代执行。",
            2,
        )
    alias_mutations = list(
        git_intent.inline_git_alias_mutations(command))
    for operation, _arguments in git_intent.git_invocations(command):
        expansion = api.argv_out([
            "git", "config", "--get", "alias." + operation,
        ])
        mutation = git_intent.git_alias_mutation(expansion)
        if mutation:
            alias_mutations.append(mutation)
    if alias_mutations:
        api.die(
            "Agent Bash 禁止用 mutating Git alias 隐藏真实写动作。"
            "检测到 alias 最终指向: "
            + "、".join(dict.fromkeys(alias_mutations))
            + "。请改用可见的 canonical git add/commit/push/"
            "restore/rm/revert 命令，让 Gate 预检 exact action；"
            "只读 alias 不受影响，用户外部终端不受 Hook 约束。",
            2,
        )
    opaque_pathspecs = git_intent.opaque_pathspec_mutations(
        command)
    if opaque_pathspecs:
        api.die(
            "Agent Git 写动作禁止使用 --pathspec-from-file/"
            "--pathspec-file-nul：Gate 无法在执行前核对其 exact candidates。"
            "检测到: " + "、".join(opaque_pathspecs)
            + "。请改为显式 `-- <paths>`，逐项展示并接受 ownership"
            " 检查；用户外部终端不受 Hook 约束。",
            2,
        )
    actions = git_intent.git_actions(
        command, actor="agent-hook")
    head_mutations = [
        action for action in actions
        if action.operation in ("commit", "revert")
    ]
    if len(head_mutations) > 1:
        api.die(
            "Agent 单条 Bash 中只能执行每次一个可审计的 "
            "git commit/revert；检测到 %d 个 HEAD 改写动作。"
            "请拆成独立命令，让 Gate 对每个 GitAction 的 message、"
            "paths 与 ownership 分别预检。用户在外部终端的操作"
            "不受此 Hook 约束。"
            % len(head_mutations),
            2,
        )
    return actions


def _gate_head_actions(actions, st, jdie):
    commit_present = any(
        action.operation == "commit" for action in actions)
    revert_actions = [
        action for action in actions
        if action.operation == "revert"
    ]
    if commit_present or revert_actions:
        # Issued COMPILE is a transient child-task boundary. It must win
        # before format/branch/checkpoint rules that create strikes.
        _gate_compile_task_window(st)
    if revert_actions:
        target = revert_actions[-1].commit or "非精确提交"
        jdie(
            "bash-git-revert-user-authorization",
            "Agent 发起 git revert 会直接改写 HEAD，必须绑定用户明确要求"
            "回退的 exact commit。当前目标: " + target
            + "。若用户原话已明确包含该 commit，使用本次拦截编号签发"
            "一次性 exact 放行；否则先让用户裁决。",
        )
    return commit_present


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
        api._gate_die(st, sid, rule, intent.subject, msg)
    # NTFS 不区分大小写:所有路径匹配一律 re.I
    if args.what == "edit":
        return _gate_edit(flow, st, sid, step, intent, jdie)
    if args.what == "bash":
        c = intent.subject
        git_command = args.arg
        git_actions = _git_actions_preflight(git_command)
        commit_present = _gate_head_actions(
            git_actions, st, jdie)
        # 按 token 匹配路径类 pattern:整串匹配时 `(^|/)src/` 对空格后的相对路径
        # (如 `sed -i ... src/main.c`)永远不命中
        toks = intent.tokens

        def hits_path(pat):
            return guard_intent.hits_path(intent, pat)

        internal_state = hits_path(
            r"(^|/)(\.mae-flow\.json(?:\.[\w-]+)*|"
            r"\.mae-flow-history\.jsonl|\.mae-flow-need-reload"
            r"|\.mae-flow-work/moonlight-report\.md)$")
        branch = intent.branch
        item = api._checkpoint_locked_item(st) or {}
        message_present, commit_message = (
            git_intent.git_commit_message(git_command))
        wanted = st["config"].get("分支名", "")
        add_paths, _add_force = api._git_add_pathspecs(
            git_command)
        context = BashGateContext(
            command=c,
            has_internal_state_path=internal_state,
            branch_name=branch.name if branch else "",
            branch_creating=bool(branch.creating) if branch else False,
            step=sid or "",
            wanted_branch=wanted,
            base_branch=st["config"].get("基线分支", ""),
            checkpoint_locked=api._checkpoint_review_locked(st),
            checkpoint_label=item.get(
                "id", item.get("title", "最终检视")),
            checkpoint_status=item.get("status", ""),
            ticket=st["config"].get("单号", ""),
            commit_message_present=message_present,
            commit_message=commit_message,
            current_branch="",
            add_paths=tuple(add_paths),
            recursive_delete_targets=
                guard_intent.recursive_delete_targets(intent),
            state_active=bool(st),
        )
        pre = decide_pre_commit(context)
        if pre.kind == "absolute":
            api.die(pre.message, 2)
        if pre.kind == "block":
            jdie(pre.rule, pre.message)
        if (message_present and wanted
                and sid not in (
                    "config_confirm", "workflow_select", "branch_create")):
            context = replace(
                context,
                current_branch=api.sh("git branch --show-current"),
            )
            branch_decision = decide_commit_branch(context)
            if branch_decision.kind == "block":
                jdie(branch_decision.rule, branch_decision.message)
        if commit_present:
            _gate_commit_candidates(git_command, st, jdie)
        post = decide_post_commit(context)
        if post.kind == "absolute":
            api.die(post.message, 2)
        if post.kind == "block":
            jdie(post.rule, post.message)
        return _gate_bash_writes(flow, st, sid, step, intent, jdie)
    api.die("gate 用法: gate edit <路径> | gate bash <命令>")
