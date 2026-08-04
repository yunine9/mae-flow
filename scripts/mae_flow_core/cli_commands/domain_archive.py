"""Local candidate and confirmed domain archive commands."""

import copy
import difflib

from .shared import os
from .wiring import api
from mae_flow_core.orchestration.domain_archive import (
    apply_candidates,
    candidate_from_dict,
    initialize_candidate,
    input_digest,
    prepare_candidate,
    require_fresh,
)
from mae_flow_core.orchestration.work_package import ensure_work_package


def _ticket(state):
    value = str(((state or {}).get("config") or {}).get("单号", "")).strip()
    if not value:
        raise ValueError("领域归档缺少需求单号")
    return value


def _package_inputs(package):
    return (package.spec, package.grill, package.story, package.decisions)


def _git_facts():
    return "%s\n%s" % (
        api.sh("git -c core.quotepath=false diff --no-ext-diff --binary HEAD -- ."),
        api.sh("git -c core.quotepath=false status --porcelain --untracked-files=all"),
    )


def _entries(root, record):
    return tuple(candidate_from_dict(root, value) for value in record.get("domains", ()))


def _fresh_digest(root, package, entries):
    return input_digest(root, _package_inputs(package), _git_facts(), entries)


def _show(record, root):
    print("[mae-flow] 领域归档状态: " + str(record.get("status", "未准备")))
    domains = record.get("domains") or ()
    if not domains:
        print("- 结论: unchanged（无需更新领域文档）")
        return
    for value in domains:
        entry = candidate_from_dict(root, value)
        print("- %s: %s -> %s" % (entry.domain, entry.action, entry.target_path))
        target = os.path.join(root, *entry.target_path.split("/"))
        try:
            with open(target, encoding="utf-8") as stream:
                before = stream.read().splitlines(True)
        except OSError:
            before = []
        with open(entry.candidate_path, encoding="utf-8") as stream:
            after = stream.read().splitlines(True)
        for line in difflib.unified_diff(
                before, after, fromfile=entry.target_path,
                tofile=value["candidate_path"]):
            print(line.rstrip("\n"))


def _prepare(state, args, root, package):
    updated = copy.deepcopy(state)
    previous = copy.deepcopy(updated.get("domain_archive") or {})
    if previous.get("status") == "applied":
        raise ValueError("领域归档已经应用，无需重复准备")
    if args.unchanged:
        if previous.get("domains"):
            raise ValueError("已经存在领域候选，不能再声明全部 unchanged")
        record = {
            "status": "prepared", "result": "unchanged", "domains": [],
            "input_sha256": _fresh_digest(root, package, ()),
            "applied_paths": [],
        }
        updated["domain_archive"] = record
        api.save_state(updated)
        _show(record, root)
        return record
    archive_root = os.path.join(package.root, "domain-archive")
    template = os.path.join(
        root, ".mae-flow-work", "plugin-resources", "assets",
        "DOMAIN-SPEC-TEMPLATE.md")
    try:
        with open(template, encoding="utf-8") as stream:
            template_content = stream.read()
    except OSError as exc:
        raise ValueError(
            "领域模板缺失；先重新执行 current 恢复项目本地资源: %s" % exc)
    initialized = initialize_candidate(
        root, archive_root, args.domain, template_content)
    values = list(previous.get("domains") or ())
    if initialized.initialized:
        values = [value for value in values if value.get("domain") != args.domain]
        values.append(initialized.to_dict(root))
        record = {
            "status": "draft", "result": "pending", "domains": values,
            "input_sha256": "", "applied_paths": [],
        }
        updated["domain_archive"] = record
        api.save_state(updated)
        print("[mae-flow] 已初始化领域候选: "
              + os.path.relpath(initialized.candidate_path, root).replace("\\", "/"))
        print("填写长期领域事实后，原样重跑本次 prepare 命令。")
        return record
    prepared = prepare_candidate(
        root, initialized.candidate_path, args.domain, args.keyword)
    values = [value for value in values if value.get("domain") != args.domain]
    values.append(prepared.to_dict(root))
    entries = tuple(candidate_from_dict(root, value) for value in values)
    record = {
        "status": "prepared", "result": "changes", "domains": values,
        "input_sha256": _fresh_digest(root, package, entries),
        "applied_paths": [],
    }
    updated["domain_archive"] = record
    api.save_state(updated)
    _show(record, root)
    return record


def _apply(state, args, root, package):
    record = copy.deepcopy(state.get("domain_archive") or {})
    if record.get("status") == "applied":
        return record
    if record.get("status") != "prepared":
        raise ValueError("领域归档尚未准备完成；执行 domain-archive status 查看恢复动作")
    entries = _entries(root, record)
    require_fresh(
        record.get("input_sha256"), _fresh_digest(root, package, entries))
    ok, answer, receipt, error = api._authorization_message(state, args.message_id)
    if not ok:
        raise ValueError(error)
    if not str(answer or "").strip():
        raise ValueError("用户确认内容为空")
    paths = apply_candidates(root, entries)
    record.update({
        "status": "applied", "applied_paths": list(paths),
        "authorization": receipt,
    })
    updated = copy.deepcopy(state)
    updated["domain_archive"] = record
    api.save_state(updated)
    print("[mae-flow] 领域归档已应用。")
    for path in paths:
        print("- " + path)
    if not paths:
        print("- 无领域文档变化")
    return record


def cmd_domain_archive(state, args):
    if state is None:
        api.die("流程未初始化，不能执行领域归档。", 2)
    root = os.getcwd()
    try:
        package = ensure_work_package(root, _ticket(state))
        if args.domain_archive_action == "prepare":
            return _prepare(state, args, root, package)
        record = state.get("domain_archive") or {}
        if args.domain_archive_action in {"show", "status"}:
            _show(record, root)
            return record
        return _apply(state, args, root, package)
    except (OSError, TypeError, ValueError) as exc:
        api.die("领域归档失败: %s" % exc, 2)
