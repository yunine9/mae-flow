"""Startup draft construction and user-owned configuration changes."""

from dataclasses import replace
import subprocess

from mae_flow_core.adapters.hook_git_facts import git_text
from mae_flow_core.orchestration import (
    CommitPace,
    DeliveryPath,
    FlowState,
    MoonlightAuthorization,
    Phase,
)
from mae_flow_core.orchestration.documents import local_full_artifacts
from mae_flow_core.orchestration.moonlight_policy import apply_moonlight_policy
from mae_flow_core.orchestration.startup_config import (
    load_startup_defaults,
    resolve_startup_config,
)
from .user_events import bind_user_event, matching_user_event


def _git_names(root, arguments):
    try:
        result = subprocess.run(
            ["git"] + list(arguments), cwd=root, shell=False,
            capture_output=True, timeout=15)
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
            if (not normalized.startswith(".mae-flow")
                    and normalized not in paths):
                paths.append(normalized)
    return tuple(paths), tuple(errors)


def build_startup_state(root, args):
    path = DeliveryPath(args.path)
    dirty, git_errors = _initial_dirty(root)
    defaults, defaults_error = load_startup_defaults(root)
    explicit_config = dict(
        worker=args.worker, ticket_type=args.ticket_type,
        requirement_source=args.requirement, base_branch=args.base_branch,
        working_branch=args.working_branch, build_method=args.build_method,
        ut_method=args.ut_method, ut_command=args.ut_command)
    startup_config = resolve_startup_config(
        args.ticket.strip(), explicit_config, defaults,
        current_branch=git_text(root, ("branch", "--show-current")),
        user_name=git_text(root, ("config", "user.name")),
    )
    state = FlowState(
        ticket=args.ticket.strip(),
        path=path,
        phase=FlowState.new(
            args.ticket.strip(), path, CommitPace(args.pace)).phase,
        commit_pace=CommitPace(args.pace),
        artifacts=(
            local_full_artifacts(args.ticket)
            if path == DeliveryPath.FULL else ()),
        initial_dirty=dirty,
        startup_config=startup_config,
        risks=tuple(
            "Git startup facts unavailable: %s" % error
            for error in git_errors),
    )
    quality_plan = (args.quality_plan or "").strip() or (
        "每个 CP 按确认的 Build 路由同步编译一次；其余质量能力按语义选择。")
    state = state.with_decision("startup.quality_plan", quality_plan)
    if defaults_error:
        state = state.with_decision("startup.defaults_warning", defaults_error)
    if args.request.strip():
        state = state.with_decision("request.summary", args.request.strip())
    if args.moonlight:
        has_exact_files = bool(args.business_file)
        state = apply_moonlight_policy(state, MoonlightAuthorization(
            True,
            tuple(args.business_file),
            bool(args.allow_commit and has_exact_files),
            bool(args.allow_push and has_exact_files),
        )).state
    elif args.business_file or args.allow_commit or args.allow_push:
        raise ValueError("Moonlight delivery options require --moonlight")
    return state


def _replace_decision(state, key, value):
    decisions = tuple(item for item in state.decisions if item[0] != key)
    if value:
        decisions += ((key, value),)
    return replace(state, decisions=decisions)


def configure_startup(root, state, args):
    mutable_fields = (
        "worker", "ticket_type", "requirement", "base_branch",
        "working_branch", "build_method", "ut_method", "ut_command",
        "quality_plan", "path", "pace", "request",
    )
    if state.phase != Phase.STARTUP:
        raise ValueError("configure 仅可修改活动 Startup 配置")
    if any(key == "moonlight.enabled" and value == "true"
           for key, value in state.decisions):
        raise ValueError("Moonlight 启动授权已替代 Startup 配置问询")
    decision = args.decision.strip()
    if not decision:
        raise ValueError("配置修改的自然语言决定不能为空")
    if not any(getattr(args, field) is not None for field in mutable_fields):
        raise ValueError("configure 至少需要修改一个配置项")
    event_id = matching_user_event(root, state)
    current = state.startup_config
    defaults = {
        "worker": current.worker,
        "ticket_type": current.ticket_type,
        "requirement_source": current.requirement_source,
        "base_branch": current.base_branch,
        "working_branch": current.working_branch,
        "build_method": current.build_method,
        "ut_method": current.ut_method,
        "ut_command": current.ut_command,
    }
    explicit = {
        "worker": args.worker,
        "ticket_type": args.ticket_type,
        "requirement_source": args.requirement,
        "base_branch": args.base_branch,
        "working_branch": args.working_branch,
        "build_method": args.build_method,
        "ut_method": args.ut_method,
        "ut_command": args.ut_command,
    }
    if (args.working_branch is None
            and (args.worker is not None or args.base_branch is not None)):
        defaults["working_branch"] = ""
    configured = resolve_startup_config(
        state.ticket, explicit, defaults,
        current_branch=current.base_branch,
        user_name=current.worker,
    )
    path = DeliveryPath(args.path) if args.path else state.path
    pace = CommitPace(args.pace) if args.pace else state.commit_pace
    updated = replace(
        state,
        path=path,
        commit_pace=pace,
        startup_config=configured,
        artifacts=(
            local_full_artifacts(state.ticket)
            if path == DeliveryPath.FULL else ()),
    )
    if args.quality_plan is not None:
        updated = _replace_decision(
            updated, "startup.quality_plan", args.quality_plan.strip())
    if args.request is not None:
        updated = _replace_decision(
            updated, "request.summary", args.request.strip())
    updated = updated.with_decision("startup.configuration_change", decision)
    updated = bind_user_event(updated, event_id, "startup-configured")
    return updated, "已按当前用户输入更新 Startup 配置；请确认新配置卡。"
