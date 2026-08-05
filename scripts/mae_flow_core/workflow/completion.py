"""Pure policy for completing the current Mae-Flow step."""

from dataclasses import dataclass
import re

from ..moonlight import enabled as moonlight_enabled
from ..moonlight import step_kind as moonlight_step_kind
from .evidence import EvidenceRegistry, evaluate_step_evidence


@dataclass(frozen=True)
class CompletionEvent:
    kind: str
    value: str = ""
    note: str = ""


def resolve_choice(step, state, requested):
    """Supply the legacy in-flight Moonlight choice when it is omitted."""
    if (
        moonlight_enabled(state)
        and step.get("skip_in_moonlight")
        and not requested
    ):
        return step.get("moonlight_choice")
    return requested


def choice_error(step, choice):
    if (
        step.get("choice_key")
        and choice not in step.get("choices", [])
    ):
        return "--choice 必须为: %s" % "|".join(
            step["choices"])
    return ""


def choice_config(step, choice):
    selected = (
        (step.get("choice_sets") or {}).get(choice, {})
        or {}
    )
    return {
        key: str(value)
        for key, value in selected.items()
    }


def natural_binary_choice(step, value, is_positive):
    """Resolve free-text fallback only for the safe continue/revise shape."""
    if set(step.get("choices") or []) != {"continue", "revise"}:
        return ""
    if is_positive(value):
        return "continue"
    compact = re.sub(r"[\s，。；;：:、!！]+", "", value or "")
    if not compact or re.search(r"[?？]", compact):
        return ""
    if re.search(
            r"需要(?:重新)?(?:调整|修改|补充|完善|修正)|"
            r"(?:有|存在)(?:遗漏|缺口|问题|错误)|"
            r"遗漏|漏了|缺少|不完整|不正确|不对|暂不|先别|拒绝",
            compact, re.I):
        return "revise"
    return ""


def receipt_choice(step, item, value):
    """Resolve a structured AskUserQuestion selection by displayed position."""
    choices = list(step.get("choices") or [])
    if not choices:
        return ""
    normalized_value = re.sub(
        r"[\s，。；;：:、!！]+", "", value or "").lower()
    selected = set()
    for question in (
            ((item.get("askuser") or {}).get("questions") or [])):
        options = question.get("options") or []
        if len(options) != len(choices):
            continue
        for index, label in enumerate(options):
            normalized_label = re.sub(
                r"[\s，。；;：:、!！]+", "", str(label or "")).lower()
            if normalized_label and normalized_value == normalized_label:
                selected.add(choices[index])
    return next(iter(selected)) if len(selected) == 1 else ""


def evidence_failures(step, state, evaluators):
    registry = (
        evaluators
        if isinstance(evaluators, EvidenceRegistry)
        else EvidenceRegistry(evaluators)
    )
    return evaluate_step_evidence(step, state, registry)


def evidence_error(
    failures,
    failure_count,
    moonlight,
    target,
    script_path,
):
    message = "证据不足,拒绝推进:\n  - " + "\n  - ".join(
        failures)
    if failure_count < 2 or moonlight:
        return message
    goto_hint = (
        '先执行 messages 取得该回答 ID，再执行 python "%s" goto %s '
        "--force --message-id <ID>"
        % (script_path, target)
        if target else
        "先按 current 完成本步选择；目标确定后再执行 goto <目标步骤> "
        "--force --message-id <messages输出的ID>"
    )
    return message + (
        "\n⚠ 本步证据已连续 %d 次不满足。机器事实不能由口头确认替代;"
        "但若**用户已明确表示**接受现状/跳过本步(如“跳过吧/我认为可以了”),"
        "这是用户的风险裁决,%s "
        "整步跳过并留痕审计;缺的是 COMPILE/CODECHECK/UT 等 Agent 令牌时,"
        "优先用报错里的 accept-risk(只放当前令牌,其他证据照查)。"
        "没有用户原话时 Agent 不得自行跳过。"
        % (failure_count, goto_hint)
    )


def _story_is_local(state):
    mode = str(
        (state.get("config") or {}).get("STORY入库", "")
    ).lower()
    return any(
        value in mode
        for value in (
            "不生成",
            "不入库",
            "不提交",
            "no",
            "false",
        )
    )


def completion_events(
    step_id,
    step,
    state,
    choice,
    ack,
):
    """Yield ordered adapter actions after Evidence has succeeded."""
    kind = moonlight_step_kind(step_id)
    if kind:
        yield CompletionEvent("resolve_moonlight", kind)

    if step_id == "story" and _story_is_local(state):
        ticket = str(
            (state.get("config") or {}).get("单号", "")
        )
        yield CompletionEvent("localize_story", ticket)

    note = ack or (
        "月光宝盒自动决策"
        if (
            moonlight_enabled(state)
            and step.get("user_ack")
        )
        else ""
    )
    yield CompletionEvent("advance", note=note)
