"""Pure transition policy for Mae-Flow workflow definitions."""


def transition_targets(step):
    nxt = step.get("next")
    if isinstance(nxt, dict):
        return tuple(nxt.values())
    return (nxt,) if nxt else ()


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
