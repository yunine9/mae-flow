"""Characterization scenarios for Delivery use-case extraction."""

import os

from differential.stage0_scenarios import fixed_cli, flow_state, write_json


def checkpoint_plan_creation(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    state = flow_state("tw_pace", "tweak")
    state["config"].update({
        "基线分支": "main",
        "CHANGE_NAME": "diff-change",
    })
    write_json(os.path.join(project, ".mae-flow.json"), state)
    return fixed_cli(
        implementation_root,
        env,
        "checkpoint",
        "plan",
        "--item",
        "core behavior",
        "--item",
        "regression coverage",
    )


def standalone_action_cancel(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    work_dir = os.path.join(
        project, ".mae-flow-work", "standalone", "delivery-diff")
    os.makedirs(work_dir, exist_ok=True)
    write_json(os.path.join(
        project, ".mae-flow-work", "standalone-action.json"), {
            "schema_version": 2,
            "revision": 1,
            "kind": "ut",
            "id": "delivery-diff",
            "expires_epoch": 4102444800,
            "work_dir": work_dir,
            "tokens": {},
            "rejections": {},
            "quality": {},
        })
    return fixed_cli(
        implementation_root, env, "action", "cancel")


def _moonlight_state(current):
    state = flow_state(current, "review")
    state["config"].update({
        "基线分支": "main",
        "CHANGE_NAME": "diff-change",
    })
    state["moonlight"] = {
        "enabled": True,
        "cycle": 1,
        "activated_at": "2026-07-29 10:00:00",
        "request": "开启月光宝盒继续开发",
        "issues": [],
    }
    return state


def moonlight_quality_defer(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    write_json(
        os.path.join(project, ".mae-flow.json"),
        _moonlight_state("rf_codecheck"),
    )
    return fixed_cli(
        implementation_root,
        env,
        "moonlight",
        "defer",
        "--reason",
        "CodeCheck tool unavailable after two verified retries",
    )


def moonlight_push_failure(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    write_json(
        os.path.join(project, ".mae-flow.json"),
        _moonlight_state("push"),
    )
    return fixed_cli(
        implementation_root,
        env,
        "moonlight",
        "push-failed",
        "--reason",
        "remote authentication failed after two bounded retries",
    )
