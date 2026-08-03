"""Bind Full Spec Grill semantics to exact local artifact bytes."""

import hashlib
import json
import os

from mae_flow_core.orchestration.documents import DocumentPaths
from mae_flow_core.orchestration.grill_session import grill_status
from mae_flow_core.orchestration.transitions import AdvanceRequest


_PREP_SECTIONS = (
    "## 1 状态机完备性",
    "## 2 边界值",
    "## 3 并发时序",
    "## 4 失败路径与残留清理",
    "## 5 数据一致性",
    "## 6 存量升级兼容",
    "## 7 规格性能",
    "## 8 可观测",
    "## 9 结论汇总",
)


def _file_sha256(path, label):
    if not os.path.isfile(path):
        raise ValueError("%s 不存在: %s" % (label, path))
    if os.path.getsize(path) <= 0:
        raise ValueError("%s is empty: %s" % (label, path))
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _compact(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def validate_grill_preparation(root, state):
    """Require the original eight-dimension Grill preparation before asking."""
    paths = DocumentPaths.for_ticket(root, state.ticket)
    survey = os.path.join(paths.local_root, "survey.md")
    prep = os.path.join(paths.local_root, "grill-prep.md")
    _file_sha256(survey, "survey.md")
    _file_sha256(prep, "grill-prep.md")
    with open(prep, encoding="utf-8") as stream:
        source = stream.read()
    missing = [heading for heading in _PREP_SECTIONS if heading not in source]
    if missing:
        raise ValueError("grill-prep.md 缺少完整维度: " + ", ".join(missing))
    if "{{" in source or "待填" in source:
        raise ValueError("grill-prep.md 仍有占位内容，八个维度必须逐项形成结论")


def prepare_grill_request(root, state, request):
    """Replace Grill receipt prose with exact file digest facts."""
    kind = request.kind.strip().lower()
    if kind not in {"grill-converged", "grill-clear"}:
        return request
    paths = DocumentPaths.for_ticket(root, state.ticket)
    status = grill_status(state)
    grill_sha = _file_sha256(paths.local_grill, "grill.md")
    if kind == "grill-converged":
        validate_grill_preparation(root, state)
        value = _compact({
            "answer_count": len(status.answered_ids),
            "grill_sha256": grill_sha,
        })
    else:
        value = _compact({
            "grill_sha256": grill_sha,
            "input_coverage": "complete",
            "spec_sha256": _file_sha256(paths.local_spec, "spec.md"),
        })
    return AdvanceRequest(request.kind, request.decision_key, value)


def validate_spec_confirmation(root, state):
    """Return a stable diagnostic when reviewed artifact bytes changed."""
    status = grill_status(state)
    critic = status.critic
    if not critic:
        return "Grill Critic 尚未形成可验证的覆盖结论。"
    paths = DocumentPaths.for_ticket(root, state.ticket)
    try:
        grill_sha = _file_sha256(paths.local_grill, "grill.md")
        spec_sha = _file_sha256(paths.local_spec, "spec.md")
    except ValueError as exc:
        return str(exc)
    if grill_sha != critic.get("grill_sha256"):
        return "Grill 结果在 Critic 后发生变化，必须重新收敛并复核。"
    if spec_sha != critic.get("spec_sha256"):
        return "Spec 在 Critic 后发生变化，必须重新复核。"
    if critic.get("input_coverage") != "complete":
        return "Grill 到 Spec 的输入覆盖尚未完成。"
    return ""
