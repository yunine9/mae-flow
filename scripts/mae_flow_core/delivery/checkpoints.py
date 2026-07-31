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

CHECKPOINT_REWIND_STEPS = {
    "config_confirm",
    "workflow_select",
    "code_reviewer_ask",
    "branch_create",
    "grill_ask",
    "grill",
    "open",
    "design",
    "test_blueprint",
    "story_ask",
    "story",
    "build_plan",
    "build_pace",
    "hf_open",
    "tw_open",
    "tw_pace",
    "rf_triage",
    "rf_pace",
}

POST_CHECKPOINT_STEPS = {
    "build_review",
    "verify_ponytail",
    "verify_codecheck",
    "verify_ut",
    "verify_comet",
    "tw_compile",
    "tw_review",
    "tw_codecheck",
    "tw_ut",
    "tw_verify",
    "rf_compile",
    "rf_review",
    "rf_codecheck",
    "rf_ut",
    "delivery_review",
    "archive_confirm",
    "archive",
    "push",
    "end",
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


def checkpoint_goto_error(state, target):
    """Reject a downstream goto while the current CP still owns the flow."""
    data = development_review(state)
    item = current_item(state)
    if (
        not data
        or data.get("status") != "active"
        or not item
    ):
        return ""
    expected = expected_code_step(state)
    if target == expected or target in CHECKPOINT_REWIND_STEPS:
        return ""
    return (
        "检查点 %s [%s] 尚未闭环，goto 不能跳到 %s。"
        "请回到 %s 并执行 checkpoint status；若要放弃当前开发方案，"
        "只能显式回退到编码前步骤重新规划，不能跳过 CP 进入验证。"
        % (
            item.get("id", "当前 CP"),
            item.get("status", "未知"),
            target,
            expected or "当前工作流编码步骤",
        )
    )


def misplaced_checkpoint_step(state):
    """Return the code step for an old state forced past an unfinished CP."""
    item = current_item(state)
    expected = expected_code_step(state)
    if (
        item
        and expected
        and state.get("current") in POST_CHECKPOINT_STEPS
        and state.get("current") != expected
    ):
        return expected
    return ""
