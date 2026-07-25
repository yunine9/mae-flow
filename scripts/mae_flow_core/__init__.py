"""Mae-Flow harness core.

Only infrastructure that must be shared by the CLI and Hook adapter belongs here.
Workflow semantics stay in flow/modes modules; host event details stay in dispatch.py.
"""

from .runtime import (
    ACTION_FILE,
    EXIT_FILE,
    FLOW_FILE,
    RuntimeMode,
    RuntimeSnapshot,
    find_project_root,
    resolve_runtime,
)
from .capabilities import (
    CAPABILITY_PACKS,
    CapabilityError,
    configure_comet_build,
    diagnostics as capability_diagnostics,
    ensure_codecheck,
    prepare_project,
    render_pack,
    run_comet,
    run_openspec,
)
from .state_store import (
    CURRENT_SCHEMA_VERSION,
    ProjectStateLock,
    StateConflictError,
    StateLockTimeout,
    StateStoreError,
    atomic_write_json,
    atomic_write_text,
    normalize_document,
    read_json,
    safe_read_json,
    save_versioned_json,
    update_json,
    update_versioned_json,
)
from .standalone import (
    action_path,
    action_work_dir,
    archive_action,
    archive_corrupt_action,
    load_action,
    save_action,
    update_action,
)

__all__ = [
    "ACTION_FILE",
    "EXIT_FILE",
    "FLOW_FILE",
    "CURRENT_SCHEMA_VERSION",
    "ProjectStateLock",
    "RuntimeMode",
    "RuntimeSnapshot",
    "CAPABILITY_PACKS",
    "CapabilityError",
    "configure_comet_build",
    "capability_diagnostics",
    "ensure_codecheck",
    "prepare_project",
    "render_pack",
    "run_comet",
    "run_openspec",
    "StateConflictError",
    "StateLockTimeout",
    "StateStoreError",
    "atomic_write_json",
    "atomic_write_text",
    "find_project_root",
    "normalize_document",
    "read_json",
    "resolve_runtime",
    "safe_read_json",
    "save_versioned_json",
    "update_json",
    "update_versioned_json",
    "action_path",
    "action_work_dir",
    "archive_action",
    "archive_corrupt_action",
    "load_action",
    "save_action",
    "update_action",
]
