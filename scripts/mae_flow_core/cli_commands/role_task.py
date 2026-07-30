"""CLI adapter for scoped Spec2Code role task cards."""

import re

from mae_flow_core.application.quality.role_task_documents import (
    ArtifactRef,
    build_role_task_document,
)
from mae_flow_core.application.quality.task_cards import (
    TaskCardStorePorts,
    store_task_card,
)
from mae_flow_core.quality.role_tasks import role_allowed

from .shared import os, read_text, time, write_text
from .wiring import api


def _artifact_refs(state):
    refs = {}
    for kind, record in (state.get("spec2code") or {}).items():
        if (
            isinstance(record, dict)
            and record.get("path")
            and record.get("sha256")
        ):
            refs[kind] = ArtifactRef(
                os.path.abspath(record["path"]),
                str(record["sha256"]),
            )
    return refs


def _plan_files(state, checkpoint):
    record = (state.get("spec2code") or {}).get("plan") or {}
    path = str(record.get("path", "") or "")
    if not path or not os.path.isfile(path):
        return ()
    text = read_text(path, errors="replace")
    blocks = re.split(r"(?m)^##\s+Task\s+", text)[1:]
    files = []
    for block in blocks:
        cp_match = re.search(
            r"(?m)^-\s*所属 CP[：:]\s*(CP[1-6])", block)
        if checkpoint and (
            not cp_match or cp_match.group(1) != checkpoint
        ):
            continue
        match = re.search(
            r"(?m)^-\s*创建/修改文件[：:]\s*(.+?)\s*$", block)
        if not match:
            continue
        for value in re.split(r"[、,，]", match.group(1).rstrip("。")):
            value = value.strip().strip("`")
            if value and value not in files:
                files.append(value)
    return tuple(files)


def _role_diff(state, role):
    if role != "craft-code":
        return ""
    item = api._checkpoint_current(state) or {}
    base = str(item.get("fixed_base", "") or "")
    return (base + "..HEAD") if base else "HEAD"


def cmd_role_task(_flow, state, args):
    role = args.role
    step = str(state.get("current", "") or "")
    if not role_allowed(role, step):
        api.die(
            "当前步骤 %s 不允许生成 %s 角色任务卡。"
            % (step or "(空)", role),
            2,
        )
    checkpoint = str(args.checkpoint or "")
    if role != "test-design" and not checkpoint:
        api.die("%s 任务卡必须指定 --checkpoint CPn。" % role, 2)
    item = api._checkpoint_current(state) or {}
    expected_status = {
        "task-analysis": "planned",
        "craft-plan": "planned",
        "cp-implement": "coding",
        "craft-code": "craft_pending",
    }.get(role)
    if expected_status and step == "build" and (
        item.get("id") != checkpoint
        or item.get("status") != expected_status
    ):
        api.die(
            "%s 只允许用于当前 %s 状态的 %s；当前为 %s@%s。"
            % (
                role,
                expected_status,
                checkpoint,
                item.get("id", "无"),
                item.get("status", "无"),
            ),
            2,
        )
    document = build_role_task_document(
        role=role,
        project_root=os.path.abspath(os.getcwd()),
        ticket=str((state.get("config") or {}).get("单号", "") or ""),
        checkpoint=checkpoint,
        artifacts=_artifact_refs(state),
        files=_plan_files(state, checkpoint),
        diff=_role_diff(state, role),
    )
    suffix = ("-" + checkpoint.lower()) if checkpoint else ""
    artifact = store_task_card(
        document,
        os.path.join(".mae-flow-work", "role-tasks"),
        "%s-%s%s.md" % (step, role, suffix),
        TaskCardStorePorts(
            absolute=os.path.abspath,
            make_directory=lambda path: os.makedirs(path, exist_ok=True),
            write_text=lambda path, body: write_text(
                path, body, encoding="utf-8"),
        ),
    )
    state.setdefault("role_tasks", {})[role] = {
        "step": step,
        "checkpoint": checkpoint,
        "path": artifact.path,
        "sha256": artifact.digest,
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    api.save_state(state)
    print("[mae-flow] %s 角色任务卡已生成: %s" % (role, artifact.path))
    print(
        '启动新鲜角色 Agent 时只传：读取并严格执行任务卡 "%s"；'
        "最终报告原样带 TASK_CARD_SHA256: %s"
        % (artifact.path, artifact.digest)
    )
