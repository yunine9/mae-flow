"""Pure fail-closed write and Git boundary for an active Chain."""

from collections.abc import Mapping
import ntpath
import os
import re

from ..foundation import git_intent
from ..foundation.git_execution import actual_command_records
from ..foundation.source_paths import repository_path_identity
from .command_policy import (
    classify_command_mutation,
    dangerous_bash_result,
    recursive_delete_facts,
)
from .intent import write_targets
from .manifest import unknown_git_alias
from .safety_models import SafetyDecision


_WRITERS = {"applypatch", "apply_patch", "edit", "multiedit", "write"}
_DELETERS = {
    "rm", "unlink", "shred", "del", "del.exe", "erase", "erase.exe",
    "remove-item",
}


def _allow(rule="chain_read_only"):
    return SafetyDecision(True, rule=rule)


def _block(rule, message):
    return SafetyDecision(False, rule=rule, message=message)


def _command(tool_input):
    if not isinstance(tool_input, Mapping):
        return ""
    value = tool_input.get("command", "")
    return value if isinstance(value, str) else ""


def _name(value):
    return re.split(r"[\\/]", str(value or ""))[-1].casefold()


def _identity(root, path):
    if not isinstance(path, str) or not path.strip():
        raise ValueError("write target is empty")
    raw = path.strip().strip("\"'").replace("\\", "/")
    drive = ntpath.splitdrive(raw)[0]
    absolute = raw if raw.startswith("/") or drive else os.path.join(root, raw)
    normalized = os.path.abspath(absolute).replace("\\", "/")
    return repository_path_identity(
        normalized,
        case_insensitive=(os.name == "nt" or bool(drive)),
    )


def _exact_document(root, state, targets):
    try:
        document = _identity(root, state.document_path)
        return bool(targets) and all(
            _identity(root, target) == document for target in targets)
    except (TypeError, ValueError):
        return False


def _git_effect(command):
    actions = git_intent.git_actions(command)
    if actions:
        return actions[0].operation
    for operation in ("reset", "switch", "clean"):
        if git_intent.has_git_subcommand(command, operation):
            return operation
    return unknown_git_alias(command)


def _deletes(command):
    return any(
        _name(record.executable) in _DELETERS
        for record in actual_command_records(command)
    )


def _bash_decision(root, state, tool_input):
    command = _command(tool_input)
    if not command:
        return _allow()
    delete_targets = recursive_delete_facts(command)
    rule, message = dangerous_bash_result(command, delete_targets)
    if rule:
        return _block("chain_delete", message)
    mutation = classify_command_mutation(command, tool_input)
    if mutation.interactive:
        return _block(
            "chain_interactive_shell",
            "Interactive shells are disabled while Chain is active.",
        )
    if mutation.destructive or _deletes(command):
        return _block(
            "chain_delete", "Delete effects are forbidden while Chain is active.")
    git_effect = _git_effect(command)
    if git_effect:
        return _block(
            "chain_git",
            "Git %s is forbidden while Chain is active." % git_effect,
        )
    if mutation.opaque_writer:
        return _block(
            "chain_write_scope",
            "Opaque writers cannot prove the exact Chain document target.",
        )
    if mutation.targets:
        return (
            _allow("chain_document_write")
            if _exact_document(root, state, mutation.targets)
            else _block(
                "chain_write_scope",
                "Active Chain may write only its exact local chain.md.",
            )
        )
    return _allow()


def decide_chain_pretool(root, state, tool, tool_input):
    """Allow inspection and exact ``chain.md`` writes, but no repo effects."""
    if os.path.realpath(state.anchor_root) != os.path.realpath(root):
        return _block("chain_owner", "Chain does not own this anchor root.")
    normalized_tool = str(tool or "").casefold().replace("-", "_")
    if normalized_tool in {"write_stdin", "writestdin"}:
        return _block(
            "chain_interactive_shell",
            "Interactive shells can bypass per-command Chain safety.",
        )
    if normalized_tool == "bash":
        return _bash_decision(root, state, tool_input)
    targets = write_targets(tool, tool_input)
    if normalized_tool not in _WRITERS and not targets:
        return _allow()
    return (
        _allow("chain_document_write")
        if _exact_document(root, state, targets)
        else _block(
            "chain_write_scope",
            "Active Chain may write only its exact local chain.md.",
        )
    )
