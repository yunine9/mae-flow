"""Exact, read-only Git facts supplied to the lean Hook safety kernel."""

import locale
import os
import re
import subprocess

from ..foundation.git_intent import git_delivery_intents


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
