"""Minimal, disk-backed recovery guidance for Spec2Code loops."""

import hashlib


_LOOPS = {
    "blueprint": "UT 蓝图 Loop",
    "roadmap": "全局路线图 Loop",
    "plan": "当前 CP 计划 Loop",
    "plan_review": "当前 CP 计划 Loop",
    "code_review": "当前 CP 代码 Loop",
}


def _current_checkpoint(state):
    review = state.get("development_review") or {}
    items = review.get("checkpoints") or []
    index = int(review.get("current_index", 0) or 0)
    return items[index] if 0 <= index < len(items) else {}


def _artifact(kind, record):
    if not isinstance(record, dict) or not record.get("path"):
        return None
    return (
        kind,
        str(record.get("path", "")),
        str(record.get("sha256", "")),
    )


def _process_artifacts(process, kinds):
    return tuple(
        value for value in (
            _artifact(kind, process.get(kind))
            for kind in kinds
        )
        if value
    )


def _checkpoint_artifacts(state, process):
    item = _current_checkpoint(state)
    result = list(
        _process_artifacts(process, ("roadmap", "plan")))
    status = item.get("status")
    if status == "plan_review_pending":
        receipt = item.get("plan_receipt") or {}
        result.append(_artifact("plan_review", {
            "path": receipt.get("review_path"),
            "sha256": receipt.get("review_sha256"),
        }))
    if status in {
            "craft_pending", "craft_decision_pending",
            "review_pending", "coding"}:
        result.append(_artifact(
            "code_review", item.get("craft_review")))
    return tuple(value for value in result if value)


def _required_artifacts(state):
    step = str(state.get("current", "") or "")
    process = state.get("spec2code") or {}
    if step == "test_blueprint":
        return _process_artifacts(process, ("blueprint",))
    if step == "verify_ut":
        return _process_artifacts(process, ("blueprint",))
    if step == "build_plan":
        return _process_artifacts(
            process, ("blueprint", "roadmap", "plan"))
    return (
        _checkpoint_artifacts(state, process)
        if step == "build" else ()
    )


def recovery_guidance(state, is_file, read_text):
    """Describe only the files needed to resume the current loop."""
    artifacts = _required_artifacts(state)
    lines = ["──── Spec2Code 最小恢复上下文 ────"]
    for kind, path, expected in artifacts:
        if not is_file(path):
            lines.append(
                "❌ %s 不存在；保留现场并回到%s。"
                % (path, _LOOPS[kind]))
            continue
        try:
            body = read_text(path)
        except (OSError, UnicodeDecodeError) as exc:
            lines.append(
                "❌ %s 无法读取（%s）；保留现场并回到%s。"
                % (path, exc, _LOOPS[kind]))
            continue
        actual = hashlib.sha256(
            body.encode("utf-8")).hexdigest()
        if expected and actual != expected:
            lines.append(
                "❌ %s 摘要已变化；旧结论失效，文件不删除，"
                "回到%s重新检视。" % (path, _LOOPS[kind]))
        else:
            lines.append("- 读取 " + path)
    step = str(state.get("current", "") or "")
    if step == "build":
        lines.append("- 读取当前 CP 的 Git diff，不回放完整会话历史")
    elif step == "verify_ut":
        lines.append("- 读取最终 Git diff 与已冻结 UT 任务范围")
    return tuple(lines)
