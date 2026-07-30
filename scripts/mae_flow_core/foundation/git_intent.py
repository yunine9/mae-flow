"""Pure parsing of Git add/commit intent from shell command text."""

from dataclasses import dataclass
import re
import shlex

from .source_paths import normalize_path


COMMIT_VALUE_OPTIONS = {
    "-m", "--message", "-F", "--file", "-C", "--reuse-message",
    "-c", "--reedit-message", "--author", "--date", "--cleanup",
    "-t", "--template", "--fixup", "--squash", "--trailer",
}

GIT_GLOBAL_VALUE_OPTIONS = {
    "-C", "-c", "--git-dir", "--work-tree", "--namespace",
    "--super-prefix", "--config-env", "--exec-path",
}

GIT_MUTATION_OPERATIONS = {
    "add", "commit", "push", "restore", "checkout", "rm", "revert",
}


@dataclass(frozen=True)
class GitAction:
    actor: str
    operation: str
    arguments: tuple
    paths: tuple = ()
    commit: str = ""
    changes: tuple = ()
    resolved_commit: str = ""
    objects: tuple = ()


def _is_git_executable(token):
    name = re.split(r"[\\/]", str(token or ""))[-1].lower()
    return name in ("git", "git.exe")


def _global_option_width(tokens, index):
    token = tokens[index]
    option = token.split("=", 1)[0]
    if option in GIT_GLOBAL_VALUE_OPTIONS:
        return 1 if "=" in token else 2
    if (
            token.startswith("-C") and token != "-C"
            or token.startswith("-c") and token != "-c"):
        return 1
    return 1 if token.startswith("-") else 0


def _fold_shell_line_continuations(command):
    """Apply shell backslash-newline removal outside single quotes."""
    result = []
    quote = ""
    index = 0
    while index < len(command):
        char = command[index]
        newline_width = (
            2 if command[index + 1:index + 3] == "\r\n"
            else 1 if command[index + 1:index + 2] == "\n"
            else 0
        )
        if char == "\\" and quote != "'" and newline_width:
            index += 1 + newline_width
            continue
        if quote == "'":
            result.append(char)
            if char == "'":
                quote = ""
            index += 1
            continue
        if char == "\\" and index + 1 < len(command):
            result.extend((char, command[index + 1]))
            index += 2
            continue
        result.append(char)
        if char in ("'", '"'):
            if not quote:
                quote = char
            elif quote == char:
                quote = ""
        index += 1
    return "".join(result)


def shell_command_groups(command):
    """Tokenize shell command positions without splitting quoted separators."""
    try:
        lexer = shlex.shlex(
            _fold_shell_line_continuations(command),
            posix=True,
            punctuation_chars=";&|()\n",
        )
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return ()
    groups, current = [], []
    for token in tokens:
        if token and all(char in ";&|()\n" for char in token):
            if current:
                groups.append(tuple(current))
                current = []
            continue
        current.append(token)
    if current:
        groups.append(tuple(current))
    return tuple(groups)


def _inline_alias_config(value):
    if not str(value).lower().startswith("alias.") or "=" not in value:
        return "", ""
    key, expansion = value.split("=", 1)
    return key[6:].lower(), expansion


def _git_invocation_records(command):
    invocations = []
    for tokens in shell_command_groups(command):
        for git_index, token in enumerate(tokens):
            if not _is_git_executable(token):
                continue
            index = git_index + 1
            aliases = {}
            while index < len(tokens):
                option = tokens[index]
                width = _global_option_width(tokens, index)
                if not width:
                    break
                config = ""
                if option == "-c" and index + 1 < len(tokens):
                    config = tokens[index + 1]
                elif option.startswith("-c") and option != "-c":
                    config = option[2:]
                name, expansion = _inline_alias_config(config)
                if name:
                    aliases[name] = expansion
                index += width
            if index < len(tokens):
                invocations.append((
                    tokens[index].lower(),
                    tuple(tokens[index + 1:]),
                    aliases,
                ))
                break
    return tuple(invocations)


def git_invocations(command):
    return tuple(
        (operation, arguments)
        for operation, arguments, _aliases
        in _git_invocation_records(command)
    )


def git_alias_mutation(expansion):
    value = str(expansion or "").strip()
    if not value:
        return ""
    if value.startswith("!"):
        actions = git_actions(value[1:])
        if actions:
            return next((
                action.operation for action in actions
                if action.operation in GIT_MUTATION_OPERATIONS
            ), "")
        match = re.search(
            r"(?:^|[\s;&|])(?:git(?:\.exe)?\s+)?"
            r"(add|commit|push|restore|checkout|rm|revert)\b",
            value[1:],
            re.I,
        )
        return match.group(1).lower() if match else ""
    try:
        tokens = shlex.split(value, posix=True)
    except ValueError:
        return ""
    operation = tokens[0].lower() if tokens else ""
    return (
        operation
        if operation in GIT_MUTATION_OPERATIONS else ""
    )


def inline_git_alias_mutations(command):
    return tuple(
        mutation
        for operation, _arguments, aliases
        in _git_invocation_records(command)
        for mutation in [git_alias_mutation(
            aliases.get(operation, ""))]
        if mutation
    )


def opaque_pathspec_mutations(command):
    return tuple(
        operation
        for operation, arguments in git_invocations(command)
        if (
            operation in GIT_MUTATION_OPERATIONS
            and any(
                token == "--pathspec-from-file"
                or token.startswith("--pathspec-from-file=")
                or token == "--pathspec-file-nul"
                for token in arguments
            )
        )
    )


def git_subcommand_tokens(command, subcommand):
    return [
        list(arguments)
        for operation, arguments in git_invocations(command)
        if operation == subcommand.lower()
    ]


def has_git_subcommand(command, subcommand):
    return bool(git_subcommand_tokens(command, subcommand))


def git_commit_message(command):
    token_sets = git_subcommand_tokens(command, "commit")
    if not token_sets:
        return False, ""
    tokens = token_sets[-1]
    for index, token in enumerate(tokens):
        if token in ("-m", "--message"):
            return True, tokens[index + 1] if index + 1 < len(tokens) else ""
        if token.startswith("--message="):
            return True, token.split("=", 1)[1]
        if token.startswith("-m") and token != "-m":
            return True, token[2:]
    return False, ""


def _action_paths(operation, arguments):
    tokens = list(arguments)
    if operation == "add":
        return tuple(git_add_intent(tokens)["pathspecs"])
    if operation == "commit":
        return tuple(command_pathspecs(tokens, COMMIT_VALUE_OPTIONS))
    if operation == "rm":
        return tuple(command_pathspecs(
            tokens, {"--pathspec-from-file"}))
    if operation == "restore":
        return tuple(command_pathspecs(
            tokens, {"-s", "--source", "--pathspec-from-file"}))
    if operation == "checkout" and "--" in tokens:
        marker = tokens.index("--")
        return tuple(
            normalize_path(token) for token in tokens[marker + 1:])
    return ()


def _revert_commit(arguments):
    values = command_pathspecs(
        list(arguments),
        {
            "-m", "--mainline", "--strategy", "-X",
            "--strategy-option", "--cleanup",
        },
    )
    return values[0] if len(values) == 1 else ""


def git_actions(command, actor="agent-hook"):
    """Return normalized direct Git actions in shell execution order."""
    actions = []
    for operation, arguments in git_invocations(command):
        if operation not in GIT_MUTATION_OPERATIONS:
            continue
        actions.append(GitAction(
            actor=actor,
            operation=operation,
            arguments=tuple(arguments),
            paths=_action_paths(operation, arguments),
            commit=(
                _revert_commit(arguments)
                if operation == "revert" else ""),
        ))
    return tuple(actions)


def _python_wrapped_git_mutations(command):
    launcher = re.search(
            r"(?:^|[\s;&|])(?:[^\s\"']*[\\/])?"
            r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?\s+[^;&|]*-c\b",
            command,
            re.I)
    if not launcher:
        return []
    mutations = []
    call_pattern = re.compile(
        r"subprocess\.(?:run|call|check_call|check_output|Popen)"
        r"\s*\(\s*\[(.*?)\]\s*[,)]",
        re.I | re.S,
    )
    for match in call_pattern.finditer(command):
        literals = re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))
        if not literals or not _is_git_executable(literals[0]):
            continue
        for token in literals[1:]:
            if token.lower() in ("add", "commit", "push"):
                mutations.append(token.lower())
                break
    for match in re.finditer(
            r"(?:os\.system|subprocess\.(?:run|call|check_call|Popen))"
            r"\s*\(\s*(['\"])(.*?)\1",
            command,
            re.I | re.S,
    ):
        inner = match.group(2)
        for action in ("add", "commit", "push"):
            if re.search(
                    r"(?:^|\s)git(?:\.exe)?(?:\s+-\S+)*\s+"
                    + action + r"\b",
                    inner,
                    re.I,
            ):
                mutations.append(action)
    # A literal-list parser cannot safely follow variables or the os.exec*
    # family.  Once an Agent-origin Python -c script visibly combines a
    # process-launch API, a literal Git executable, and a literal mutation
    # subcommand, treat it as a high-confidence wrapper even when argv is
    # assembled indirectly.  This remains intentionally narrower than a claim
    # to understand arbitrary Python code.
    script = command[launcher.end():]
    if (
            re.search(
                r"\b(?:subprocess\.[A-Za-z_]\w*|"
                r"os\.(?:exec\w*|spawn\w*|system|popen))\b",
                script,
                re.I,
            )
            and re.search(r"['\"]git(?:\.exe)?['\"]", script, re.I)):
        mutations.extend(
            action for action in ("add", "commit", "push")
            if re.search(
                r"['\"]" + action + r"['\"]",
                script,
                re.I,
            )
        )
    return mutations


def _shell_wrapped_git_mutations(command):
    """Parse shell-wrapper payloads with the same Git global-option rules."""
    payloads = []
    shells = {"sh", "sh.exe", "bash", "bash.exe", "zsh", "zsh.exe",
              "fish", "fish.exe"}
    powershells = {
        "powershell", "powershell.exe", "pwsh", "pwsh.exe",
    }
    for group in shell_command_groups(command):
        for index, token in enumerate(group):
            executable = re.split(r"[\\/]", token)[-1].lower()
            if (
                    executable in shells
                    and index + 2 < len(group)
                    and group[index + 1].lower() == "-c"):
                payloads.append(group[index + 2])
                continue
            if (
                    executable in powershells
                    and index + 2 < len(group)
                    and group[index + 1].lower()
                    in ("-command", "-c")):
                payloads.append(" ".join(group[index + 2:]))
                continue
            if (
                    executable in ("cmd", "cmd.exe")
                    and index + 2 < len(group)
                    and group[index + 1].lower() == "/c"):
                payloads.append(" ".join(group[index + 2:]))
    return [
        operation
        for payload in payloads
        for operation, _arguments in git_invocations(payload)
        if operation in ("add", "commit", "push")
    ]


def wrapped_git_mutations(command):
    """Detect high-confidence Agent interpreter wrappers around Git writes."""
    return tuple(dict.fromkeys(
        _python_wrapped_git_mutations(command)
        + _shell_wrapped_git_mutations(command)
    ))


def option_consumes_following(token, value_options):
    option = token.split("=", 1)[0]
    if option in value_options:
        return "=" not in token
    return bool(re.fullmatch(r"-[A-Za-z]*[mFCctS]", token))


class PathspecCollector:
    def __init__(self, value_options):
        self.value_options = value_options
        self.paths = []

    def _consume(self, tokens, index):
        token = tokens[index]
        if not token.startswith("-"):
            self.paths.append(normalize_path(token))
            return index + 1
        return index + (
            2 if option_consumes_following(
                token, self.value_options) else 1)

    def collect(self, tokens):
        index = 0
        while index < len(tokens):
            index = self._consume(tokens, index)
        return self.paths


def command_pathspecs(tokens, value_options=None):
    value_options = value_options or set()
    if "--" in tokens:
        marker = tokens.index("--")
        before, explicit = tokens[:marker], tokens[marker + 1:]
    else:
        before, explicit = tokens, []
    paths = PathspecCollector(value_options).collect(before)
    paths.extend(normalize_path(token) for token in explicit)
    return list(dict.fromkeys(paths))


def git_add_intent(tokens):
    token_set = set(tokens)
    short_flags = short_option_flags(tokens)
    all_mode = bool(
        "A" in short_flags
        or token_set & {"--all", "--no-ignore-removal"})
    update = "u" in short_flags or "--update" in token_set
    paths = command_pathspecs(tokens)
    default_paths = ["."] if all_mode or update else []
    return {
        "pathspecs": paths or default_paths,
        "force": "f" in short_flags or "--force" in token_set,
        "tracked_only": update,
        "all": all_mode,
    }


def git_add_intents(command):
    return [
        git_add_intent(tokens)
        for tokens in git_subcommand_tokens(command, "add")
    ]


def short_option_flags(tokens):
    return "".join(
        match.group(1) for token in tokens
        for match in [re.fullmatch(r"-([A-Za-z]+)", token)]
        if match)


def git_commit_intent(command):
    token_sets = git_subcommand_tokens(command, "commit")
    tokens = token_sets[-1] if token_sets else []
    token_set = set(tokens)
    short_flags = short_option_flags(tokens)
    return {
        "pathspecs": command_pathspecs(tokens, COMMIT_VALUE_OPTIONS),
        "all": "a" in short_flags or "--all" in token_set,
        "include": "i" in short_flags or "--include" in token_set,
    }
