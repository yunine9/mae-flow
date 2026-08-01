"""Immutable orchestration values for lean workflow recovery state."""

from dataclasses import dataclass, replace
from enum import Enum


class DeliveryPath(str, Enum):
    FULL = "full"
    FOCUSED = "focused"


class CommitPace(str, Enum):
    CONTINUOUS = "continuous"
    STAGED = "staged"


class Phase(str, Enum):
    STARTUP = "startup"
    SPEC = "spec"
    STORY = "story"
    CONSTRUCTION = "construction"
    QUALITY = "quality"
    DELIVERY = "delivery"


@dataclass(frozen=True)
class CapabilityAttempt:
    kind: str
    source_revision: str
    environment_revision: str
    outcome: str
    summary: str = ""


@dataclass(frozen=True)
class FlowState:
    ticket: str
    path: DeliveryPath
    phase: Phase
    commit_pace: CommitPace
    status: str = "active"
    current_cp: str = ""
    artifacts: tuple = ()
    decisions: tuple = ()
    risks: tuple = ()
    capabilities: tuple = ()
    delivery_files: tuple = ()
    initial_dirty: tuple = ()

    @classmethod
    def new(cls, ticket, path, pace):
        return cls(ticket, path, Phase.STARTUP, pace)

    def with_decision(self, key, value):
        return replace(self, decisions=self.decisions + ((key, value),))

    def to_dict(self):
        from .state_schema import encode_flow_state
        return encode_flow_state(self)

    @classmethod
    def from_dict(cls, raw):
        from .state_schema import decode_flow_state
        return decode_flow_state(raw)
