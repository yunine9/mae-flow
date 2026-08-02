"""Pure parsing for Mae-Flow Gate requests."""

from dataclasses import dataclass
from collections.abc import Mapping
import ntpath
import os
import posixpath
import re

from ..foundation.git_execution import actual_command_records
from ..foundation.source_paths import (
    DOCUMENT_EXTENSIONS,
    normalize_path,
    repository_path_identity,
)


@dataclass(frozen=True)
class BranchCommand:
    name: str
    creating: bool


@dataclass(frozen=True)
class GateIntent:
    kind: str
    subject: str
    tokens: tuple
    branch: object = None
    execution_subject: str = ""


def write_targets(tool, tool_input):
    if isinstance(tool_input, Mapping):
        value = tool_input.get("targets", ())
        if isinstance(value, str):
            targets = (value,)
        else:
            try:
                targets = tuple(value)
            except TypeError:
                targets = ()
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
    drive, _unused = ntpath.splitdrive(normalized)
    return os.name == "nt" or bool(drive)


def _canonical_repository_root(repository_root):
    normalized = normalize_path(repository_root).strip().strip("\"'")
    if not normalized:
        raise ValueError("repository root is required")
    return posixpath.normpath(normalized)


def relative_target(context, path):
    if not isinstance(path, str):
        return ""
    normalized = normalize_path(path).strip().strip("\"'")
    if not normalized:
        return ""
    root = _canonical_repository_root(context.repository_root)
    root_drive, _unused = ntpath.splitdrive(root)
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


def write_identity(context, path):
    return repository_path_identity(
        path,
        case_insensitive=_uses_windows_paths(context.repository_root),
    )


def is_protected_control(path):
    lowered = repository_path_identity(
        path, case_insensitive=True).casefold()
    first = lowered.split("/", 1)[0]
    if first == ".mae-flow-work":
        return lowered == ".mae-flow-work/moonlight-report.md"
    return (
        first == ".mae-flow"
        or first.startswith(".mae-flow.")
        or first.startswith(".mae-flow-")
        or first == ".codecheckcli"
    )


def is_local_work_package(path):
    identity = repository_path_identity(path, case_insensitive=True)
    return (
        identity == ".mae-flow-work"
        or identity.startswith(".mae-flow-work/")
    )


def is_documentation(path):
    return path.casefold().endswith(DOCUMENT_EXTENSIONS)


def _tokens(command):
    return tuple(
        token
        for token in re.split(
            r"""[\s;|&()<>'"]+""",
            command,
        )
        if token
    )


def _branch_command(command):
    match = re.search(
        r"git\s+(?:checkout\s+-[bB]|switch\s+-[cC])\s+(\S+)"
        r"|git\s+(?:checkout|switch)\s+(?!-)(\S+)"
        r"|git\s+branch\s+(?:-[mM]\s+\S+\s+)?(?!-)(\S+)\s*$",
        command,
    )
    if not match:
        return None
    name = match.group(1) or match.group(2) or match.group(3)
    creating = bool(match.group(1))
    if not creating and (
        " -- " in command
        or name == "."
        or re.fullmatch(
            r"HEAD([~^]\d*)*|FETCH_HEAD|ORIG_HEAD|MERGE_HEAD|@",
            name or "",
            re.I,
        )
        or re.fullmatch(r"[0-9a-f]{7,40}", name or "", re.I)
    ):
        name = ""
    return BranchCommand(name, creating)


def parse_intent(kind, subject):
    normalized = normalize_path(subject)
    tokens = _tokens(normalized) if kind == "bash" else ()
    branch = (
        _branch_command(normalized)
        if kind == "bash"
        else None
    )
    execution_subject = subject if isinstance(subject, str) else ""
    return GateIntent(kind, normalized, tokens, branch, execution_subject)


def hits_path(intent, pattern):
    return any(
        re.search(pattern, token, re.I)
        for token in intent.tokens
    )


def _recursive_delete(record):
    executable = re.split(r"[\\/]", record.executable)[-1].casefold()
    if executable == "rm":
        return any(
                argument == "--recursive"
                or (
                    argument.startswith("-")
                    and not argument.startswith("--")
                    and argument != "--"
                    and "r" in argument.casefold()[1:]
                )
            for argument in record.arguments
        )
    if executable in {"rd", "rmdir", "rd.exe", "rmdir.exe"}:
        return any(
            argument.casefold() == "/s" for argument in record.arguments)
    return False


def _recursive_delete_arguments(record):
    executable = re.split(r"[\\/]", record.executable)[-1].casefold()
    positional = False
    for argument in record.arguments:
        if argument == "--":
            positional = True
            continue
        if executable == "rm" and not positional and argument.startswith("-"):
            continue
        if executable in {"rd", "rmdir", "rd.exe", "rmdir.exe"} and (
                argument.casefold() in {"/s", "/q"}):
            continue
        if argument:
            yield argument


def _execution_records(intent):
    records = actual_command_records(
        intent.execution_subject or intent.subject)
    if not records and intent.execution_subject != intent.subject:
        return actual_command_records(intent.subject)
    return records


def recursive_delete_targets(intent):
    """Return recursive-delete targets only from commands that execute."""
    return tuple(
        normalize_path(token)
        for record in _execution_records(intent)
        if _recursive_delete(record)
        for token in _recursive_delete_arguments(record)
    )
