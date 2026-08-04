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
from mae_flow_core.orchestration.behavior_baseline import (
    load_relevant_domain_context,
)
from mae_flow_core.orchestration.work_package import ensure_work_package

from .shared import hashlib, os, read_text, time, write_text
from .wiring import api


_REQUIRED_ARTIFACTS = {
    "test-design": (),
    "task-analysis": ("blueprint", "roadmap"),
    "craft-plan": ("blueprint", "roadmap", "plan"),
    "cp-implement": ("blueprint", "roadmap", "plan"),
    "craft-code": ("roadmap", "plan"),
    "story-generate": (),
    "story-review": (),
    "grill-critic": (),
}


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


def _require_artifact_refs(role, refs, story_mode=False):
    if story_mode and role in ("cp-implement", "craft-code"):
        return
    missing = [
        kind for kind in _REQUIRED_ARTIFACTS[role]
        if kind not in refs
    ]
    if missing:
        api.die(
            "%s 角色任务卡缺少已登记过程件: %s。"
            % (role, "、".join(missing)),
            2,
        )


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


def _survey_neighbors(path):
    if not path or not os.path.isfile(path):
        return ()
    text = read_text(path, encoding="utf-8", errors="replace")
    tokens = re.findall(
        r"`([^`\n]+)`|(?<![\w:/])([\w.@+-]+(?:/[\w.@+-]+)+)",
        text,
    )
    result = []
    for pair in tokens:
        value = next((item for item in pair if item), "")
        value = value.rstrip(".,，。:：;；)")
        root = os.path.realpath(os.getcwd())
        absolute = os.path.realpath(value)
        relative = os.path.relpath(absolute, root).replace("\\", "/")
        if (
            value
            and os.path.isfile(absolute)
            and relative != ".."
            and not relative.startswith("../")
            and relative not in result
        ):
            result.append(relative)
    return tuple(result)


def _document_paths(path):
    """Extract repository-local existing or creatable paths from Story."""
    if not path or not os.path.isfile(path):
        return ()
    text = read_text(path, encoding="utf-8", errors="replace")
    tokens = re.findall(
        r"`([^`\n]+)`|(?<![\w:/])([\w.@+-]+(?:/[\w.@+-]+)+)",
        text,
    )
    root = os.path.realpath(os.getcwd())
    result = []
    for pair in tokens:
        value = next((item for item in pair if item), "")
        value = value.rstrip(".,，。:：;；)")
        absolute = os.path.realpath(value)
        relative = os.path.relpath(absolute, root).replace("\\", "/")
        if (
                not value
                or relative == ".."
                or relative.startswith("../")
                or relative.startswith(".mae-flow-work/")
                or relative.startswith("docs/specs/")
                or relative in result
                or not os.path.isdir(os.path.dirname(absolute))):
            continue
        result.append(relative)
    return tuple(result)


def _plain_existing(paths):
    result = []
    for path in paths:
        value = str(path or "")
        if value and os.path.isfile(value):
            absolute = os.path.abspath(value)
            if absolute not in result:
                result.append(absolute)
    return tuple(result)


def _stable_story_context(state, role, document=""):
    config = state.get("config") or {}
    ticket = str(config.get("单号", "") or "")
    package = ensure_work_package(os.getcwd(), ticket)
    survey = os.path.join(package.root, "survey.md")
    terms = []
    for path in (config.get("需求文档", ""), package.spec, package.grill):
        if path and os.path.isfile(path):
            terms.append(read_text(path, encoding="utf-8", errors="replace"))
    domain = load_relevant_domain_context(os.getcwd(), terms)
    domain_paths = [
        os.path.join(os.getcwd(), *item.path.split("/"))
        for item in domain.documents
    ]
    common = [
        config.get("需求文档", ""), package.spec, package.grill,
        package.decisions, survey,
        os.path.join("docs", "specs", "index.md"), *domain_paths,
    ]
    if role in ("story-review", "cp-implement", "craft-code"):
        common.append(package.story)
    if role in ("story-generate", "story-review"):
        common.append(os.path.join(
            ".mae-flow-work", "plugin-resources", "assets",
            "STORY-TEMPLATE.md"))
    if document:
        common.append(document)
    return package, _plain_existing(common)


def _context_ref(path):
    absolute = os.path.abspath(path)
    try:
        with open(path, "rb") as stream:
            digest = hashlib.sha256(stream.read()).hexdigest()
    except OSError:
        return ""
    return "%s | SHA256 %s" % (absolute, digest)


def _existing_context_paths(state, files):
    config = state.get("config") or {}
    ticket = str(config.get("单号", "") or "")
    change = str(config.get("CHANGE_NAME", "") or "")
    spec = state.get("spec") or {}
    package = ensure_work_package(os.getcwd(), ticket)
    survey = os.path.join(package.root, "survey.md")
    candidates = (
        config.get("需求文档", ""),
        package.spec,
        spec.get("design_doc", ""),
        package.decisions,
        survey,
        "runtime/standards/comment-standard-v1.md",
        *_survey_neighbors(survey),
        *tuple(files),
    )
    result = []
    for path in candidates:
        value = str(path or "")
        if value and os.path.isfile(value):
            reference = _context_ref(value)
            if reference and reference not in result:
                result.append(reference)
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


def _write_output(ticket, role):
    kind = {
        "test-design": "blueprint",
        "task-analysis": "plan",
    }.get(role)
    return (
        os.path.abspath(artifact_path(kind, ticket))
        if kind else ""
    )


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
    if role in (
            "task-analysis", "craft-plan", "cp-implement", "craft-code",
    ) and not checkpoint:
        api.die("%s 任务卡必须指定 --checkpoint CPn。" % role, 2)
    if role == "grill-critic":
        checkpoint = str(args.stage or "")
        if not checkpoint or not args.document:
            api.die(
                "grill-critic 必须同时指定 --stage prep|final 和 --document。",
                2,
            )
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
    package = ensure_work_package(os.getcwd(), ticket)
    story_mode = os.path.isfile(package.story)
    plan_files = (
        _document_paths(package.story)
        if story_mode and role in ("cp-implement", "craft-code")
        else _plan_files(state, checkpoint)
    )
    artifact_refs = _artifact_refs(state)
    _require_artifact_refs(role, artifact_refs, story_mode=story_mode)
    if role in ("story-generate", "story-review", "grill-critic") or (
            story_mode and role in ("cp-implement", "craft-code")):
        package, context_paths = _stable_story_context(
            state, role, getattr(args, "document", "") or "")
    else:
        context_paths = _existing_context_paths(state, plan_files)
    document = build_role_task_document(
        role=role,
        project_root=os.path.abspath(os.getcwd()),
        ticket=ticket,
        checkpoint=checkpoint,
        context=RoleTaskContext(
            artifacts=artifact_refs,
            files=plan_files,
            context_paths=context_paths,
            diff=_role_diff(state, role, plan_files),
            review_output=_review_output(ticket, checkpoint, role),
            review_target_sha256=_review_target_sha(state, role),
            write_output=(
                package.story if role == "story-generate"
                else _write_output(ticket, role)
            ),
            lifecycle_only=bool(
                story_mode and role in ("cp-implement", "craft-code")),
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
        "review_target_sha256": _review_target_sha(state, role),
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    agent_kind = {
        "story-generate": "STORY",
        "story-review": "REVIEWER",
        "grill-critic": "GRILL_" + checkpoint.upper(),
        "cp-implement": "CP_IMPLEMENT",
        "craft-code": "REVIEWER",
    }.get(role, "")
    if agent_kind:
        head = api.sh("git rev-parse --verify HEAD")
        precommit_review = role == "craft-code"
        state.setdefault("agent_tasks", {})[agent_kind] = {
            "step": step,
            "checkpoint": checkpoint,
            "stage": checkpoint if role == "grill-critic" else "",
            "path": artifact.path,
            "head": head,
            "precommit_review": precommit_review,
            "source_snapshot": (
                api._source_snapshot_since(head, state, api.FLOW)
                if precommit_review and head else {}
            ),
            "task_files": list(plan_files),
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    api.save_state(state)
    print("[mae-flow] %s 角色任务卡已生成: %s" % (role, artifact.path))
    agent = {
        "story-generate": "story-generator-agent",
        "story-review": "craft-reviewer-agent",
        "grill-critic": "grill-critic-agent",
        "cp-implement": "cp-implementer-agent",
        "craft-code": "craft-reviewer-agent",
    }.get(role, "对应角色 Agent")
    print(
        '启动 %s 时只传：读取并严格执行任务卡 "%s"；'
        "返回内容可以使用任意自然语言格式。" % (agent, artifact.path)
    )
