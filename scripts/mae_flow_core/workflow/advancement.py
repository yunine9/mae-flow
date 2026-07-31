"""Pure advancement policy for Mae-Flow workflow transitions."""

from dataclasses import dataclass

from .transitions import next_step


PACE_STEPS = {"build_pace", "tw_pace", "rf_pace"}
LEGACY_CODE_REVIEW_STEPS = {
    "build_review",
    "tw_review",
    "rf_review",
}
REDUNDANT_CHECKPOINT_COMPILE_STEPS = {
    "tw_compile",
    "rf_compile",
}


@dataclass(frozen=True)
class TransitionEvent:
    kind: str
    step: object
    result: str = ""
    note: str = ""


class TransitionResolutionError(Exception):
    def __init__(self, step_id):
        super().__init__(step_id)
        self.step_id = step_id


def _moonlight_enabled(state):
    return bool(((state or {}).get("moonlight") or {}).get("enabled"))


def _development_review(state):
    data = state.get("development_review")
    return (
        data
        if (
            isinstance(data, dict)
            and data.get("version") in (1, 2)
        )
        else None
    )


def _development_checkpoints_enabled(state):
    protocols = state.get("protocols") or {}
    return bool(
        isinstance(protocols, dict)
        and int(protocols.get("development_checkpoints", 0) or 0) >= 1
    )


def _audit(step, result, note):
    return TransitionEvent("audit", step, result, note)


def _legacy_pace_events(flow, state, target):
    if (
        target in PACE_STEPS
        and not _development_checkpoints_enabled(state)
        and not _development_review(state)
        and not _moonlight_enabled(state)
    ):
        yield _audit(
            target,
            "legacy:skipped-development-pace",
            "旧版在途状态没有检查点协议标记，保持升级前路径",
        )
        target = next_step(
            flow["steps"][target],
            state,
            "continuous",
        )
    return target


def _legacy_delivery_review_events(
        flow, state, target, review_state):
    if (
        target == "delivery_review"
        and not review_state
        and not _moonlight_enabled(state)
    ):
        yield _audit(
            "delivery_review",
            "legacy:skipped-final-review",
            "旧版在途状态没有开发节奏收据，保持升级前路径",
        )
        target = next_step(
            flow["steps"]["delivery_review"],
            state,
        )
    return target


def _checkpoint_review_events(
        flow, state, target, review_state):
    items = (review_state or {}).get("checkpoints") or []
    checkpoints_closed = bool(items) and int(
        (review_state or {}).get("current_index", 0) or 0
    ) >= len(items)
    while (
        not _moonlight_enabled(state)
        and review_state
        and review_state.get("status") == "active"
        and (
            target in LEGACY_CODE_REVIEW_STEPS
            or (
                checkpoints_closed
                and target in REDUNDANT_CHECKPOINT_COMPILE_STEPS
            )
        )
    ):
        bypass = flow["steps"][target]
        if target in REDUNDANT_CHECKPOINT_COMPILE_STEPS:
            yield _audit(
                target,
                "checkpoint:replaced-duplicate-compile",
                "检查点内已完成逐批编译",
            )
            target = next_step(bypass, state)
            continue
        yield _audit(
            target,
            "checkpoint:replaced-legacy-review",
            (
                "分阶段检查点已检视"
                if review_state.get("mode") == "staged"
                else "一次完成模式改在质量链后统一检视"
            ),
        )
        target = next_step(bypass, state, "continue")
    return target


def _moonlight_review_events(flow, state, target):
    seen = set()
    while (
        _moonlight_enabled(state)
        and target
        and target not in seen
        and flow.get("steps", {}).get(target, {}).get(
            "skip_in_moonlight"
        )
    ):
        seen.add(target)
        bypass = flow["steps"][target]
        moonlight_choice = bypass.get("moonlight_choice", "")
        resolved = next_step(
            bypass,
            state,
            moonlight_choice,
        )
        if not resolved:
            raise TransitionResolutionError(target)
        yield _audit(
            target,
            "moonlight:skipped-human-review",
            "无人值守模式不进入编译后用户检视",
        )
        target = resolved
    return target


def _moonlight_archive_events(state, step_id, target):
    if _moonlight_enabled(state) and target == "archive_confirm":
        yield _audit(
            step_id,
            "moonlight:archive-deferred",
            "夜间先推送，规格定稿留到晨间 finalize",
        )
        target = "push"
    return target


def transition_events(flow, state, step_id, step):
    """Yield audit events followed by the final visible transition target."""
    target = next_step(step, state)
    target = yield from _legacy_pace_events(
        flow, state, target)
    review_state = _development_review(state)
    target = yield from _legacy_delivery_review_events(
        flow, state, target, review_state)
    target = yield from _checkpoint_review_events(
        flow, state, target, review_state)
    target = yield from _moonlight_review_events(
        flow, state, target)
    target = yield from _moonlight_archive_events(
        state, step_id, target)

    if _moonlight_enabled(state) and step_id == "push":
        target = "moonlight_review"

    yield TransitionEvent("target", target)
