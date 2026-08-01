"""Pure parsing for Mae-Flow Gate requests."""

from dataclasses import dataclass
import re

from ..foundation.git_execution import actual_command_records
from ..foundation.source_paths import normalize_path


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
    return GateIntent(kind, normalized, tokens, branch)


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


def _dangerous_delete_target(token):
    lowered = token.casefold()
    return (
        bool(token)
        and token != "--"
        and not token.startswith("-")
        and lowered not in {"/s", "/q"}
        and (
            lowered in {
                "/", "~", "*", ".", "..", "$home", "%userprofile%",
            }
            or bool(re.fullmatch(r"[a-z]:[\\/]*", lowered))
        )
    )


def recursive_delete_targets(intent):
    """Return dangerous roots only from commands that actually execute."""
    return tuple(
        normalize_path(token)
        for record in actual_command_records(intent.subject)
        if _recursive_delete(record)
        for token in record.arguments
        if _dangerous_delete_target(token)
    )
