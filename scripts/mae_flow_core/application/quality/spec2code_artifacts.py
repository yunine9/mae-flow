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
