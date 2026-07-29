"""Pure policy for completing the current Mae-Flow step."""

from dataclasses import dataclass

from ..moonlight import enabled as moonlight_enabled
from ..moonlight import step_kind as moonlight_step_kind
from .advancement import PACE_STEPS


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


def evidence_failures(step, state, evaluators):
    failures = []
    for spec in step.get("evidence", []):
        ok, why = evaluators[spec["type"]](spec, state)
        if not ok:
            failures.append(why)
    return failures


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
    if step_id in PACE_STEPS and not moonlight_enabled(state):
        if choice == "adjust":
            yield CompletionEvent("adjust_checkpoint")
            return
        yield CompletionEvent(
            "activate_checkpoint",
            choice,
        )

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
