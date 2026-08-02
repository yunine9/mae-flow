"""Small immutable inputs and outputs for the lean safety policy."""

from dataclasses import dataclass

from ..orchestration.models import FlowState


@dataclass(frozen=True)
class SafetyDecision:
    allow: bool
    rule: str = ""
    message: str = ""


@dataclass(frozen=True)
class SafetyContext:
    state: FlowState
    repository_root: str
    staged_files: tuple = ()
    commit_files: tuple = ()
    initial_dirty: tuple = ()
    current_dirty_fingerprints: tuple = ()
    safe_write_targets: tuple = ()
    task_owned_temp_dir: str = ""
    current_branch: str = ""
