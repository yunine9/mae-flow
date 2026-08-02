"""Safe one-way migration of the active legacy flow state."""

import json
import os
import sys
from dataclasses import dataclass, replace

from mae_flow_core.adapters.lean_exit import exclusive_backup_bytes
from mae_flow_core.orchestration import (
    decode_flow_state,
    migrate_legacy_flow,
)
from mae_flow_core.state_store import (
    ProjectStateLock,
    atomic_write_json,
)

STATE_PATH = ".mae-flow.json"


_DELIVERY_AUTHORIZATION_KEYS = {
    "allow_commit",
    "allow_push",
    "auto_commit",
    "auto_push",
    "automatic_commit",
    "automatic_push",
    "commit_authorization",
    "commit_message",
    "delivery_manifest",
    "push_authorization",
}


@dataclass(frozen=True)
class StateMigrationResult:
    state: object
    migrated: bool
    backup_path: str = ""
    legacy_position: str = ""


def _read_bytes(path):
    with open(path, "rb") as stream:
        return stream.read()


def _write_raw_backup(path, raw):
    """Publish an exact immutable backup without replacing prior bytes."""
    return exclusive_backup_bytes(path, raw, "v2-backup")


def _capability_tokens(path):
    sidecar = path + ".tokens"
    if not os.path.isfile(sidecar):
        return {}, ()
    try:
        tokens = _parse_json(_read_bytes(sidecar))
        if not isinstance(tokens, dict):
            raise ValueError("token sidecar must be a JSON object")
        return tokens, ()
    except Exception as exc:
        return {}, (
            "Legacy capability token sidecar is unreadable; no sidecar "
            "execution facts were migrated (%s: %s)."
            % (type(exc).__name__, exc),
        )


def _parse_json(raw):
    text = raw.decode("utf-8-sig", errors="strict")
    return json.loads(text)


def _authorization_decision(key, value):
    lowered = key.strip().lower().replace("-", "_").replace(" ", "_")
    if lowered == "delivery" or lowered.startswith("delivery."):
        return True
    if lowered == "moonlight" or lowered.startswith("moonlight."):
        return True
    tail = lowered[7:] if lowered.startswith("config.") else lowered
    if tail in _DELIVERY_AUTHORIZATION_KEYS:
        return True
    authorization_words = (
        "月光宝盒", "自动提交", "自动推送", "提交授权", "推送授权", "交付清单",
    )
    if any(word in tail for word in authorization_words):
        return True
    serialized = value.strip().lower()
    return any(marker in serialized for marker in (
        '"allow_commit"',
        '"allow_push"',
        '"auto_commit"',
        '"auto_push"',
        '"automatic_commit"',
        '"automatic_push"',
        '"commit_authorization"',
        '"push_authorization"',
        '"moonlight"',
        "月光宝盒",
        "自动提交",
        "自动推送",
        "提交授权",
        "推送授权",
    ))


def _safe_warning_state(state, warnings):
    if not warnings:
        return state
    decisions = tuple(
        (key, value) for key, value in state.decisions
        if not _authorization_decision(key, value)
    )
    risks = list(state.risks)
    for warning in warnings:
        risk = (
            "Migration warning requires a natural-language user decision "
            "before Delivery: %s" % warning
        )
        if risk not in risks:
            risks.append(risk)
    return replace(
        state,
        decisions=decisions,
        risks=tuple(risks),
        delivery_files=(),
    )


def migrate_state_file(path=STATE_PATH, project_root=None):
    """Migrate one state file without printing before durable replacement.

    Corrupt legacy bytes receive the same byte-for-byte recovery backup as a
    parseable v2 file.  A valid unsupported schema is left untouched without a
    misleading v2 backup.  Existing strict v3 state is read-only and idempotent.
    """
    project = os.path.abspath(project_root or os.getcwd())
    state_path = path if os.path.isabs(path) else os.path.join(project, path)
    with ProjectStateLock(project):
        raw = _read_bytes(state_path)
        try:
            document = _parse_json(raw)
        except Exception as exc:
            backup = _write_raw_backup(state_path, raw)
            raise ValueError(
                "状态 JSON 损坏，原文件未覆盖；原始字节已备份到 %s (%s: %s)" %
                (backup, type(exc).__name__, exc))

        if isinstance(document, dict) and document.get(
                "schema_version") == 3:
            state = decode_flow_state(document)
            return StateMigrationResult(state, False)

        if (not isinstance(document, dict)
                or type(document.get("schema_version")) is not int
                or document.get("schema_version") != 2):
            version = document.get("schema_version") if isinstance(
                document, dict) else type(document).__name__
            raise ValueError(
                "不支持的流程状态版本 %r；状态文件保持不变" % version)

        backup = _write_raw_backup(state_path, raw)
        capability_tokens, sidecar_warnings = _capability_tokens(state_path)
        migration = migrate_legacy_flow(
            document, capability_tokens=capability_tokens)
        warnings = migration.warnings + sidecar_warnings
        state = _safe_warning_state(migration.state, warnings)
        encoded = state.to_dict()
        atomic_write_json(state_path, encoded)
        return StateMigrationResult(
            state, True, backup, str(document.get("current", "")))


def _summary_lines(state, legacy_position=""):
    lines = [
        "恢复摘要",
        "阶段: %s" % state.phase.value,
        "路径: %s" % state.path.value,
        "状态: %s" % state.status,
    ]
    if legacy_position:
        lines.append("旧流程位置: %s" % legacy_position)
    if state.status == "complete":
        lines.append("流程已完成")
    lines.append("产物:")
    if state.artifacts:
        lines.extend("- %s: %s" % item for item in state.artifacts)
    else:
        lines.append("- (无)")
    lines.append("决策:")
    if state.decisions:
        lines.extend("- %s: %s" % item for item in state.decisions)
    else:
        lines.append("- (无)")
    lines.append("风险:")
    if state.risks:
        lines.extend("- %s" % risk for risk in state.risks)
    else:
        lines.append("- (无)")
    lines.append("能力尝试:")
    if state.capabilities:
        lines.extend("- %s | %s | %s" % (
            attempt.kind,
            attempt.outcome,
            attempt.summary or "(无摘要)",
        ) for attempt in state.capabilities)
    else:
        lines.append("- (无)")
    return lines


def _print_result(result):
    if result.migrated:
        print("[mae-flow] 迁移完成；旧状态备份: %s" % result.backup_path)
    for line in _summary_lines(result.state, result.legacy_position):
        print(line)


def _terminal_lean_gate_bypasses():
    """Preserve the established post-completion gate bypass during cutover."""
    if not os.path.isfile(STATE_PATH):
        return False
    try:
        document = _parse_json(_read_bytes(STATE_PATH))
        if not (isinstance(document, dict)
                and document.get("schema_version") == 3):
            return False
        return decode_flow_state(document).status in {"complete", "exited"}
    except Exception:
        return False


def handle_early_state_command(args):
    """Handle v2 migration/current before the legacy loader is entered."""
    if args.cmd == "gate" and _terminal_lean_gate_bypasses():
        return True
    if args.cmd not in {"current", "migrate-flow"}:
        return False
    if not os.path.isfile(STATE_PATH):
        if args.cmd == "current":
            return False
        print("[mae-flow] 没有可迁移的 .mae-flow.json。", file=sys.stderr)
        raise SystemExit(2)
    try:
        result = migrate_state_file(STATE_PATH, project_root=os.getcwd())
    except Exception as exc:
        print("[mae-flow] 迁移失败: %s" % exc, file=sys.stderr)
        raise SystemExit(2)
    _print_result(result)
    return True
