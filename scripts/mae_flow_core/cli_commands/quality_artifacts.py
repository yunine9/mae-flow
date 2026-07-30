"""CLI adapter for local Spec2Code process artifacts."""

from mae_flow_core.application.quality.spec2code_artifacts import (
    ArtifactPorts,
    ConfirmationPorts,
    confirm_artifacts,
    prepare_confirmation,
    register_artifact,
    verify_confirmation,
)
from mae_flow_core.delivery.models import thaw
from mae_flow_core.quality.spec2code_artifacts import artifact_path

from .shared import hashlib, json, os, read_text, time
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


def _confirmation_definition(state, step_id):
    ticket = str((state.get("config") or {}).get("单号", "") or "")
    if step_id == "test_blueprint":
        return ("blueprint",), ""
    if step_id == "build_plan":
        return (
            ("roadmap", "plan"),
            artifact_path("review", ticket, "CP1", "plan"),
        )
    raise ValueError("当前步骤不支持 Spec2Code 展示收据: " + step_id)


def _confirmation_ports():
    return ConfirmationPorts(
        is_file=os.path.isfile,
        read_text=lambda path: read_text(path, encoding="utf-8"),
        digest=lambda text: hashlib.sha256(
            text.encode("utf-8")).hexdigest(),
        ack_cursor=api._ack_message_cursor,
        now=lambda: time.strftime("%Y-%m-%d %H:%M:%S"),
    )


def _spec2code_confirmation_cursor(state, step_id):
    kinds, review_path = _confirmation_definition(state, step_id)
    try:
        return verify_confirmation(
            state.get("spec2code") or {},
            step_id,
            kinds,
            review_path,
            _confirmation_ports(),
        )
    except ValueError as exc:
        api.die(str(exc), 2)


def _present_spec2code_confirmation(state, kind):
    step_id = {
        "blueprint": "test_blueprint",
        "plan": "build_plan",
    }[kind]
    if state.get("current") != step_id:
        api.die(
            "只能在当前 %s 步骤冻结展示版本。" % step_id,
            2,
        )
    kinds, review_path = _confirmation_definition(state, step_id)
    if kind == "plan":
        evidence = api.ev_spec2code_plan_review(
            {"checkpoint": "CP1"}, state)
        if not evidence.passed:
            api.die(
                "PLAN 展示前置校验失败: " + evidence.reason,
                2,
            )
    result = prepare_confirmation(
        state.get("spec2code") or {},
        step_id,
        kinds,
        review_path,
        _confirmation_ports(),
    )
    _apply_artifact_result(state, result)
    print("现在展示本收据绑定的完整内容/差异，再用 AskUserQuestion "
          "取得一次新的用户选择。")


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
    if args.quality_action == "present":
        _present_spec2code_confirmation(state, args.kind)
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
