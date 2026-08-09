"""Pure transition policy for Mae-Flow workflow definitions."""


_QUALITY_REVIEW_ROUTES = {
    "ponytail-source": ("verify_codecheck", "quality_recompile"),
    "codecheck-source": ("verify_codecheck", "quality_recompile"),
    "ut-source": ("verify_codecheck", "quality_recompile"),
    "ut-test": ("verify_spec", "verify_ut"),
}


def quality_review_context(
        origin, changed_files, entered_head, resume="", rework=""):
    """Create the semantic quality-review cursor without content digests."""
    if origin not in _QUALITY_REVIEW_ROUTES:
        raise ValueError("unknown quality review origin: %s" % origin)
    default_resume, default_rework = _QUALITY_REVIEW_ROUTES[origin]
    resume = str(resume or default_resume)
    rework = str(rework or default_rework)
    files = tuple(dict.fromkeys(
        str(path) for path in changed_files if str(path).strip()))
    if not files:
        raise ValueError("quality review requires changed files")
    return {
        "origin": origin,
        "resume": resume,
        "rework": rework,
        "changed_files": list(files),
        "entered_head": str(entered_head or ""),
    }


def _state_value(state, dotted_path):
    value = state
    for part in str(dotted_path or "").split("."):
        if not part or not isinstance(value, dict):
            return None
        value = value.get(part)
    return value if isinstance(value, str) and value else None


def transition_targets(step):
    targets = []

    def append(target, declared=False):
        if (declared or target is not None) and target not in targets:
            targets.append(target)

    nxt = step.get("next")
    if isinstance(nxt, dict):
        for target in nxt.values():
            append(target, declared=True)
    elif nxt:
        append(nxt)
    # 每一种"改了源码就换步"的声明都是真实转移边。漏登记的后果不是运行期出错
    # (done 直接改 current)，而是图校验、活性红线和环分析全都看不见那条边。
    for key in ("source_change_next", "source_change_recheck",
                "late_source_change_next"):
        if key in step:
            append(step.get(key), declared=True)
    dynamic = step.get("dynamic_next")
    if isinstance(dynamic, (list, tuple)):
        for target in dynamic:
            append(target, declared=True)
    elif "dynamic_next" in step:
        append(dynamic, declared=True)
    return tuple(targets)


def next_step(step, state, choice_override=""):
    if step.get("next_from_state"):
        return _state_value(state, step["next_from_state"])
    nxt = step.get("next")
    try:
        if step.get("next_by"):
            # 选择项缺失时走明写的默认分支。没有兜底的话,这一步就"缺少可解析
            # 的下一步"——done 拒绝推进,current 又不给恢复办法,流程当场活锁
            # (实测:月光宝盒跑到 build,code_reviewer 从未被写进配置,卡死 38 轮)。
            picked = state.get("choices", {}).get(step["next_by"])
            if picked is None and step.get("next_default"):
                picked = step["next_default"]
            return nxt[picked]
        if isinstance(nxt, dict):
            choice = (
                choice_override
                or state.get("choices", {}).get(step.get("choice_key"))
            )
            return nxt[choice]
    except Exception:
        return None
    return nxt


def resolved_next(flow, state, step_id):
    step = flow.get("steps", {}).get(step_id, {})
    return next_step(step, state)


def workflow_chain(flow, workflow):
    chain = []
    step_id = flow["start"]
    seen = set()
    while step_id and step_id not in seen:
        seen.add(step_id)
        chain.append(step_id)
        step = flow["steps"][step_id]
        nxt = step.get("next")
        if step.get("next_by"):
            nxt = nxt.get(workflow) if isinstance(nxt, dict) else nxt
        elif isinstance(nxt, dict):
            nxt = nxt.get("yes") or next(iter(nxt.values()))
        step_id = nxt
    return chain
