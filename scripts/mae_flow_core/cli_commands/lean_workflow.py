"""Thin production CLI adapter for the schema-v3 lean workflow."""

from dataclasses import replace
import json
import os
import re
import subprocess
import sys
import time

from mae_flow_core.guard.manifest import DeliveryManifest, authorize_delivery
from mae_flow_core.foundation.commit_message import valid_business_commit_message
from mae_flow_core.orchestration import (
    AdvanceRequest,
    AttemptContext,
    CommitPace,
    DeliveryPath,
    FlowState,
    MoonlightAuthorization,
    ToolboxRequest,
    advance_flow,
    decode_flow_state,
    record_flow_attempt,
    run_toolbox_request,
)
from mae_flow_core.orchestration.documents import (
    DocumentPaths,
    conditional_document_kind,
)
from mae_flow_core.orchestration.guidance import (
    render_guidance,
    render_user_card,
)
from mae_flow_core.orchestration.moonlight_policy import apply_moonlight_policy
from mae_flow_core.state_store import (
    ProjectStateLock,
    _replace_with_retry,
    atomic_write_json,
    safe_read_json,
)

STATE_NAME = ".mae-flow.json"
_TOOLBOX = {"ut", "codecheck", "grill", "story", "chain"}
_CONDITIONAL_DECISION = "delivery.conditional_document"
_RETRY_KINDS = {"build", "ut", "codecheck", "reviewer", "grill", "story"}


def _die(message):
    print("[mae-flow] " + message, file=sys.stderr)
    raise SystemExit(2)


def _state_path(root):
    return os.path.join(root, STATE_NAME)


def _read_state(path):
    raw, error = safe_read_json(path)
    if error:
        raise ValueError("流程状态不可读: %s" % error)
    if raw is None:
        raise ValueError("没有在途流程；先执行 start")
    return decode_flow_state(raw)


def _load_state(root):
    path = _state_path(root)
    raw, error = safe_read_json(path)
    if error:
        raise ValueError("流程状态不可读: %s" % error)
    if raw is None:
        raise ValueError("没有在途流程；先执行 start")
    if isinstance(raw, dict) and raw.get("schema_version") == 2:
        raise ValueError("旧状态需要先执行 migrate-flow")
    return decode_flow_state(raw)


def _mutate(root, operation, allow_inactive=False):
    _load_state(root)
    path = _state_path(root)
    with ProjectStateLock(root):
        state = _read_state(path)
        if state.status != "active" and not allow_inactive:
            raise ValueError(
                "流程未激活（状态 %s）；仅 current、exit 或新的 start 可用"
                % state.status)
        updated, reason = operation(state)
        if not isinstance(updated, FlowState):
            raise TypeError("lean command must return a FlowState")
        atomic_write_json(path, updated.to_dict())
    return updated, reason


def _git_names(root, arguments):
    try:
        result = subprocess.run(
            ["git"] + list(arguments),
            cwd=root,
            shell=False,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return (), "%s: %s" % (type(exc).__name__, exc)
    if result.returncode != 0:
        return (), "git returned %s" % result.returncode
    names = tuple(
        item.decode("utf-8", errors="surrogateescape")
        for item in result.stdout.split(b"\x00") if item)
    return names, ""


def _initial_dirty(root):
    groups = (
        ("diff", "--name-only", "-z"),
        ("diff", "--cached", "--name-only", "-z"),
        ("ls-files", "--others", "--exclude-standard", "-z"),
    )
    paths = []
    errors = []
    for arguments in groups:
        names, error = _git_names(root, arguments)
        if error:
            errors.append(error)
        for name in names:
            normalized = name.replace("\\", "/")
            if not normalized.startswith(".mae-flow") and normalized not in paths:
                paths.append(normalized)
    return tuple(paths), tuple(errors)


def _relative(root, path):
    return os.path.relpath(path, root).replace("\\", "/")


def _start_state(root, args):
    documents = DocumentPaths.for_ticket(root, args.ticket)
    dirty, git_errors = _initial_dirty(root)
    artifacts = (
        ("spec", _relative(root, documents.spec)),
        ("story", _relative(root, documents.local_story)),
        ("ut-handoff", _relative(root, documents.ut_handoff)),
    )
    state = FlowState(
        ticket=args.ticket.strip(),
        path=DeliveryPath(args.path),
        phase=FlowState.new(
            args.ticket.strip(), DeliveryPath(args.path),
            CommitPace(args.pace)).phase,
        commit_pace=CommitPace(args.pace),
        artifacts=artifacts,
        initial_dirty=dirty,
        risks=tuple(
            "Git startup facts unavailable: %s" % error
            for error in git_errors),
    )
    if args.request.strip():
        state = state.with_decision("request.summary", args.request.strip())
    if args.moonlight:
        has_exact_files = bool(args.business_file)
        authorization = MoonlightAuthorization(
            True,
            tuple(args.business_file),
            bool(args.allow_commit and has_exact_files),
            bool(args.allow_push and has_exact_files),
        )
        state = apply_moonlight_policy(state, authorization).state
    elif args.business_file or args.allow_commit or args.allow_push:
        raise ValueError("Moonlight delivery options require --moonlight")
    return state


def _terminal_backup(path, raw):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = "%s.terminal-backup.%s.%s" % (path, stamp, os.getpid())
    temporary = "%s.tmp.%s" % (target, time.time_ns())
    try:
        with open(temporary, "xb") as stream:
            stream.write(raw)
            stream.flush()
            try:
                os.fsync(stream.fileno())
            except OSError:
                pass
        _replace_with_retry(temporary, target)
    finally:
        if os.path.exists(temporary):
            try:
                os.remove(temporary)
            except OSError:
                pass
    return target


def _render(state, reason):
    if reason:
        print("[mae-flow] " + reason)
    print("阶段: %s" % state.phase.value)
    print("路径: %s" % state.path.value)
    print("状态: %s" % state.status)
    if state.delivery_files:
        print("精确交付清单:")
        for path in state.delivery_files:
            print("- " + path)
    card = render_user_card(state)
    if card:
        print(card)
    print(render_guidance(state), end="")
    if state.capabilities:
        print("能力尝试（只记录返回事实，不解释工具输出）:")
        for attempt in state.capabilities:
            print("- %s | %s | %s" % (
                attempt.kind, attempt.outcome, attempt.summary or "无摘要"))


def _run(command):
    try:
        return command()
    except SystemExit:
        raise
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        _die(str(exc))


def cmd_lean_start(root, args):
    def execute():
        path = _state_path(root)
        with ProjectStateLock(root):
            if os.path.exists(path):
                raw, error = safe_read_json(path)
                if error:
                    raise ValueError(
                        "旧流程状态损坏；拒绝覆盖，请先 current 查看恢复信息")
                existing = decode_flow_state(raw)
                if existing.status not in {"complete", "exited"}:
                    raise ValueError("活动流程已存在；用 current 恢复，或先 exit")
                with open(path, "rb") as stream:
                    terminal_raw = stream.read()
                _terminal_backup(path, terminal_raw)
            state = _start_state(root, args)
            atomic_write_json(path, state.to_dict())
        _render(state, "Lean workflow started.")
    return _run(execute)


def cmd_lean_current(root, unused_args):
    def execute():
        state = _load_state(root)
        _render(state, "Current lean recovery context.")
    return _run(execute)


def _moonlight_enabled(state):
    return any(
        key == "moonlight.enabled" and value == "true"
        for key, value in state.decisions)


def _advance_state(state, request):
    if _moonlight_enabled(state):
        result = apply_moonlight_policy(state, request)
        return result.state, result.reason
    result = advance_flow(state, request)
    return result.state, result.reason


def cmd_lean_advance(root, args):
    def execute():
        request = AdvanceRequest(
            args.event, args.key, args.decision)
        state, reason = _mutate(
            root, lambda current: _advance_state(current, request))
        _render(state, reason)
    return _run(execute)


def _validate_natural_decision(state, key, text):
    """Keep user prose separate from facts owned by semantic commands."""
    if not key:
        raise ValueError("自然语言决定的 key 不能为空")
    if key == "delivery.commit_message":
        if not valid_business_commit_message(state.ticket, text):
            raise ValueError("commit message 必须是 [单号][feat|fix]描述")
        return
    retry_prefix = "capability.retry."
    if key.startswith(retry_prefix):
        kind = key[len(retry_prefix):]
        if kind in _RETRY_KINDS:
            return
        raise ValueError("该 capability key 是流程保留事实，不能直接写入")
    if key.startswith(("capability.", "moonlight.", "delivery.", "review.")):
        raise ValueError("该 key 是流程保留事实，请使用对应语义命令")


def cmd_lean_decision(root, args):
    def operation(state):
        text = args.text.strip()
        if not text:
            raise ValueError("自然语言决定不能为空")
        if "." in args.event:
            key = args.key.strip() or args.event.strip()
            _validate_natural_decision(state, key, text)
            return state.with_decision(key, text), "已记录自然语言决定。"
        request = AdvanceRequest(args.event, args.key, text)
        return _advance_state(state, request)

    def execute():
        state, reason = _mutate(root, operation)
        _render(state, reason)
    return _run(execute)


def cmd_lean_capability_record(root, args):
    def operation(state):
        context = AttemptContext(
            args.kind, args.source.strip(), args.environment.strip())
        updated = record_flow_attempt(
            state, context, args.outcome, summary=args.summary)
        return updated, (
            "已记录 %s 能力返回事实；未解析私有输出或推断 PASS/CLEAN。"
            % args.kind)

    def execute():
        state, reason = _mutate(root, operation)
        _render(state, reason)
    return _run(execute)


def _validate_manifest_files(files):
    for path in files:
        parts = path.replace("\\", "/").split("/")
        if any(part.startswith(".mae-flow.json") for part in parts):
            raise ValueError("交付清单不能包含 Mae-Flow 控制文件")
        if ".mae-flow-work" in parts:
            raise ValueError("本地过程文档不能进入交付清单")


def _conditional_decisions(state, selected, files):
    file_ids = {path.replace("\\", "/").casefold() for path in files}
    selected_ids = []
    decisions = tuple(
        item for item in state.decisions
        if item[0] != _CONDITIONAL_DECISION)
    for path in selected:
        normalized = path.replace("\\", "/")
        if normalized.casefold() not in file_ids:
            raise ValueError("条件文档必须同时出现在精确交付清单中")
        if not conditional_document_kind(normalized):
            raise ValueError("--conditional-document 只接受需求目录下的条件文档")
        selected_ids.append(normalized.casefold())
        decisions += ((_CONDITIONAL_DECISION, normalized),)
    missing = tuple(
        path for path in files
        if conditional_document_kind(path)
        and path.replace("\\", "/").casefold() not in selected_ids)
    if missing:
        raise ValueError(
            "交付清单中的每个条件文档都需要本次独立选择: %s"
            % ", ".join(missing))
    return decisions


def _checkpoint_prefix(checkpoint):
    if (
            not isinstance(checkpoint, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]+", checkpoint)):
        raise ValueError("checkpoint 必须是字母、数字、下划线或短横线")
    return "delivery.cp.%s." % checkpoint


def _record_checkpoint(state, manifest, args):
    prefix = _checkpoint_prefix(args.checkpoint)
    message = (args.commit_message or "").strip()
    decision = (args.decision or "").strip()
    if not valid_business_commit_message(state.ticket, message):
        raise ValueError("CP commit message 必须是 [单号][feat|fix]描述")
    if not decision:
        raise ValueError("CP manifest 需要用户的自然语言检视决定")
    decisions = tuple(
        item for item in state.decisions if not item[0].startswith(prefix))
    decisions += tuple((prefix + "file", path) for path in manifest.files)
    decisions += (
        (prefix + "message", message),
        (prefix + "confirmation", decision),
    )
    return replace(state, decisions=decisions, current_cp=args.checkpoint)


def _checkpoint_union(state):
    files = []
    for key, value in state.decisions:
        if key.startswith("delivery.cp.") and key.endswith(".file"):
            identity = value.replace("\\", "/").casefold()
            if all(
                    identity != item.replace("\\", "/").casefold()
                    for item in files):
                files.append(value)
    return tuple(files)


def _validate_staged_manifest(state, manifest, args, root):
    checkpoint = bool(args.checkpoint)
    final = bool(args.final)
    if checkpoint == final:
        raise ValueError(
            "Staged manifest 必须二选一: --checkpoint <CP> 或 --final")
    if checkpoint:
        return _record_checkpoint(state, manifest, args)
    expected = DeliveryManifest.from_paths(
        _checkpoint_union(state), repository_root=root).files
    expected_ids = {path.replace("\\", "/").casefold() for path in expected}
    actual_ids = {
        path.replace("\\", "/").casefold() for path in manifest.files}
    if not expected or expected_ids != actual_ids:
        raise ValueError("最终 manifest 必须等于所有已确认 CP manifest 的累计 union")
    if args.commit_message or args.decision:
        raise ValueError("最终累计 manifest 不创建额外本地 commit")
    return state


def cmd_lean_manifest(root, args):
    def operation(state):
        manifest = DeliveryManifest.from_paths(
            args.file,
            adopted_dirty=args.adopt_dirty,
            repository_root=root,
        )
        _validate_manifest_files(manifest.files)
        if state.commit_pace == CommitPace.STAGED:
            state = _validate_staged_manifest(state, manifest, args, root)
        elif args.checkpoint or args.final or args.commit_message or args.decision:
            raise ValueError("Continuous 只记录一次最终精确 manifest")
        updated = authorize_delivery(state, manifest)
        updated = replace(
            updated,
            decisions=_conditional_decisions(
                updated, args.conditional_document, manifest.files),
        )
        if args.moonlight_refresh:
            requested = MoonlightAuthorization(
                True,
                manifest.files,
                bool(args.allow_commit),
                bool(args.allow_push),
            )
            updated = apply_moonlight_policy(updated, requested).state
        elif args.allow_commit or args.allow_push:
            raise ValueError(
                "Moonlight 权限刷新需要显式 --moonlight-refresh")
        return updated, "已记录精确交付清单；尚未执行 Git。"

    def execute():
        state, reason = _mutate(root, operation)
        _render(state, reason)
    return _run(execute)


def _corrupt_exit_backup(path):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = "%s.exited-backup.%s.%s" % (path, stamp, os.getpid())
    _replace_with_retry(path, target)
    return target


def cmd_lean_exit(root, args):
    def execute():
        path = _state_path(root)
        if not os.path.exists(path):
            print("[mae-flow] 当前没有在途流程，无需退出。")
            return
        try:
            state = _load_state(root)
        except Exception:
            with ProjectStateLock(root):
                backup = _corrupt_exit_backup(path)
            print("[mae-flow] 状态不可读，已保留到 %s 并立即退出。" % backup)
            return

        def operation(current):
            decision = (args.reason or "用户选择退出 Mae-Flow").strip()
            exited = advance_flow(current, AdvanceRequest(
                "exit", "workflow.exit", decision)).state
            return exited, "流程已立即退出；业务文件保持原样。"

        updated, reason = _mutate(
            root, operation, allow_inactive=True)
        _render(updated, reason)
    return _run(execute)


def cmd_lean_toolbox(unused_root, args):
    def execute():
        if args.cmd not in _TOOLBOX:
            raise ValueError("未知的一次性工具箱动作")
        result = run_toolbox_request(ToolboxRequest(
            args.cmd, args.request, tuple(args.file)))
        print(result.guidance)
        for risk in result.risks:
            print("风险: " + risk)
    return _run(execute)


def cmd_lean_lightcheck(unused_root, args):
    """Run one fail-open changed-code suggestion pass without state effects."""
    from .lightcheck import cmd_lightcheck
    return cmd_lightcheck(None, args)
