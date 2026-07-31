"""SubagentStop orchestration independent of Hook protocol and storage."""

from dataclasses import dataclass
import os
import re
from typing import Callable

from mae_flow_core.application.hooks.models import HookResponse
from mae_flow_core.quality.tool_transcript import (
    parse_transcript,
    select_contract_marker,
)


@dataclass(frozen=True)
class AgentCompletionPorts:
    latest_subagent_transcript: Callable
    load_transcript: Callable
    read_transcript_head: Callable
    contract_state: Callable
    record_codecheck_trace: Callable
    run_contract: Callable
    record_token: Callable
    record_rejection: Callable
    autopsy: Callable
    log: Callable


def _transcript_path(payload, ports):
    for key, value in payload.items():
        if (
                isinstance(value, str)
                and "transcript" in key.lower()
                and "agent" in key.lower()):
            return value
    main = payload.get("transcript_path", "")
    return ports.latest_subagent_transcript(main) or main


def _standalone_expected(state):
    if not state.get("_standalone"):
        return ""
    kind = str(state.get("current", "")).replace(
        "standalone_", "")
    return {
        "ut": "UT",
        "codecheck": "CODECHECK",
        "grill": "GRILL",
    }.get(kind, "")


def _contract_agent_signature(head):
    return bool(re.search(
        r"_RESULT:|ut-generator-agent|codecheck-fix-agent|"
        r"story-generator-agent|compile-agent|grill-critic-agent",
        head,
    ))


def _role_result_marker(last):
    """Informational role markers are validated by their artifact command."""
    return bool(re.search(
        r"^\s*(CRAFT_REVIEW|TASK_ANALYSIS|TEST_DESIGN|CP_IMPLEMENT)"
        r"_RESULT:\s*\S+",
        last,
        re.M,
    ))


def _standalone_signature(expected, head):
    agent = {
        "UT": "ut-generator-agent",
        "CODECHECK": "codecheck-fix-agent",
        "GRILL": "grill-critic-agent",
    }.get(expected, "")
    return bool(
        agent in head
        or re.search(
            r"\b" + re.escape(expected) + r"_RESULT:", head)
    )


def _missing_marker_message(reason, clue):
    instruction = reason or (
        "最终回复必须以 XXX_RESULT: <状态> 开头(第一行)。"
        "请按你的定义文件顶部「最终回复格式」重新输出完整结果;"
        "不确定时用失败/待确认类状态,禁止省略标记。"
    )
    return (
        "[mae-flow] 子 agent 契约违规:" + instruction + "\n"
        "尸检线索(" + clue + ")——若死因是工具不可用/持续报错,"
        "按契约「带着情报死」条款以 FAIL/BLOCKED 收尾并写明详情;"
        "主 agent 重启新实例时必须把此线索转告它。"
    )


def _log_marker_tolerance(last, marker, ports):
    matches = list(re.finditer(
        r"^\s*(ENV|UT|CODECHECK|STORY|GRILL|COMPILE)_RESULT:\s*(\S+)",
        last,
        re.M,
    ))
    first = re.match(
        r"^(ENV|UT|CODECHECK|STORY|GRILL|COMPILE)_RESULT:\s*(\S+)",
        last.splitlines()[0] if last else "",
    )
    if len(matches) > 1 and marker.kind:
        kinds = {
            match.group(1) + "/" + match.group(2)
            for match in matches
        }
        ports.log(
            "subagentstop: 多个相同结果标记(%s),判定无歧义,接受"
            % next(iter(kinds))
        )
    elif not first and len(matches) == 1 and marker.kind:
        ports.log(
            "subagentstop: 契约标记不在第一行,兼容接受并继续验完整契约")


def _run_marked_contract(
        marker, last, transcript, path, retry, ports):
    if marker.kind == "CODECHECK":
        ports.record_codecheck_trace(
            marker.status,
            last,
            transcript.tool_calls,
            path,
            retry,
        )
    if marker.kind in ("CODECHECK", "UT", "COMPILE", "GRILL"):
        response = ports.run_contract(
            marker.kind,
            marker.status,
            last,
            transcript.tool_calls,
            retry,
        )
        if response.exit_code:
            return response
    ports.record_token(marker.kind, marker.status, last)
    return HookResponse()


def _handle_unmarked_completion(
        retry, path, prompt, last, transcript, assistants, rejection,
        standalone, ports):
    if retry:
        ports.autopsy(path, assistants)
        ports.record_rejection(
            "SUBAGENT",
            rejection
            or "重答后仍未找到唯一的 XXX_RESULT 结果标记。",
        )
        ports.log(
            "subagentstop: 重答后仍无可判定契约标记,"
            "放行防死循环(不发令牌,done 会拦;尸检已留档)")
        return HookResponse()
    try:
        head = ports.read_transcript_head(path, 16000)
    except OSError:
        head = prompt
    if standalone and not _standalone_signature(standalone, head):
        ports.log(
            "standalone action ignores unrelated subagent "
            "without expected contract")
        return HookResponse()
    if not _contract_agent_signature(head):
        ports.log(
            "subagentstop: 无契约标记且 transcript "
            "头部未见契约 agent 特征,跳过")
        return HookResponse()
    if (
            standalone == "CODECHECK"
            or "codecheck-fix-agent" in head
            or re.search(r"\bCODECHECK_RESULT:", head)):
        ports.record_codecheck_trace(
            "NO_RESULT",
            last,
            transcript.tool_calls,
            path,
            retry,
        )
    clue = ports.autopsy(path, assistants)
    return HookResponse(
        exit_code=2,
        stderr=_missing_marker_message(rejection, clue) + "\n",
    )


def handle_agent_completion(payload, ports):
    """Handle one SubagentStop payload and return its protocol response."""
    retry = bool(payload.get("stop_hook_active"))
    path = _transcript_path(payload, ports)
    ports.log(
        "subagentstop transcript: "
        + (os.path.basename(path) or "?"))
    try:
        lines = ports.load_transcript(path)
    except Exception:
        return HookResponse()
    transcript = parse_transcript(lines)
    users = transcript.user_texts
    assistants = transcript.assistant_texts
    prompt = users[0] if users else ""
    last = (assistants[-1] if assistants else "").strip()
    if _role_result_marker(last):
        ports.log(
            "subagentstop: role result marker accepted; "
            "artifact/checkpoint command owns validation")
        return HookResponse()
    marker = select_contract_marker(last)
    _log_marker_tolerance(last, marker, ports)
    rejection = marker.error
    if rejection:
        ports.record_rejection("SUBAGENT", rejection)

    state = ports.contract_state()
    standalone = _standalone_expected(state)
    if marker.kind and standalone and marker.kind != standalone:
        ports.log(
            "standalone action ignores unrelated contract agent: "
            + marker.kind)
        return HookResponse()
    if marker.kind:
        return _run_marked_contract(
            marker, last, transcript, path, retry, ports)
    return _handle_unmarked_completion(
        retry,
        path,
        prompt,
        last,
        transcript,
        assistants,
        rejection,
        standalone,
        ports,
    )
