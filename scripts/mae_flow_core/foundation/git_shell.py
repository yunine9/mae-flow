"""Shell tokenization and direct Git invocation discovery."""

import re
import shlex


GIT_GLOBAL_VALUE_OPTIONS = {
    "-C", "-c", "--git-dir", "--work-tree", "--namespace",
    "--super-prefix", "--config-env", "--exec-path",
}

_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")
_DELIVERY_OPERATIONS = {"commit", "push"}
_MAX_EXECUTION_DEPTH = 6
_SHELLS = {
    "sh", "sh.exe", "bash", "bash.exe", "zsh", "zsh.exe",
    "fish", "fish.exe",
}
_SHELL_LONG_FLAGS = {
    "--login", "--noprofile", "--norc", "--posix", "--restricted",
    "--verbose",
}
_SHELL_VALUE_FLAGS = {"--init-file", "--rcfile", "-O", "+O"}
_SHELL_SHORT_FLAGS = set("abefhkmnptuvxBCHP")
_POWERSHELLS = {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}
_POWERSHELL_FLAGS = {
    "-login", "-mta", "-nologo", "-noexit", "-noninteractive",
    "-noprofile", "-noprofileloadtime", "-sta", "-usemta",
}
_POWERSHELL_VALUE_FLAGS = {
    "-configurationname", "-custompipename", "-executionpolicy", "-file",
    "-inputformat", "-outputformat", "-settingsfile", "-version",
    "-windowstyle", "-workingdirectory",
}
_CMD_FLAGS = {
    "/a", "/d", "/q", "/s", "/u",
    "/e:on", "/e:off", "/f:on", "/f:off", "/v:on", "/v:off",
}
_SUDO_FLAGS = {
    "-A", "-b", "-E", "-e", "-H", "-K", "-k", "-n", "-P", "-S",
    "-s", "-V", "-v", "--askpass", "--background", "--edit",
    "--help", "--host", "--login", "--non-interactive",
    "--preserve-groups", "--remove-timestamp", "--reset-timestamp",
    "--shell", "--stdin", "--validate", "--version",
}
_SUDO_VALUE_FLAGS = {
    "-C", "-D", "-g", "-h", "-p", "-R", "-r", "-T", "-t", "-u",
    "--chdir", "--chroot", "--close-from", "--command-timeout", "--group",
    "--host", "--other-user", "--prompt", "--role", "--type", "--user",
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


def _executable_name(token):
    return re.split(r"[\\/]", str(token or ""))[-1].lower()


def _skip_assignments(tokens, index=0):
    while index < len(tokens) and _ASSIGNMENT.fullmatch(tokens[index]):
        index += 1
    return index


def _git_delivery_operation(tokens):
    if not tokens or not _is_git_executable(tokens[0]):
        return ""
    index = 1
    while index < len(tokens):
        width = _global_option_width(tokens, index)
        if not width:
            break
        if index + width > len(tokens):
            return ""
        index += width
    if index >= len(tokens):
        return ""
    operation = tokens[index].lower()
    return operation if operation in _DELIVERY_OPERATIONS else ""


def _prefixed_command(tokens, index, kind):
    if kind == "command":
        inspection = False
        while index < len(tokens) and tokens[index].startswith("-"):
            option = tokens[index]
            if option == "--":
                index += 1
                break
            if not re.fullmatch(r"-[pVv]+", option):
                return ()
            inspection = inspection or "v" in option.lower()
            index += 1
        return () if inspection else tokens[index:]

    if kind == "exec":
        while index < len(tokens) and tokens[index].startswith("-"):
            option = tokens[index]
            if option == "--":
                index += 1
                break
            if option == "-a":
                index += 2
            elif re.fullmatch(r"-[cl]+", option):
                index += 1
            else:
                return ()
            if index > len(tokens):
                return ()
        return tokens[index:]

    if kind == "sudo":
        while index < len(tokens) and tokens[index].startswith("-"):
            option = tokens[index]
            if option == "--":
                index += 1
                break
            base = option.split("=", 1)[0]
            if base in _SUDO_VALUE_FLAGS:
                index += 1 if "=" in option else 2
            elif option in _SUDO_FLAGS or re.fullmatch(r"-[AbEHKknPSsVv]+", option):
                index += 1
            elif re.fullmatch(r"-[CDghpRrTtu].+", option):
                index += 1
            else:
                return ()
            if index > len(tokens):
                return ()
        return tokens[index:]
    return ()


def _env_command(tokens, index, depth):
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            index += 1
            break
        if _ASSIGNMENT.fullmatch(token):
            index += 1
            continue
        base = token.split("=", 1)[0]
        if base in ("-u", "--unset", "-C", "--chdir"):
            index += 1 if "=" in token else 2
        elif base in ("-S", "--split-string"):
            if "=" in token:
                split_value = token.split("=", 1)[1]
                remainder = tokens[index + 1:]
            elif index + 1 < len(tokens):
                split_value = tokens[index + 1]
                remainder = tokens[index + 2:]
            else:
                return ()
            try:
                split_tokens = tuple(shlex.split(split_value, posix=True))
            except ValueError:
                return ()
            return _executed_delivery_operations(
                split_tokens + remainder, depth + 1)
        elif token in ("-i", "--ignore-environment", "-0", "--null"):
            index += 1
        elif token.startswith("-"):
            return ()
        else:
            break
        if index > len(tokens):
            return ()
    return _executed_delivery_operations(tokens[index:], depth + 1)


def _shell_command(tokens, index, depth):
    while index < len(tokens):
        option = tokens[index]
        if option == "--":
            return ()
        if option == "-c":
            return (
                _executed_delivery_text(tokens[index + 1], depth + 1)
                if index + 1 < len(tokens) else ())
        if option.startswith("-") and not option.startswith("--"):
            flags = option[1:]
            if "c" in flags:
                if not set(flags) <= (_SHELL_SHORT_FLAGS | {"c"}):
                    return ()
                return (
                    _executed_delivery_text(tokens[index + 1], depth + 1)
                    if index + 1 < len(tokens) else ())
            if option in _SHELL_VALUE_FLAGS:
                index += 2
            elif flags and set(flags) <= _SHELL_SHORT_FLAGS:
                index += 1
            else:
                return ()
        elif option in _SHELL_LONG_FLAGS:
            index += 1
        else:
            return ()
        if index > len(tokens):
            return ()
    return ()


def _powershell_command(tokens, index, depth):
    while index < len(tokens):
        option = tokens[index].lower()
        if option in ("-command", "-c"):
            payload = tokens[index + 1:]
            if len(payload) == 1:
                return _executed_delivery_text(payload[0], depth + 1)
            return _executed_delivery_operations(payload, depth + 1)
        if option in _POWERSHELL_FLAGS:
            index += 1
        elif option.split("=", 1)[0] in _POWERSHELL_VALUE_FLAGS:
            index += 1 if "=" in option else 2
        else:
            return ()
        if index > len(tokens):
            return ()
    return ()


def _cmd_command(tokens, index, depth):
    while index < len(tokens):
        option = tokens[index].lower()
        if option in ("/c", "/k"):
            payload = tokens[index + 1:]
            if len(payload) == 1:
                return _executed_delivery_text(payload[0], depth + 1)
            return _executed_delivery_operations(payload, depth + 1)
        if option not in _CMD_FLAGS:
            return ()
        index += 1
    return ()


def _executed_delivery_operations(tokens, depth):
    if depth > _MAX_EXECUTION_DEPTH:
        return ()
    index = _skip_assignments(tokens)
    if index >= len(tokens):
        return ()
    tokens = tuple(tokens[index:])
    direct = _git_delivery_operation(tokens)
    if direct:
        return (direct,)

    executable = _executable_name(tokens[0])
    if executable in ("command", "command.exe", "exec", "exec.exe"):
        kind = executable.split(".", 1)[0]
        return _executed_delivery_operations(
            _prefixed_command(tokens, 1, kind), depth + 1)
    if executable in ("sudo", "sudo.exe"):
        return _executed_delivery_operations(
            _prefixed_command(tokens, 1, "sudo"), depth + 1)
    if executable in ("env", "env.exe"):
        return _env_command(tokens, 1, depth)
    if executable in _SHELLS:
        return _shell_command(tokens, 1, depth)
    if executable in _POWERSHELLS:
        return _powershell_command(tokens, 1, depth)
    if executable in ("cmd", "cmd.exe"):
        return _cmd_command(tokens, 1, depth)
    return ()


def _executed_delivery_text(command, depth):
    if depth > _MAX_EXECUTION_DEPTH or not isinstance(command, str):
        return ()
    operations = []
    for tokens in shell_command_groups(command):
        operations.extend(_executed_delivery_operations(tokens, depth))
    return tuple(operations)


def executed_git_delivery_operations(command):
    """Return commit/push operations actually executed at command positions."""
    if not isinstance(command, str):
        return ()
    spellings = [command]
    if re.search(
            r"(?i)[A-Za-z]:\\(?:[^\\\s\"']+\\)*git\.exe\b",
            command):
        spellings.append(command.replace("\\", "/"))
    operations = []
    for spelling in dict.fromkeys(spellings):
        operations.extend(_executed_delivery_text(spelling, 0))
    return tuple(dict.fromkeys(operations))
