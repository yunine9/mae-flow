"""Characterization scenarios for Quality use-case extraction."""

import os

from differential.stage0_scenarios import fixed_cli, flow_state, write_json


def _quality_state(current):
    state = flow_state(current, "tweak")
    state["config"].update({
        "基线分支": "main",
        "CHANGE_NAME": "quality-diff",
    })
    return state


def quality_codecheck_empty_scan(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    write_json(
        os.path.join(project, ".mae-flow.json"),
        _quality_state("tw_codecheck"),
    )
    write_json(
        os.path.join(project, ".mae-flow.json.usermsg"),
        [{
            "id": "scope-answer",
            "text": "全部不涉及本次修改",
            "step": "tw_codecheck",
            "at": "9999-12-31 23:59:59",
        }],
    )
    return fixed_cli(
        implementation_root, env, "codecheck-scan")


def quality_codecheck_scope_missing_scan(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    write_json(
        os.path.join(project, ".mae-flow.json"),
        _quality_state("tw_codecheck"),
    )
    return fixed_cli(
        implementation_root,
        env,
        "codecheck-scope",
        "--none",
        "--message-id",
        "scope-answer",
    )


def quality_agent_task_missing_scan(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    write_json(
        os.path.join(project, ".mae-flow.json"),
        _quality_state("tw_codecheck"),
    )
    return fixed_cli(
        implementation_root,
        env,
        "agent-task",
        "codecheck",
        "--scope",
        "current warnings",
    )


def quality_standalone_finish_missing_token(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    work_dir = os.path.join(
        project, ".mae-flow-work", "standalone", "quality-diff")
    os.makedirs(work_dir, exist_ok=True)
    write_json(os.path.join(
        project, ".mae-flow-work", "standalone-action.json"), {
            "schema_version": 2,
            "revision": 1,
            "kind": "ut",
            "id": "quality-diff",
            "status": "active",
            "expires_epoch": 4102444800,
            "work_dir": work_dir,
            "tokens": {},
            "rejections": {},
            "quality": {},
        })
    return fixed_cli(
        implementation_root, env, "action", "finish")
