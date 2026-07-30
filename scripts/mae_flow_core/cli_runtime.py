"""Public composition root for Mae-Flow CLI commands."""

import sys
import types
from .cli_commands import shared
from .cli_commands.shared import *  # noqa: F401,F403
from .cli_commands.wiring import api
from .cli_commands import git_authorization as _git_authorization
from .cli_commands import git_ownership as _git_ownership
from .cli_commands import state_config as _state_config
from .cli_commands import source_facts as _source_facts
from .cli_commands import checkpoint_facts as _checkpoint_facts
from .cli_commands import lightcheck as _lightcheck
from .cli_commands import codecheck_facts as _codecheck_facts
from .cli_commands import ack as _ack
from .cli_commands import current as _current
from .cli_commands import standalone_core as _standalone_core
from .cli_commands import standalone_commands as _standalone_commands
from .cli_commands import direct_reentry as _direct_reentry
from .cli_commands import init_capability as _init_capability
from .cli_commands import advancement as _advancement
from .cli_commands import checkpoint_plan as _checkpoint_plan
from .cli_commands import checkpoint_commands as _checkpoint_commands
from .cli_commands import done_status as _done_status
from .cli_commands import gate_permit_state as _gate_permit_state
from .cli_commands import spec as _spec
from .cli_commands import gate as _gate
from .cli_commands import agent_task as _agent_task
from .cli_commands import quality_artifacts as _quality_artifacts
from .cli_commands import role_task as _role_task
from .cli_commands import codecheck_commands as _codecheck_commands
from .cli_commands import story_diag as _story_diag
from .cli_commands import moonlight_commands as _moonlight_commands
from .cli_commands import lifecycle as _lifecycle
from .cli_commands import dispatch as _dispatch

api.register(shared)
_COMMAND_MODULES = (
    _git_authorization,
    _git_ownership,
    _state_config,
    _source_facts,
    _checkpoint_facts,
    _lightcheck,
    _codecheck_facts,
    _ack,
    _current,
    _standalone_core,
    _standalone_commands,
    _direct_reentry,
    _init_capability,
    _advancement,
    _checkpoint_plan,
    _checkpoint_commands,
    _done_status,
    _gate_permit_state,
    _spec,
    _gate,
    _agent_task,
    _quality_artifacts,
    _role_task,
    _codecheck_commands,
    _story_diag,
    _moonlight_commands,
    _lifecycle,
    _dispatch,
)
for _module in _COMMAND_MODULES:
    api.register(_module)

from .cli_commands import evidence_registry as _evidence_registry
api.register(_evidence_registry)
_EVIDENCE_COMPAT_NAMES = {
    "EVIDENCE",
    "_AGENT_EVIDENCE",
    "_DELIVERY_EVIDENCE",
    "_EVIDENCE_REGISTRY",
    "_QUALITY_EVIDENCE",
    "_WORKFLOW_EVIDENCE",
}
api.register_values({
    name: value
    for name, value in vars(_evidence_registry).items()
    if name in _EVIDENCE_COMPAT_NAMES or name.startswith("ev_")
})
globals().update(api.exports())

class _CliRuntimeModule(types.ModuleType):
    def __getattribute__(self, name):
        if name == "FLOW":
            return api.FLOW
        return super().__getattribute__(name)

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        if not name.startswith("__"):
            setattr(api, name, value)

sys.modules[__name__].__class__ = _CliRuntimeModule

def __getattr__(name):
    return getattr(api, name)
