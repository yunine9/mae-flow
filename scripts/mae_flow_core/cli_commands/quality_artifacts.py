"""CLI adapter for local Spec2Code process artifacts."""

from mae_flow_core.application.quality.spec2code_artifacts import (
    ArtifactPorts,
    confirm_artifacts,
    register_artifact,
)
from mae_flow_core.delivery.models import thaw

from .shared import json, os, read_text, time
from .wiring import api


def _relative_local_path(path):
    return os.path.normpath(
        os.path.relpath(os.path.realpath(path), os.path.realpath(os.getcwd()))
    ).replace("\\", "/")


def _apply_artifact_result(state, result):
    if result.exit_code:
        api.die(result.stderr[0], result.exit_code)
    for effect in result.effects:
        if effect.kind == "set_spec2code":
            state["spec2code"] = thaw(effect.payload)
        elif effect.kind == "append_history":
            state.setdefault("history", []).append(thaw(effect.payload))
        else:
            raise RuntimeError(
                "unsupported quality artifact effect: " + effect.kind)
    api.save_state(state)
    for line in result.stdout:
        print(line)


def _confirm_spec2code_artifacts(state, kinds, actor):
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    result = confirm_artifacts(
        state.get("spec2code") or {},
        kinds,
        actor,
        now,
    )
    _apply_artifact_result(state, result)


def cmd_quality_artifact(_flow, state, args):
    if args.quality_action == "show":
        print(json.dumps(
            {
                "note": "以下均为本地过程件，不入库",
                **(state.get("spec2code") or {}),
            },
            ensure_ascii=False,
            indent=2,
        ))
        return
    ticket = str((state.get("config") or {}).get("单号", "") or "")
    result = register_artifact(
        state.get("spec2code") or {},
        args.kind,
        args.path,
        ticket,
        ArtifactPorts(
            is_file=os.path.isfile,
            read_text=lambda path: read_text(path, encoding="utf-8"),
            normalize_path=_relative_local_path,
            now=lambda: time.strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    _apply_artifact_result(state, result)
