"""Exact, read-only Git facts supplied to the lean Hook safety kernel."""

import locale
import os
import re
import subprocess

from ..foundation.git_intent import git_delivery_intents
from ..foundation.git_shell import (
    _global_option_width,
    shell_command_records,
)


GIT_SECS = 5
_PUSH_VALUE_OPTIONS = {
    "--repo", "--receive-pack", "--exec", "-o", "--push-option",
}
_PUSH_FLAGS = {
    "-f", "--force", "--force-if-includes", "--dry-run", "--porcelain",
    "--prune", "--no-verify", "--follow-tags", "--atomic", "--ipv4",
    "--ipv6", "-u", "--set-upstream", "-q", "--quiet", "-v",
    "--verbose",
}
_AMBIGUOUS_PUSH_FLAGS = {"--all", "--mirror", "--tags", "--delete"}
_SAFE_REF = re.compile(r"[A-Za-z0-9._/-]+")
_CONTEXT_OPTIONS = {
    "-C", "--bare", "--git-dir", "--work-tree", "--namespace",
}
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")
_OPAQUE_CONTEXT_OPERATIONS = {
    ".", "eval", "popd", "pushd", "shopt", "source", "trap",
}
_SAFE_REMOTE_CONFIG = {
    "partialclonefilter", "promisor", "proxy", "proxyauthmethod",
    "prune", "prunetags", "pushoption", "receivepack",
    "skipdefaultupdate", "skipfetchall", "tagopt", "uploadpack", "vfs",
}
_SAFE_BRANCH_CONFIG = {"description", "mergeoptions", "rebase"}
_SAFE_PUSH_CONFIG = {
    "gpgsign", "negotiate", "pushoption", "usebitmaps",
    "useforceifincludes",
}


def _decode_paths(raw):
    encodings = ["utf-8"]
    for encoding in (locale.getpreferredencoding(False), "gb18030"):
        normalized = str(encoding or "").lower().replace("-", "")
        if normalized and all(
                normalized != item.lower().replace("-", "")
                for item in encodings):
            encodings.append(encoding)
    for encoding in encodings:
        try:
            text = raw.decode(encoding, errors="strict")
            return tuple(path for path in text.split("\0") if path)
        except (UnicodeDecodeError, LookupError):
            continue
    return ()


def git_paths(root, arguments):
    """Return exact NUL-delimited repository paths or no facts on failure."""
    try:
        result = subprocess.run(
            ["git", "-c", "core.quotepath=false"] + list(arguments),
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=GIT_SECS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    return _decode_paths(result.stdout) if result.returncode == 0 else ()


def git_text(root, arguments):
    try:
        result = subprocess.run(
            ["git", "-c", "core.quotepath=false"] + list(arguments),
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=GIT_SECS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    paths = _decode_paths(result.stdout + b"\0")
    return paths[0].strip() if len(paths) == 1 else ""


def staged_files(root):
    return git_paths(
        root,
        ("diff", "--cached", "--name-only", "--diff-filter=ACDMRTUXB",
         "-z", "--"),
    )


def _context_environment_name(value):
    name = str(value or "").split("=", 1)[0].upper()
    return name if (
        name in {"GIT_DIR", "GIT_WORK_TREE", "GIT_NAMESPACE"}
        or name.startswith("GIT_CONFIG_")
    ) else ""


def _remote_changing_config(value):
    key = str(value or "").split("=", 1)[0].casefold()
    if key == "remote.pushdefault":
        return True
    remote = re.fullmatch(r"remote\..+\.([^.]+)", key)
    if remote:
        return remote.group(1) not in _SAFE_REMOTE_CONFIG
    branch = re.fullmatch(r"branch\..+\.([^.]+)", key)
    if branch:
        return branch.group(1) not in _SAFE_BRANCH_CONFIG
    if key.startswith("push."):
        return key[5:] not in _SAFE_PUSH_CONFIG
    return bool(
        key.startswith("url.")
        or key == "include.path"
        or key.startswith("includeif.")
        or key.startswith("submodule.")
    )


def _inline_context_changed(tokens, git_index, push_index):
    context = tokens[:git_index] + tokens[git_index + 1:push_index]
    index = 0
    while index < len(context):
        value = context[index]
        option = value.split("=", 1)[0]
        if (
                option in _CONTEXT_OPTIONS
                or value.startswith("-C") and value != "-C"
                or _context_environment_name(value)):
            return True
        if value == "-c":
            index += 1
            if index >= len(context) or _remote_changing_config(context[index]):
                return True
        elif value.startswith("-c") and value != "-c":
            if _remote_changing_config(value[2:]):
                return True
        elif option == "--config-env":
            configured = (
                value.split("=", 1)[1]
                if "=" in value else (
                    context[index + 1] if index + 1 < len(context) else "")
            )
            if not configured or _remote_changing_config(configured):
                return True
            if "=" not in value:
                index += 1
        index += 1
    return any(
        value == "--repo" or value.startswith("--repo=")
        for value in tokens[push_index + 1:])


def _next_shell_cwd(current, arguments):
    arguments = list(arguments)
    if arguments[:1] == ["--"]:
        arguments = arguments[1:]
    if (
            len(arguments) != 1
            or arguments[0] == "-"
            or any(marker in arguments[0] for marker in ("$", "`", "%"))):
        return None
    path = arguments[0]
    if not os.path.isabs(path):
        if current is None:
            return None
        path = os.path.join(current, path)
    return os.path.normcase(os.path.realpath(path))


def _next_context_environment(active, operation, arguments):
    if active is None:
        return None
    updated = set(active)
    if operation in {"export", "set"}:
        for value in arguments:
            name = _context_environment_name(value)
            if name:
                updated.add(name)
    elif operation == "unset":
        for value in arguments:
            name = _context_environment_name(value)
            if name:
                updated.discard(name)
    elif operation == "assignment":
        for value in arguments:
            name = _context_environment_name(value)
            if name:
                updated.add(name)
    return frozenset(updated)


def _operation_position(tokens):
    index = 0
    while index < len(tokens) and _ASSIGNMENT.fullmatch(tokens[index]):
        index += 1
    while index < len(tokens) and tokens[index] == "!":
        index += 1
    return index


def _persistent_context_after(state, tokens):
    cwd, environment, opaque = state
    operation_index = _operation_position(tokens)
    if operation_index >= len(tokens):
        return (
            cwd,
            _next_context_environment(
                environment, "assignment", tokens),
            opaque,
        )

    operation = tokens[operation_index].casefold()
    arguments = tokens[operation_index + 1:]
    if operation == "cd":
        return _next_shell_cwd(cwd, arguments), environment, opaque
    if operation in {"export", "set", "unset"}:
        if operation == "set" and any(
                value.startswith(("-", "+")) for value in arguments):
            return cwd, environment, True
        return (
            cwd,
            _next_context_environment(environment, operation, arguments),
            opaque,
        )
    if operation in _OPAQUE_CONTEXT_OPERATIONS:
        return cwd, environment, True
    if operation in {"builtin", "command"}:
        nested = 0
        inspection = False
        while nested < len(arguments) and arguments[nested].startswith("-"):
            option = arguments[nested]
            nested += 1
            if option == "--":
                break
            if operation == "command" and re.fullmatch(r"-[Vv]+", option):
                inspection = True
        nested_operation = (
            arguments[nested].casefold()
            if not inspection and nested < len(arguments) else "")
        if nested_operation in (
                _OPAQUE_CONTEXT_OPERATIONS
                | {"cd", "export", "set", "unset"}):
            return cwd, environment, True
    if operation in {"declare", "local", "readonly", "typeset"} and any(
            _context_environment_name(value) for value in arguments):
        return cwd, environment, True
    return state


def _conditional_context(before, after):
    return (
        before[0] if before[0] == after[0] else None,
        before[1] if before[1] == after[1] else None,
        before[2] or after[2],
    )


def _direct_git_index(tokens):
    index = _operation_position(tokens)
    while index < len(tokens):
        executable = re.split(
            r"[\\/]", str(tokens[index] or ""))[-1].casefold()
        if executable in {"command", "command.exe"}:
            index += 1
            while index < len(tokens) and tokens[index].startswith("-"):
                if tokens[index] == "--":
                    index += 1
                    break
                if not re.fullmatch(r"-[p]+", tokens[index]):
                    return None
                index += 1
            continue
        if executable in {"env", "env.exe"}:
            index += 1
            while index < len(tokens):
                if tokens[index] == "--":
                    index += 1
                    break
                if _ASSIGNMENT.fullmatch(tokens[index]):
                    index += 1
                    continue
                if tokens[index].startswith("-"):
                    return None
                break
            continue
        return index if executable in {"git", "git.exe"} else None
    return None


def _direct_push_position(tokens):
    git_index = _direct_git_index(tokens)
    if git_index is None:
        return None
    index = git_index + 1
    while index < len(tokens):
        width = _global_option_width(tokens, index)
        if not width:
            break
        index += width
    if index < len(tokens) and tokens[index].casefold() == "push":
        return git_index, index
    return None


def _changes_repository_context(root, command, expected_pushes):
    expected_cwd = os.path.normcase(os.path.realpath(root))
    records = shell_command_records(command)
    if records is None:
        return True
    contexts = {(): (expected_cwd, frozenset(), False)}
    direct_pushes = 0

    def context_for(scope):
        if scope not in contexts:
            contexts[scope] = context_for(scope[:-1])
        return contexts[scope]

    for record in records:
        before = context_for(record.scope)
        push_position = _direct_push_position(record.tokens)
        if push_position is not None:
            direct_pushes += 1
            git_index, push_index = push_position
            if (
                    before[0] != expected_cwd
                    or before[1] != frozenset()
                    or before[2]
                    or _inline_context_changed(
                        record.tokens, git_index, push_index)):
                return True
        after = _persistent_context_after(before, record.tokens)
        contexts[record.scope] = (
            _conditional_context(before, after)
            if record.conditional else after)
    return direct_pushes != expected_pushes


def _push_positionals(arguments):
    values = []
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if token == "--":
            values.extend(arguments[index + 1:])
            break
        option = token.split("=", 1)[0]
        if option in _AMBIGUOUS_PUSH_FLAGS:
            return None
        if option in _PUSH_VALUE_OPTIONS:
            if "=" not in token:
                index += 1
                if index >= len(arguments):
                    return None
            index += 1
            continue
        if (
                option in _PUSH_FLAGS
                or option == "--force-with-lease"
                or token.startswith("--force-with-lease=")):
            index += 1
            continue
        if token.startswith("-"):
            return None
        values.append(token)
        index += 1
    return tuple(values)


def _safe_ref(value):
    return bool(
        isinstance(value, str)
        and value
        and _SAFE_REF.fullmatch(value)
        and ".." not in value
        and not value.startswith("/")
        and not value.endswith("/")
    )


def _push_endpoints(root, arguments, read_text):
    positionals = _push_positionals(arguments)
    if positionals is None or len(positionals) > 2:
        return ()
    if not positionals:
        tracking = read_text(
            root,
            ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{push}"),
        )
        remote, separator, destination = tracking.partition("/")
        if not separator:
            return ()
        source = "HEAD"
    else:
        remote = positionals[0]
    if not re.fullmatch(r"[A-Za-z0-9._-]+", remote):
        return ()

    if len(positionals) == 1:
        tracking = read_text(
            root,
            ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{push}"),
        )
        prefix = remote + "/"
        if not tracking.startswith(prefix):
            return ()
        source = "HEAD"
        destination = tracking[len(prefix):]
    elif len(positionals) == 2:
        refspec = positionals[1]
        if refspec.startswith("+"):
            refspec = refspec[1:]
        if refspec.count(":") > 1:
            return ()
        if ":" in refspec:
            source, destination = refspec.split(":", 1)
        else:
            source, destination = refspec, ""
        if not source:
            return ()
        if not destination:
            destination = (
                read_text(root, ("symbolic-ref", "--quiet", "--short", "HEAD"))
                if source == "HEAD" else source
            )

    if source.startswith("refs/heads/"):
        source = source[len("refs/heads/"):]
    if destination.startswith("refs/heads/"):
        destination = destination[len("refs/heads/"):]
    if not _safe_ref(source) or not _safe_ref(destination):
        return ()
    if destination.startswith("refs/"):
        return ()
    return source, "refs/remotes/%s/%s" % (remote, destination)


def push_commit_files(
        root, payload, git_text=git_text, git_paths=git_paths):
    """Return the union of paths in the one unambiguous published range."""
    tool_input = payload.get("tool_input") if isinstance(payload, dict) else None
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if payload.get("tool_name") != "Bash" or not isinstance(command, str):
        return ()
    pushes = tuple(
        intent for intent in git_delivery_intents(command)
        if intent.operation == "push")
    if len(pushes) != 1 or pushes[0].opaque_pathspec:
        return ()
    if _changes_repository_context(root, command, len(pushes)):
        return ()
    endpoints = _push_endpoints(root, pushes[0].arguments, git_text)
    if not endpoints:
        return ()
    source, tracking = endpoints
    source_commit = git_text(
        root, ("rev-parse", "--verify", source + "^{commit}"))
    remote_commit = git_text(
        root, ("rev-parse", "--verify", tracking + "^{commit}"))
    if not source_commit or not remote_commit:
        return ()
    paths = git_paths(
        root,
        ("log", "--format=", "--name-only", "-z",
         remote_commit + ".." + source_commit, "--"),
    )
    return tuple(dict.fromkeys(paths))
