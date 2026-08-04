"""Non-destructive recovery of an in-flight Lean v3 state into stable v2."""

import hashlib
import json
import os
import re
import sys
import time

from mae_flow_core.orchestration import recover_lean_flow
from mae_flow_core.state_store import atomic_write_json

from .shared import STATE_PATH


_BACKUP_DIRECTORY = os.path.join(".mae-flow-work", "state-backups")
_PROPOSAL_PATH = os.path.join(_BACKUP_DIRECTORY, "lean-v3-recovery.json")


def _read_bytes(path):
    with open(path, "rb") as stream:
        return stream.read()


def _parse_json(raw):
    return json.loads(raw.decode("utf-8-sig", errors="strict"))


def _lean_document(path=STATE_PATH):
    raw = _read_bytes(path)
    document = _parse_json(raw)
    return raw, document


def _is_lean(document):
    return isinstance(document, dict) and document.get("engine") == "lean-v1"


def _proposal_for(raw, recovery):
    digest = hashlib.sha256(raw).hexdigest()
    if os.path.isfile(_PROPOSAL_PATH):
        try:
            with open(_PROPOSAL_PATH, encoding="utf-8") as stream:
                existing = json.load(stream)
            backup = existing.get("backup_path", "")
            if existing.get("source_sha256") == digest and os.path.isfile(backup):
                return existing
        except (OSError, ValueError, TypeError):
            pass
    os.makedirs(_BACKUP_DIRECTORY, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(
        _BACKUP_DIRECTORY, "%s-%s-lean-v3.json" % (stamp, digest[:10]))
    suffix = 2
    base = backup
    while os.path.exists(backup):
        backup = base[:-5] + "-%d.json" % suffix
        suffix += 1
    with open(backup, "xb") as stream:
        stream.write(raw)
        stream.flush()
        try:
            os.fsync(stream.fileno())
        except OSError:
            pass
    proposal = {
        "source_sha256": digest,
        "backup_path": backup.replace("\\", "/"),
        "safe_boundary": recovery.safe_boundary,
        "terminal": recovery.terminal,
        "confirmed": False,
    }
    atomic_write_json(_PROPOSAL_PATH, proposal)
    return proposal


def prepare_stable_recovery(path=STATE_PATH):
    raw, document = _lean_document(path)
    if not _is_lean(document):
        raise ValueError("当前状态不是 Lean v3，无需恢复")
    recovery = recover_lean_flow(document)
    if recovery.warning:
        raise ValueError(recovery.warning)
    return recovery, _proposal_for(raw, recovery), raw


def _confirmation_text(message_id):
    wanted = str(message_id or "").strip()
    if not wanted:
        raise ValueError("缺少 --message-id；先执行 messages 获取真实用户消息 ID")
    path = STATE_PATH + ".usermsg"
    try:
        with open(path, encoding="utf-8") as stream:
            rows = json.load(stream)
    except (OSError, ValueError) as exc:
        raise ValueError("无法读取用户消息: %s" % exc)
    matches = [row for row in rows if isinstance(row, dict)
               and str(row.get("id", "")) == wanted]
    if not matches:
        raise ValueError("不存在用户消息 ID %s" % wanted)
    return str(matches[-1].get("text", "") or "")


def _assert_natural_confirmation(text):
    compact = re.sub(r"\s+", "", text)
    if any(word in compact for word in ("不确认", "不同意", "不要恢复", "取消")):
        raise ValueError("用户消息没有授权恢复")
    if not any(word in compact for word in ("确认", "同意", "批准", "恢复", "迁移")):
        raise ValueError("用户消息没有明确确认恢复")


def confirm_stable_recovery(path, message_id):
    recovery, proposal, raw = prepare_stable_recovery(path)
    _assert_natural_confirmation(_confirmation_text(message_id))
    if _read_bytes(path) != raw:
        raise ValueError("Lean 状态在确认期间发生变化，请重新查看恢复卡")
    if recovery.terminal:
        terminal = proposal["backup_path"][:-5] + "-terminal.json"
        if not os.path.exists(terminal):
            os.replace(path, terminal)
        proposal["terminal_archive"] = terminal.replace("\\", "/")
    else:
        stable = dict(recovery.state)
        stable["started"] = time.strftime("%Y-%m-%d %H:%M:%S")
        stable["initial_dirty_fingerprints"] = {}
        atomic_write_json(path, stable)
    proposal["confirmed"] = True
    atomic_write_json(_PROPOSAL_PATH, proposal)
    return recovery, proposal


def _print_card(recovery, proposal):
    print("[mae-flow] 检测到 Lean v3 在途状态；已创建逐字节恢复备份。")
    print("备份: " + proposal["backup_path"])
    if recovery.terminal:
        print("状态: 已完成/已退出；确认后仅归档，不启动稳定流程。")
    else:
        print("建议恢复到稳定流程步骤: " + recovery.safe_boundary)
        print("仅迁移单号、用户配置、分支、启动时修改和已确认产物路径；"
              "不会迁移令牌、哈希、指纹、检视摘要或交付收据。")
    print("请用户明确确认后先执行 messages，再运行: "
          "migrate-flow --confirm --message-id <消息ID>")


def _terminal_lean_gate_bypasses():
    if not os.path.isfile(STATE_PATH):
        return False
    try:
        _raw, document = _lean_document(STATE_PATH)
        recovery = recover_lean_flow(document)
        return recovery.terminal
    except Exception:
        return False


def handle_early_state_command(args):
    """Intercept Lean state before the stable loader sees it."""
    if args.cmd == "gate" and _terminal_lean_gate_bypasses():
        return True
    if args.cmd not in {"current", "migrate-flow"}:
        return False
    if not os.path.isfile(STATE_PATH):
        if args.cmd == "current":
            return False
        print("[mae-flow] 没有可恢复的 .mae-flow.json。", file=sys.stderr)
        raise SystemExit(2)
    try:
        _raw, document = _lean_document(STATE_PATH)
    except Exception as exc:
        print("[mae-flow] 状态读取失败: %s" % exc, file=sys.stderr)
        raise SystemExit(2)
    if not _is_lean(document):
        if args.cmd == "current":
            return False
        print("[mae-flow] 当前已经是稳定流程状态，无需迁移。")
        return True
    try:
        if args.cmd == "migrate-flow" and args.confirm:
            if not args.message_id:
                raise ValueError("--confirm 必须同时提供 --message-id")
            recovery, proposal = confirm_stable_recovery(
                STATE_PATH, args.message_id)
            if recovery.terminal:
                print("[mae-flow] Lean 终态已安全归档，当前没有活动流程。")
            else:
                print("[mae-flow] 已恢复到稳定流程步骤: "
                      + recovery.safe_boundary)
            print("原始备份: " + proposal["backup_path"])
            return True
        if args.cmd == "migrate-flow" and args.message_id:
            raise ValueError("--message-id 只能与 --confirm 一起使用")
        recovery, proposal, _raw = prepare_stable_recovery(STATE_PATH)
    except Exception as exc:
        print("[mae-flow] 恢复失败: %s" % exc, file=sys.stderr)
        raise SystemExit(2)
    _print_card(recovery, proposal)
    return True
