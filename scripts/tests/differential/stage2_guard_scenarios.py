"""Characterization scenarios for Guard, Permit, and Ownership extraction."""

import hashlib
import os
import subprocess

from differential.stage0_scenarios import fixed_cli, flow_state, write_json


def _state(project, current="build"):
    state = flow_state(current, "full")
    state["config"].update({
        "分支名": "",
        "基线分支": "main",
        "CHANGE_NAME": "diff-change",
    })
    write_json(os.path.join(project, ".mae-flow.json"), state)


def guard_internal_state_edit(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    _state(project)
    return fixed_cli(
        implementation_root, env, "gate", "edit", ".mae-flow.json")


def guard_requirement_bash_write(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    _state(project, "config_confirm")
    return fixed_cli(
        implementation_root,
        env,
        "gate",
        "bash",
        "printf requirement > docs/req/REQ-DIFF.md",
    )


def guard_expired_permit(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    _state(project, "config_confirm")
    subject = "docs/req/REQ-DIFF.md"
    rule = "edit-docs-req"
    block_id = hashlib.sha256(
        (rule + "\n" + subject).encode("utf-8")).hexdigest()[:10]
    write_json(os.path.join(project, ".mae-flow.json.gate-permits"), {
        block_id: {
            "rule": rule,
            "step": "config_confirm",
            "head": "0000000000000000000000000000000000000000",
            "sample": subject,
            "created_at": "2026-07-29 10:00:00",
            "ack": "同意本次操作",
            "used": False,
        },
    })
    return fixed_cli(
        implementation_root, env, "gate", "edit", subject)


def ownership_foreign_openspec(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    _state(project)
    path = os.path.join(
        project, "openspec", "changes", "other-change", "change.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as stream:
        stream.write("# Foreign change\n")
    subprocess.run(
        ["git", "add", "--", "openspec/changes/other-change/change.md"],
        cwd=project,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )
    return fixed_cli(
        implementation_root,
        env,
        "gate",
        "bash",
        "git commit -m '[REQ-DIFF][feat] foreign openspec'",
    )
