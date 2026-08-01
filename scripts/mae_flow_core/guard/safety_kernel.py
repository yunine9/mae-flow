"""Pure, fail-open safety policy for lean workflow tool calls."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
import posixpath

from ..foundation import git_intent
from ..foundation.source_paths import (
    DOCUMENT_EXTENSIONS,
    normalize_path,
    repo_relative_for_match,
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


def _relative_target(context, path):
    if not isinstance(path, str):
        return ""
    normalized = normalize_path(path).strip().strip("\"'")
    if not normalized:
        return ""
    normalized = posixpath.normpath(normalized)
    root = posixpath.normpath(
        normalize_path(context.repository_root).rstrip("/"))
    relative = repo_relative_for_match(normalized, root)
    if relative is None:
        return normalized
    return posixpath.normpath(relative) if relative else "."


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
    targets = tuple(
        relative
        for relative in (
            _relative_target(context, path)
            for path in _write_targets(tool, tool_input)
        )
        if relative
    )
    if any(_is_protected_control(path) for path in targets):
        return _block(
            "protected_control",
            "Mae-Flow control files cannot be edited by workflow tools.",
        )
    safe_targets = _identities(
        relative
        for relative in (
            _relative_target(context, path)
            for path in context.safe_write_targets
        )
        if relative
    )
    controlled_targets = tuple(
        path for path in targets
        if (
            not _is_documentation(path)
            and not _is_local_work_package(path)
            and repository_path_identity(path, case_insensitive=True)
            not in safe_targets
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


def _stage_decision(context, command):
    intents = git_intent.git_add_intents(command)
    if not intents:
        return None
    manifest = _manifest(context)
    for intent in intents:
        paths = intent["pathspecs"]
        if intent["all"]:
            return _block(
                "git_staging",
                "Broad Git staging is not allowed; name exact files.",
            )
        if not paths:
            continue
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


def _opaque_pathspec_decision(command):
    for operation in git_intent.opaque_pathspec_mutations(command):
        if operation == "add":
            return _block(
                "git_staging",
                "Opaque Git staging pathspecs cannot be authorized exactly.",
            )
        if operation == "commit":
            return _block(
                "git_commit",
                "Opaque commit pathspecs cannot be compared with the manifest.",
            )
    return None


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


def _commit_decision(context, command):
    intents = git_intent.git_commit_intents(command)
    if not intents:
        return None
    for intent in intents:
        if intent["all"] or intent["include"] or intent["pathspecs"]:
            return _block(
                "git_commit",
                "Commit must use the already-staged exact manifest.",
            )
        decision = _exact_manifest_decision(
            context, context.staged_files, "git_commit")
        if not decision.allow:
            return decision
    return _allow("git_commit")


def _push_decision(context, command):
    if not git_intent.has_git_subcommand(command, "push"):
        return None
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
        opaque = _opaque_pathspec_decision(command)
        if opaque is not None:
            return opaque
        for evaluator in (_stage_decision, _commit_decision, _push_decision):
            decision = evaluator(context, command)
            if decision is not None and not decision.allow:
                return decision
    return _allow()
