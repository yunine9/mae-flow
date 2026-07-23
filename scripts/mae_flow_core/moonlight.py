"""Pure policy helpers for unattended (moonlight) execution."""

import time


QUALITY_STEPS = {
    "env_setup": "environment",
    "build": "compile",
    "rf_compile": "compile",
    "tw_compile": "compile",
    "verify_post_ponytail_compile": "compile",
    "verify_recompile": "compile",
    "rf_codecheck": "codecheck",
    "tw_codecheck": "codecheck",
    "verify_codecheck": "codecheck",
    "rf_ut": "ut",
    "tw_ut": "ut",
    "verify_ut": "ut",
    "verify_comet": "comet",
}

REPAIR_ENTRY = {
    "review": "rf_compile",
    "tweak": "tw_compile",
    "full": "verify_recompile",
    "hotfix": "verify_recompile",
}


def enabled(state):
    return bool(((state or {}).get("moonlight") or {}).get("enabled"))


def data(state):
    return (state or {}).setdefault("moonlight", {})


def unresolved(state):
    return [row for row in (data(state).get("issues") or [])
            if not row.get("resolved_at")]


def step_kind(step_id):
    return QUALITY_STEPS.get(step_id, "")


def can_hard_block(step_id):
    return step_id == "build" or (
        step_id not in QUALITY_STEPS
        and step_id not in ("push", "moonlight_review", "end"))


def resolve_kind(state, kind, head=""):
    if not enabled(state):
        return
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for issue in unresolved(state):
        if issue.get("kind") == kind:
            issue["resolved_at"] = now
            issue["resolved_head"] = head
