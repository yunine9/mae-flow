"""Opaque PostToolUse return observation without quality interpretation."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
import hashlib
import json
import re

from mae_flow_core.application.hooks.models import HookResponse
from mae_flow_core.foundation.git_intent import git_delivery_intents
from mae_flow_core.guard.manifest import git_receipt_reservation
from mae_flow_core.orchestration.capabilities import SUMMARY_LIMIT, flow_attempt_context
from mae_flow_core.orchestration.capability_registry import load_capability_registry, match_capability
from mae_flow_core.orchestration.models import FlowState, Phase


@dataclass(frozen=True)
class ReturnObservation:
    return_present: bool
    summary: str


@dataclass(frozen=True)
class CapabilityObservation:
    kind: str
    tool_name: str
    identity_field: str
    identity: str
    return_present: bool
    summary: str


@dataclass(frozen=True)
class CapabilityObservationResult:
    observation: object = None


def _human_summary(value):
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(
                value, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"))
        except (TypeError, ValueError, OverflowError):
            text = str(value)
    return text[:SUMMARY_LIMIT]


def observe_return(payload):
    """Observe only response-key presence and a bounded human summary."""
    if not isinstance(payload, Mapping) or "tool_response" not in payload:
        return ReturnObservation(False, "")
    return ReturnObservation(
        True, _human_summary(payload.get("tool_response")))


def _matched_result(payload, registry):
    matched = match_capability(payload, registry)
    if matched is None:
        return None
    returned = observe_return(payload)
    observation = CapabilityObservation(
        matched.kind,
        matched.tool_name,
        matched.identity_field,
        matched.identity,
        returned.return_present,
        returned.summary,
    )
    return CapabilityObservationResult(observation)


def observe_capability(payload, registry):
    """Build an exact observation from a registered real host identity."""
    matched = _matched_result(payload, registry)
    return matched if matched is not None else CapabilityObservationResult()


def _same_slot_attempted(state, kind):
    context = flow_attempt_context(state, kind)
    return any(
        item.kind == context.kind.value
        and item.source_revision == context.source_revision
        and item.environment_revision == context.environment_revision
        for item in state.capabilities)


def _one_shot_launch_gap(state, payload, registry):
    matched = match_capability(payload, registry)
    if (matched is None or matched.kind not in {"reviewer", "grill"}
            or not _same_slot_attempted(state, matched.kind)):
        return ""
    if matched.kind == "grill":
        return (
            "Grill Critic 在当前 Spec 槽位已执行一次，禁止重复调用；"
            "直接展示最终 Spec 并使用 spec-confirmed 完成用户确认。")
    if state.phase == Phase.STORY:
        return (
            "Design Reviewer 在当前 Story 槽位已执行一次，禁止重复调用；"
            "不得请求 Reviewer 重试，直接展示最终 Story 并使用 "
            "story-confirmed 进入编码实现。")
    if state.phase == Phase.CONSTRUCTION:
        return (
            "CODE Reviewer 在当前 CP 槽位已执行一次，禁止重复调用；"
            "继续本 CP Build，并通过 cp-ready 展示用户检视卡。")
    return (
        "集成 Reviewer 在当前质量槽位已执行一次，禁止重复调用；"
        "继续最终质量收口。")


def _reviewer_prompt(payload):
    tool_input = payload.get("tool_input", {})
    if not isinstance(tool_input, Mapping):
        return ""
    return "\n".join(
        str(tool_input.get(key, "") or "")
        for key in ("description", "prompt"))


def _scope_present(prompt):
    return re.search(
        r"(?:Changed production files \(exact\)|本 CP 精确修改文件)"
        r"[ \t]*:[ \t]*(?:\S[^\r\n]*|\r?\n[ \t]*-[ \t]*\S[^\r\n]*)",
        prompt, re.IGNORECASE) is not None


def _exact_field_present(prompt, label, value=""):
    prefix = label + ":"
    return ((prefix + " " + value) in prompt if value
            else re.search(
                re.escape(prefix) + r"[ \t]+\S[^\r\n]*", prompt) is not None)


def _reviewer_input_gap(state, payload, registry):
    matched = match_capability(payload, registry)
    if state.path.value != "full" or matched is None or matched.kind != "reviewer":
        return ""
    prompt = _reviewer_prompt(payload)
    artifacts = dict(state.artifacts)
    missing = any(
        not artifacts.get(kind) or artifacts[kind] not in prompt
        for kind in ("spec", "story"))
    needs_scope = state.phase in {Phase.CONSTRUCTION, Phase.QUALITY}
    if not missing and (not needs_scope or _scope_present(prompt)):
        return ""
    lines = ["Reviewer Task 必须显式携带精确输入路径："]
    for kind, label in (("spec", "Spec"), ("story", "Story")):
        if artifacts.get(kind):
            lines.append("%s path (exact): %s" % (label, artifacts[kind]))
    if needs_scope:
        lines.append("Changed production files (exact):\n- <本 CP 精确文件>")
    return "\n".join(lines)


def _build_input_gap(state, payload, registry):
    matched = match_capability(payload, registry)
    if (matched is None or matched.kind != "build"
            or matched.tool_name not in {"Task", "Agent"}):
        return ""
    method = state.startup_config.build_method.strip()
    checkpoint = state.current_cp or "CP1"
    prompt = _reviewer_prompt(payload)
    fields_ok = (
        method
        and _exact_field_present(prompt, "CP (exact)", checkpoint)
        and _exact_field_present(prompt, "Build method (exact)", method)
        and _exact_field_present(prompt, "Build directory (exact)")
        and _scope_present(prompt))
    if fields_ok:
        return ""
    return (
        "compile-agent Task 必须显式携带本 CP 精确构建输入：\n"
        "CP (exact): %s\n"
        "Build method (exact): %s\n"
        "Build directory (exact): <精确构建目录>\n"
        "Changed production files (exact):\n- <本 CP 精确文件>"
        % (checkpoint, method or "<启动配置尚未确认>"))


def _record_build_invocation(state, payload, registry):
    method = state.startup_config.build_method.strip()
    matched = match_capability(payload, registry)
    if (state.phase != Phase.CONSTRUCTION or not method or matched is None
            or matched.kind != "build"
            or matched.tool_name not in {"Task", "Agent"}):
        return state
    checkpoint = state.current_cp or "CP1"
    key = "construction.cp.%s.build-invoked" % checkpoint
    decisions = tuple(item for item in state.decisions if item[0] != key)
    return replace(state, decisions=decisions + ((key, method),))


def apply_capability_pretool(state, payload, root, update_state):
    """Persist real Build invocation and reject invalid capability launches."""
    if not isinstance(state, FlowState):
        return state, None
    registry = load_capability_registry(root)
    gap = (_one_shot_launch_gap(state, payload, registry)
           or _reviewer_input_gap(state, payload, registry)
           or _build_input_gap(state, payload, registry))
    if gap:
        return state, HookResponse(
            exit_code=2, stderr="[mae-flow] %s\n" % gap)
    recorded = _record_build_invocation(state, payload, registry)
    if recorded != state:
        state = update_state(lambda current: _record_build_invocation(
            current, payload, registry))
    return state, None


def _observation_payload(observation):
    return {
        "kind": observation.kind,
        "tool_name": observation.tool_name,
        "identity_field": observation.identity_field,
        "identity": observation.identity,
        "return_present": observation.return_present,
        "summary": observation.summary,
    }


def handle_capability_posttool(payload, registry, audit, update_state):
    """Sequence audit and persistence through fail-open adapter ports."""
    result = observe_capability(payload, registry)
    if result.observation is not None:
        audit("CapabilityObservation", _observation_payload(
            result.observation))
        update_state(payload, result.observation)
    return HookResponse()


_PENDING_GIT = "delivery.git.pending"


def _canonical_json(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _git_command(payload):
    tool_input = payload.get("tool_input") if isinstance(payload, Mapping) else None
    command = tool_input.get("command") if isinstance(tool_input, Mapping) else None
    return command if payload.get("tool_name") == "Bash" and isinstance(
        command, str) else ""


def _commit_message(arguments):
    for index, token in enumerate(arguments):
        if token in {"-m", "--message"}:
            return arguments[index + 1] if index + 1 < len(arguments) else ""
        if token.startswith("--message="):
            return token.split("=", 1)[1]
        if token.startswith("-m") and token != "-m":
            return token[2:]
    return ""


def _git_intent(payload):
    command = _git_command(payload)
    intents = git_delivery_intents(command) if command else ()
    return command, tuple(intents)


def reserve_git_pretool(payload, state, facts, update_state):
    """Persist a one-tool-use Git reservation or fail closed."""
    command, intents = _git_intent(payload)
    if not intents:
        return None
    if len(intents) != 1 or intents[0].opaque_pathspec:
        return HookResponse(
            exit_code=2,
            stderr="[mae-flow] Git reservation requires one direct effect.\n",
        )
    tool_use_id = payload.get("tool_use_id")
    if not isinstance(tool_use_id, str) or not tool_use_id:
        return HookResponse(
            exit_code=2,
            stderr="[mae-flow] Git reservation requires a tool_use_id.\n",
        )
    intent = intents[0]
    operation = intent.operation
    files = (
        intent.pathspecs if operation == "add"
        else facts.get("staged_files", ()) if operation == "commit"
        else facts.get("commit_files", ())
    )
    message = _commit_message(intent.arguments) if operation == "commit" else ""
    try:
        grant = git_receipt_reservation(
            state, operation, files, intent.arguments, message)
        pre_head = facts.get("head_sha", "") or "unborn"
        pre_destination = facts.get("destination_sha", "")
        if operation == "push":
            if pre_destination != grant[
                    "expected_destination_sha"]:
                raise ValueError(
                    "push destination no longer equals the receipt lease SHA")
        if pre_head != grant["expected_source_sha"]:
            raise ValueError(
                "repository HEAD no longer equals the receipt source chain")
        pending = dict(
            grant,
            version=1,
            operation=operation,
            tool_use_id=tool_use_id,
            command_sha256=hashlib.sha256(
                command.encode("utf-8", errors="strict")).hexdigest(),
            pre_head=pre_head,
            pre_destination_sha=pre_destination,
        )

        def reserve(current):
            if any(key == _PENDING_GIT for key, unused in current.decisions):
                raise ValueError("another Git reservation is still pending")
            current_grant = git_receipt_reservation(
                current, operation, files, intent.arguments, message)
            for key, value in grant.items():
                if current_grant.get(key) != value:
                    raise ValueError("delivery receipt changed before reservation")
            return replace(
                current,
                decisions=current.decisions + (
                    (_PENDING_GIT, _canonical_json(pending)),),
            )

        update_state(reserve)
        return HookResponse()
    except (Exception, SystemExit) as exc:
        return HookResponse(
            exit_code=2,
            stderr="[mae-flow] Git reservation failed closed (%s).\n" %
            type(exc).__name__,
        )


def _same_files(left, right):
    return {
        str(path).replace("\\", "/").casefold() for path in left
    } == {
        str(path).replace("\\", "/").casefold() for path in right
    }


def _pending_value(state):
    values = [value for key, value in state.decisions if key == _PENDING_GIT]
    if len(values) != 1:
        return None
    try:
        value = json.loads(values[0])
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _observed_git_effect(pending, facts, tool_use_id):
    operation = pending["operation"]
    head = facts.get("head_sha", "")
    if operation == "add":
        return _same_files(
            pending.get("files", ()), facts.get("staged_files", ())), None
    if operation == "commit":
        success = bool(
            head and head != pending.get("pre_head")
            and _same_files(
                pending.get("files", ()), facts.get("head_commit_files", ())))
        return success, ({
            "files": pending["files"],
            "pre_head": pending.get("pre_head", ""),
            "receipt_digest": pending["receipt_digest"],
            "sha": head,
            "tool_use_id": tool_use_id,
        } if success else None)
    destination = facts.get("destination_sha", "")
    success = bool(head and destination == head)
    return success, ({
        "destination_ref": pending["destination_ref"],
        "destination_sha": destination,
        "local_sha": head,
        "receipt_digest": pending["receipt_digest"],
        "remote": pending["remote"],
        "tool_use_id": tool_use_id,
    } if success else None)


def complete_git_posttool(payload, facts, update_state):
    """Promote only repository-observed effects from the exact reservation."""
    command, intents = _git_intent(payload)
    if len(intents) != 1:
        return None
    tool_use_id = payload.get("tool_use_id")
    handled = [False]
    observation_error = [""]

    def complete(current):
        pending = _pending_value(current)
        command_digest = hashlib.sha256(
            command.encode("utf-8", errors="strict")).hexdigest()
        if (pending is None
                or pending.get("tool_use_id") != tool_use_id
                or pending.get("command_sha256") != command_digest
                or pending.get("operation") != intents[0].operation):
            return current
        handled[0] = True
        operation = pending["operation"]
        success, observation = _observed_git_effect(
            pending, facts, tool_use_id)
        decisions = tuple(
            item for item in current.decisions if item[0] != _PENDING_GIT)
        risks = current.risks
        if not success:
            risk = "Git %s repository observation failed for receipt %s." % (
                operation, pending.get("receipt_digest", "unknown"))
            risks = risks if risk in risks else risks + (risk,)
            observation_error[0] = risk
        elif observation is not None:
            key = (
                "delivery.git.commit_observation"
                if operation == "commit"
                else "delivery.git.push_observation")
            decisions += ((key, _canonical_json(observation)),)
        return replace(current, decisions=decisions, risks=risks)

    try:
        update_state(complete)
    except (Exception, SystemExit) as exc:
        return HookResponse(
            exit_code=2,
            stderr="[mae-flow] Git observation persistence failed (%s).\n" %
            type(exc).__name__,
        )
    if not handled[0]:
        return None
    return HookResponse(
        exit_code=2 if observation_error[0] else 0,
        stderr=("[mae-flow] %s\n" % observation_error[0])
        if observation_error[0] else "",
    )
