"""Task-card freshness and source-scope use cases for Hook Agents."""

from dataclasses import dataclass
from typing import Callable

from mae_flow_core.application.hooks.models import accepted, rejected
from mae_flow_core.foundation.source_paths import repository_path_identity


@dataclass(frozen=True)
class TaskCardPorts:
    read_text: Callable
    current_head: Callable
    merge_base: Callable
    changed_paths_since: Callable
    source_changed_since: Callable
    source_snapshot: Callable
    path_fingerprint: Callable
    review_path_fingerprint: Callable
    source_like: Callable
    test_like: Callable
    path_exists: Callable
    script_path: Callable


def _task_for(state, kind):
    return (state.get("agent_tasks", {}) or {}).get(kind, {}) or {}


def verify_completion_task(kind, report, state, ports):
    """Compatibility helper: validate task identity, never return wording."""
    task = _task_for(state, kind)
    if not task:
        return rejected(
            "未生成 harness 任务卡。主 agent 必须先执行 mae-flow agent-task。")
    if task.get("step") != state.get("current"):
        return rejected("任务卡属于旧步骤,禁止拿旧配置执行当前任务。", task)
    return accepted(task)


def _dispatch_missing_message(kind, script_path):
    if kind == "GRILL":
        remedy = (
            'python "%s" action status，并按输出执行 action critic 生成 GRILL 任务卡'
            % script_path
        )
    else:
        remedy = (
            'python "%s" agent-task %s 生成并签发任务卡'
            % (script_path, kind.lower())
        )
    return (
        "[mae-flow] 派发前拦截:%s 尚无本步任务卡。先执行 %s,再按其输出话术派发。"
        "现在拦下只损失一次调用;跑完整只 agent 才被契约打回,重做要上百轮白跑。"
        % (kind, remedy)
    )


def _dispatch_refresh_remedy(kind, script_path):
    if kind == "GRILL":
        return (
            'python "%s" action status，并重新执行当前 action critic'
            % script_path
        )
    return 'python "%s" agent-task %s' % (script_path, kind.lower())


def verify_dispatch_task(kind, state, ports):
    """Require the current task card without fingerprint freshness gates."""
    task = _task_for(state, kind)
    script_path = ports.script_path()
    if not task:
        return rejected(_dispatch_missing_message(kind, script_path))
    if task.get("step") != state.get("current"):
        return rejected(
            "[mae-flow] 派发前拦截:%s 任务卡属于旧步骤 %s，当前步骤为 %s。"
            "先按 current/action status 生成当前步骤的新任务卡，再派发。"
            % (
                kind,
                task.get("step", "?"),
                state.get("current", "?"),
            ),
            task,
        )
    return accepted(task)


def _verify_dispatch_source_freshness(kind, state, task, head, ports):
    if task.get("precommit_review") and head:
        if ports.source_snapshot(head) != (
                task.get("source_snapshot") or {}):
            return rejected(
                "[mae-flow] 派发前拦截:%s 未提交任务卡签发后代码又发生变化。"
                "重新生成任务卡再派发，避免编译的不是即将检视的 diff。"
                % kind,
                task,
            )
    elif not task.get("standalone") and head:
        changed, error = ports.source_changed_since(head, state)
        if error:
            return rejected(
                "[mae-flow] 派发前拦截:%s 无法核对任务卡新鲜度(%s)。"
                "先重新生成任务卡。" % (kind, error),
                task,
            )
        if changed:
            return rejected(
                "[mae-flow] 派发前拦截:%s 签卡后源码又发生未提交变化: %s。"
                "先提交本单改动并重新生成任务卡；现在拦下可避免整只 agent 白跑。"
                % (kind, "、".join(changed[:5])),
                task,
            )
    return accepted(task)


def _current_source_change(path, task, state, ports):
    if task.get("standalone"):
        initial = task.get("initial_source_fingerprints", {}) or {}
        return initial.get(path) != ports.path_fingerprint(path)
    if task.get("precommit_review"):
        initial = task.get("source_snapshot", {}) or {}
        return initial.get(path) != ports.review_path_fingerprint(path)
    initial_dirty = set(state.get("initial_dirty", []) or [])
    fingerprints = state.get("initial_dirty_fingerprints", {}) or {}
    return not (
        path in initial_dirty
        and fingerprints.get(path) == ports.path_fingerprint(path)
    )


def _changed_source_paths(task, state, ports):
    changed = tuple(
        path for path in ports.changed_paths_since(task.get("head", ""))
        if ports.source_like(path)
    )
    return tuple(
        path for path in changed
        if _current_source_change(path, task, state, ports)
    )


def _compile_scope_rejection(changed, ports):
    bad = [path for path in changed if ports.test_like(path)]
    return (
        "compile-agent 越权修改了测试文件: " + "、".join(bad[:5])
        if bad else ""
    )


def _codecheck_scope_rejection(task, changed):
    allowed = {
        str(path).replace("\\", "/").lower()
        for path in task.get("allowed_files", [])
    }
    bad = [path for path in changed if path.lower() not in allowed]
    return (
        "codecheck-fix-agent 修改了首检范围外文件: "
        + "、".join(bad[:5])
        if bad else ""
    )


def _ut_command_side_effect_rejection(paths):
    return (
        "UT 命令产生了非测试文件副作用: "
        + "、".join(paths[:5])
        + "。不要使用 unlock source 或 accept-risk，不要询问用户。"
        "只恢复任务签发时干净的路径；本次新增输出应恢复性移出交付范围后"
        "重试收尾。任务基线已有的用户脏文件不得删除或覆盖。"
    )


def _ut_non_test_changes(changed, ports, direct_write_paths):
    bad = [path for path in changed if not ports.test_like(path)]
    direct = {
        repository_path_identity(path)
        for path in direct_write_paths
    }
    return (
        [
            path for path in bad
            if repository_path_identity(path) in direct
        ],
        [
            path for path in bad
            if repository_path_identity(path) not in direct
        ],
    )


def _ut_scope_rejection(changed, ports, direct_write_paths):
    deleted = [
        path for path in changed
        if ports.test_like(path) and not ports.path_exists(path)
    ]
    if deleted:
        return (
            "ut-generator-agent 删除了既有测试文件: "
            + "、".join(deleted[:5])
            + "；不能通过删测试取得 PASS。"
        )
    intentional, command_effects = _ut_non_test_changes(
        changed, ports, direct_write_paths)
    if not intentional and not command_effects:
        return ""
    message = (
        "ut-generator-agent 修改了非测试源码: "
        + "、".join(intentional[:5])
        + "；源码缺陷必须先交用户裁决。"
        if intentional else ""
    )
    if command_effects:
        message += (
            (" 此外，" if message else "")
            + _ut_command_side_effect_rejection(command_effects)
        )
    return message


def _scope_rejection(kind, task, changed, ports, direct_write_paths):
    if kind == "COMPILE":
        return _compile_scope_rejection(changed, ports)
    if kind == "CODECHECK":
        return _codecheck_scope_rejection(task, changed)
    if kind == "UT":
        return _ut_scope_rejection(
            changed, ports, direct_write_paths)
    if kind == "GRILL" and changed:
        return (
            "grill-critic-agent 是只读审查角色，却修改了文件: "
            + "、".join(changed[:5])
        )
    return ""


def verify_agent_scope(
        kind, task, state, ports, direct_write_paths=()):
    """Apply the four Agent write boundaries to frozen repository facts."""
    changed = _changed_source_paths(task, state, ports)
    reason = _scope_rejection(
        kind, task, changed, ports, direct_write_paths)
    return (
        rejected(reason, task, changed)
        if reason else accepted(task, changed)
    )
