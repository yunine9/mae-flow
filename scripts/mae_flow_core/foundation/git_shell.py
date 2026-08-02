"""Shell tokenization and direct Git invocation discovery."""

from dataclasses import dataclass
import re
import shlex


GIT_GLOBAL_VALUE_OPTIONS = {
    "-C", "-c", "--git-dir", "--work-tree", "--namespace",
    "--super-prefix", "--config-env", "--exec-path",
}


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


def _shell_tokens(command):
    try:
        lexer = shlex.shlex(
            _fold_shell_line_continuations(command),
            posix=True,
            punctuation_chars=";&|()\n",
        )
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        lexer.commenters = ""
        return tuple(lexer)
    except ValueError:
        return None


def shell_command_groups(command):
    """Tokenize shell command positions without splitting quoted separators."""
    tokens = _shell_tokens(command)
    if tokens is None:
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


@dataclass(frozen=True)
class ShellCommandRecord:
    """One simple command plus only the control facts needed by proofs."""

    tokens: tuple
    scope: tuple
    conditional: bool = False


def _control_tokens(tokens):
    controls = set(";&|()\n")
    for token in tokens:
        if not token or not all(char in controls for char in token):
            yield token
            continue
        index = 0
        while index < len(token):
            pair = token[index:index + 2]
            if pair in ("&&", "||", "|&"):
                yield pair
                index += 2
            else:
                yield token[index]
                index += 1


def shell_command_records(command):
    """Preserve bounded shell scope/control metadata, or ``None`` if opaque."""
    tokens = _shell_tokens(command)
    if tokens is None:
        return None

    records = []
    words = []
    scope = ()
    conditional_scopes = (False,)
    pending = ""
    closed_compound = False
    next_scope = 0

    def child_scope(parent):
        nonlocal next_scope
        next_scope += 1
        return parent + (next_scope,)

    def flush(after=""):
        nonlocal words
        if not words:
            return False
        isolated = pending in ("|", "|&") or after in ("|", "|&", "&")
        record_scope = child_scope(scope) if isolated else scope
        records.append(ShellCommandRecord(
            tuple(words),
            record_scope,
            conditional_scopes[-1] or pending in ("&&", "||"),
        ))
        words = []
        return True

    for token in _control_tokens(tokens):
        if token not in {";", "&", "&&", "||", "|", "|&", "(", ")", "\n"}:
            if closed_compound:
                return None
            words.append(token)
            continue

        if token == "(":
            if words or closed_compound:
                return None
            scope = child_scope(scope)
            conditional_scopes += (
                conditional_scopes[-1] or pending in ("&&", "||"),)
            pending = ""
            continue

        if token == ")":
            if not flush() and not closed_compound:
                return None
            if not scope:
                return None
            scope = scope[:-1]
            conditional_scopes = conditional_scopes[:-1]
            pending = ""
            closed_compound = True
            continue

        had_operand = flush(token) or closed_compound
        if not had_operand:
            if token == "\n" and pending in ("", ";", "\n"):
                pending = "\n"
                continue
            return None
        pending = ";" if token == "\n" else token
        closed_compound = False

    if words:
        flush()
    elif not closed_compound and pending in ("&&", "||", "|", "|&"):
        return None
    if scope:
        return None
    return tuple(records)


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
