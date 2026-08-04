"""Bind Full Spec Grill semantics to exact local artifact bytes."""

from dataclasses import replace
import hashlib
import json
import os

from mae_flow_core.orchestration.documents import DocumentPaths
from mae_flow_core.orchestration.capabilities import (
    flow_attempt_context, retry_decision_key)
from mae_flow_core.orchestration.grill_session import grill_status
from mae_flow_core.orchestration.models import Phase
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

_DESIGN_REVIEW_EVENTS = frozenset({
    "design-review-approved", "design-review-clear",
    "reviewer-clear", "reviewer-tradeoff-resolved",
    "design-review-failed", "reviewer-failed",
})
_FALLBACK_FIELDS = {
    "grill": "local_grill",
    "spec": "local_spec",
    "story": "local_story",
}


def _artifact_path(root, state, kind):
    """Resolve persisted local artifacts before deriving paths for old state."""
    repository = os.path.abspath(root)
    for artifact_kind, raw_path in state.artifacts:
        if artifact_kind != kind:
            continue
        candidate = os.path.abspath(os.path.join(repository, raw_path))
        try:
            inside = os.path.commonpath((repository, candidate)) == repository
        except ValueError:
            inside = False
        if not inside:
            raise ValueError("流程产物路径越出仓库: %s" % raw_path)
        return candidate
    paths = DocumentPaths.for_ticket(root, state.ticket)
    return getattr(paths, _FALLBACK_FIELDS[kind])


def _local_work_root(root, state):
    return os.path.dirname(_artifact_path(root, state, "grill"))


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
    work_root = _local_work_root(root, state)
    survey = os.path.join(work_root, "survey.md")
    prep = os.path.join(work_root, "grill-prep.md")
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
    status = grill_status(state)
    grill_sha = _file_sha256(
        _artifact_path(root, state, "grill"), "grill.md")
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
            "spec_sha256": _file_sha256(
                _artifact_path(root, state, "spec"), "spec.md"),
        })
    return AdvanceRequest(request.kind, request.decision_key, value)


def validate_spec_confirmation(root, state):
    """Require one Critic attempt without turning file digests into a loop."""
    status = grill_status(state)
    attempted = any(
        key == "review.grill.attempted" for key, unused in state.decisions)
    if not status.critic and not attempted:
        return "Grill Critic 尚未形成可验证的覆盖结论。"
    if status.critic and status.critic.get("input_coverage") != "complete":
        return "Grill 到 Spec 的输入覆盖尚未完成。"
    return ""


def _object(value):
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _latest_design_review(state):
    for key, value in reversed(state.decisions):
        if key in {"review.design", "review.design.attempted"}:
            return _object(value)
    return {}


def _latest_spec_review(state):
    for key, value in reversed(state.decisions):
        if key in {"review.grill", "review.grill.attempted"}:
            return key, _object(value)
    return "", {}


def _has_current_story_attempt(state):
    context = flow_attempt_context(state, "story")
    return any(
        attempt.kind == context.kind.value
        and attempt.source_revision == context.source_revision
        and attempt.environment_revision == context.environment_revision
        for attempt in state.capabilities
    )


def _current_attempt(state, kind):
    context = flow_attempt_context(state, kind)
    return next((
        attempt for attempt in reversed(state.capabilities)
        if attempt.kind == context.kind.value
        and attempt.source_revision == context.source_revision
        and attempt.environment_revision == context.environment_revision
    ), None)


def reconcile_phase_state(root, state, request):
    """Repair lean pre-atomic review state without rerunning the Reviewer."""
    kind = request.kind.strip().lower()
    if kind != "story-confirmed" or state.phase != Phase.STORY:
        return state
    if any(
            key in {"review.design", "review.design.attempted"}
            for key, unused in state.decisions):
        return state
    attempt = _current_attempt(state, "reviewer")
    if attempt is None:
        return state
    review_key = (
        "review.design"
        if attempt.outcome == "returned" else "review.design.attempted")
    receipt = _compact({
        "legacy_reconciled": True,
        "story_sha256": _file_sha256(
            _artifact_path(root, state, "story"), "story.md"),
        "summary": attempt.summary,
    })
    return replace(
        state, decisions=state.decisions + ((review_key, receipt),))


def require_configured_build_invocation(state, request):
    if (request.kind.strip().lower() != "cp-ready"
            or state.phase != Phase.CONSTRUCTION):
        return
    method = state.startup_config.build_method.strip()
    if not method:
        return
    checkpoint = state.current_cp or "CP1"
    invoked_key = "construction.cp.%s.build-invoked" % checkpoint
    if any(key == invoked_key for key, unused in state.decisions):
        return
    raise ValueError(
        "当前 CP 尚未实际启动 compile-agent 执行 Build 路由 %s；"
        "先完成子 Agent 调用，再登记 Build 事实并执行 cp-ready" % method)


def capability_retry_decision_key(state, kind):
    retry_kinds = {"build", "ut", "codecheck", "reviewer", "grill", "story"}
    if kind not in retry_kinds:
        raise ValueError("该 capability key 是流程保留事实，不能直接写入")
    context = flow_attempt_context(state, kind)
    attempt = _current_attempt(state, kind)
    if kind in {"reviewer", "grill"} and attempt is not None:
        label = "Reviewer" if kind == "reviewer" else "Grill Critic"
        raise ValueError(
            "%s 为单次检视，当前槽位已尝试；"
            "不得申请重试，直接进入当前阶段的用户确认" % label)
    return retry_decision_key(context)


def prepare_phase_request(root, state, request):
    """Bind final user confirmations without forcing review loops."""
    kind = request.kind.strip().lower()
    if kind == "spec-confirmed" and state.phase == Phase.SPEC:
        review_key, review = _latest_spec_review(state)
        if not review_key:
            raise ValueError(
                "当前 Spec 缺少 Grill Critic 调用收据；"
                "请先完成本阶段唯一一次 Critic 调用")
        return AdvanceRequest(
            request.kind,
            request.decision_key,
            _compact({
                "critic_grill_sha256": review.get("grill_sha256", ""),
                "critic_spec_sha256": review.get("spec_sha256", ""),
                "critic_status": (
                    "returned" if review_key == "review.grill"
                    else "attempted"),
                "grill_sha256": _file_sha256(
                    _artifact_path(root, state, "grill"), "grill.md"),
                "spec_sha256": _file_sha256(
                    _artifact_path(root, state, "spec"), "spec.md"),
                "summary": request.decision_value.strip(),
            }),
        )
    if kind not in _DESIGN_REVIEW_EVENTS | {"story-confirmed"}:
        return request
    if state.phase != Phase.STORY:
        return request
    story_sha = _file_sha256(
        _artifact_path(root, state, "story"), "story.md")
    if kind == "story-confirmed":
        review = _latest_design_review(state)
        reviewed_story_sha = review.get("story_sha256")
        if not reviewed_story_sha:
            raise ValueError(
                "当前 Story 缺少 Design Reviewer 内容收据；"
                "请先完成本阶段唯一一次 Design Review")
        return AdvanceRequest(
            request.kind,
            request.decision_key,
            _compact({
                "reviewed_story_sha256": reviewed_story_sha,
                "story_sha256": story_sha,
                "summary": request.decision_value.strip(),
            }),
        )
    if not _has_current_story_attempt(state):
        raise ValueError(
            "当前 Story 阶段尚未记录 story-generator-agent 调用事实")
    value = _compact({
        "story_sha256": story_sha,
        "summary": request.decision_value.strip(),
    })
    return AdvanceRequest(request.kind, request.decision_key, value)
