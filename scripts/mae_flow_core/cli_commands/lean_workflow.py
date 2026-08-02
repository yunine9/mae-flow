"""Thin production CLI adapter for the schema-v3 lean workflow."""

from dataclasses import replace
import json
import os
import re
import subprocess
import sys

from mae_flow_core.adapters.lean_exit import (
    archive_file_exclusive,
    effective_exit_pointer,
    exclusive_backup_bytes,
    release_flow_state,
)

from mae_flow_core.orchestration import (
    AdvanceRequest,
    CommitPace,
    DeliveryPath,
    FlowState,
    MoonlightAuthorization,
    Phase,
    ToolboxRequest,
    advance_flow,
    decode_flow_state,
    flow_attempt_context,
    retry_decision_key,
    run_toolbox_request,
)
from mae_flow_core.orchestration.documents import DocumentPaths
from mae_flow_core.orchestration.guidance import (
    render_guidance,
    render_user_card,
)
from mae_flow_core.orchestration.moonlight_policy import apply_moonlight_policy
from mae_flow_core.state_store import (
    ProjectStateLock,
    atomic_write_json,
    safe_read_json,
)
from .lean_manifest import prepare_manifest_state
from .lean_lightcheck import run_exact_lightcheck

STATE_NAME = ".mae-flow.json"
_TOOLBOX = {"ut", "codecheck", "grill", "story", "chain"}
_RETRY_KINDS = {"build", "ut", "codecheck", "reviewer", "grill", "story"}
_KEYED_SEMANTIC_EVENTS = {"risk-resolved", "cp-ready", "cp-progress"}
_USER_OWNED_EVENTS = {
    "startup-confirmed", "spec-confirmed", "story-confirmed",
    "cp-confirmed", "delivery-confirmed", "reviewer-tradeoff-resolved",
    "risk-resolved", "upgrade-to-full", "quality-defect-repair",
}


def _die(message):
    print("[mae-flow] " + message, file=sys.stderr)
    raise SystemExit(2)


def _state_path(root):
    return os.path.join(root, STATE_NAME)


def _exit_paths(root):
    path = _state_path(root)
    return (
        path + ".exited",
        os.path.join(root, ".mae-flow-work", "exited"),
    )


def _exit_pointer(root):
    pointer_path, snapshot_dir = _exit_paths(root)
    return effective_exit_pointer(
        root, pointer_path, snapshot_dir, _state_path(root))


def _read_state(path):
    raw, error = safe_read_json(path)
    if error:
        raise ValueError("流程状态不可读: %s" % error)
    if raw is None:
        raise ValueError("没有在途流程；先执行 start")
    return decode_flow_state(raw)


def _load_state(root):
    path = _state_path(root)
    if _exit_pointer(root) is not None:
        raise ValueError(
            "流程已退出；仅 current、exit 或新的 start 可用")
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
    return exclusive_backup_bytes(path, raw, "terminal-backup")


def _snapshot_state(root, pointer):
    path = os.path.join(root, *pointer["snapshot"].split("/"))
    raw, error = safe_read_json(path)
    if error or raw is None:
        return None
    try:
        return decode_flow_state(raw)
    except (TypeError, ValueError):
        return None


def _render_exited(root, pointer, reason):
    state = _snapshot_state(root, pointer)
    if state is not None:
        _render(replace(state, status="exited"), reason)
        return
    if reason:
        print("[mae-flow] " + reason)
    print("状态: exited")
    print("快照: %s" % pointer["snapshot"])


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
    if state.phase in {Phase.STARTUP, Phase.DELIVERY} and state.initial_dirty:
        adopted = {
            value.replace("\\", "/").casefold()
            for key, value in state.decisions
            if key == "delivery.adopted_dirty"
        }
        reasons = {}
        for key, value in state.decisions:
            if key == "delivery.adopted_dirty_reason" and "\t" in value:
                path, detail = value.split("\t", 1)
                reasons[path.replace("\\", "/").casefold()] = detail
        print("启动时已有改动与归属:")
        for path in state.initial_dirty:
            identity = path.replace("\\", "/").casefold()
            if identity in adopted:
                print("- %s: 本单已接管 — %s" % (
                    path, reasons.get(identity, "用户已确认归属")))
            else:
                print("- %s: 默认不属于本单" % path)
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
        pointer_path, unused_snapshot_dir = _exit_paths(root)
        with ProjectStateLock(root):
            pointer = _exit_pointer(root)
            if os.path.exists(path):
                if pointer is None:
                    raw, error = safe_read_json(path)
                    if error:
                        raise ValueError(
                            "旧流程状态损坏；拒绝覆盖，请先 current 查看恢复信息")
                    existing = decode_flow_state(raw)
                    if existing.status not in {"complete", "exited"}:
                        raise ValueError(
                            "活动流程已存在；用 current 恢复，或先 exit")
                    with open(path, "rb") as stream:
                        terminal_raw = stream.read()
                    _terminal_backup(path, terminal_raw)
            state = _start_state(root, args)
            atomic_write_json(path, state.to_dict())
            if os.path.isfile(pointer_path):
                archive_file_exclusive(
                    pointer_path, "exited-backup", backup_base=path)
        _render(state, "Lean workflow started.")
    return _run(execute)


def cmd_lean_current(root, unused_args):
    def execute():
        pointer = _exit_pointer(root)
        if pointer is not None:
            _render_exited(
                root, pointer, "Current lean recovery context.")
            return
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


def _semantic_request(event, key, decision):
    normalized = event.strip().lower()
    if key.strip() and normalized not in _KEYED_SEMANTIC_EVENTS:
        raise ValueError("语义事件 %s 不接受 --key" % normalized)
    return AdvanceRequest(event, key, decision)


def cmd_lean_advance(root, args):
    def operation(current):
        if args.event.strip().lower() in _USER_OWNED_EVENTS:
            raise ValueError(
                "该用户决定事件只能使用 decision 与自然语言确认")
        request = _semantic_request(args.event, args.key, args.decision)
        return _advance_state(current, request)

    def execute():
        state, reason = _mutate(
            root, operation)
        _render(state, reason)
    return _run(execute)


def _validate_natural_decision(state, key, text):
    """Keep user prose separate from facts owned by semantic commands."""
    if not key:
        raise ValueError("自然语言决定的 key 不能为空")
    retry_prefix = "capability.retry."
    if key.startswith(retry_prefix):
        kind = key[len(retry_prefix):]
        if kind in _RETRY_KINDS:
            return retry_decision_key(flow_attempt_context(state, kind))
        raise ValueError("该 capability key 是流程保留事实，不能直接写入")
    if key.startswith((
            "capability.", "moonlight.", "delivery.", "review.",
            "startup.", "spec.", "story.", "focused.", "construction.",
            "quality.", "risk.")) or key == "workflow.path":
        raise ValueError("该 key 是流程保留事实，请使用对应语义命令")
    return key


def cmd_lean_decision(root, args):
    def operation(state):
        text = args.text.strip()
        if not text:
            raise ValueError("自然语言决定不能为空")
        if "." in args.event:
            key = args.key.strip() or args.event.strip()
            key = _validate_natural_decision(state, key, text)
            return state.with_decision(key, text), "已记录自然语言决定。"
        request = _semantic_request(args.event, args.key, text)
        return _advance_state(state, request)

    def execute():
        state, reason = _mutate(root, operation)
        _render(state, reason)
    return _run(execute)


def cmd_lean_manifest(root, args):
    def operation(state):
        updated, manifest = prepare_manifest_state(state, args, root)
        if args.moonlight_refresh:
            if not _moonlight_enabled(updated):
                raise ValueError("当前流程未启用 Moonlight，不能刷新不可逆权限")
            authorization_decision = (args.decision or "").strip()
            if not authorization_decision:
                raise ValueError("Moonlight 权限刷新需要自然语言用户决定")
            requested = MoonlightAuthorization(
                True,
                manifest.files,
                bool(args.allow_commit),
                bool(args.allow_push),
            )
            updated = apply_moonlight_policy(updated, requested).state
            decisions = tuple(
                item for item in updated.decisions
                if item[0] != "moonlight.authorization_decision")
            decisions += ((
                "moonlight.authorization_decision",
                authorization_decision,
            ),)
            updated = replace(updated, decisions=decisions)
        elif args.allow_commit or args.allow_push:
            raise ValueError(
                "Moonlight 权限刷新需要显式 --moonlight-refresh")
        return updated, "已记录精确交付清单；尚未执行 Git。"

    def execute():
        state, reason = _mutate(root, operation)
        _render(state, reason)
    return _run(execute)


def cmd_lean_exit(root, args):
    def execute():
        path = _state_path(root)
        pointer_path, snapshot_dir = _exit_paths(root)
        pointer = _exit_pointer(root)
        if not os.path.exists(path) and pointer is None:
            print("[mae-flow] 当前没有在途流程，无需退出。")
            return
        decision = (args.reason or "用户选择退出 Mae-Flow").strip()
        pointer = release_flow_state(
            root, path, pointer_path, snapshot_dir, reason=decision)
        _render_exited(
            root, pointer, "流程已立即退出；业务文件保持原样。")
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
    if not args.file:
        print("[mae-flow] 轻量编码预检未提供精确本次修改文件，已自动放行。")
        return 0
    return run_exact_lightcheck(args.file, quiet=args.quiet)
