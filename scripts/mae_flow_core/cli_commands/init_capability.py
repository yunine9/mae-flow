"""CLI responsibilities extracted from the historical entrypoint."""

from .shared import (
    AGENT_WRITES_PATH, CapabilityError, EXIT_PATH, STATE_PATH, atomic_write_json,
    capability_diagnostics, ensure_codecheck, json, os, prepare_project,
    remove_with_retry, run_comet, run_openspec, sys, time,
)
from .wiring import api

def cmd_init(flow, args):
    from .lean_migration import migrate_legacy_spec_workspace
    moved, note = migrate_legacy_spec_workspace(os.getcwd())
    if moved:
        print(note)
    api._git_local_runtime_ignore()
    action = api._load_action()
    if action:
        api.die("独立任务 %s(%s) 尚未收尾。先 action finish 或 action cancel；"
            "独立任务不会自动升级成完整流程。" % (
                action.get("id", "?"), action.get("kind", "?")), 2)
    live_before = api.load_state()
    has_exit = os.path.exists(EXIT_PATH)
    new_exit_snapshot = ""
    terminal_live = bool(
        live_before and flow.get("steps", {}).get(
            live_before.get("current", ""), {}).get("terminal"))
    rollover_message = (
        api._terminal_rollover_message(
            live_before, getattr(args, "message_id", "") or "",
            args.ack or "")
        if terminal_live else None
    )
    if (not live_before and not has_exit
            and (getattr(args, "message_id", None) or args.ack)):
        api.die("当前没有退出指针，--message-id/--ack 已失效，不能悄悄改成新建流程。"
            "若确实要开启全新流程，请去掉这两个参数后执行 init；"
            "若原本要恢复旧现场，请先用 doctor 查明退出指针为何不存在。", 2)
    if getattr(args, "new", False) and live_before and not terminal_live:
        api.die("当前仍有完整流程状态，init --new 不会覆盖它。先查看 current/status；"
            "确需放弃时走 /mae-flow:mae-flow exit 留存现场，再用 Direct 模式的 messages + "
            "init --new --message-id。禁止删除或改名状态文件。", 2)
    if getattr(args, "new", False) and terminal_live:
        print("[mae-flow] 当前已是交付终态；已将 init --new 归一化为终态换轮。"
              "无需 exit/goto/skip，上一单会自动归档为 .mae-flow.json.last。")
    if getattr(args, "new", False) and not terminal_live:
        _previous, new_exit_snapshot = api._start_new_from_direct(
            flow, args.ack or "", getattr(args, "message_id", "") or "")
    elif not live_before:
        resumed = api._resume_direct_mode(
            args.ack or "", getattr(args, "message_id", "") or "")
        if resumed is not None:
            # 退出现场本身已经终态时，“重新启用”不能只恢复到 end 然后原地
            # 返回；继续走下面既有终态滚动逻辑，自动备份 .last 并开启下一轮。
            if not flow["steps"].get(resumed.get("current"), {}).get("terminal"):
                api.print_current(flow, resumed)
                return
    old = api.load_state()
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
                    api.die("插件运行时预检失败，上一单状态和退出指针均未改动：%s" % exc, 2)
                prepared = True
            api._clear_auxiliary_state()
            auxiliary_cleared = True
            api._append_history(old)
            if os.path.exists(EXIT_PATH):
                # FLOW 与 EXIT 冲突时有效主状态优先。终态 init 已获开启下一轮授权，
                # 消费陈旧退出指针前仍把它留到过程区，绝不让旧 snapshot 覆盖主状态。
                stale = api._preserve_exit_pointer(api._read_exit_record())
                remove_with_retry(EXIT_PATH)
                print("[mae-flow] 已收敛陈旧退出指针，旧记录保留在 %s。"
                      % api.norm(stale))
            os.replace(STATE_PATH, STATE_PATH + ".last")
            print(f"[mae-flow] 上一单({old.get('config', {}).get('单号', '?')})已交付完成,"
                  f"旧状态备份为 {STATE_PATH}.last,开启新流程。")
        else:
            api.die(f"流程已存在(进行中,当前步骤 {sid}),查看用 status。"
                "不要删除或改名状态文件；确要放弃并开启另一流程，先执行 /mae-flow:mae-flow exit "
                "留存现场，再按 Direct 模式 messages 输出使用 init --new。", 2)
    if not prepared:
        try:
            prepare_project(os.getcwd())
        except CapabilityError as exc:
            api.die("插件运行时预检失败，尚未创建流程状态，因此不会拦截普通开发: %s" % exc, 2)
    if not auxiliary_cleared:
        api._clear_auxiliary_state()
    api._gitignore()
    dirty = api._dirty_paths()
    st = {"current": flow["start"], "config": {}, "choices": {},
          "protocols": {},
          "history": [], "started": time.strftime("%Y-%m-%d %H:%M:%S"),
          "initial_dirty": dirty,
          "initial_dirty_fingerprints": {p: api._path_fingerprint(p) for p in dirty}}
    atomic_write_json(AGENT_WRITES_PATH, {"paths": {}})
    api.save_state(st)
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
              % api.norm(new_exit_snapshot))
    print("[mae-flow] 流程已初始化；内置规格引擎已就绪，未创建项目级 Skill。")
    # 开启流程就是面板的第一个感知时刻:此后每到需要用户裁决/跨阶段时自动同步。
    from mae_flow_core.cli_commands.panel import refresh as _panel_refresh
    panel_path = _panel_refresh(flow, st)
    if panel_path:
        print("[mae-flow] 现场面板已生成(浏览器打开,之后每到确认点自动同步): %s"
              % panel_path)
        print("  ⚠ 把上面这个面板路径原样告诉用户——工具输出用户看不见。")
    api.print_current(flow, st)

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
            api.die("插件运行时预检失败: " + str(exc), 2)
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
                    st_now = api.load_state()
                except Exception:
                    st_now = None
                if st_now is not None and st_now.get("current") != "archive":
                    api.die("规格定稿(archive)只能在 archive 步执行:它把规格合并进真相源并移动"
                        "变更目录,不可逆;绕过验证链与 archive_confirm 用户确认等于伪造交付状态。"
                        "当前步骤 %s;先完成验证链并经用户确认定稿。"
                        % st_now.get("current", "?"), 2)
            if sub == "init":
                api.die("openspec init 由插件统一执行:手动 init 可能生成 AI 工具目录污染仓库。"
                    "需要重建规格配置时执行 capability prepare。", 2)
            result = run_openspec(arguments, cwd=os.getcwd())
        else:
            comet_action = action.replace("comet-", "")
            result = run_comet(
                comet_action, _capability_arguments(args), cwd=os.getcwd())
    except CapabilityError as exc:
        api.die("内嵌能力执行失败: " + str(exc), 2)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode:
        sys.exit(result.returncode)
