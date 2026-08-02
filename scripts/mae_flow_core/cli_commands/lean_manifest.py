"""Exact-manifest preparation for the lean production CLI."""

from dataclasses import replace
import re

from mae_flow_core.foundation.commit_message import valid_business_commit_message
from mae_flow_core.foundation.source_paths import is_flow_control_path
from mae_flow_core.guard.manifest import DeliveryManifest, authorize_delivery
from mae_flow_core.orchestration.documents import conditional_document_kind
from mae_flow_core.orchestration.models import CommitPace, Phase


_CONDITIONAL_DECISION = "delivery.conditional_document"
_DELIVERY_BINDING_KEYS = {
    "delivery.confirmation",
    "delivery.confirmed_file",
    "delivery.receipt",
    "delivery.result",
    "delivery.git.commit_observation",
    "delivery.git.push_observation",
}
_STAGED_FINAL_FILE = "delivery.staged_final_file"
_TARGET_FACTS = {
    "delivery.plan.remote",
    "delivery.plan.destination_ref",
    "delivery.plan.expected_destination_sha",
    "delivery.plan.new_branch",
}


def _identity(files):
    return {path.replace("\\", "/").casefold() for path in files}


def _validate_files(files):
    for path in files:
        if is_flow_control_path(path):
            raise ValueError(
                "交付清单不能包含 Mae-Flow 控制文件")


def _adoption_requests(entries, root):
    paths = []
    reasons = []
    for entry in entries:
        if "=" not in entry:
            raise ValueError("--adopt-dirty 需要 FILE=自然语言归属决定")
        path, decision = entry.split("=", 1)
        decision = decision.strip()
        if not decision:
            raise ValueError("启动时脏文件的归属决定不能为空")
        normalized = DeliveryManifest.from_paths(
            (path,), repository_root=root).files[0]
        paths.append(normalized)
        reasons.append((normalized, decision))
    return tuple(paths), tuple(reasons)


def _require_initial_dirty_ownership(state, manifest):
    initial = _identity(DeliveryManifest.from_paths(state.initial_dirty).files)
    included = initial & _identity(manifest.files)
    adopted = _identity(manifest.adopted_dirty)
    missing = tuple(
        path for path in manifest.files
        if path.replace("\\", "/").casefold() in included - adopted)
    if missing:
        raise ValueError(
            "交付中的启动时脏文件需要逐文件自然语言归属决定: %s"
            % ", ".join(missing))


def _conditional_decisions(state, selected, files):
    file_ids = _identity(files)
    selected_ids = []
    decisions = tuple(
        item for item in state.decisions
        if item[0] != _CONDITIONAL_DECISION)
    for path in selected:
        normalized = path.replace("\\", "/")
        if normalized.casefold() not in file_ids:
            raise ValueError("条件文档必须同时出现在精确交付清单中")
        if not conditional_document_kind(normalized):
            raise ValueError("--conditional-document 只接受需求目录下的条件文档")
        selected_ids.append(normalized.casefold())
        decisions += ((_CONDITIONAL_DECISION, normalized),)
    missing = tuple(
        path for path in files
        if (conditional_document_kind(path)
            and path.replace("\\", "/").casefold() not in selected_ids))
    if missing:
        raise ValueError(
            "交付清单中的每个条件文档都需要本次独立选择: %s"
            % ", ".join(missing))
    return decisions


def _checkpoint_prefix(checkpoint):
    if (not isinstance(checkpoint, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]+", checkpoint)):
        raise ValueError("checkpoint 必须是字母、数字、下划线或短横线")
    return "delivery.cp.%s." % checkpoint


def _record_checkpoint(state, manifest, args):
    prefix = _checkpoint_prefix(args.checkpoint)
    if state.phase != Phase.CONSTRUCTION or state.current_cp != args.checkpoint:
        raise ValueError("Staged manifest 只能记录当前 CP 的精确文件")
    message = (args.commit_message or "").strip()
    if not valid_business_commit_message(state.ticket, message):
        raise ValueError("CP commit message 必须是 [单号][feat|fix]描述")
    if args.decision:
        raise ValueError("CP manifest 只声明计划；请另用 decision 确认")
    decisions = tuple(
        item for item in state.decisions
        if not item[0].startswith(prefix) and item[0] != _STAGED_FINAL_FILE)
    decisions += tuple((prefix + "file", path) for path in manifest.files)
    decisions += ((prefix + "message", message),)
    return replace(state, decisions=decisions, current_cp=args.checkpoint)


def _checkpoint_union(state):
    files = []
    identities = set()
    for key, value in state.decisions:
        if key.startswith("delivery.cp.") and key.endswith(".file"):
            identity = value.replace("\\", "/").casefold()
            if identity not in identities:
                files.append(value)
                identities.add(identity)
    return tuple(files)


def _staged_state(state, manifest, args, root):
    checkpoint = bool(args.checkpoint)
    final = bool(args.final)
    if checkpoint == final:
        raise ValueError(
            "Staged manifest 必须二选一: --checkpoint <CP> 或 --final")
    if checkpoint:
        if any((args.remote, args.destination_ref,
                args.expected_destination_sha, args.new_branch)):
            raise ValueError("CP 本地提交不能声明最终 push 目标")
        return _record_checkpoint(state, manifest, args)
    expected = DeliveryManifest.from_paths(
        _checkpoint_union(state), repository_root=root).files
    if not expected or _identity(expected) != _identity(manifest.files):
        raise ValueError("最终 manifest 必须等于所有已确认 CP manifest 的累计 union")
    if args.commit_message or args.decision:
        raise ValueError("最终累计 manifest 不创建额外本地 commit")
    decisions = tuple(
        item for item in state.decisions if item[0] != _STAGED_FINAL_FILE)
    decisions += tuple(
        (_STAGED_FINAL_FILE, path) for path in manifest.files)
    return replace(state, decisions=decisions)


def _invalidate_delivery_binding(state, manifest):
    return replace(
        state,
        decisions=tuple(
            item for item in state.decisions
            if item[0] not in _DELIVERY_BINDING_KEYS),
    )


def _record_continuous_message(state, args, has_target):
    decisions = tuple(
        item for item in state.decisions
        if item[0] != "delivery.commit_message")
    message = (args.commit_message or "").strip()
    if message and not valid_business_commit_message(state.ticket, message):
        raise ValueError("commit message 必须是 [单号][feat|fix]描述")
    if has_target and not message:
        raise ValueError("Git delivery requires one exact commit message")
    if message:
        decisions += (("delivery.commit_message", message),)
    return replace(state, decisions=decisions)


def _record_target(state, args):
    supplied = any((
        args.remote, args.destination_ref, args.expected_destination_sha,
        args.new_branch,
    ))
    decisions = tuple(
        item for item in state.decisions if item[0] not in _TARGET_FACTS)
    if not supplied:
        return replace(state, decisions=decisions), False
    remote = (args.remote or "").strip()
    destination = (args.destination_ref or "").strip()
    expected = (args.expected_destination_sha or "").strip().casefold()
    if not re.fullmatch(r"[A-Za-z0-9._-]+", remote):
        raise ValueError("remote 必须是一个显式安全名称")
    if (not destination.startswith("refs/heads/")
            or not re.fullmatch(r"refs/heads/[A-Za-z0-9._/-]+", destination)
            or ".." in destination or destination.endswith("/")):
        raise ValueError("destination ref 必须是显式 refs/heads/... 引用")
    if args.new_branch:
        if expected:
            raise ValueError("新分支的 expected destination SHA 必须为空")
    elif not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise ValueError("已有分支需要 40 位 expected destination SHA")
    decisions += (
        ("delivery.plan.remote", remote),
        ("delivery.plan.destination_ref", destination),
        ("delivery.plan.expected_destination_sha", expected),
        ("delivery.plan.new_branch", "true" if args.new_branch else "false"),
    )
    return replace(state, decisions=decisions), True


def prepare_manifest_state(state, args, root):
    """Validate and store one exact manifest without irreversible effects."""
    adopted_dirty, adoption_reasons = _adoption_requests(
        args.adopt_dirty, root)
    manifest = DeliveryManifest.from_paths(
        args.file, adopted_dirty=adopted_dirty, repository_root=root)
    _validate_files(manifest.files)
    _require_initial_dirty_ownership(state, manifest)
    state = _invalidate_delivery_binding(state, manifest)
    if state.commit_pace == CommitPace.STAGED:
        state = _staged_state(state, manifest, args, root)
    elif (args.checkpoint or args.final
          or (args.decision and not args.moonlight_refresh)):
        raise ValueError("Continuous 只记录一次最终精确 manifest")
    state, has_target = _record_target(state, args)
    if state.commit_pace == CommitPace.CONTINUOUS:
        state = _record_continuous_message(state, args, has_target)
    updated = authorize_delivery(state, manifest)
    decisions = tuple(
        item for item in updated.decisions
        if item[0] != "delivery.adopted_dirty_reason")
    decisions += tuple((
        "delivery.adopted_dirty_reason",
        "%s\t%s" % (path, decision),
    ) for path, decision in adoption_reasons)
    updated = replace(updated, decisions=decisions)
    return replace(
        updated,
        decisions=_conditional_decisions(
            updated, args.conditional_document, manifest.files),
    ), manifest
