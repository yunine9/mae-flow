"""Deterministic public-behavior scenarios for Mae-Flow."""

import json
import os
import subprocess
import sys


FIXED_GIT_DATE = "2026-07-29T00:00:00+00:00"


def _run_git(project, env, *args):
    completed = subprocess.run(
        ["git", *args],
        cwd=project,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            "git %s failed: %s" % (" ".join(args), completed.stderr))


def _prepare_repository(project):
    env = dict(os.environ)
    env.update({
        "GIT_AUTHOR_DATE": FIXED_GIT_DATE,
        "GIT_COMMITTER_DATE": FIXED_GIT_DATE,
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    _run_git(
        project,
        env,
        "-c",
        "init.defaultObjectFormat=sha1",
        "init",
        "-q",
    )
    _run_git(project, env, "checkout", "-qb", "main")
    _run_git(project, env, "config", "user.name", "Mae Flow Diff")
    _run_git(
        project, env, "config", "user.email", "diff@example.invalid")
    _run_git(project, env, "config", "core.autocrlf", "false")
    with open(os.path.join(project, "README.md"), "w", encoding="utf-8",
              newline="\n") as stream:
        stream.write("# Differential Fixture\n")
    _run_git(project, env, "add", "--", "README.md")
    _run_git(
        project,
        env,
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-qm",
        "fixture",
    )
    return env


def inactive_pretooluse_bypass(project, implementation_root):
    env = _prepare_repository(project)
    payload = {
        "cwd": project,
        "tool_name": "Edit",
        "tool_input": {
            "file_path": os.path.join(project, "README.md"),
        },
    }
    return {
        "argv": [
            sys.executable,
            os.path.join(implementation_root, "hooks", "dispatch.py"),
            "pretooluse",
        ],
        "stdin": json.dumps(payload, ensure_ascii=False) + "\n",
        "env": env,
    }, {}


def terminal_status(project, implementation_root):
    env = _prepare_repository(project)
    state = {
        "schema_version": 2,
        "revision": 1,
        "updated_at": "2026-07-29 10:00:00",
        "current": "end",
        "config": {"单号": "REQ-DIFF", "分支名": "main"},
        "choices": {"workflow": "tweak"},
        "history": [],
        "started": "2026-07-29 10:00:00",
    }
    with open(
            os.path.join(project, ".mae-flow.json"),
            "w",
            encoding="utf-8",
            newline="\n") as stream:
        json.dump(
            state,
            stream,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        stream.write("\n")
    return {
        "argv": [
            sys.executable,
            os.path.join(
                implementation_root, "scripts", "mae-flow.py"),
            "status",
        ],
        "stdin": "",
        "env": env,
    }, {}


def corrupt_state_doctor(project, implementation_root):
    env = _prepare_repository(project)
    with open(os.path.join(project, ".mae-flow.json"), "wb") as stream:
        stream.write(b"{broken")
    return {
        "argv": [
            sys.executable,
            os.path.join(
                implementation_root, "scripts", "mae-flow.py"),
            "doctor",
        ],
        "stdin": "",
        "env": env,
    }, {}


def workflow_steps(project, implementation_root):
    env = _prepare_repository(project)
    return {
        "argv": [
            sys.executable,
            os.path.join(
                implementation_root, "scripts", "mae-flow.py"),
            "steps",
        ],
        "stdin": "",
        "env": env,
    }, {}


def ordinary_advance(project, implementation_root):
    env = _prepare_repository(project)
    state = {
        "schema_version": 2,
        "revision": 1,
        "updated_at": "2026-07-29 10:00:00",
        "current": "rf_verify",
        "config": {
            "单号": "REQ-DIFF",
            "分支名": "",
        },
        "choices": {"workflow": "tweak"},
        "history": [],
        "started": "2026-07-29 10:00:00",
    }
    with open(
            os.path.join(project, ".mae-flow.json"),
            "w",
            encoding="utf-8",
            newline="\n") as stream:
        json.dump(
            state,
            stream,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        stream.write("\n")

    script = os.path.join(
        implementation_root,
        "scripts",
        "mae-flow.py",
    )
    fixed_time_runner = (
        "import os,runpy,sys,time;"
        "path=sys.argv[1];"
        "sys.path.insert(0,os.path.dirname(path));"
        "time.strftime=lambda *_args:'2026-07-29 10:00:00';"
        "sys.argv=[path,'done'];"
        "runpy.run_path(path,run_name='__main__')"
    )
    return {
        "argv": [
            sys.executable,
            "-c",
            fixed_time_runner,
            script,
        ],
        "stdin": "",
        "env": env,
    }, {}


SCENARIOS = {
    "inactive_pretooluse_bypass": inactive_pretooluse_bypass,
    "terminal_status": terminal_status,
    "corrupt_state_doctor": corrupt_state_doctor,
    "workflow_steps": workflow_steps,
    "ordinary_advance": ordinary_advance,
}
