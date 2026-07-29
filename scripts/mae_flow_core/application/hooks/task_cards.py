"""Task-card freshness and source-scope use cases for Hook Agents."""

from dataclasses import dataclass
import hashlib
import re
from typing import Callable

from mae_flow_core.application.hooks.models import accepted, rejected


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


def _card_digest(ports, task):
    text = ports.read_text(task["path"])
    body = text.rsplit("TASK_CARD_SHA256:", 1)[0]
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def verify_completion_task(kind, report, state, ports):
    """Verify the card returned by a completed contract Agent."""
    task = _task_for(state, kind)
    if not task:
        return rejected(
            "未生成 harness 任务卡。主 agent 必须先执行 mae-flow agent-task。")
    if task.get("step") != state.get("current"):
        return rejected("任务卡属于旧步骤,禁止拿旧配置执行当前任务。", task)
    match = re.search(
        r"^TASK_CARD_SHA256:\s*([0-9a-f]{64})\s*$",
        report,
        re.M | re.I,
    )
    if (
            not match
            or match.group(1).lower()
            != str(task.get("sha256", "")).lower()):
        return rejected(
            "最终报告缺少当前任务卡的 TASK_CARD_SHA256,说明启动信息不完整。",
            task,
        )
    try:
        actual = _card_digest(ports, task)
    except Exception as exc:
        return rejected("任务卡不可读:" + str(exc), task)
    if actual != task.get("sha256"):
        return rejected(
            "任务卡内容被修改过,必须重新执行 agent-task 生成。", task)
    head = task.get("head", "")
    if not re.fullmatch(r"[0-9a-f]{7,64}", head or ""):
        return rejected("任务卡缺少可验证的基点 HEAD。", task)
    current = ports.current_head()
    if ports.merge_base(head, current) != head and head != current:
        return rejected(
            "任务卡基点已不在当前提交历史中(amend/rebase/切分支)，"
            "请重新生成任务卡。",
            task,
        )
    if task.get("standalone") and current != head:
        return rejected(
            "独立任务禁止自动 commit，但当前 HEAD 已变化。"
            "保留代码后结束本任务并由用户自行决定是否提交。",
            task,
        )
    if task.get("precommit_review") and current != head:
        return rejected(
            "当前检查点要求用户先检视未提交 diff；子 Agent 禁止自动 commit。"
            "保留工作区代码并重新按真实结果收尾。",
            task,
        )
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
    """Reject stale Agent work before the expensive subagent is launched."""
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
    try:
        actual = _card_digest(ports, task)
    except Exception as exc:
        return rejected(
            "[mae-flow] 派发前拦截:%s 任务卡不可读(%s)。"
            "先重新生成任务卡，避免整只 agent 跑完才发现输入失效。"
            % (kind, exc),
            task,
        )
    if actual != task.get("sha256"):
        return rejected(
            "[mae-flow] 派发前拦截:%s 任务卡内容已变化。"
            "先重新生成任务卡；旧卡不能代表当前任务。" % kind,
            task,
        )
    head = task.get("head", "")
    current = ports.current_head()
    if head and current and head != current:
        remedy = _dispatch_refresh_remedy(kind, script_path)
        return rejected(
            "[mae-flow] 派发前拦截:%s 任务卡签发于 HEAD %s,当前 HEAD %s"
            "——源码已变化,旧卡描述的不是现在的代码,跑完也拿不到令牌。"
            "先重新执行 %s 再派发。"
            % (kind, head[:10], current[:10], remedy),
            task,
        )
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


def _changed_source_paths(task, state, ports):
    changed = tuple(
        path for path in ports.changed_paths_since(task.get("head", ""))
        if ports.source_like(path)
    )
    if task.get("standalone"):
        initial = task.get("initial_source_fingerprints", {}) or {}
        return tuple(
            path for path in changed
            if initial.get(path) != ports.path_fingerprint(path)
        )
    if task.get("precommit_review"):
        initial = task.get("source_snapshot", {}) or {}
        return tuple(
            path for path in changed
            if initial.get(path) != ports.review_path_fingerprint(path)
        )
    initial_dirty = set(state.get("initial_dirty", []) or [])
    fingerprints = state.get("initial_dirty_fingerprints", {}) or {}
    return tuple(
        path for path in changed
        if not (
            path in initial_dirty
            and fingerprints.get(path) == ports.path_fingerprint(path)
        )
    )


def _scope_rejection(kind, task, changed, ports):
    if kind == "COMPILE":
        bad = [path for path in changed if ports.test_like(path)]
        return (
            "compile-agent 越权修改了测试文件: " + "、".join(bad[:5])
            if bad else ""
        )
    if kind == "CODECHECK":
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
    if kind == "UT":
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
        bad = [path for path in changed if not ports.test_like(path)]
        return (
            "ut-generator-agent 修改了非测试源码: "
            + "、".join(bad[:5])
            + "；源码缺陷必须先交用户裁决。"
            if bad else ""
        )
    if kind == "GRILL" and changed:
        return (
            "grill-critic-agent 是只读审查角色，却修改了文件: "
            + "、".join(changed[:5])
        )
    return ""


def verify_agent_scope(kind, task, state, ports):
    """Apply the four Agent write boundaries to frozen repository facts."""
    changed = _changed_source_paths(task, state, ports)
    reason = _scope_rejection(kind, task, changed, ports)
    return (
        rejected(reason, task, changed)
        if reason else accepted(task, changed)
    )
