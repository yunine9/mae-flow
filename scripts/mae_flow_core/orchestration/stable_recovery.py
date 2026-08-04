"""Conservative Lean-v3 to stable-v2 semantic recovery."""

from dataclasses import dataclass

from .models import DeliveryPath
from .state_schema import decode_flow_state


@dataclass(frozen=True)
class StableRecoveryResult:
    state: object
    safe_boundary: str
    terminal: bool = False
    warning: str = ""


SAFE_BOUNDARY_BY_PHASE = {
    "startup": "config_confirm",
    "spec": "open",
    "story": "story",
    "construction": "build_pace",
    "quality": "verify_ponytail",
    "delivery": "delivery_review",
}


def recover_lean_flow(raw):
    """Project durable semantics without importing any evidence contract."""
    lean = decode_flow_state(raw)
    if lean.status in {"complete", "exited"}:
        return StableRecoveryResult(None, "", terminal=True)
    phase = lean.phase.value
    boundary = SAFE_BOUNDARY_BY_PHASE.get(phase)
    if not boundary:
        return StableRecoveryResult(
            None, "", warning="无法确定安全恢复阶段，保留原现场等待人工判断。")

    semantic = {key: value for key, value in lean.decisions}
    config = {"单号": lean.ticket}
    choices = {}
    for key, value in semantic.items():
        if key.startswith("config."):
            config[key[len("config."):]] = value
        elif key in {
                "workflow", "grill", "STORY入库", "code_reviewer",
                "development_pace"}:
            choices[key] = value
    choices.setdefault(
        "workflow", "full" if lean.path == DeliveryPath.FULL else "tweak")
    choices.setdefault("development_pace", lean.commit_pace.value)

    artifact_fields = {
        "request": "需求文档", "spec": "SPEC路径", "story": "STORY路径",
    }
    artifacts = {}
    for kind, path in lean.artifacts:
        field = artifact_fields.get(kind)
        if field and path:
            config[field] = path
            artifacts[kind] = path

    workflow = choices["workflow"]
    if lean.path == DeliveryPath.FOCUSED:
        if phase == "spec":
            boundary = {
                "hotfix": "hf_open", "review": "rf_triage",
            }.get(workflow, "tw_open")
        elif phase == "construction":
            boundary = {
                "hotfix": "hf_open", "review": "rf_pace",
            }.get(workflow, "tw_pace")
        elif phase == "quality":
            boundary = "rf_verify" if workflow == "review" else "tw_compile"

    stable = {
        "schema_version": 2,
        "revision": 0,
        "current": boundary,
        "config": config,
        "choices": choices,
        "protocols": {"development_checkpoints": 1},
        "history": [{
            "step": boundary,
            "result": "从 Lean v3 安全恢复；旧质量证据未复用",
        }],
        "started": "",
        "initial_dirty": list(lean.initial_dirty),
        "initial_dirty_fingerprints": {},
        "recovered_artifacts": artifacts,
        "recovery_risks": list(lean.risks),
    }
    return StableRecoveryResult(stable, boundary)
