"""Adopt a Cloud user-intervention workspace without treating it as evidence.

The host calls this after the user deliberately pauses the main Agent and uses
the sidecar developer assistant.  This command can only keep or rewind the
workflow; it never advances a step or marks quality evidence as passed.
"""

from .shared import STATE_PATH, json, os, time
from .wiring import api
from .lightcheck import _is_test_file
from .state_config import _is_source_path


SCHEMA = "mae-flow-user-intervention/1"
_LATE_FULL = {
    "verify_ponytail", "verify_post_ponytail_compile", "verify_recompile",
    "verify_codecheck", "verify_codecheck_compile", "verify_ut",
    "verify_spec", "verify_comet", "domain_archive", "delivery_review",
    "archive_confirm", "archive", "push", "external_verify", "end",
}
_LATE_REVIEW = {
    "rf_codecheck", "rf_ut", "delivery_review", "push",
    "external_verify", "end",
}
_LATE_TWEAK = {
    "tw_codecheck", "tw_ut", "tw_verify", "delivery_review",
    "archive_confirm", "archive", "push", "external_verify", "end",
}
_EVIDENCE_SIDECARS = (
    ".tokens", ".agent-evidence", ".agent-observations",
    ".agent-rejections", ".quality-executions", ".advisories",
)


def _text(value, limit):
    return str(value or "").strip()[:limit]


def _load_payload(path):
    try:
        info = os.lstat(path)
        if os.path.islink(path) or not os.path.isfile(path):
            raise ValueError("介入事实文件必须是普通文件")
        if info.st_size > 128 * 1024:
            raise ValueError("介入事实文件超过 128 KiB")
        with open(path, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        api.die("无法读取用户介入事实：%s" % exc, 2)
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        api.die("用户介入事实 schema 不受支持", 2)
    return payload


def _paths(payload):
    result = []
    for raw in payload.get("changed_paths", []) or []:
        value = str(raw or "").replace("\\", "/").strip().lstrip("./")
        if (not value or value.startswith("../") or "/../" in value
                or os.path.isabs(value)):
            continue
        if value not in result:
            result.append(value)
    return result[:200]


def intervention_target(state, changed, paths):
    """Choose a non-forward re-entry point; uncertainty rewinds, never blocks."""
    current = str(state.get("current", "") or "")
    if not changed:
        return current
    if current in ("build", "build_rework"):
        return current
    if current in ("build_review", "build_commit", "build_agent_review"):
        return "build_review"
    if current in ("quality_review", "quality_commit"):
        return "quality_review"

    tests = [path for path in paths if _is_test_file(path, state)]
    sources = [
        path for path in paths
        if _is_source_path(path, state) and path not in tests
    ]
    # Missing path detail is a diagnostic loss, not a reason to reject the
    # user's workspace.  Conservatively treat it as source work and rewind.
    source_changed = bool(sources) or not paths
    test_changed = bool(tests)
    workflow = (state.get("choices", {}) or {}).get("workflow", "")

    if test_changed and not source_changed:
        if workflow == "review" and current in _LATE_REVIEW:
            return "rf_ut"
        if workflow == "tweak" and current in _LATE_TWEAK:
            return "tw_ut"
        if current in _LATE_FULL:
            return "verify_ut"
        return current
    if source_changed:
        if workflow == "review" and current in _LATE_REVIEW:
            return "build"
        if workflow == "tweak" and current in _LATE_TWEAK:
            return "build_rework"
        if current in _LATE_FULL:
            return "quality_recompile"
    return current


def _execution_rows(payload):
    rows = []
    for raw in payload.get("executions", []) or []:
        if not isinstance(raw, dict):
            continue
        rows.append({
            "name": _text(raw.get("name"), 80),
            "state": _text(raw.get("state"), 24),
            "result": _text(raw.get("result"), 800),
        })
    return rows[-8:]


def _clear_stale_evidence(state):
    for key in (
            "agent_tasks", "quality", "risk_acceptances", "unlock",
            "delivery_manifest", "host_actions", "approval_subject"):
        state.pop(key, None)
    for suffix in _EVIDENCE_SIDECARS:
        try:
            os.remove(STATE_PATH + suffix)
        except FileNotFoundError:
            pass


def cmd_user_intervention(flow, state, args):
    if args.intervention_action != "reconcile":
        api.die("未知用户介入动作", 2)
    payload = _load_payload(args.file)
    paths = _paths(payload)
    changed = bool(payload.get("changed", False))
    old = str(state.get("current", "") or "")
    target = intervention_target(state, changed, paths)
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    if changed:
        _clear_stale_evidence(state)
        if target != "quality_review":
            state.pop("quality_review", None)
    state["current"] = target
    state["user_intervention"] = {
        "at": now,
        "actor": _text(payload.get("actor"), 100) or "用户",
        "request": _text(payload.get("request"), 2000),
        "assistant_summary": _text(payload.get("assistant_summary"), 4000),
        "changed": changed,
        "changed_paths": paths,
        "executions": _execution_rows(payload),
        "from_step": old,
        "target_step": target,
    }
    state.setdefault("history", []).append({
        "step": old,
        "result": "user-intervention:" + target,
        "note": "用户接管代码现场；旧证据已作废" if changed
                else "用户介入未改变业务文件",
        "at": now,
    })
    if target and target != old:
        state.setdefault("step_heads", {})[target] = api.sh(
            "git rev-parse --verify HEAD")
    api.save_state(state)
    print(json.dumps({
        "schema": SCHEMA,
        "changed": changed,
        "from": old,
        "target": target,
    }, ensure_ascii=False))


def render_user_intervention(state):
    record = (state or {}).get("user_intervention") or {}
    if not isinstance(record, dict) or not record:
        return ""
    lines = [
        "──── 用户接管现场（最高优先级上下文，不是质量证据） ────",
        "用户要求：" + (_text(record.get("request"), 2000) or "未记录"),
        "开发助手结果：" + (
            _text(record.get("assistant_summary"), 4000) or "未记录"),
    ]
    paths = record.get("changed_paths", []) or []
    lines.append("变更文件：" + ("、".join(paths[:30]) if paths else "未检测到业务文件变化"))
    executions = record.get("executions", []) or []
    if executions:
        lines.append("已执行：")
        for item in executions[-8:]:
            lines.append("- %s [%s] %s" % (
                _text(item.get("name"), 80) or "工具",
                _text(item.get("state"), 24) or "未知",
                _text(item.get("result"), 300)))
    lines.append(
        "接手要求：以当前工作区为用户授权后的事实继续；不要恢复旧审批、旧质量结论或旧流水线，"
        "也不要重复用户已完成且结果明确的排查。需要交付前仍按当前流程完成必要验证。")
    return "\n".join(lines)
