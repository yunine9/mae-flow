"""Characterization scenarios for Delivery use-case extraction."""

import os
import subprocess

from differential.stage0_scenarios import fixed_cli, flow_state, write_json


def _git(project, env, *args):
    return subprocess.run(
        ["git", *args],
        cwd=project,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=True,
    ).stdout.strip()


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


def checkpoint_staged_status(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    head = _git(project, env, "rev-parse", "HEAD")
    state = flow_state("tw_change", "tweak")
    state["development_review"] = {
        "version": 1,
        "mode": "staged",
        "status": "active",
        "review_before_commit": False,
        "current_index": 0,
        "delivery_base": head,
        "last_reviewed_head": head,
        "checkpoints": [{
            "id": "CP1",
            "title": "staged batch",
            "status": "push_pending",
            "fixed_base": head,
            "compile_head": head,
            "head": head,
        }],
    }
    write_json(os.path.join(project, ".mae-flow.json"), state)
    return fixed_cli(
        implementation_root, env, "checkpoint", "status")


def checkpoint_continuous_ready(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    base = _git(project, env, "rev-parse", "HEAD")
    with open(
            os.path.join(project, "notes.md"),
            "w", encoding="utf-8", newline="\n") as stream:
        stream.write("# completed batch\n")
    _git(project, env, "add", "--", "notes.md")
    _git(
        project, env, "-c", "commit.gpgsign=false",
        "commit", "-qm", "[REQ-DIFF][feat]continuous batch")
    state = flow_state("tw_change", "tweak")
    state["development_review"] = {
        "version": 1,
        "mode": "continuous",
        "status": "active",
        "review_before_commit": True,
        "current_index": 0,
        "delivery_base": base,
        "last_reviewed_head": base,
        "checkpoints": [{
            "id": "CP1",
            "title": "continuous batch",
            "status": "coding",
            "fixed_base": base,
        }],
    }
    write_json(os.path.join(project, ".mae-flow.json"), state)
    return fixed_cli(
        implementation_root,
        env,
        "checkpoint",
        "ready",
        "CP1",
    )


def checkpoint_revise_decision(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    head = _git(project, env, "rev-parse", "HEAD")
    state = flow_state("tw_change", "tweak")
    state["development_review"] = {
        "version": 1,
        "mode": "staged",
        "status": "active",
        "review_before_commit": True,
        "current_index": 0,
        "delivery_base": head,
        "last_reviewed_head": head,
        "checkpoints": [{
            "id": "CP1",
            "title": "revise batch",
            "status": "review_pending",
            "fixed_base": head,
            "head": head,
            "receipt": {
                "base": head,
                "snapshot": {},
                "ack_cursor": [],
            },
        }],
    }
    write_json(os.path.join(project, ".mae-flow.json"), state)
    write_json(os.path.join(project, ".mae-flow.json.usermsg"), [{
        "text": "需要调整代码",
        "step": "tw_change",
        "at": "9999-12-31 23:59:59",
    }])
    return fixed_cli(
        implementation_root,
        env,
        "checkpoint",
        "decide",
        "revise",
    )


def checkpoint_final_review(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    base = _git(project, env, "rev-parse", "HEAD")
    os.makedirs(os.path.join(project, "src"))
    with open(
            os.path.join(project, "src", "main.py"),
            "w", encoding="utf-8", newline="\n") as stream:
        stream.write("def answer():\n    return 42\n")
    _git(project, env, "add", "--", "src/main.py")
    _git(
        project, env, "-c", "commit.gpgsign=false",
        "commit", "-qm", "[REQ-DIFF][feat]final delta")
    state = flow_state("delivery_review", "tweak")
    state["config"]["基线分支"] = base
    state["development_review"] = {
        "version": 1,
        "mode": "continuous",
        "status": "active",
        "review_before_commit": True,
        "current_index": 1,
        "delivery_base": base,
        "last_reviewed_head": base,
        "checkpoints": [{
            "id": "CP1",
            "title": "completed batch",
            "status": "completed",
            "fixed_base": base,
            "completed_head": base,
        }],
    }
    write_json(os.path.join(project, ".mae-flow.json"), state)
    return fixed_cli(
        implementation_root, env, "checkpoint", "final")


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


def standalone_scope_confirmation(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    os.makedirs(os.path.join(project, "src"))
    source = os.path.join(project, "src", "main.py")
    with open(source, "w", encoding="utf-8", newline="\n") as stream:
        stream.write("def answer():\n    return 42\n")
    action = {
        "schema_version": 2,
        "revision": 1,
        "kind": "ut",
        "id": "delivery-scope",
        "status": "awaiting_scope_confirmation",
        "expires_epoch": 4102444800,
        "scope_proposed_epoch": 1,
        "scope_sha256": "scope-diff",
        "work_dir": os.path.join(
            project, ".mae-flow-work", "standalone",
            "delivery-scope"),
        "files": ["src/main.py"],
        "sources": [],
        "config": {
            "UT生成方式": "existing",
            "UT运行命令": "python -m unittest",
        },
        "tokens": {},
        "rejections": {},
        "quality": {},
        "user_messages": [{
            "id": "scope-answer",
            "text": "确认以上范围",
            "epoch": 2,
            "scope_sha256": "scope-diff",
        }],
    }
    write_json(os.path.join(
        project, ".mae-flow-work",
        "standalone-action.json"), action)
    return fixed_cli(
        implementation_root,
        env,
        "action",
        "confirm-scope",
    )


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


def moonlight_finalize_clean(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    state = _moonlight_state("moonlight_review")
    write_json(os.path.join(project, ".mae-flow.json"), state)
    return fixed_cli(
        implementation_root, env, "moonlight", "finalize")


def moonlight_repair_issue(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    state = _moonlight_state("moonlight_review")
    state["moonlight"]["issues"] = [{
        "id": "ML-001",
        "step": "rf_ut",
        "kind": "ut",
        "at": "2026-07-29 09:00:00",
        "head": "",
        "reason": "one deterministic test remains unresolved",
    }]
    write_json(os.path.join(project, ".mae-flow.json"), state)
    return fixed_cli(
        implementation_root, env, "moonlight", "repair")
