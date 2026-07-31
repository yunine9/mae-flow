"""Pure navigation for development checkpoint state."""


CODE_STEPS = {
    "full": "build",
    "hotfix": "build",
    "tweak": "tw_change",
    "review": "rf_fix",
}

LOCKED_STATUSES = {
    "plan_review_pending",
    "craft_pending",
    "craft_decision_pending",
    "review_pending",
    "commit_pending",
    "commit_recovery",
    "reset_pending",
    "push_pending",
}


def development_review(state):
    data = state.get("development_review")
    return (
        data
        if isinstance(data, dict)
        and data.get("version") in (1, 2)
        else None
    )


def current_item(state):
    data = development_review(state)
    if not data:
        return None
    items = data.get("checkpoints") or []
    index = int(data.get("current_index", 0) or 0)
    return (
        items[index]
        if 0 <= index < len(items)
        else None
    )


def expected_code_step(state):
    workflow = (
        (state.get("choices") or {}).get("workflow", "")
    )
    return CODE_STEPS.get(workflow, "")


def final_review_item(state):
    data = development_review(state)
    if not data or state.get("current") != "delivery_review":
        return None
    final = data.get("final_review")
    if not isinstance(final, dict):
        return None
    return (
        final
        if final.get("status") in LOCKED_STATUSES
        else None
    )


def locked_item(state):
    item = current_item(state)
    if (
        item
        and item.get("status") in LOCKED_STATUSES
    ):
        return item
    return final_review_item(state)


def review_pending(state, moonlight=False):
    if moonlight:
        return False
    item = locked_item(state)
    return bool(
        item and item.get("status") == "review_pending"
    )


def review_locked(state, moonlight=False):
    return False if moonlight else locked_item(state) is not None
