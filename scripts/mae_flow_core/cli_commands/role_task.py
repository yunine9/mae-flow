"""CLI adapter for scoped Spec2Code role task cards."""

import re

from mae_flow_core.application.quality.role_task_documents import (
    ArtifactRef,
    RoleTaskContext,
    build_role_task_document,
)
from mae_flow_core.quality.spec2code_artifacts import artifact_path
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
            if not value:
                continue
            root = os.path.realpath(os.getcwd())
            absolute = os.path.realpath(value)
            relative = os.path.relpath(absolute, root).replace("\\", "/")
            if (
                relative == ".."
                or relative.startswith("../")
                or relative in files
            ):
                continue
            files.append(relative)
    return tuple(files)


def _existing_context_paths(state, files):
    config = state.get("config") or {}
    ticket = str(config.get("单号", "") or "")
    change = str(config.get("CHANGE_NAME", "") or "")
    spec = state.get("spec") or {}
    candidates = (
        config.get("需求文档", ""),
        os.path.join("openspec", "changes", change, "change.md")
        if change else "",
        spec.get("design_doc", ""),
        os.path.join("docs", "clarifications-%s.md" % ticket),
        os.path.join(".mae-flow-work", "survey-%s.md" % ticket),
        "runtime/standards/comment-standard-v1.md",
        *tuple(files),
    )
    result = []
    for path in candidates:
        value = str(path or "")
        if value and os.path.isfile(value):
            absolute = os.path.abspath(value)
            if absolute not in result:
                result.append(absolute)
    return tuple(result)


def _untracked_bodies(paths):
    untracked = set(api.argv_out([
        "git", "-c", "core.quotepath=false",
        "ls-files", "--others", "--exclude-standard", "--",
        *paths,
    ]).splitlines())
    bodies = []
    for path in paths:
        if path not in untracked or not os.path.isfile(path):
            continue
        try:
            body = read_text(path, encoding="utf-8", errors="replace")
        except OSError:
            body = "（无法读取）"
        bodies.extend([
            "### 未跟踪文件: " + path,
            body[:100000],
        ])
    return bodies


def _role_diff(state, role, plan_files):
    if role != "craft-code":
        return ""
    item = api._checkpoint_current(state) or {}
    base = str(item.get("fixed_base", "") or "")
    receipt = item.get("receipt") or {}
    snapshot = receipt.get("snapshot") or {}
    paths = tuple(snapshot) if isinstance(snapshot, dict) else ()
    paths = paths or tuple(plan_files)
    if not paths:
        return ""
    staged = bool(snapshot)
    command = [
        "git", "-c", "core.quotepath=false", "diff", "--no-ext-diff",
    ]
    command.extend(
        ["HEAD", "--", *paths]
        if staged else [base or "HEAD^", "HEAD", "--", *paths]
    )
    patch = api.argv_out(command)
    if len(patch) > 100000:
        patch = (
            patch[:100000]
            + "\n（补丁超过 100000 字符已截断；"
            "按文件清单 Read 目标文件核对剩余内容）"
        )
    status = api.argv_out([
        "git", "-c", "core.quotepath=false",
        "status", "--short", "--", *paths,
    ])
    body = [
        "文件清单:",
        *("- " + path for path in paths),
        "工作区状态:",
        status or "（已提交范围）",
        "补丁:",
        patch or "（无 tracked patch；检查下方未跟踪文件内容）",
        *_untracked_bodies(paths),
    ]
    return "\n".join(body)


def _review_output(ticket, checkpoint, role):
    if role not in ("craft-plan", "craft-code"):
        return ""
    mode = "plan" if role == "craft-plan" else "code"
    return os.path.abspath(
        artifact_path("review", ticket, checkpoint, mode))


def _review_target_sha(state, role):
    if role == "craft-plan":
        return str(
            ((state.get("spec2code") or {}).get("plan") or {}).get(
                "sha256", "")
            or "")
    if role == "craft-code":
        item = api._checkpoint_current(state) or {}
        return str(item.get("compile_source_sha256", "") or "")
    return ""


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
    ticket = str((state.get("config") or {}).get("单号", "") or "")
    plan_files = _plan_files(state, checkpoint)
    document = build_role_task_document(
        role=role,
        project_root=os.path.abspath(os.getcwd()),
        ticket=ticket,
        checkpoint=checkpoint,
        context=RoleTaskContext(
            artifacts=_artifact_refs(state),
            files=plan_files,
            context_paths=_existing_context_paths(state, plan_files),
            diff=_role_diff(state, role, plan_files),
            review_output=_review_output(ticket, checkpoint, role),
            review_target_sha256=_review_target_sha(state, role),
        ),
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
