"""Human-readable, exact delivery manifest commands for the stable flow."""

import copy
import shlex

from mae_flow_core.guard.manifest import (
    DeliveryManifest,
    validate_delivery_document_boundary,
)
from mae_flow_core.workflow.command_catalog import render_display

from .shared import os
from .wiring import api


def _identity(path):
    return str(path).replace("\\", "/").casefold()


def _adoption_decisions(values, repository_root):
    decisions = {}
    for value in values or ():
        if "=" not in value:
            raise ValueError(
                "--adopt-dirty 必须使用 精确路径=用户自然语言决定")
        path, decision = value.split("=", 1)
        normalized = DeliveryManifest.from_paths(
            [path], repository_root=repository_root).files[0]
        decision = decision.strip()
        if len(decision) < 2:
            raise ValueError("启动时已有修改必须附带明确的用户自然语言决定")
        decisions[normalized] = decision
    return decisions


def build_delivery_manifest(
        state, files, message, target, adoption_values=(),
        candidate_paths=(), repository_root=None):
    """Build a stable manifest while preserving an unchanged confirmation."""
    root = os.path.abspath(repository_root or os.getcwd())
    exact = DeliveryManifest.from_paths(files, repository_root=root)
    if not exact.files:
        raise ValueError("交付清单至少需要一个精确文件")
    message = str(message or "").strip()
    target = str(target or "").strip()
    if not message:
        raise ValueError("交付清单缺少提交说明")
    if not target:
        raise ValueError("交付清单缺少目标分支")
    archive = (state or {}).get("domain_archive") or {}
    archive_paths = (
        archive.get("applied_paths") or ()
        if archive.get("status") == "applied" else ())
    validate_delivery_document_boundary(exact.files, archive_paths)

    candidates = {_identity(path) for path in candidate_paths}
    outside = [path for path in exact.files if _identity(path) not in candidates]
    if outside:
        raise ValueError("文件不在当前候选增量: " + "、".join(outside))

    adopted = _adoption_decisions(adoption_values, root)
    initial = {
        _identity(path): str(path).replace("\\", "/")
        for path in (state or {}).get("initial_dirty", ())
    }
    selected = {_identity(path): path for path in exact.files}
    adopted_ids = {_identity(path) for path in adopted}
    missing_adoption = [
        selected[identity] for identity in selected
        if identity in initial and identity not in adopted_ids
    ]
    if missing_adoption:
        raise ValueError(
            "启动时已有修改必须逐文件记录用户决定: "
            + "、".join(missing_adoption))
    outside_adoption = [
        path for path in adopted if _identity(path) not in selected
    ]
    if outside_adoption:
        raise ValueError("采用决定不属于交付文件: " + "、".join(outside_adoption))

    candidate = {
        "files": sorted(exact.files, key=str.casefold),
        "commit_message": message,
        "target_branch": target,
        "adopted_dirty": {
            path: adopted[path] for path in sorted(adopted, key=str.casefold)
        },
        "confirmed": False,
    }
    previous = (state or {}).get("delivery_manifest") or {}
    comparable = dict(candidate)
    comparable.pop("confirmed")
    old_comparable = dict(previous)
    old_confirmed = bool(old_comparable.pop("confirmed", False))
    if comparable == old_comparable and old_confirmed:
        candidate["confirmed"] = True
    return candidate


def confirm_delivery_manifest(state, message_id, command_api=api):
    manifest = (state or {}).get("delivery_manifest") or {}
    if not manifest.get("files"):
        raise ValueError("尚未生成交付清单，请先执行 manifest set")
    if manifest.get("confirmed") is True:
        return state
    ok, answer, _receipt, error = command_api._authorization_message(
        state, message_id)
    if not ok:
        raise ValueError(error)
    if not str(answer or "").strip():
        raise ValueError("用户确认内容为空")
    updated = copy.deepcopy(state)
    updated["delivery_manifest"]["confirmed"] = True
    return updated


def _current_candidates(files):
    command = "git add -- " + " ".join(shlex.quote(path) for path in files)
    return tuple(api._pending_commit_candidates(command).get("paths", ()))


def _print_manifest(manifest):
    print("[mae-flow] 精确交付清单")
    print("目标分支: " + str(manifest.get("target_branch", "")))
    print("提交说明: " + str(manifest.get("commit_message", "")))
    print("用户确认: " + ("已确认" if manifest.get("confirmed") else "待确认"))
    print("文件:")
    for path in manifest.get("files", ()):
        print("- " + path)
    adopted = manifest.get("adopted_dirty") or {}
    if adopted:
        print("启动时已有修改的采用决定:")
        for path, decision in adopted.items():
            print("- %s: %s" % (path, decision))


def cmd_delivery_manifest(state, args):
    if state is None:
        api.die("流程未初始化，不能生成交付清单。", 2)
    if args.manifest_action == "show":
        manifest = state.get("delivery_manifest") or {}
        if not manifest:
            api.die("尚未生成交付清单。", 2)
        _print_manifest(manifest)
        return manifest
    if args.manifest_action == "set":
        try:
            manifest = build_delivery_manifest(
                state, args.file, args.message, args.target,
                args.adopt_dirty, _current_candidates(args.file))
        except ValueError as exc:
            api.die(str(exc), 2)
        updated = copy.deepcopy(state)
        updated["delivery_manifest"] = manifest
        api.save_state(updated)
        _print_manifest(manifest)
        if not manifest["confirmed"]:
            print("下一步: 请向用户展示以上清单；收到回答后执行 "
                  + render_display("messages") + "，再执行 "
                  + render_display(
                      "manifest_confirm", {"message_id": "<消息ID>"}) + "。")
        return manifest
    try:
        updated = confirm_delivery_manifest(state, args.message_id)
    except ValueError as exc:
        api.die(str(exc), 2)
    if updated is not state:
        api.save_state(updated)
    print("[mae-flow] 交付清单已由用户确认；只允许暂存并提交上述精确文件。")
    return updated.get("delivery_manifest")
