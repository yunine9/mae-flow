"""CLI responsibilities extracted from the historical entrypoint."""

import hashlib

from mae_flow_core.quality.spec2code_artifacts import (
    blueprint_scenario_ids,
)
from mae_flow_core.orchestration.work_package import ensure_work_package
from mae_flow_core.orchestration.behavior_baseline import (
    load_relevant_domain_context,
)

from .shared import (
    BUILD_DESCRIPTOR_EXTS, SOURCE_FILENAMES, STATE_PATH, append_codecheck_event,
    codecheck_log_path, globmod, os, quality_task_card_documents,
    quality_task_card_use_cases, quality_task_cards, read_text, time, write_text,
    sys,
)
from .wiring import api

def _task_scope(st, diff_override=""):
    if diff_override:
        diff, err = diff_override, ""
    else:
        diff, err = api._scope_diff(st)
        if err:
            return "", [], err
    out = api.argv_out([
        "git", "-c", "core.quotepath=false", "diff", "--name-status", diff])
    return diff, [x for x in out.splitlines() if x.strip()], ""

def _classify_task_files_from_runtime(files, st):
    """把子任务范围拆成业务源码、测试、构建三组；文档根本不应传进来。"""
    return quality_task_card_use_cases.task_file_groups(
        files,
        is_build=api._is_build_path,
        is_test=lambda path: api._is_test_file(path, st),
    ).as_legacy()

def _resolve_task_roots_from_runtime(files):
    """生成去重的模块执行目录和依据，供任务卡阻止根目录意外全量构建。"""
    plan = quality_task_card_use_cases.execution_roots(
        files,
        quality_task_card_use_cases.ExecutionRootPorts(
            repository=os.path.abspath(os.getcwd()),
            absolute=os.path.abspath,
            is_directory=os.path.isdir,
            list_directory=os.listdir,
            is_file=os.path.isfile,
            is_build_path=api._is_build_path,
            relative=os.path.relpath,
            dirname=os.path.dirname,
            join=os.path.join,
            separator=os.sep,
            source_filenames=tuple(
                str(name).lower()
                for name in SOURCE_FILENAMES),
            descriptor_suffixes=tuple(BUILD_DESCRIPTOR_EXTS),
        ),
    )
    return list(plan.roots), list(plan.unresolved)

def _resolve_requirement_sources_from_runtime(st):
    config = st.get("config", {})
    ticket = str(config.get("单号", "") or "")
    local_sources = ()
    if ticket:
        package = ensure_work_package(os.getcwd(), ticket)
        local_sources = (
            package.spec, package.grill, package.story, package.decisions)
        terms = []
        for path in (config.get("需求文档", ""), *local_sources):
            if path and os.path.isfile(path):
                terms.append(read_text(path, encoding="utf-8", errors="replace"))
        try:
            domain = load_relevant_domain_context(os.getcwd(), terms)
        except ValueError as exc:
            api.die(
                "领域索引无效: %s。修复后先执行 domain-docs validate，"
                "通过后原样重试 agent-task。"
                % exc,
                2,
            )
        local_sources += tuple(
            os.path.join(os.getcwd(), *document.path.split("/"))
            for document in domain.documents)
        index = os.path.join(os.getcwd(), "docs", "specs", "index.md")
        if os.path.isfile(index):
            local_sources += (index,)
    return list(quality_task_card_use_cases.requirement_sources(
        config,
        exists=os.path.exists,
        absolute=os.path.abspath,
        glob_paths=globmod.glob,
        local_sources=local_sources,
    ))


def _compile_worktree_snapshot(kind, head):
    if kind != "COMPILE":
        return {}, False
    try:
        return api._worktree_snapshot_since(head), True
    except Exception as exc:
        print(
            "[mae-flow] COMPILE provenance baseline unavailable; "
            "issuing task with invalid baseline: %s" % exc,
            file=sys.stderr,
        )
        return {}, False


def _approved_blueprint(state, kind):
    if kind != "UT":
        return {}
    process = state.get("spec2code") or {}
    registered = process.get("blueprint") or {}
    new_full = (
        process.get("version") == 1
        and (state.get("choices") or {}).get("workflow") == "full"
    )
    if not registered:
        if new_full:
            api.die(
                "新 full 流程缺少已确认 UT 蓝图；"
                "回到 test_blueprint Loop 生成并登记。",
                2,
            )
        return {}
    if new_full and (
        not registered.get("revision")
        or registered.get("confirmed_revision")
        != registered.get("revision")
        or registered.get("confirmed_sha256")
        != registered.get("sha256")
        or registered.get("confirmed_by")
        not in ("user", "moonlight")
        or not registered.get("confirmed_at")
    ):
        api.die(
            "UT 蓝图尚未按当前版本确认，或确认绑定已失效；"
            "回到 test_blueprint Loop 重新检视并选择 continue。",
            2,
        )
    path = str(registered.get("path", "") or "")
    if not path or not os.path.isfile(path):
        api.die("已登记的 UT 蓝图不存在；重新生成并登记 blueprint。", 2)
    try:
        body = read_text(path, encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        api.die("已登记的 UT 蓝图无法读取: %s" % exc, 2)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    if digest != registered.get("sha256"):
        api.die("UT 蓝图登记后已变化；必须重新执行 quality-artifact register。", 2)
    return {
        "path": os.path.abspath(path),
        "sha256": digest,
        "scenario_ids": blueprint_scenario_ids(body),
    }


def _store_agent_task(flow, st, args, context):
    kind = context["kind"]
    sid = context["sid"]
    from mae_flow_core.workflow.quality_executions import (
        invalidate_quality_executions,
    )
    invalidate_quality_executions(STATE_PATH, kind, sid)
    document = context["document"]
    api._drop_agent_token(kind, strict=True)
    artifact = quality_task_card_use_cases.store_task_card(
        document,
        os.path.join(".mae-flow-work", "agent-tasks"),
        f"{sid}-{kind.lower()}.md",
        quality_task_card_use_cases.TaskCardStorePorts(
            absolute=os.path.abspath,
            make_directory=lambda path: os.makedirs(
                path, exist_ok=True),
            write_text=lambda path, body: write_text(
                path, body, encoding="utf-8"),
        ),
    )
    digest = artifact.digest
    path = artifact.path
    lightcheck_result = context["lightcheck_result"]
    worktree_snapshot, worktree_snapshot_valid = (
        _compile_worktree_snapshot(kind, context["task_head"]))
    st.setdefault("agent_tasks", {})[kind] = quality_task_cards.task_record(
        step=sid, path=path, digest=digest, head=context["task_head"],
        scope=args.scope or "", checkpoint=context["checkpoint_id"],
        precommit_review=context["precommit_review"],
        initial_compile_net=(
            api._working_source_net(context["task_head"], st, flow)
            if context["precommit_review"] else 0),
        source_snapshot=(
            api._source_snapshot_since(context["task_head"], st, flow)
            if context["precommit_review"] else {}),
        worktree_snapshot=worktree_snapshot,
        worktree_snapshot_valid=worktree_snapshot_valid,
        allowed_files=(
            context["scan"].get("files", [])
            if kind == "CODECHECK" else []),
        task_files=context["task_files"],
        execution_roots=[
            root for root, _reason in _resolve_task_roots_from_runtime(
                context["execution_files"])[0]],
        lightcheck=({
            "status": lightcheck_result.get("status"),
            "findings": len(lightcheck_result.get("findings") or []),
            "report_path": lightcheck_result.get("report_path", ""),
        } if lightcheck_result is not None else {}),
        ut_targets=context["ut_targets"] if kind == "UT" else {},
        unchanged_initial_dirty=context["inherited_dirty"],
        at=time.strftime("%Y-%m-%d %H:%M:%S"),
        blueprint=context["blueprint"])
    if kind == "CODECHECK":
        append_codecheck_event(
            os.getcwd(), st, "agent.task_created", {
                "task_path": os.path.abspath(path),
                "head": context["task_head"],
                "allowed_files": context["scan"].get("files", []),
                "scan_count": context["scan"].get("count"),
                "scope": args.scope or "",
            })
    api.save_state(st)
    print(f"[mae-flow] {kind} 任务卡已生成: {path}")
    if kind == "COMPILE" and lightcheck_result is not None:
        api._print_lightcheck_result(lightcheck_result, quiet=True)
    if kind == "CODECHECK":
        print("[mae-flow] CodeCheck 详细日志: %s"
              % api.norm(codecheck_log_path(os.getcwd(), st)))
    print(
        "启动对应专项 Agent 时只传这一句:\n"
        f"读取并严格执行任务卡 \"{path}\"；完成后用自然语言报告实际执行、结果和阻塞。")

def cmd_agent_task(flow, st, args):
    """由代码生成完整子 Agent 任务卡，主模型不再临时拼参数。"""
    kind = args.kind.upper()
    sid = st["current"]
    checkpoint_id = str(getattr(args, "checkpoint", "") or "")
    task_diff_override = ""
    precommit_review = False
    (st.get("risk_acceptances", {}) or {}).pop(kind, None)  # 新任务卡=新证据轮次，旧风险确认作废
    if not quality_task_cards.task_allowed(kind, sid):
        api.die(f"当前步骤 {sid} 不允许生成 {kind} 任务卡；先执行 current,禁止提前派发。", 2)
    if checkpoint_id:
        if kind != "COMPILE":
            api.die("--checkpoint 只用于 compile 任务卡。", 2)
        item = api._checkpoint_current(st)
        review_state = api._development_review(st) or {}
        if (not item
                and (review_state.get("final_rework") or {}).get("status")
                == "coding"):
            api.die("当前是最终检视返工，原检查点已闭环；不要传 --checkpoint，"
                "按本步骤正常生成编译任务卡并重走质量链。", 2)
        if (not item or item.get("id") != checkpoint_id
                or sid != api._checkpoint_expected_code_step(st)):
            api.die("检查点编译目标不匹配：当前应为 %s@%s，收到 %s@%s。"
                % ((item or {}).get("id", "无"), api._checkpoint_expected_code_step(st),
                   checkpoint_id, sid), 2)
        if item.get("status") != "coding":
            api.die("检查点 %s 当前状态为 %s，不能重复生成编译任务卡。"
                % (checkpoint_id, item.get("status", "未知")), 2)
        checkpoint_base = item.get("fixed_base", "")
        precommit_review = bool(
            review_state.get("mode") == "staged"
            and api._review_before_commit(review_state))
        if precommit_review:
            current_head = api.sh("git rev-parse --verify HEAD")
            if current_head != checkpoint_base:
                api.die("当前检查点采用先检视后提交，但 HEAD 已偏离固定基点。"
                    "禁止拿已提交代码伪装成 IDE 未提交差异；保留现场让用户归因。", 2)
            task_diff_override = "HEAD"
        elif checkpoint_base and api.argv_out(
                ["git", "cat-file", "-t", checkpoint_base]) == "commit":
            task_diff_override = checkpoint_base + "..HEAD"
    dirty_source = api._blocking_dirty_source_paths(st, flow)
    inherited_dirty = api._unchanged_initial_dirty_source_paths(st, flow)
    if dirty_source and not precommit_review:
        api.die("生成任务卡前仍有未提交源码/测试/构建文件: " + "、".join(dirty_source[:8])
            + "。任务卡只信 Git 可追踪范围；先按单号格式精确提交，或回退不属于本单的改动。", 2)
    if precommit_review:
        checkpoint_snapshot = api._checkpoint_worktree_snapshot(st, flow)
        source_files = [
            path for path in checkpoint_snapshot
            if api._is_source_path(path, st, flow)
        ]
        if not source_files:
            api.die("当前检查点只有配置、资源、文档或夹具等非代码交付差异，"
                "无需生成空编译任务卡；直接执行 checkpoint ready %s，"
                "流程会跳过编译并进入未提交 diff 检视。" % checkpoint_id, 2)
        diff = "HEAD"
        changes = api.argv_out([
            "git", "-c", "core.quotepath=false", "status", "--short",
            "--untracked-files=all", "--", *source_files,
        ]).splitlines()
    else:
        diff, changes, err = _task_scope(st, task_diff_override)
        if err:
            api.die(err, 2)
        source_files, source_err = (
            api._source_files_for_diff(diff, st) if diff
            else (None, "无法计算任务卡 Git 范围"))
        if source_err:
            api.die(source_err, 2)
    if kind in ("COMPILE", "UT") and not source_files:
        api.die("本轮只有文档/台账等非代码变更，无需生成 %s 任务卡；直接 done。"
            "Harness 在证据层会自动放行，不要启动专项 Agent。" % kind, 2)
    lightcheck_result = None
    if kind == "COMPILE":
        try:
            lightcheck_result = (
                api._working_lightcheck_scope(st, source_files)
                if precommit_review else
                api._run_lightcheck_diff(
                    diff, source_files,
                    "编译前兜底：" + (checkpoint_id or sid)))
        except Exception as exc:
            lightcheck_result = api._lightcheck_tool_error(
                "编译前轻量检查异常；已记录诊断，不阻断流程: " + str(exc))
            lightcheck_result["report_path"] = api._save_lightcheck_result(
                lightcheck_result, "编译前：异常安全降级")
    ut_targets = {}
    if kind == "CODECHECK":
        scan = (st.get("quality", {}) or {}).get("codecheck_scan", {})
        if scan.get("step") != sid:
            api.die("先执行 codecheck-scan 冻结首检结果，再生成 CODECHECK 任务卡。", 2)
        if scan.get("scope_pending"):
            api.die("CodeCheck 仍有机器准备排除的候选，必须先让用户确认是否涉及本次修改，"
                "再按 scan 输出执行 codecheck-scope；禁止先派修复 Agent。", 2)
        if scan.get("status") == "TOOL_ERROR":
            api.die("CodeCheck 工具本轮已真实尝试但不可用/不可解析；这是建议项留痕，"
                "不派修复 Agent，直接 done。", 2)
        if scan.get("count", 0) == 0:
            api.die("机器首检为 0 告警，不应派 codecheck-fix-agent；直接 done。", 2)
        if not scan.get("files"):
            api.die("CodeCheck 首检没有业务代码文件却记录了告警，状态自相矛盾；"
                "重新执行 codecheck-scan，禁止把文档或全仓当修复范围。", 2)
        changed, why = api._source_changed_since(scan.get("head", ""), st)
        if why:
            api.die("CodeCheck 首检基点失效:" + why + "；重新执行 codecheck-scan", 2)
        if changed:
            api.die("首检后、修复 Agent 启动前源码已变化: " + "、".join(changed[:5])
                + "。禁止主会话先修再补手续；回退这些改动后重扫。", 2)
    scan = (st.get("quality", {}) or {}).get("codecheck_scan", {})
    task_files = list(scan.get("files", [])) if kind == "CODECHECK" else list(source_files)
    groups = _classify_task_files_from_runtime(
        task_files, st)
    cfg = st.get("config", {})
    task_head = api.sh("git rev-parse --verify HEAD")
    sources = _resolve_requirement_sources_from_runtime(st)
    execution_files = (
        task_files if kind == "COMPILE"
        else (
            groups["business"]
            or groups["tests"]
            or groups["build"]
        )
    )
    roots, unresolved = _resolve_task_roots_from_runtime(
        execution_files)
    execution_plan = quality_task_card_use_cases.ExecutionRootPlan(
        roots=tuple(roots),
        unresolved=tuple(unresolved),
    )
    notes = []
    if kind == "UT":
        ut_targets, target_err = api._changed_hunk_targets(
            st, groups["business"])
        if target_err:
            api.die("无法计算 UT 函数级范围：" + target_err, 2)
    blueprint = _approved_blueprint(st, kind)
    lines = quality_task_card_documents.build_full_task_document({
        "kind": kind,
        "sid": sid,
        "project_root": os.path.abspath(os.getcwd()),
        "head": task_head,
        "config": cfg,
        "diff": diff,
        "scope": args.scope or "",
        "checkpoint_id": checkpoint_id,
        "precommit_review": precommit_review,
        "inherited_dirty": tuple(inherited_dirty),
        "sources": tuple(sources),
        "groups": quality_task_card_use_cases.TaskFileGroups(
            business=tuple(groups["business"]),
            tests=tuple(groups["tests"]),
            build=tuple(groups["build"]),
        ),
        "change_count": len(changes),
        "task_file_count": len(task_files),
        "execution_plan": execution_plan,
        "lightcheck": lightcheck_result,
        "notes": tuple(notes),
        "scan": scan,
        "ut_targets": ut_targets,
        "blueprint": blueprint,
    })
    _store_agent_task(flow, st, args, {
        "kind": kind, "sid": sid, "document": lines,
        "task_head": task_head, "checkpoint_id": checkpoint_id,
        "precommit_review": precommit_review, "scan": scan,
        "task_files": task_files, "execution_files": execution_files,
        "lightcheck_result": lightcheck_result, "ut_targets": ut_targets,
        "inherited_dirty": inherited_dirty,
        "blueprint": blueprint,
    })
