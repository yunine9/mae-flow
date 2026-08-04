"""Opaque Agent lifecycle observations used as workflow evidence."""

from dataclasses import asdict, dataclass
from typing import Optional

from mae_flow_core.state_store import safe_read_json, update_json


_LIFECYCLES = {"started", "returned", "interrupted", "timeout"}


@dataclass(frozen=True)
class AgentObservation:
    kind: str
    step: str
    invocation_id: str
    lifecycle: str
    at: str
    detail: str = ""


def observation_path(state_path):
    return str(state_path) + ".agent-observations"


def _records(state_path):
    data, error = safe_read_json(observation_path(state_path))
    if error or not isinstance(data, dict):
        return []
    records = data.get("observations", [])
    return records if isinstance(records, list) else []


def _append(state_path, observation):
    def mutate(data):
        if not isinstance(data, dict):
            data = {}
        records = data.setdefault("observations", [])
        if not isinstance(records, list):
            records = []
            data["observations"] = records
        duplicate = any(
            item.get("invocation_id") == observation.invocation_id
            and item.get("lifecycle") == observation.lifecycle
            for item in records if isinstance(item, dict)
        )
        if not duplicate:
            records.append(asdict(observation))
            if len(records) > 1000:
                del records[:-1000]
        return data

    update_json(
        observation_path(state_path), mutate,
        default={"observations": []}, recover_corrupt=True)
    return observation


def record_agent_started(state_path, kind, step, invocation_id, at):
    observation = AgentObservation(
        kind=str(kind or ""), step=str(step or ""),
        invocation_id=str(invocation_id or ""), lifecycle="started",
        at=str(at or ""),
    )
    if not observation.invocation_id:
        raise ValueError("Agent invocation_id 不能为空")
    return _append(state_path, observation)


def _started_for(records, invocation_id):
    return next((
        item for item in reversed(records)
        if isinstance(item, dict)
        and item.get("invocation_id") == invocation_id
        and item.get("lifecycle") == "started"
    ), {})


def started_observation(state_path, invocation_id):
    started = _started_for(_records(state_path), str(invocation_id or ""))
    return dict(started) if started else None


def record_agent_finished(
        state_path, invocation_id, lifecycle, at, detail=""):
    lifecycle = str(lifecycle or "returned").lower()
    if lifecycle not in _LIFECYCLES - {"started"}:
        raise ValueError("未知 Agent lifecycle: " + lifecycle)
    records = _records(state_path)
    started = _started_for(records, str(invocation_id or ""))
    observation = AgentObservation(
        kind=str(started.get("kind", "")),
        step=str(started.get("step", "")),
        invocation_id=str(invocation_id or ""), lifecycle=lifecycle,
        at=str(at or ""), detail=str(detail or ""),
    )
    if not observation.invocation_id:
        raise ValueError("Agent invocation_id 不能为空")
    return _append(state_path, observation)


def latest_started_invocation(state_path, kind="", step=""):
    records = _records(state_path)
    finished = {
        item.get("invocation_id")
        for item in records if isinstance(item, dict)
        and item.get("lifecycle") in ("returned", "interrupted", "timeout")
    }
    for item in reversed(records):
        if not isinstance(item, dict) or item.get("lifecycle") != "started":
            continue
        if item.get("invocation_id") in finished:
            continue
        if kind and item.get("kind") != kind:
            continue
        if step and item.get("step") != step:
            continue
        return str(item.get("invocation_id", ""))
    return ""


def finished_observation(
        state_path, kind, step, since="") -> Optional[dict]:
    for item in reversed(_records(state_path)):
        if not isinstance(item, dict):
            continue
        if (item.get("kind") == kind
                and item.get("step") == step
                and item.get("lifecycle") == "returned"
                and str(item.get("at", "")) >= str(since or "")):
            return dict(item)
    return None


def has_finished_observation(state_path, kind, step, since=""):
    return finished_observation(state_path, kind, step, since) is not None
