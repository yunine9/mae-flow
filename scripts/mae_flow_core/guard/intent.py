"""Pure parsing for Mae-Flow Gate requests."""

from dataclasses import dataclass
import re

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


def recursive_delete_targets(intent):
    targets = []
    for segment in re.split(
            r"&&|\|\||[;\n]", intent.subject):
        if not (
            re.search(r"\brm\s+-\S*r", segment, re.I)
            or re.search(r"\b(rd|rmdir)\s+/s", segment, re.I)
        ):
            continue
        destructive = {
            "/",
            "~",
            "*",
            ".",
            "..",
            "$home",
            "%userprofile%",
        }
        for token in re.split(r"""[\s'"]+""", segment):
            lowered = token.lower()
            if (
                token
                and not token.startswith("-")
                and (
                    lowered in destructive
                    or re.match(r"^[a-z]:[\\/]*$", lowered)
                )
            ):
                targets.append(token)
    return tuple(targets)
