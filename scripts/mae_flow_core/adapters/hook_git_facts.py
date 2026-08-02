"""Exact, read-only Git facts supplied to the lean Hook safety kernel."""

import locale
import os
import re
import subprocess

from ..foundation.git_intent import git_delivery_intents
from ..foundation.git_shell import shell_command_groups


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
    "-C", "--git-dir", "--work-tree", "--namespace",
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
    return bool(
        key == "remote.pushdefault"
        or re.fullmatch(r"remote\..+\.(?:url|pushurl)", key)
        or re.fullmatch(r"branch\..+\.(?:remote|pushremote)", key)
        or re.fullmatch(r"url\..+\.(?:insteadof|pushinsteadof)", key)
        or key == "include.path"
        or re.fullmatch(r"includeif\..+\.path", key)
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


def _next_shell_cwd(current, tokens):
    if not tokens or tokens[0].casefold() != "cd":
        return current
    arguments = list(tokens[1:])
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


def _next_context_environment(active, tokens):
    updated = set(active)
    if not tokens:
        return updated
    operation = tokens[0].casefold()
    if operation in {"export", "set"}:
        for value in tokens[1:]:
            name = _context_environment_name(value)
            if name:
                updated.add(name)
    elif operation == "unset":
        for value in tokens[1:]:
            name = _context_environment_name(value)
            if name:
                updated.discard(name)
    elif all("=" in value for value in tokens):
        for value in tokens:
            name = _context_environment_name(value)
            if name:
                updated.add(name)
    return updated


def _changes_repository_context(root, command):
    expected_cwd = os.path.normcase(os.path.realpath(root))
    effective_cwd = expected_cwd
    context_environment = set()
    for tokens in shell_command_groups(command):
        for git_index, token in enumerate(tokens):
            executable = re.split(r"[\\/]", str(token or ""))[-1].casefold()
            if executable not in {"git", "git.exe"}:
                continue
            push_index = next((
                index for index in range(git_index + 1, len(tokens))
                if tokens[index].casefold() == "push"
            ), None)
            if push_index is None:
                continue
            if (
                    effective_cwd != expected_cwd
                    or context_environment
                    or _inline_context_changed(tokens, git_index, push_index)):
                return True
        effective_cwd = _next_shell_cwd(effective_cwd, tokens)
        context_environment = _next_context_environment(
            context_environment, tokens)
    return False


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
    if _changes_repository_context(root, command):
        return ()
    pushes = tuple(
        intent for intent in git_delivery_intents(command)
        if intent.operation == "push")
    if len(pushes) != 1 or pushes[0].opaque_pathspec:
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
