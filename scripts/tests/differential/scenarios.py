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


def action_status(project, implementation_root):
    env = _prepare_repository(project)
    return {
        "argv": [
            sys.executable,
            os.path.join(
                implementation_root, "scripts", "mae-flow.py"),
            "action",
            "status",
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


def evidence_rejection(project, implementation_root):
    env = _prepare_repository(project)
    state = {
        "schema_version": 2,
        "revision": 1,
        "updated_at": "2026-07-29 10:00:00",
        "current": "rf_triage",
        "config": {
            "单号": "REQ-DIFF",
            "分支名": "",
        },
        "choices": {"workflow": "review"},
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


def _active_gate(project, implementation_root, kind, subject):
    env = _prepare_repository(project)
    state = {
        "schema_version": 2,
        "revision": 1,
        "updated_at": "2026-07-29 10:00:00",
        "current": "build",
        "config": {
            "单号": "REQ-DIFF",
            "分支名": "",
            "CHANGE_NAME": "diff-change",
        },
        "choices": {"workflow": "full"},
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
            "gate",
            kind,
            subject,
        ],
        "stdin": "",
        "env": env,
    }, {}


def active_gate_edit(project, implementation_root):
    return _active_gate(
        project, implementation_root, "edit", "README.md")


def dangerous_gate_bash(project, implementation_root):
    return _active_gate(
        project, implementation_root, "bash", "rm -rf .")


def combined_git_add_flags(project, implementation_root):
    invocation, replacements = _active_gate(
        project,
        implementation_root,
        "bash",
        "git add -fu && git commit -m '[REQ-DIFF][fix]combined flags'",
    )
    with open(
            os.path.join(project, "README.md"),
            "a",
            encoding="utf-8",
            newline="\n") as stream:
        stream.write("tracked update\n")
    script = invocation["argv"][1]
    fixed_time_runner = (
        "import os,runpy,sys,time;"
        "path=sys.argv[1];"
        "sys.path.insert(0,os.path.dirname(path));"
        "time.strftime=lambda *_args:'2026-07-29 10:00:00';"
        "time.monotonic=lambda:0.0;"
        "sys.argv=[path,'gate','bash',sys.argv[2]];"
        "runpy.run_path(path,run_name='__main__')"
    )
    invocation["argv"] = [
        sys.executable,
        "-c",
        fixed_time_runner,
        script,
        "git add -fu && git commit -m '[REQ-DIFF][fix]combined flags'",
    ]
    return invocation, replacements


def compile_task_card(project, implementation_root):
    env = _prepare_repository(project)
    _run_git(project, env, "branch", "baseline")
    os.makedirs(os.path.join(project, "src"))
    with open(
            os.path.join(project, "src", "main.py"),
            "w",
            encoding="utf-8",
            newline="\n") as stream:
        stream.write("def answer():\n    return 42\n")
    _run_git(project, env, "add", "--", "src/main.py")
    _run_git(
        project,
        env,
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-qm",
        "[REQ-DIFF][feat]add source",
    )
    state = {
        "schema_version": 2,
        "revision": 1,
        "updated_at": "2026-07-29 10:00:00",
        "current": "build",
        "config": {
            "单号": "REQ-DIFF",
            "单号类型": "feat",
            "基线分支": "baseline",
            "分支名": "",
            "编译方式": "project command",
            "UT生成方式": "existing",
            "UT运行命令": "python -m unittest",
        },
        "choices": {"workflow": "full"},
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
        "time.monotonic=lambda:0.0;"
        "sys.argv=[path,'agent-task','compile'];"
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


def moonlight_finalize(project, implementation_root):
    env = _prepare_repository(project)
    state = {
        "schema_version": 2,
        "revision": 1,
        "updated_at": "2026-07-29 10:00:00",
        "current": "moonlight_review",
        "config": {
            "单号": "REQ-DIFF",
            "分支名": "",
        },
        "choices": {"workflow": "review"},
        "history": [],
        "moonlight": {
            "enabled": True,
            "cycle": 1,
            "issues": [],
        },
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
        "sys.argv=[path,'moonlight','finalize'];"
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


from differential import stage0_scenarios  # noqa: E402


def direct_current(project, implementation_root):
    return stage0_scenarios.direct_current(
        project, implementation_root, _prepare_repository)


def standalone_action_status(project, implementation_root):
    return stage0_scenarios.standalone_action_status(
        project, implementation_root, _prepare_repository)


def corrupt_exit_repair(project, implementation_root):
    return stage0_scenarios.corrupt_exit_repair(
        project, implementation_root, _prepare_repository)


def terminal_pretooluse_bypass(project, implementation_root):
    return stage0_scenarios.terminal_pretooluse_bypass(
        project, implementation_root, _prepare_repository)


SCENARIOS = {
    "action_status": action_status,
    "active_gate_edit": active_gate_edit,
    "compile_task_card": compile_task_card,
    "combined_git_add_flags": combined_git_add_flags,
    "corrupt_exit_repair": corrupt_exit_repair,
    "dangerous_gate_bash": dangerous_gate_bash,
    "direct_current": direct_current,
    "evidence_rejection": evidence_rejection,
    "inactive_pretooluse_bypass": inactive_pretooluse_bypass,
    "moonlight_finalize": moonlight_finalize,
    "standalone_action_status": standalone_action_status,
    "terminal_status": terminal_status,
    "terminal_pretooluse_bypass": terminal_pretooluse_bypass,
    "corrupt_state_doctor": corrupt_state_doctor,
    "workflow_steps": workflow_steps,
    "ordinary_advance": ordinary_advance,
}
