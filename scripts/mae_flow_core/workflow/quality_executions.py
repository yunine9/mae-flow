"""Structural quality execution facts independent of Agent return prose."""

from mae_flow_core.state_store import safe_read_json, update_json


def quality_execution_path(state_path):
    return str(state_path) + ".quality-executions"


def quality_input_snapshot(state, kind, step):
    task = (state.get("agent_tasks", {}) or {}).get(kind, {}) or {}
    config = state.get("config", {}) or {}
    return {
        "kind": kind,
        "step": step,
        "head": str(task.get("head", "")),
        "task_files": sorted(str(path) for path in task.get("task_files", [])),
        "execution_roots": sorted(
            str(path) for path in task.get("execution_roots", [])),
        "build": str(config.get("编译方式", "")),
        "ut": str(config.get("UT运行命令", "")),
    }


def record_quality_execution(
        state_path, kind, step, invocation_id, command, succeeded,
        input_snapshot, at, lifecycle="returned"):
    record = {
        "kind": str(kind), "step": str(step),
        "invocation_id": str(invocation_id), "command": str(command or ""),
        "succeeded": bool(succeeded), "input_snapshot": dict(input_snapshot),
        "at": str(at), "lifecycle": str(lifecycle),
    }

    def mutate(data):
        records = data.setdefault("executions", [])
        records[:] = [
            item for item in records
            if not (item.get("invocation_id") == record["invocation_id"]
                    and item.get("kind") == record["kind"])
        ]
        records.append(record)
        if len(records) > 500:
            del records[:-500]
        return data

    update_json(
        quality_execution_path(state_path), mutate,
        default={"executions": []}, recover_corrupt=True)
    return record


def successful_quality_execution(state_path, kind, step, input_snapshot):
    data, error = safe_read_json(quality_execution_path(state_path))
    if error or not isinstance(data, dict):
        return None
    for item in reversed(data.get("executions", [])):
        if (item.get("kind") == kind and item.get("step") == step
                and item.get("succeeded") is True
                and item.get("lifecycle") == "returned"
                and item.get("input_snapshot") == input_snapshot):
            return dict(item)
    return None
