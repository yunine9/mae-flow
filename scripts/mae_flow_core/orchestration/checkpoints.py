"""Small recoverable checkpoint briefs, results, reviews, and UT intents."""

from dataclasses import dataclass, replace

from .models import FlowState
from .transition_facts import checkpoint_name


_PREFIX = "construction.cp."
_FACTS = {"brief", "result", "review", "ut-intent"}


@dataclass(frozen=True)
class CheckpointFacts:
    name: str
    brief: str = ""
    result: str = ""
    review: str = ""
    ut_intent: str = ""


def _key(checkpoint, fact):
    if fact not in _FACTS:
        raise ValueError("unsupported checkpoint fact")
    return "%s%s.%s" % (_PREFIX, checkpoint_name(checkpoint), fact)


def record_checkpoint_fact(state, checkpoint, fact, text):
    if not isinstance(state, FlowState):
        raise TypeError("state must be a FlowState")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("checkpoint fact must be non-empty natural language")
    key = _key(checkpoint, fact)
    value = text.strip()
    decisions = list(state.decisions)
    for index, item in enumerate(decisions):
        if item[0] == key:
            decisions[index] = (key, value)
            break
    else:
        decisions.append((key, value))
    return replace(state, decisions=tuple(decisions))


def checkpoint_facts(state):
    if not isinstance(state, FlowState):
        raise TypeError("state must be a FlowState")
    order = []
    values = {}
    for key, value in state.decisions:
        if not key.startswith(_PREFIX):
            continue
        remainder = key[len(_PREFIX):]
        if "." not in remainder:
            continue
        checkpoint, fact = remainder.rsplit(".", 1)
        if fact not in _FACTS:
            continue
        if checkpoint not in values:
            values[checkpoint] = {}
            order.append(checkpoint)
        values[checkpoint][fact] = value
    return tuple(
        CheckpointFacts(
            name,
            brief=values[name].get("brief", ""),
            result=values[name].get("result", ""),
            review=values[name].get("review", ""),
            ut_intent=values[name].get("ut-intent", ""),
        )
        for name in order
    )


def checkpoint_context(state, checkpoint):
    name = checkpoint_name(checkpoint)
    for item in checkpoint_facts(state):
        if item.name == name:
            return item
    return CheckpointFacts(name)


def next_checkpoint_context(state, checkpoint):
    name = checkpoint_name(checkpoint)
    items = checkpoint_facts(state)
    for index, item in enumerate(items):
        if item.name == name and index + 1 < len(items):
            return items[index + 1]
    return None


def cumulative_ut_handoff(state):
    return "\n".join(
        "%s: %s" % (item.name, item.ut_intent)
        for item in checkpoint_facts(state) if item.ut_intent)
