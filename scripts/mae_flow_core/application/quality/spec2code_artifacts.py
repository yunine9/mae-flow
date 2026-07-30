"""Register validated local Spec2Code artifacts without repository writes."""

import hashlib
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

from mae_flow_core.delivery.models import DeliveryEffect, DeliveryResult
from mae_flow_core.quality.spec2code_artifacts import (
    artifact_path,
    validate_blueprint,
    validate_plan,
    validate_roadmap,
)


@dataclass(frozen=True)
class ArtifactPorts:
    is_file: Callable[[str], bool]
    read_text: Callable[[str], str]
    normalize_path: Callable[[str], str]
    now: Callable[[], str]


@dataclass(frozen=True)
class ConfirmationPorts:
    is_file: Callable[[str], bool]
    read_text: Callable[[str], str]
    digest: Callable[[str], str]
    ack_cursor: Callable[[], object]
    now: Callable[[], str]


_VALIDATORS = {
    "blueprint": validate_blueprint,
    "roadmap": validate_roadmap,
    "plan": validate_plan,
}


def _failure(message):
    return DeliveryResult(
        effects=(),
        stdout=(),
        stderr=(message,),
        exit_code=2,
    )


def _confirmation_snapshot(process, kinds, review_path, ports):
    artifacts = {}
    for kind in kinds:
        record = (process or {}).get(kind) or {}
        path = str(record.get("path", "") or "")
        expected = str(record.get("sha256", "") or "")
        revision = int(record.get("revision", 0) or 0)
        if not path or not expected or not revision:
            raise ValueError("尚未登记待展示过程件: " + kind)
        if not ports.is_file(path):
            raise ValueError("待展示过程件不存在: " + path)
        try:
            actual = ports.digest(ports.read_text(path))
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError("待展示过程件无法读取: %s" % exc) from exc
        if actual != expected:
            raise ValueError(
                "%s 登记后内容已变化；重新登记后再展示。" % kind)
        artifacts[kind] = {
            "path": path,
            "sha256": expected,
            "revision": revision,
        }
    review_sha256 = ""
    if review_path:
        if not ports.is_file(review_path):
            raise ValueError("待展示 Review 不存在: " + review_path)
        try:
            review_sha256 = ports.digest(ports.read_text(review_path))
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError("待展示 Review 无法读取: %s" % exc) from exc
    return artifacts, review_sha256


def prepare_confirmation(
        process, step_id, kinds, review_path, ports):
    """Freeze the exact artifact/review versions shown before asking a user."""
    try:
        artifacts, review_sha256 = _confirmation_snapshot(
            process, kinds, review_path, ports)
    except ValueError as exc:
        return _failure(str(exc))
    updated = deepcopy(process) if isinstance(process, dict) else {}
    updated.setdefault("confirmation_receipts", {})[step_id] = {
        "artifacts": artifacts,
        "review_path": review_path,
        "review_sha256": review_sha256,
        "ack_cursor": list(ports.ack_cursor() or ()),
        "at": ports.now(),
    }
    return DeliveryResult(
        effects=(DeliveryEffect("set_spec2code", updated),),
        stdout=(
            "[mae-flow] 已冻结 %s 展示版本；后续用户回答只对本收据有效。"
            % step_id,
        ),
        stderr=(),
        exit_code=0,
    )


def verify_confirmation(
        process, step_id, kinds, review_path, ports):
    """Return the presentation cursor only while every displayed byte is fresh."""
    receipt = (
        ((process or {}).get("confirmation_receipts") or {}).get(step_id)
        or {}
    )
    if not receipt:
        raise ValueError(
            "尚未冻结本轮展示版本；先执行 quality-artifact present。")
    try:
        artifacts, review_sha256 = _confirmation_snapshot(
            process, kinds, review_path, ports)
    except ValueError as exc:
        raise ValueError(
            "%s 旧展示收据失效，必须重新展示并取得新回答。"
            % exc) from exc
    if (
        receipt.get("artifacts") != artifacts
        or str(receipt.get("review_path", "") or "") != review_path
        or str(receipt.get("review_sha256", "") or "") != review_sha256
    ):
        raise ValueError(
            "过程件或 Review 在展示后发生变化；"
            "旧回答不能确认新版本，必须重新展示并取得新回答。")
    return tuple(receipt.get("ack_cursor") or ())


def confirm_artifacts(process, kinds, actor, now):
    """Bind user or Moonlight approval to exact registered revisions."""
    if actor not in ("user", "moonlight"):
        return _failure("Spec2Code 确认主体必须为 user 或 moonlight")
    requested = tuple(dict.fromkeys(
        str(kind) for kind in kinds if str(kind)))
    if not requested:
        return _failure("Spec2Code 确认至少需要一个过程件")
    current = process if isinstance(process, dict) else {}
    missing = [
        kind for kind in requested
        if not isinstance(current.get(kind), dict)
        or not current[kind].get("revision")
        or not current[kind].get("sha256")
    ]
    if missing:
        return _failure(
            "无法确认未登记的 Spec2Code 过程件: "
            + "、".join(missing)
        )
    updated = deepcopy(current)
    for kind in requested:
        record = updated[kind]
        record["confirmed_revision"] = record["revision"]
        record["confirmed_sha256"] = record["sha256"]
        record["confirmed_by"] = actor
        record["confirmed_at"] = now
    joined = ",".join(requested)
    return DeliveryResult(
        effects=(
            DeliveryEffect("set_spec2code", updated),
            DeliveryEffect("append_history", {
                "result": "spec2code:confirm:" + joined,
                "note": actor,
                "at": now,
            }),
        ),
        stdout=(
            "[mae-flow] 已确认 Spec2Code 过程件 %s（确认主体: %s）"
            % (joined, actor),
        ),
        stderr=(),
        exit_code=0,
    )


def register_artifact(process, kind, path, ticket, ports):
    """Validate one existing artifact and return an immutable state update."""
    if kind not in _VALIDATORS:
        return _failure("未知 Spec2Code 过程件类型: " + str(kind))
    normalized = ports.normalize_path(path)
    expected = artifact_path(kind, ticket)
    if normalized != expected:
        return _failure(
            "%s 必须使用规范路径 %s，收到 %s"
            % (kind, expected, normalized)
        )
    if not ports.is_file(path):
        return _failure("过程件不存在: " + normalized)
    try:
        text = ports.read_text(path)
    except (OSError, UnicodeDecodeError) as exc:
        return _failure("过程件读取失败: %s" % exc)
    errors = _VALIDATORS[kind](text)
    if errors:
        return _failure(
            "%s 结构校验失败: %s" % (kind, "；".join(errors))
        )
    updated = deepcopy(process) if isinstance(process, dict) else {}
    previous = updated.get(kind) or {}
    updated["version"] = 1
    updated[kind] = {
        "path": normalized,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "revision": int(previous.get("revision", 0) or 0) + 1,
        "confirmed_revision": 0,
        "registered_at": ports.now(),
    }
    return DeliveryResult(
        effects=(
            DeliveryEffect("set_spec2code", updated),
            DeliveryEffect("append_history", {
                "result": "spec2code:register:" + kind,
                "note": normalized,
                "at": ports.now(),
            }),
        ),
        stdout=(
            "[mae-flow] 已登记 %s: %s（本地过程件，不入库）"
            % (kind, normalized),
        ),
        stderr=(),
        exit_code=0,
    )
