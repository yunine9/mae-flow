"""Characterization scenarios for the Evidence domain extraction."""

import os
import subprocess

from differential.stage0_scenarios import (
    fixed_cli,
    flow_state,
    write_json,
)


def _write_flow(project, state):
    write_json(os.path.join(project, ".mae-flow.json"), state)


def _write_user_message(project, step, text):
    write_json(os.path.join(project, ".mae-flow.json.usermsg"), [{
        "id": "evidence-fixture",
        "step": step,
        "at": "2026-07-29 10:00:00",
        "text": text,
    }])


def _feature_source_commit(project, env):
    subprocess.run(
        ["git", "checkout", "-qb", "feature/evidence"],
        cwd=project,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )
    source = os.path.join(project, "src", "main.py")
    os.makedirs(os.path.dirname(source), exist_ok=True)
    with open(source, "w", encoding="utf-8", newline="\n") as stream:
        stream.write("VALUE = 1\n")
    subprocess.run(
        ["git", "add", "--", "src/main.py"],
        cwd=project,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git", "-c", "commit.gpgsign=false", "commit", "-qm",
            "[REQ-DIFF][feat] evidence fixture",
        ],
        cwd=project,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )


def _feature_state(current, workflow):
    state = flow_state(current, workflow)
    state["config"].update({
        "分支名": "feature/evidence",
        "基线分支": "main",
        "CHANGE_NAME": "diff-change",
    })
    return state


def evidence_branch_rejection(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    state = flow_state("branch_create", "tweak")
    state["config"].update({
        "分支名": "feature/evidence",
        "基线分支": "main",
    })
    _write_flow(project, state)
    return fixed_cli(implementation_root, env, "done")


def evidence_spec_rejection(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    state = flow_state("tw_open", "tweak")
    state["config"].update({
        "基线分支": "main",
        "CHANGE_NAME": "diff-change",
    })
    _write_flow(project, state)
    _write_user_message(project, "tw_open", "确认范围并继续")
    return fixed_cli(implementation_root, env, "done")


def evidence_checkpoint_rejection(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    state = flow_state(
        "tw_pace",
        "tweak",
        development_review={
            "version": 1,
            "status": "planning",
            "plan_step": "tw_pace",
            "ack_cursor": [],
            "checkpoints": [],
        },
    )
    state["config"]["基线分支"] = "main"
    _write_flow(project, state)
    _write_user_message(
        project, "tw_pace", "一次完成全部代码，最终统一检视")
    return fixed_cli(
        implementation_root, env, "done", "--choice", "continuous")


def evidence_agent_rejection(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    _feature_source_commit(project, env)
    _write_flow(project, _feature_state("tw_compile", "tweak"))
    return fixed_cli(implementation_root, env, "done")


def evidence_review_rejection(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    _feature_source_commit(project, env)
    state = _feature_state("tw_review", "tweak")
    _write_flow(project, state)
    _write_user_message(
        project, "tw_review", "我已认真检视并完成自验证，继续")
    return fixed_cli(
        implementation_root, env, "done", "--choice", "continue")


def evidence_codecheck_rejection(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    _feature_source_commit(project, env)
    _write_flow(project, _feature_state("tw_codecheck", "tweak"))
    return fixed_cli(implementation_root, env, "done")


def evidence_archive_rejection(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    state = flow_state("archive", "tweak")
    state["config"].update({
        "基线分支": "main",
        "CHANGE_NAME": "diff-change",
    })
    _write_flow(project, state)
    return fixed_cli(implementation_root, env, "done")


def evidence_push_rejection(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    _feature_source_commit(project, env)
    _write_flow(project, _feature_state("push", "tweak"))
    return fixed_cli(implementation_root, env, "done")
