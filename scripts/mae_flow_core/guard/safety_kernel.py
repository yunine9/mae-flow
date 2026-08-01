"""Pure, fail-open safety policy for lean workflow tool calls."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
import ntpath
import os
import posixpath

from ..foundation import git_intent
from ..foundation.source_paths import (
    DOCUMENT_EXTENSIONS,
    normalize_path,
    repository_path_identity,
)
from ..orchestration import DeliveryPath, FlowState, Phase
from .bash import BashGateContext, decide_post_commit
from .intent import parse_intent, recursive_delete_targets
from .manifest import DeliveryManifest, authorize_delivery, compare_staged


_ADOPTED_DIRTY = "delivery.adopted_dirty"
_FOCUSED_SCOPE_APPROVED = "focused.scope_approved"
_QUALITY_SOURCE_FIX_APPROVED = "quality.source_fix_approved"
_DESTRUCTIVE_BASH_RULES = {
    "bash-force-push",
    "bash-git-clean-ignored",
    "bash-wipe-worktree",
}


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


def _allow(rule=""):
    return SafetyDecision(True, rule=rule)


def _block(rule, message):
    return SafetyDecision(False, rule=rule, message=message)


def _values(input_value, key):
    if not isinstance(input_value, Mapping):
        return ()
    value = input_value.get(key, ())
    if isinstance(value, str):
        return (value,)
    try:
        return tuple(value)
    except TypeError:
        return ()


def _command(tool_input):
    if isinstance(tool_input, str):
        return tool_input
    if isinstance(tool_input, Mapping):
        value = tool_input.get("command", "")
        return value if isinstance(value, str) else ""
    return ""


def _write_targets(tool, tool_input):
    targets = _values(tool_input, "targets")
    if targets:
        return targets
    if not isinstance(tool_input, Mapping):
        return ()
    if str(tool or "").lower() not in {
            "applypatch", "apply_patch", "edit", "multiedit", "write"}:
        return ()
    for key in ("file_path", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return (value,)
    return ()


def _uses_windows_paths(repository_root):
    normalized = normalize_path(repository_root).strip().strip("\"'")
    drive, _ = ntpath.splitdrive(normalized)
    return os.name == "nt" or bool(drive)


def _canonical_repository_root(repository_root):
    normalized = normalize_path(repository_root).strip().strip("\"'")
    if not normalized:
        raise ValueError("repository root is required")
    return posixpath.normpath(normalized)


def _relative_target(context, path):
    if not isinstance(path, str):
        return ""
    normalized = normalize_path(path).strip().strip("\"'")
    if not normalized:
        return ""
    root = _canonical_repository_root(context.repository_root)
    root_drive, _ = ntpath.splitdrive(root)
    target_drive, target_tail = ntpath.splitdrive(normalized)
    if target_drive and not target_tail.startswith("/"):
        raise ValueError("drive-relative write targets are ambiguous")
    if target_drive:
        canonical = posixpath.normpath(normalized)
    elif normalized.startswith("/"):
        if root_drive and not normalized.startswith("//"):
            canonical = posixpath.normpath(root_drive + normalized)
        else:
            canonical = posixpath.normpath(normalized)
    else:
        canonical = posixpath.normpath(posixpath.join(root, normalized))

    case_insensitive = _uses_windows_paths(context.repository_root)
    root_identity = repository_path_identity(
        root, case_insensitive=case_insensitive)
    canonical_identity = repository_path_identity(
        canonical, case_insensitive=case_insensitive)
    if canonical_identity == root_identity:
        return "."
    root_prefix = root_identity.rstrip("/") + "/"
    if canonical_identity.startswith(root_prefix):
        return canonical[len(root.rstrip("/")) + 1:]
    return canonical


def _write_identity(context, path):
    return repository_path_identity(
        path,
        case_insensitive=_uses_windows_paths(context.repository_root),
    )


def _is_protected_control(path):
    lowered = repository_path_identity(
        path, case_insensitive=True).casefold()
    first = lowered.split("/", 1)[0]
    if first == ".mae-flow-work":
        return lowered == ".mae-flow-work/moonlight-report.md"
    return (
        first == ".mae-flow"
        or first.startswith(".mae-flow.")
        or first.startswith(".mae-flow-")
    )


def _is_local_work_package(path):
    identity = repository_path_identity(path, case_insensitive=True)
    return (
        identity == ".mae-flow-work"
        or identity.startswith(".mae-flow-work/")
    )


def _is_documentation(path):
    return path.casefold().endswith(DOCUMENT_EXTENSIONS)


def _has_decision(state, key):
    return any(existing == key for existing, unused in state.decisions)


def _source_edit_allowed(state):
    if state.path == DeliveryPath.FOCUSED:
        return _has_decision(state, _FOCUSED_SCOPE_APPROVED)
    if state.path != DeliveryPath.FULL:
        return False
    if state.phase == Phase.CONSTRUCTION:
        return True
    return (
        state.phase == Phase.QUALITY
        and _has_decision(state, _QUALITY_SOURCE_FIX_APPROVED)
    )


def _edit_decision(context, tool, tool_input):
    targets = []
    try:
        for path in _write_targets(tool, tool_input):
            relative = _relative_target(context, path)
            if relative:
                targets.append(relative)
    except ValueError:
        return _block(
            "source_edit",
            "Write targets must be unambiguous repository paths.",
        )
    if any(_is_protected_control(path) for path in targets):
        return _block(
            "protected_control",
            "Mae-Flow control files cannot be edited by workflow tools.",
        )
    safe_targets = set()
    for path in context.safe_write_targets:
        try:
            relative = _relative_target(context, path)
        except ValueError:
            continue
        if relative:
            safe_targets.add(_write_identity(context, relative))
    controlled_targets = tuple(
        path for path in targets
        if (
            not _is_documentation(path)
            and not _is_local_work_package(path)
            and _write_identity(context, path) not in safe_targets
        )
    )
    if controlled_targets and not _source_edit_allowed(context.state):
        return _block(
            "source_edit",
            "Source edits require semantic authorization for this path and phase.",
        )
    return None


def _bash_gate_context(command, delete_targets):
    return BashGateContext(
        command=command,
        has_internal_state_path=False,
        branch_name="",
        branch_creating=False,
        step="",
        wanted_branch="",
        base_branch="",
        checkpoint_locked=False,
        checkpoint_label="",
        checkpoint_status="",
        ticket="",
        commit_message_present=False,
        commit_message="",
        current_branch="",
        add_paths=(),
        recursive_delete_targets=tuple(delete_targets),
        state_active=True,
    )


def _dangerous_bash_decision(command, tool_input):
    supplied = _values(tool_input, "recursive_delete_targets")
    delete_targets = supplied or recursive_delete_targets(
        parse_intent("bash", command))
    gate = decide_post_commit(_bash_gate_context(command, delete_targets))
    if gate.rule == "bash-recursive-delete":
        return _block("filesystem", gate.message)
    if gate.rule in _DESTRUCTIVE_BASH_RULES:
        return _block("git_destructive", gate.message)
    return None


def _adopted_paths(state):
    return tuple(
        value for key, value in state.decisions
        if key == _ADOPTED_DIRTY
    )


def _manifest(context):
    try:
        manifest = DeliveryManifest.from_paths(
            context.state.delivery_files,
            adopted_dirty=_adopted_paths(context.state),
            repository_root=context.repository_root,
        )
        validation_state = replace(
            context.state,
            initial_dirty=_initial_dirty_paths(context),
        )
        authorize_delivery(validation_state, manifest)
        return manifest
    except (TypeError, ValueError):
        return None


def _identities(paths):
    return {
        repository_path_identity(path, case_insensitive=True)
        for path in paths
        if isinstance(path, str)
    }


def _initial_dirty_paths(context):
    paths = []
    seen = set()

    def append(path):
        identity = repository_path_identity(path, case_insensitive=True)
        if identity not in seen:
            seen.add(identity)
            paths.append(path)

    for path in context.state.initial_dirty:
        if isinstance(path, str):
            append(path)
    for item in context.initial_dirty:
        if isinstance(item, str):
            append(item)
        elif (
                isinstance(item, (list, tuple))
                and len(item) == 2
                and isinstance(item[0], str)):
            append(item[0])
    return tuple(paths)


def _manifest_has_unadopted_dirty(context, manifest):
    initial = _identities(_initial_dirty_paths(context))
    adopted = _identities(manifest.adopted_dirty)
    delivery = _identities(manifest.files)
    return bool((initial & delivery) - adopted)


def _stage_decision(context, intent):
    if intent.opaque_pathspec:
        return _block(
            "git_staging",
            "Opaque Git staging pathspecs cannot be authorized exactly.",
        )
    manifest = _manifest(context)
    paths = intent.pathspecs
    if intent.all:
        return _block(
            "git_staging",
            "Broad Git staging is not allowed; name exact files.",
        )
    if not paths:
        return _allow("git_staging")
    try:
        requested = DeliveryManifest.from_paths(
            paths, repository_root=context.repository_root)
    except (TypeError, ValueError):
        return _block(
            "git_staging",
            "Git staging pathspecs must identify exact files.",
        )
    if manifest is None or not manifest.files:
        return _block(
            "git_staging",
            "Git staging requires an authorized delivery manifest.",
        )
    if not _identities(requested.files).issubset(
            _identities(manifest.files)):
        return _block(
            "git_staging",
            "Git staging includes files outside the authorized manifest.",
        )
    dirty = _identities(_initial_dirty_paths(context))
    adopted = _identities(manifest.adopted_dirty)
    if (_identities(requested.files) & dirty) - adopted:
        return _block(
            "git_staging",
            "Startup-dirty files require explicit manifest adoption.",
        )
    return _allow("git_staging")


def _exact_manifest_decision(context, actual_files, rule):
    manifest = _manifest(context)
    if (
            manifest is None
            or not manifest.files
            or _manifest_has_unadopted_dirty(context, manifest)):
        return _block(
            rule,
            "Delivery requires an authorized manifest with explicit dirty adoption.",
        )
    try:
        comparison = compare_staged(manifest, actual_files)
    except (TypeError, ValueError):
        return _block(rule, "Delivery file facts are not exact repository files.")
    if not comparison.matches:
        return _block(
            rule,
            "Delivery files do not exactly match the authorized manifest.",
        )
    return _allow(rule)


def _commit_decision(context, intent):
    if intent.opaque_pathspec:
        return _block(
            "git_commit",
            "Opaque commit pathspecs cannot be compared with the manifest.",
        )
    if intent.all or intent.include or intent.pathspecs:
        return _block(
            "git_commit",
            "Commit must use the already-staged exact manifest.",
        )
    return _exact_manifest_decision(
        context, context.staged_files, "git_commit")


def _push_decision(context):
    return _exact_manifest_decision(
        context, context.commit_files, "git_publish")


def decide_pretool(context, tool, tool_input):
    """Return the first narrow safety rule for one already-factored tool call."""
    if not isinstance(context, SafetyContext):
        raise TypeError("context must be a SafetyContext")
    if not isinstance(context.state, FlowState):
        raise TypeError("context.state must be a FlowState")

    command = _command(tool_input)
    if command:
        dangerous = _dangerous_bash_decision(command, tool_input)
        if dangerous is not None:
            return dangerous

    edit = _edit_decision(context, tool, tool_input)
    if edit is not None:
        return edit

    if command:
        for intent in git_intent.git_delivery_intents(command):
            if intent.operation == "add":
                decision = _stage_decision(context, intent)
            elif intent.operation == "commit":
                decision = _commit_decision(context, intent)
            else:
                decision = _push_decision(context)
            if not decision.allow:
                return decision
    return _allow()
