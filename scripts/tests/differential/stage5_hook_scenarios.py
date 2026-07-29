"""Characterization scenarios for Hook Agent contract extraction."""

import hashlib
import json
import os
import subprocess

from differential.stage0_scenarios import fixed_hook, flow_state, write_json


def _head(project):
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=True,
    ).stdout.strip()


def _write_task(project, state, kind, **extra):
    body = "# %s fixture task\n" % kind
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    path = os.path.join(
        project, ".mae-flow-work", "tasks", kind.lower() + "-task.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(body)
        stream.write("TASK_CARD_SHA256: " + digest + "\n")
    task = {
        "step": state["current"],
        "head": _head(project),
        "sha256": digest,
        "path": path,
    }
    task.update(extra)
    state.setdefault("agent_tasks", {})[kind] = task
    return task


def _write_transcript(project, name, report, calls=()):
    path = os.path.join(
        project, ".mae-flow-work", "transcripts", name + ".jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows = []
    for index, call in enumerate(calls):
        call_id = "call-%s" % index
        rows.append({
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{
                    "type": "tool_use",
                    "id": call_id,
                    "name": call["name"],
                    "input": call.get("input", {}),
                }],
            },
        })
        rows.append({
            "type": "user",
            "message": {
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": call_id,
                    "is_error": call.get("is_error", False),
                    "content": call.get("result", ""),
                }],
            },
        })
    rows.append({
        "type": "assistant",
        "message": {"role": "assistant", "content": report},
    })
    with open(path, "w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def _subagentstop(
        project, implementation_root, prepare_repository, kind, report,
        calls=(), mutate_task=False, state_updates=None, task_updates=None):
    env = prepare_repository(project)
    state = flow_state("tw_" + kind.lower(), "tweak")
    state["config"].update(state_updates or {})
    task = _write_task(project, state, kind, **(task_updates or {}))
    if mutate_task:
        with open(task["path"], encoding="utf-8") as stream:
            signed = stream.read()
        marker = "TASK_CARD_SHA256:"
        body, digest_line = signed.rsplit(marker, 1)
        with open(
                task["path"], "w", encoding="utf-8", newline="\n") as stream:
            stream.write(body)
            stream.write("tampered before signed marker\n")
            stream.write(marker + digest_line)
    write_json(os.path.join(project, ".mae-flow.json"), state)
    transcript = _write_transcript(
        project, kind.lower(), report % task["sha256"], calls)
    return fixed_hook(
        implementation_root,
        env,
        "subagentstop",
        {
            "cwd": project,
            "agent_transcript_path": transcript,
        },
    )


def hook_compile_missing_execution(
        project, implementation_root, prepare_repository):
    return _subagentstop(
        project,
        implementation_root,
        prepare_repository,
        "COMPILE",
        (
            "COMPILE_RESULT: OK\n"
            "TASK_CARD_SHA256: %s\n"
            "EXECUTED_BUILD: python build.py\n"
            "BUILD_ERRORS: 0"
        ),
        state_updates={"编译方式": "python build.py"},
    )


def hook_ut_zero_tests(project, implementation_root, prepare_repository):
    return _subagentstop(
        project,
        implementation_root,
        prepare_repository,
        "UT",
        (
            "UT_RESULT: PASS\n"
            "TASK_CARD_SHA256: %s\n"
            "GENERATOR_USED: manual\n"
            "EXECUTED_UT: python -m unittest\n"
            "AC_COVERAGE: REQ-1 -> test_fixture\n"
            "TESTS_TOTAL: 0\n"
            "TESTS_PASSED: 0\n"
            "TESTS_FAILED: 0"
        ),
        calls=[{
            "name": "Bash",
            "input": {"command": "python -m unittest"},
            "result": "No tests were found\nexit code: 0",
        }],
        state_updates={
            "UT生成方式": "manual",
            "UT运行命令": "python -m unittest",
        },
    )


def hook_grill_without_read(
        project, implementation_root, prepare_repository):
    return _subagentstop(
        project,
        implementation_root,
        prepare_repository,
        "GRILL",
        (
            "GRILL_RESULT: CLEAR\n"
            "TASK_CARD_SHA256: %s\n"
            "STAGE: design\n"
            "GAPS_FOUND: 0"
        ),
        task_updates={"stage": "design"},
    )


def hook_task_card_tampered(
        project, implementation_root, prepare_repository):
    return _subagentstop(
        project,
        implementation_root,
        prepare_repository,
        "COMPILE",
        (
            "COMPILE_RESULT: OK\n"
            "TASK_CARD_SHA256: %s\n"
            "EXECUTED_BUILD: python build.py\n"
            "BUILD_ERRORS: 0"
        ),
        mutate_task=True,
        state_updates={"编译方式": "python build.py"},
    )


def hook_stop_moonlight_blocks(
        project, implementation_root, prepare_repository):
    env = prepare_repository(project)
    state = flow_state("tw_change", "tweak")
    state["moonlight"] = {
        "enabled": True,
        "cycle": 1,
        "issues": [],
    }
    write_json(os.path.join(project, ".mae-flow.json"), state)
    return fixed_hook(
        implementation_root,
        env,
        "stop",
        {"cwd": project, "stop_hook_active": False},
    )
