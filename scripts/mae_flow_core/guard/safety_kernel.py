"""Pure, fail-open safety policy for lean workflow tool calls."""
from collections.abc import Mapping
from dataclasses import replace
import os

from ..foundation import git_intent
from ..foundation.commit_message import valid_business_commit_message
from ..foundation.source_paths import repository_path_identity
from ..orchestration.models import DeliveryPath, FlowState, Phase
from .command_policy import (
    classify_command_mutation,
    dangerous_bash_result,
    recursive_delete_facts,
)
from .manifest import (
    DeliveryManifest,
    authorize_delivery,
    git_receipt_error,
    unknown_git_alias,
)
from .safety_models import SafetyContext, SafetyDecision
from .intent import (
    is_documentation as _is_documentation,
    is_local_work_package as _is_local_work_package,
    is_protected_control as _is_protected_control,
    relative_target as _relative_target,
    write_identity as _write_identity,
    write_targets as _write_targets,
)


_ADOPTED_DIRTY = "delivery.adopted_dirty"
_FOCUSED_SCOPE_APPROVED = "focused.scope_approved"


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


def _has_decision(state, key):
    return any(existing == key for existing, unused in state.decisions)


def _source_edit_allowed(state):
    if state.path == DeliveryPath.FOCUSED:
        return _has_decision(state, _FOCUSED_SCOPE_APPROVED)
    if state.path != DeliveryPath.FULL:
        return False
    return state.phase == Phase.CONSTRUCTION


def _relative_write_targets(context, tool, tool_input):
    targets = []
    ambiguous = False
    for path in _write_targets(tool, tool_input):
        try:
            relative = _relative_target(context, path)
            if relative:
                targets.append(relative)
        except ValueError:
            ambiguous = True
    return tuple(targets), ambiguous


def _safe_write_identities(context):
    identities = set()
    for path in context.safe_write_targets:
        try:
            relative = _relative_target(context, path)
        except ValueError:
            continue
        if relative:
            identities.add(_write_identity(context, relative))
    return identities


def _task_temp_identity(context):
    if not context.task_owned_temp_dir:
        return ""
    try:
        task_temp = _relative_target(context, context.task_owned_temp_dir)
        return _write_identity(context, task_temp).rstrip("/")
    except ValueError:
        return ""


def _inside_task_temp(identity, task_temp):
    return bool(
        task_temp
        and (identity.rstrip("/") == task_temp
             or identity.startswith(task_temp + "/"))
    )


def _controlled_write_targets(context, targets):
    safe = _safe_write_identities(context)
    task_temp = _task_temp_identity(context)
    controlled = []
    for path in targets:
        identity = _write_identity(context, path)
        if (
                not _is_documentation(path)
                and not _is_local_work_package(path)
                and identity not in safe
                and not _inside_task_temp(identity, task_temp)):
            controlled.append(path)
    return tuple(controlled)


def _edit_decision(context, tool, tool_input, opaque_writer=False):
    targets, ambiguous = _relative_write_targets(context, tool, tool_input)
    if any(_is_protected_control(path) for path in targets):
        return _block(
            "protected_control",
            "Mae-Flow control files cannot be edited by workflow tools.",
        )
    if ambiguous:
        return _block(
            "source_edit",
            "Write targets must be unambiguous repository paths.",
        )
    if opaque_writer:
        return _block(
            "source_edit",
            "A recognized writer must name literal repository targets.",
        )
    controlled_targets = _controlled_write_targets(context, targets)
    if controlled_targets and not _source_edit_allowed(context.state):
        return _block(
            "source_edit",
            "Source edits require semantic authorization for this path and phase.",
        )
    return None


def _unsafe_delete_targets(context, targets):
    if not context.task_owned_temp_dir:
        return tuple(targets)
    try:
        task_temp = _relative_target(context, context.task_owned_temp_dir)
        task_identity = _write_identity(context, task_temp).rstrip("/")
    except ValueError:
        return tuple(targets)
    unsafe = []
    for target in targets:
        try:
            relative = _relative_target(context, target)
            identity = _write_identity(context, relative).rstrip("/")
        except ValueError:
            unsafe.append(target)
            continue
        if identity != task_identity and not identity.startswith(
                task_identity + "/"):
            unsafe.append(target)
    return tuple(unsafe)


def _dangerous_bash_decision(context, command, tool_input):
    supplied = _values(tool_input, "recursive_delete_targets")
    delete_targets = supplied or recursive_delete_facts(command)
    rule, message = dangerous_bash_result(
        command, _unsafe_delete_targets(context, delete_targets))
    return _block(rule, message) if rule else None


def _interactive_shell_decision(tool, tool_input, command):
    normalized = str(tool or "").casefold().replace("-", "_")
    if normalized in {"write_stdin", "writestdin"}:
        return _block(
            "interactive_shell",
            "Reused interactive shells bypass per-command PreToolUse safety.",
        )
    if normalized != "bash":
        return None
    mutation = classify_command_mutation(command, tool_input)
    if mutation.interactive:
        return _block(
            "interactive_shell",
            "Interactive, TTY, background, and reused shells are disabled "
            "while Mae-Flow is active.",
        )
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
    receipt_error = git_receipt_error(
        context.state, "add", requested.files, intent.arguments)
    if receipt_error:
        return _block("git_staging", receipt_error)
    return _allow("git_staging")


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
    message = _commit_message(intent.arguments)
    ticket = context.state.ticket
    config = context.state.startup_config
    expected_branch = config.working_branch
    if expected_branch and context.current_branch != expected_branch:
        return _block(
            "git_commit",
            "Commit must run on the confirmed working branch %s; current is %s."
            % (expected_branch, context.current_branch or "unknown"),
        )
    if not valid_business_commit_message(
            ticket, message, config.ticket_type):
        expected_type = config.ticket_type or "feat|fix"
        return _block(
            "git_commit",
            "Commit message must use [%s][%s]描述."
            % (ticket or "单号", expected_type),
        )
    receipt_error = git_receipt_error(
        context.state, "commit", context.staged_files,
        intent.arguments, message or "")
    return (
        _block("git_commit", receipt_error)
        if receipt_error else _allow("git_commit"))


def _commit_message(arguments):
    for index, token in enumerate(arguments):
        if token in ("-m", "--message"):
            return arguments[index + 1] if index + 1 < len(arguments) else ""
        if token.startswith("--message="):
            return token.split("=", 1)[1]
        if token.startswith("-m") and token != "-m":
            return token[2:]
    return None


def _push_decision(context, intent):
    if intent.opaque_pathspec:
        return _block(
            "git_publish",
            "Opaque wrapped Git publish cannot be authorized exactly.",
        )
    receipt_error = git_receipt_error(
        context.state, "push", context.commit_files, intent.arguments)
    return (
        _block("git_publish", receipt_error)
        if receipt_error else _allow("git_publish"))


def _mutation_precheck(context, tool, tool_input, command):
    interactive = _interactive_shell_decision(tool, tool_input, command)
    if interactive is not None:
        return interactive, None
    mutation = classify_command_mutation(command, tool_input) if command else None
    if not command:
        return None, mutation
    dangerous = _dangerous_bash_decision(context, command, tool_input)
    if dangerous is not None:
        return dangerous, mutation
    if mutation.destructive:
        return _block(
            "filesystem",
            "Recursive or destructive filesystem mutation requires "
            "explicit user handling.",
        ), mutation
    return None, mutation


def _classified_write_input(tool_input, mutation):
    if mutation is None or not mutation.targets:
        return tool_input
    classified = dict(tool_input) if isinstance(tool_input, Mapping) else {}
    classified["targets"] = _values(
        classified, "targets") + mutation.targets
    return classified


def _git_delivery_decision(context, command):
    for intent in git_intent.git_delivery_intents(command):
        if intent.operation == "add":
            decision = _stage_decision(context, intent)
        elif intent.operation == "commit":
            decision = _commit_decision(context, intent)
        else:
            decision = _push_decision(context, intent)
        if not decision.allow:
            return decision
    alias = unknown_git_alias(command)
    if alias:
        return _block(
            "git_alias",
            "Unknown Git alias invocation is fail-closed: %s." % alias,
        )
    return None


def decide_pretool(context, tool, tool_input):
    """Return the first narrow safety rule for one already-factored tool call."""
    if not isinstance(context, SafetyContext):
        raise TypeError("context must be a SafetyContext")
    if not isinstance(context.state, FlowState):
        raise TypeError("context.state must be a FlowState")

    command = (
        _command(tool_input)
        if str(tool or "").casefold() == "bash"
        else ""
    )
    precheck, mutation = _mutation_precheck(
        context, tool, tool_input, command)
    if precheck is not None:
        return precheck
    classified_input = _classified_write_input(tool_input, mutation)
    edit = _edit_decision(
        context,
        tool,
        classified_input,
        opaque_writer=bool(mutation and mutation.opaque_writer),
    )
    if edit is not None:
        return edit

    if command:
        delivery = _git_delivery_decision(context, command)
        if delivery is not None:
            return delivery
    return _allow()


def decide_stateless_pretool(
        repository_root, tool, tool_input, task_owned_temp_dir=""):
    """Keep confirmed danger blocked when FlowState cannot be decoded."""
    context = SafetyContext(
        state=None,
        repository_root=repository_root,
        task_owned_temp_dir=task_owned_temp_dir,
    )
    normalized_tool = str(tool or "").casefold()
    command = _command(tool_input) if normalized_tool == "bash" else ""
    mutation = (
        classify_command_mutation(command, tool_input) if command else None)
    classified_input = _classified_write_input(tool_input, mutation)
    targets, unused_ambiguous = _relative_write_targets(
        context, tool, classified_input)
    if (os.path.isfile(os.path.join(repository_root, ".mae-flow.json"))
            and any(_is_protected_control(path) for path in targets)):
        return _block(
            "protected_control",
            "Corrupt Mae-Flow control files remain single-writer state.",
        )
    if normalized_tool != "bash":
        return _allow()
    if not command:
        return _allow()
    dangerous = _dangerous_bash_decision(context, command, tool_input)
    if dangerous is not None:
        return dangerous
    alias = unknown_git_alias(command)
    if alias:
        return _block("git_alias", "Unknown Git alias is fail-closed.")
    if any(
            intent.operation in ("commit", "push")
            for intent in git_intent.git_delivery_intents(command)):
        return _block(
            "git_delivery",
            "Delivery is blocked because the exact manifest state is unavailable.",
        )
    return _allow()
