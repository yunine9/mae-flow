"""Additional characterization scenarios for the completion refactor."""

import json
import os
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
    return cli(implementation_root, env, "doctor", "--repair-state")


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
