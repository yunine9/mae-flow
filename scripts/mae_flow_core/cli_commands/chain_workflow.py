"""Production CLI adapter for the recoverable cross-repository Chain."""

from dataclasses import replace
import hashlib
import json
import ntpath
import os
import posixpath
import sys
import time

from mae_flow_core.orchestration import (
    ChainRequest,
    ChainState,
    advance_chain,
    decode_chain_state,
    encode_chain_state,
)
from mae_flow_core.orchestration.documents import DocumentPaths
from mae_flow_core.orchestration.state_schema import decode_flow_state
from mae_flow_core.state_store import (
    ProjectStateLock,
    atomic_write_json,
    remove_with_retry,
    safe_read_json,
)
from .user_events import bind_user_event, matching_user_event


POINTER_RELATIVE = ".mae-flow-work/chain-current.json"


def _die(message):
    print("[mae-flow] " + message, file=sys.stderr)
    raise SystemExit(2)


def _run(command):
    try:
        return command()
    except SystemExit:
        raise
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        _die(str(exc))


def _pointer_path(root):
    return os.path.join(root, *POINTER_RELATIVE.split("/"))


def _relative_path(root, value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s不能为空" % label)
    raw = value.strip().replace("\\", "/")
    if raw.startswith("/") or ntpath.splitdrive(raw)[0]:
        raise ValueError("%s必须是仓库内相对路径" % label)
    normalized = posixpath.normpath(raw)
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        raise ValueError("%s包含越界路径" % label)
    absolute = os.path.abspath(os.path.join(root, *normalized.split("/")))
    try:
        inside = os.path.commonpath((os.path.abspath(root), absolute))
    except ValueError as exc:
        raise ValueError("%s无法解析" % label) from exc
    if inside != os.path.abspath(root):
        raise ValueError("%s越出锚点仓库" % label)
    return normalized, absolute


def _read_pointer(root, required=True):
    path = _pointer_path(root)
    raw, error = safe_read_json(path)
    if error:
        raise ValueError("Chain 指针不可读: %s" % error)
    if raw is None:
        if required:
            raise ValueError("没有活动 Chain；先执行 chain start")
        return None, None
    if (not isinstance(raw, dict)
            or set(raw) != {"schema_version", "state"}
            or raw.get("schema_version") != 1):
        raise ValueError("Chain 指针格式无效")
    relative, absolute = _relative_path(root, raw.get("state"), "Chain 指针")
    if (not relative.startswith(".mae-flow-work/")
            or not relative.endswith("/chain-state.json")):
        raise ValueError("Chain 指针目标不受支持")
    return relative, absolute


def _read_state(root):
    unused_relative, path = _read_pointer(root)
    raw, error = safe_read_json(path)
    if error:
        raise ValueError("Chain 状态不可读: %s" % error)
    if raw is None:
        raise ValueError("Chain 状态缺失；拒绝扫描猜测恢复路径")
    state = decode_chain_state(raw)
    if os.path.realpath(state.anchor_root) != os.path.realpath(root):
        raise ValueError("Chain 状态不属于当前锚点仓库")
    return path, state


def load_active_chain(root):
    """Resolve the single exact Chain pointer for Hook recovery."""
    return _read_state(root)


def _active_flow(root):
    raw, error = safe_read_json(os.path.join(root, ".mae-flow.json"))
    if error:
        raise ValueError("现有交付状态不可读，拒绝启动 Chain: %s" % error)
    if raw is None:
        return False
    try:
        return decode_flow_state(raw).status == "active"
    except (TypeError, ValueError) as exc:
        raise ValueError("现有交付状态无效，拒绝启动 Chain: %s" % exc)


def _render(state, reason):
    if reason:
        print("[mae-flow] " + reason)
    print("Chain 工单: %s" % state.ticket)
    print("状态: %s" % state.status)
    print("需求来源: %s" % state.requirement_source)
    print("Chain 文档: %s" % state.document_path)
    print(
        "Chain 模板: "
        ".mae-flow-work/plugin-resources/assets/CHAIN-TEMPLATE.md")
    counts = {}
    for item in state.records:
        counts[item.kind] = counts.get(item.kind, 0) + 1
    if counts:
        print("记录: " + ", ".join(
            "%s=%s" % item for item in sorted(counts.items())))


def _mutate_with(root, operation):
    with ProjectStateLock(root):
        path, state = _read_state(root)
        result = operation(state, path)
        if result.state == state:
            raise ValueError(result.reason)
        atomic_write_json(path, encode_chain_state(result.state))
    return result.state, result.reason


def _mutate(root, request):
    return _mutate_with(
        root, lambda state, unused_path: advance_chain(state, request))


def _question_request(args):
    legacy_value = getattr(args, "value", "")
    fields = {
        name: getattr(args, name, None)
        for name in ("parent", "evidence", "impact", "recommendation")
    }
    supplied = any(value is not None for value in fields.values())
    if not supplied:
        if not legacy_value.strip():
            raise ValueError(
                "Chain question 需要 --evidence/--impact/--recommendation")
        return ChainRequest("question", args.key, legacy_value)
    if legacy_value.strip():
        raise ValueError("Chain question 不能同时使用 --value 和显式元数据")
    missing = [
        name for name in ("evidence", "impact", "recommendation")
        if not isinstance(fields[name], str) or not fields[name].strip()
    ]
    if missing:
        raise ValueError(
            "Chain question 缺少非空参数: "
            + ", ".join("--" + name for name in missing))
    parent = (fields["parent"] or "ROOT").strip()
    value = {
        "parent": "" if parent.casefold() == "root" else parent,
        "evidence": fields["evidence"].strip(),
        "impact": fields["impact"].strip(),
        "recommendation": fields["recommendation"].strip(),
    }
    return ChainRequest(
        "question", args.key,
        json.dumps(
            value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":")))


def _answer(root, args):
    fields_supplied = any(
        getattr(args, name, None) is not None
        for name in ("parent", "evidence", "impact", "recommendation"))
    question = _question_request(args) if fields_supplied else None

    def operation(state, path):
        event_id = matching_user_event(root, state, state_path=path)
        current = state
        if question is not None:
            opened = advance_chain(current, question)
            if opened.state == current:
                raise ValueError(opened.reason)
            current = opened.state
        result = advance_chain(
            current, ChainRequest("answer", args.key, args.text))
        if result.state == current:
            raise ValueError(result.reason)
        return replace(
            result,
            state=bind_user_event(result.state, event_id, "chain-answer"),
        )
    return _mutate_with(root, operation)


def _start(root, args):
    with ProjectStateLock(root):
        if _active_flow(root):
            raise ValueError("活动 Mae-Flow 交付已占用锚点仓库")
        pointer_relative, pointer_state = _read_pointer(root, required=False)
        if pointer_relative is not None:
            raw, error = safe_read_json(pointer_state)
            if error or raw is None:
                raise ValueError("现有 Chain 状态不可恢复，拒绝覆盖")
            existing = decode_chain_state(raw)
            if existing.status == "active":
                raise ValueError("活动 Chain 已存在；请使用 chain current")
            raise ValueError("Chain 指针仍存在；请先检查或退出")
        paths = DocumentPaths.for_ticket(root, args.ticket)
        state_relative = ".mae-flow-work/%s/chain-state.json" % paths.safe_ticket
        unused_relative, state_path = _relative_path(
            root, state_relative, "Chain 状态路径")
        if os.path.exists(state_path):
            raise ValueError("该工单已有未归档 Chain 状态，拒绝覆盖")
        document_relative = os.path.relpath(paths.local_chain, root).replace(
            "\\", "/")
        state = ChainState(
            ticket=args.ticket.strip(),
            request=args.request.strip(),
            requirement_source=args.requirement.strip(),
            anchor_root=os.path.abspath(root),
            document_path=document_relative,
        )
        atomic_write_json(state_path, encode_chain_state(state))
        atomic_write_json(_pointer_path(root), {
            "schema_version": 1,
            "state": state_relative,
        })
    return state, "Cross-repository Chain started."


def _repository_roots(root, state):
    result = {}
    for item in state.records:
        if item.kind != "repository":
            continue
        value = json.loads(item.value)
        raw = value["path"]
        candidate = raw if os.path.isabs(raw) else os.path.join(root, raw)
        absolute = os.path.abspath(candidate)
        if not os.path.isdir(absolute):
            raise ValueError("仓库路径不存在: %s" % raw)
        result[item.key] = absolute
    return result


def _citation_facts(root, state):
    repositories = _repository_roots(root, state)
    facts = []
    for item in state.records:
        if item.kind != "touchpoint":
            continue
        value = json.loads(item.value)
        repository = repositories.get(value["repository"])
        if repository is None:
            raise ValueError("触点引用未知仓库: %s" % value["repository"])
        unused_relative, path = _relative_path(
            repository, value["file"], "触点文件")
        if not os.path.isfile(path):
            raise ValueError("触点文件不存在: %s" % value["file"])
        with open(path, "rb") as stream:
            content = stream.read()
        text = content.decode("utf-8", errors="replace")
        if value["symbol"] not in text:
            raise ValueError(
                "触点符号不存在: %s:%s" % (value["file"], value["symbol"]))
        facts.append({
            "key": item.key,
            "repository": value["repository"],
            "file": value["file"].replace("\\", "/"),
            "symbol": value["symbol"],
            "content_sha256": hashlib.sha256(content).hexdigest(),
        })
    encoded = json.dumps(
        facts, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")
    return len(facts), hashlib.sha256(encoded).hexdigest()


def _verify(root):
    def operation(state, unused_path):
        count, digest = _citation_facts(root, state)
        return advance_chain(state, ChainRequest(
            "citations-verified",
            value=json.dumps({"count": count, "digest": digest}),
        ))
    return _mutate_with(root, operation)


def _document_digest(root, state):
    unused_relative, path = _relative_path(
        root, state.document_path, "Chain 文档路径")
    if not os.path.isfile(path):
        raise ValueError("Chain 文档尚未生成")
    with open(path, "rb") as stream:
        content = stream.read()
    if not content.strip():
        raise ValueError("Chain 文档不能为空")
    return hashlib.sha256(content).hexdigest()


def _latest_value(state, kind):
    values = [
        json.loads(item.value) for item in state.records if item.kind == kind
    ]
    return values[-1] if values else {}


def _confirm(root, text):
    def operation(state, path):
        count, digest = _citation_facts(root, state)
        if _latest_value(state, "citations-verified") != {
                "count": count, "digest": digest}:
            raise ValueError("仓库引用在校验后发生变化；请重新执行 chain verify")
        if _latest_value(state, "rendered").get(
                "sha256") != _document_digest(root, state):
            raise ValueError("Chain 文档在摘要后发生变化；请重新执行 chain rendered")
        event_id = matching_user_event(root, state, state_path=path)
        result = advance_chain(state, ChainRequest("confirmed", value=text))
        if result.state == state:
            return result
        return replace(
            result,
            state=bind_user_event(result.state, event_id, "chain-confirmed"),
        )
    return _mutate_with(root, operation)


def _rendered(root):
    def operation(state, unused_path):
        return advance_chain(state, ChainRequest(
            "rendered", value=json.dumps({
                "sha256": _document_digest(root, state),
            })))
    return _mutate_with(root, operation)


def _exit(root, reason):
    with ProjectStateLock(root):
        state_path, state = _read_state(root)
        result = advance_chain(state, ChainRequest("exit"))
        exited = replace(
            result.state,
            decisions=result.state.decisions + ((
                "chain.exit.reason", reason.strip()),),
        )
        atomic_write_json(state_path, encode_chain_state(exited))
        archive_dir = os.path.join(root, ".mae-flow-work", "chain-exited")
        os.makedirs(archive_dir, exist_ok=True)
        archive = os.path.join(
            archive_dir,
            "%s-%s.json" % (
                os.path.basename(os.path.dirname(state_path)), time.time_ns()),
        )
        os.replace(state_path, archive)
        remove_with_retry(_pointer_path(root))
    return exited, "Chain exited and its state was archived locally."


def cmd_lean_chain(root, args):
    def execute():
        action = args.chain_cmd
        if action == "start":
            state, reason = _start(root, args)
        elif action == "current":
            unused_path, state = _read_state(root)
            reason = "Current Chain recovery context."
        elif action == "record":
            state, reason = _mutate(
                root, ChainRequest(args.kind, args.key, args.value))
        elif action == "question":
            state, reason = _mutate(root, _question_request(args))
        elif action == "answer":
            state, reason = _answer(root, args)
        elif action == "verify":
            state, reason = _verify(root)
        elif action == "rendered":
            state, reason = _rendered(root)
        elif action == "confirm":
            state, reason = _confirm(root, args.text)
        elif action == "exit":
            state, reason = _exit(root, args.reason)
        else:  # pragma: no cover - argparse closes this branch.
            raise ValueError("未知 Chain 动作")
        _render(state, reason)
    return _run(execute)
