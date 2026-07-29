"""Pure transition policy for Mae-Flow workflow definitions."""


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
    for key in ("source_change_next", "source_change_recheck"):
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
    nxt = step.get("next")
    try:
        if step.get("next_by"):
            return nxt[state.get("choices", {}).get(step["next_by"])]
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
