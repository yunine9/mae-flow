"""Additional characterization scenarios for the completion refactor."""

import json
import os
import subprocess
import sys


def write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")


def cli(implementation_root, env, *arguments):
    return {
        "argv": [
            sys.executable,
            os.path.join(implementation_root, "scripts", "mae-flow.py"),
            *arguments,
        ],
        "stdin": "",
        "env": env,
    }, {}


def hook(implementation_root, env, event, payload):
    return {
        "argv": [
            sys.executable,
            os.path.join(implementation_root, "hooks", "dispatch.py"),
            event,
        ],
        "stdin": json.dumps(payload, ensure_ascii=False) + "\n",
        "env": env,
    }, {}


def fixed_entrypoint(
        implementation_root, env, relative_path, arguments, stdin=""):
    script = os.path.join(implementation_root, *relative_path)
    runner = (
        "import os,runpy,sys,time;"
        "path=sys.argv[1];"
        "sys.path.insert(0,os.path.dirname(path));"
        "time.strftime=lambda fmt,*_args:"
        "'20260729-100000' if fmt=='%Y%m%d-%H%M%S' "
        "else '2026-07-29 10:00:00';"
        "time.time=lambda:1785290400.0;"
        "time.time_ns=lambda:1785290400000000000;"
        "os.getpid=lambda:4242;"
        "sys.argv=[path,*sys.argv[2:]];"
        "runpy.run_path(path,run_name='__main__')"
    )
    return {
        "argv": [
            sys.executable,
            "-c",
            runner,
            script,
            *arguments,
        ],
        "stdin": stdin,
        "env": env,
    }, {}


def fixed_cli(implementation_root, env, *arguments):
    return fixed_entrypoint(
        implementation_root,
        env,
        ("scripts", "mae-flow.py"),
        arguments,
    )


def fixed_hook(implementation_root, env, event, payload):
    return fixed_entrypoint(
        implementation_root,
        env,
        ("hooks", "dispatch.py"),
        (event,),
        json.dumps(payload, ensure_ascii=False) + "\n",
    )


def flow_state(current, workflow, **extra):
    state = {
        "schema_version": 2,
        "revision": 1,
        "updated_at": "2026-07-29 10:00:00",
        "current": current,
        "config": {
            "单号": "REQ-DIFF",
            "单号类型": "feat",
            "分支名": "main",
        },
        "choices": {"workflow": workflow},
        "history": [],
        "started": "2026-07-29 10:00:00",
    }
    state.update(extra)
    return state


def direct_current(project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    write_json(os.path.join(project, ".mae-flow.json.exited"), {
        "schema_version": 2,
        "revision": 1,
        "status": "exited",
        "snapshot": ".mae-flow-work/exited/REQ-DIFF.json",
    })
    return cli(implementation_root, env, "current")


def standalone_action_status(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    write_json(
        os.path.join(
            project, ".mae-flow-work", "standalone-action.json"),
        {
            "schema_version": 2,
            "revision": 1,
            "kind": "ut",
            "id": "diff-action",
            "expires_epoch": 4102444800,
            "work_dir": os.path.join(
                project, ".mae-flow-work", "standalone", "diff-action"),
            "tokens": {},
            "rejections": {},
            "quality": {},
        },
    )
    return cli(implementation_root, env, "action", "status")


def corrupt_exit_repair(project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    with open(
            os.path.join(project, ".mae-flow.json.exited"),
            "w", encoding="utf-8", newline="\n") as stream:
        stream.write("{broken-exit")
    return fixed_cli(implementation_root, env, "doctor", "--repair-state")


def terminal_pretooluse_bypass(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    write_json(os.path.join(project, ".mae-flow.json"), {
        "schema_version": 2,
        "revision": 1,
        "updated_at": "2026-07-29 10:00:00",
        "current": "end",
        "config": {"单号": "REQ-DIFF", "分支名": "main"},
        "choices": {"workflow": "tweak"},
        "history": [],
        "started": "2026-07-29 10:00:00",
    })
    return hook(
        implementation_root,
        env,
        "pretooluse",
        {
            "cwd": project,
            "tool_name": "Bash",
            "tool_input": {"command": "git reset --hard"},
        },
    )


def checkpoint_status(project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=True,
    ).stdout.strip()
    state = flow_state(
        "tw_change",
        "tweak",
        development_review={
            "version": 1,
            "mode": "staged",
            "status": "active",
            "current_index": 0,
            "delivery_base": head,
            "last_reviewed_head": head,
            "checkpoints": [{
                "id": "CP1",
                "title": "core behavior",
                "status": "coding",
                "fixed_base": head,
            }],
        },
    )
    write_json(os.path.join(project, ".mae-flow.json"), state)
    return cli(implementation_root, env, "checkpoint", "status")


def moonlight_report_issue(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    state = flow_state(
        "moonlight_review",
        "review",
        moonlight={
            "enabled": True,
            "cycle": 2,
            "activated_at": "2026-07-29 00:00:00",
            "request": "开启月光宝盒继续开发",
            "issues": [{
                "id": "ML-001",
                "kind": "environment",
                "reason": "deterministic fixture failure",
                "step": "rf_ut",
                "at": "2026-07-29 01:00:00",
                "head": "",
            }],
        },
    )
    write_json(os.path.join(project, ".mae-flow.json"), state)
    return cli(implementation_root, env, "moonlight", "report")


def active_pretooluse_edit(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    write_json(
        os.path.join(project, ".mae-flow.json"),
        flow_state("build", "full"),
    )
    return hook(
        implementation_root,
        env,
        "pretooluse",
        {
            "cwd": project,
            "tool_name": "Edit",
            "tool_input": {
                "file_path": os.path.join(project, "README.md"),
            },
        },
    )


def subagentstop_missing_task_card(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    write_json(
        os.path.join(project, ".mae-flow.json"),
        flow_state("build", "full"),
    )
    transcript = os.path.join(
        project, ".mae-flow-work", "agent-compile.jsonl")
    os.makedirs(os.path.dirname(transcript), exist_ok=True)
    with open(transcript, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps({
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": (
                    "COMPILE_RESULT: OK\n"
                    "TASK_CARD_SHA256: "
                    + "0" * 64
                    + "\nEXECUTED_BUILD: fixture\nBUILD_ERRORS: 0"
                ),
            },
        }, ensure_ascii=False) + "\n")
    return fixed_hook(
        implementation_root,
        env,
        "subagentstop",
        {
            "cwd": project,
            "agent_transcript_path": transcript,
        },
    )
