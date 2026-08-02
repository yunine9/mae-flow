"""Shared execution-aware command facts for stateful and stateless safety."""

import ast
from dataclasses import dataclass
import re
import shlex

from ..foundation import git_intent
from ..foundation.git_execution import actual_command_records
from ..foundation.shell_execution import windows_command_tokens
from .bash import BashGateContext, decide_post_commit
from .intent import parse_intent, recursive_delete_targets


_SHELL_NAMES = {
    "bash", "bash.exe", "fish", "fish.exe", "sh", "sh.exe", "zsh",
    "zsh.exe",
}
_POWERSHELL_NAMES = {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}
_CMD_NAMES = {"cmd", "cmd.exe"}
_PYTHON_NAME = re.compile(r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?", re.I)
_WRITE_REDIRECTIONS = {">", ">>", ">|", "<>", "&>", "&>>", ">&"}
_DYNAMIC_PATH = re.compile(r"[$`%]|\{\{|\}\}")


@dataclass(frozen=True)
class CommandMutation:
    targets: tuple = ()
    opaque_writer: bool = False
    interactive: bool = False
    destructive: bool = False


def _name(value):
    return re.split(r"[\\/]", str(value or ""))[-1].casefold()


def _literal(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Str):  # pragma: no cover - Python 3.8 AST alias
        return node.s
    return None


def _path_owner(node):
    function = node.func if isinstance(node, ast.Call) else None
    if not isinstance(function, ast.Attribute):
        return None, ""
    owner = function.value
    if (
            isinstance(owner, ast.Call)
            and isinstance(owner.func, ast.Name)
            and owner.func.id == "Path"
            and owner.args):
        return owner, function.attr
    return None, ""


def _open_mode(node):
    mode = _literal(node.args[1]) if len(node.args) > 1 else "r"
    for keyword in node.keywords:
        if keyword.arg == "mode":
            mode = _literal(keyword.value)
    return mode


def _python_path_call(node):
    if not isinstance(node, ast.Call) or not node.args:
        return False, None
    function = node.func
    if isinstance(function, ast.Name) and function.id == "open":
        mode = _open_mode(node)
        return (
            (True, _literal(node.args[0]))
            if isinstance(mode, str) and any(flag in mode for flag in "wax+")
            else (False, None)
        )
    owner, method = _path_owner(node)
    if owner is None:
        return False, None
    if method in {"write_text", "write_bytes", "touch", "unlink"}:
        return True, _literal(owner.args[0])
    if method == "open":
        mode = _literal(node.args[0]) if node.args else "r"
        if isinstance(mode, str) and any(flag in mode for flag in "wax+"):
            return True, _literal(owner.args[0])
    return False, None


def _python_function(node):
    function = node.func if isinstance(node, ast.Call) else None
    if not isinstance(function, ast.Attribute):
        return ""
    owner = function.value
    if isinstance(owner, ast.Name):
        return "%s.%s" % (owner.id, function.attr)
    return ""


def _python_mutation(script):
    try:
        tree = ast.parse(script)
    except (SyntaxError, TypeError, ValueError):
        return (), True
    targets = []
    opaque = False
    functions = {
        "os.remove": (0,), "os.unlink": (0,), "os.rename": (0, 1),
        "os.replace": (0, 1), "shutil.copy": (1,), "shutil.copy2": (1,),
        "shutil.copyfile": (1,), "shutil.move": (0, 1),
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        matched, direct = _python_path_call(node)
        if matched:
            if direct is not None:
                targets.append(direct)
            else:
                opaque = True
            continue
        indexes = functions.get(_python_function(node))
        if indexes is None:
            continue
        for index in indexes:
            path = _literal(node.args[index]) if index < len(node.args) else None
            if path:
                targets.append(path)
            else:
                opaque = True
    return tuple(targets), opaque


def _non_options(arguments, value_options=()):
    values = []
    positional = False
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if token == "--":
            positional = True
            index += 1
            continue
        option = token.split("=", 1)[0]
        if not positional and option in value_options:
            index += 1 if "=" in token else 2
            continue
        if not positional and token.startswith("-"):
            index += 1
            continue
        values.append(token)
        index += 1
    return tuple(values)


def _sed_targets(arguments):
    in_place = any(
        token == "--in-place"
        or token.startswith("--in-place=")
        or token == "-i"
        or token.startswith("-i") and token != "-"
        for token in arguments)
    if not in_place:
        return ()
    value_options = {"-e", "--expression", "-f", "--file"}
    values = _non_options(arguments, value_options)
    explicit = any(
        token.split("=", 1)[0] in value_options for token in arguments)
    return values if explicit else values[1:]


def _powershell_paths(operation, arguments):
    named = {
        "-path", "-literalpath", "-filepath", "-destination",
        "-destinationpath", "-targetpath",
    }
    targets = []
    index = 0
    while index < len(arguments):
        token = arguments[index]
        option, separator, value = token.partition(":")
        if option.casefold() in named:
            if separator:
                targets.append(value)
                index += 1
            elif index + 1 < len(arguments):
                targets.append(arguments[index + 1])
                index += 2
            else:
                return (), True
            continue
        index += 1
    if targets:
        return tuple(targets), False
    values = _non_options(arguments)
    if operation in {"copy-item", "move-item", "rename-item"}:
        return values[:2], not bool(values)
    return values[:1], not bool(values)


def _python_record(arguments):
    try:
        index = arguments.index("-c")
    except ValueError:
        return (), False, False
    if index + 1 >= len(arguments):
        return (), True, False
    paths, opaque = _python_mutation(arguments[index + 1])
    return paths, opaque, False


def _literal_targets(values):
    values = tuple(values)
    literal = tuple(value for value in values if not _DYNAMIC_PATH.search(value))
    return literal, len(literal) != len(values) or not bool(values)


def _in_place_script_targets(arguments):
    in_place = any(
        re.match(r"^-[A-Za-z]*i", token) or token.startswith("--in-place")
        for token in arguments
    )
    if not in_place:
        return (), False
    program_options = {"-e", "-E", "--expression", "-I"}
    values = _non_options(arguments, program_options)
    explicit_program = any(
        token.split("=", 1)[0] in program_options for token in arguments)
    targets = values if explicit_program else values[1:]
    return _literal_targets(targets)


def _record_mutation(record):
    executable = _name(record.executable)
    arguments = tuple(record.arguments)
    if executable == "sed":
        return _sed_targets(arguments), False, False
    if executable == "truncate":
        targets = _non_options(
            arguments, {"-s", "--size", "-r", "--reference"})
        paths, opaque = _literal_targets(targets)
        return paths, opaque, False
    if executable == "dd":
        outputs = tuple(
            token.split("=", 1)[1]
            for token in arguments if token.startswith("of=")
        )
        if not outputs:
            return (), False, False
        paths, opaque = _literal_targets(outputs)
        return paths, opaque, False
    if executable in {"perl", "ruby"}:
        paths, opaque = _in_place_script_targets(arguments)
        return paths, opaque, False
    if executable == "patch":
        if any(token in {"--dry-run", "-C"} for token in arguments):
            return (), False, False
        return (), True, False
    if executable == "git" and arguments[:1] == ("apply",):
        if any(token in {"--check", "--stat", "--numstat", "--summary"}
               for token in arguments[1:]):
            return (), False, False
        return (), True, False
    if executable == "tee":
        return _non_options(arguments, {"--output-error"}), False, False
    if executable in {"cp", "copy", "copy.exe"}:
        values = _non_options(arguments)
        return values[-1:], not bool(values), False
    if executable in {"mv", "move", "move.exe"}:
        values = _non_options(arguments)
        return values, not bool(values), False
    if executable in {
            "touch", "rm", "unlink", "shred", "del", "del.exe", "erase",
            "erase.exe"}:
        values = _non_options(arguments)
        destructive = executable in {
            "shred", "del", "del.exe", "erase", "erase.exe"}
        return values, not bool(values), destructive
    if executable in {
            "set-content", "add-content", "out-file", "new-item",
            "remove-item", "copy-item", "move-item", "rename-item"}:
        paths, opaque = _powershell_paths(executable, arguments)
        destructive = executable == "remove-item" and any(
            token.casefold() in {"-recurse", "-r"} for token in arguments)
        return paths, opaque, destructive
    if _PYTHON_NAME.fullmatch(executable):
        return _python_record(arguments)
    return (), False, False


def _windows_writer_targets(command):
    tokens = windows_command_tokens(command)
    if not tokens:
        return ()
    lowered = tuple(_name(token) for token in tokens)
    writers = {
        "set-content", "add-content", "out-file", "new-item",
        "remove-item", "copy-item", "move-item", "rename-item",
    }
    power_index = next((
        index for index, token in enumerate(lowered) if token in writers
    ), None)
    if power_index is not None:
        paths, _opaque = _powershell_paths(
            lowered[power_index], tokens[power_index + 1:])
        return paths
    commands = {"copy", "copy.exe", "move", "move.exe", "del", "del.exe",
                "erase", "erase.exe"}
    command_index = next((
        index for index, token in enumerate(lowered) if token in commands
    ), None)
    if command_index is None:
        return ()
    values = _non_options(tokens[command_index + 1:])
    if lowered[command_index] in {"copy", "copy.exe"}:
        return values[-1:]
    return values


def _shell_tokens(command):
    try:
        lexer = shlex.shlex(
            command, posix=True, punctuation_chars=";&|()<>\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        lexer.commenters = ""
        return tuple(lexer)
    except ValueError:
        return None


def _redirection_targets(tokens):
    targets = []
    opaque = False
    for index, token in enumerate(tokens):
        if token.isdigit() and index + 1 < len(tokens):
            operator = tokens[index + 1]
            operand_index = index + 2
        else:
            operator = token
            operand_index = index + 1
        if operator not in _WRITE_REDIRECTIONS:
            continue
        if operand_index >= len(tokens):
            opaque = True
            continue
        target = tokens[operand_index]
        if operator == ">&" and re.fullmatch(r"[0-9]+|-", target):
            continue
        if target and not _DYNAMIC_PATH.search(target):
            targets.append(target)
        else:
            opaque = True
    return tuple(targets), opaque


def _nested_payloads(tokens):
    if not tokens:
        return ()
    executable = _name(tokens[0])
    if executable in _SHELL_NAMES:
        for index, token in enumerate(tokens[1:], 1):
            if token in {"-c", "--command"} and index + 1 < len(tokens):
                return (tokens[index + 1],)
    if executable in _POWERSHELL_NAMES:
        for index, token in enumerate(tokens[1:], 1):
            if token.casefold() in {"-c", "-command"}:
                return (" ".join(tokens[index + 1:]),)
    if executable in _CMD_NAMES:
        for index, token in enumerate(tokens[1:], 1):
            if token.casefold() in {"/c", "/k"}:
                return (" ".join(tokens[index + 1:]).replace("^>", ">"),)
    return ()


def _redirections(command, depth=0):
    if depth > 4:
        return (), True
    tokens = _shell_tokens(command)
    if tokens is None:
        return (), False
    targets, opaque = _redirection_targets(tokens)
    for payload in _nested_payloads(tokens):
        nested, nested_opaque = _redirections(payload, depth + 1)
        targets += nested
        opaque = opaque or nested_opaque
    return targets, opaque


def _interactive(command, tool_input):
    if isinstance(tool_input, dict) and any(
            tool_input.get(key) for key in (
                "background", "is_background", "run_in_background", "tty",
                "pty", "interactive", "shell_id", "session_id")):
        return True
    tokens = _shell_tokens(command)
    if not tokens:
        return False
    executable = _name(tokens[0])
    if executable in _SHELL_NAMES:
        return not any(token in {"-c", "--command"} for token in tokens[1:])
    if executable in _POWERSHELL_NAMES:
        return not any(
            token.casefold() in {"-c", "-command", "-file"}
            for token in tokens[1:])
    if executable in _CMD_NAMES:
        return not any(token.casefold() == "/c" for token in tokens[1:])
    return False


def classify_command_mutation(command, tool_input=None):
    if not isinstance(command, str):
        return CommandMutation()
    targets = []
    opaque = False
    destructive = False
    for record in actual_command_records(command):
        found, unknown, removes = _record_mutation(record)
        targets.extend(found)
        opaque = opaque or unknown
        destructive = destructive or removes
    targets.extend(_windows_writer_targets(command))
    redirected, redirect_opaque = _redirections(command)
    targets.extend(redirected)
    return CommandMutation(
        targets=tuple(dict.fromkeys(path for path in targets if path)),
        opaque_writer=opaque or redirect_opaque,
        interactive=_interactive(command, tool_input),
        destructive=destructive,
    )


_DESTRUCTIVE_BASH_RULES = {
    "bash-force-push",
    "bash-git-clean-ignored",
    "bash-wipe-worktree",
}


def recursive_delete_facts(command):
    return recursive_delete_targets(parse_intent("bash", command))


def _bash_gate_context(command, delete_targets):
    return BashGateContext(
        command=command,
        has_internal_state_path=False,
        branch_name="",
        branch_creating=False,
        step="",
        wanted_branch="",
        base_branch="",
        checkpoint_locked=False,
        checkpoint_label="",
        checkpoint_status="",
        ticket="",
        commit_message_present=False,
        commit_message="",
        current_branch="",
        add_paths=(),
        recursive_delete_targets=tuple(delete_targets),
        state_active=True,
    )


def dangerous_bash_result(command, delete_targets=()):
    """Return the lean rule/message for confirmed destructive execution."""
    gate = decide_post_commit(_bash_gate_context(command, delete_targets))
    if gate.rule == "bash-recursive-delete":
        return "filesystem", gate.message
    if gate.rule in _DESTRUCTIVE_BASH_RULES:
        return "git_destructive", gate.message
    return "", ""


def stateless_command_relevant(command):
    """Whether corrupt-state routing must retain a bounded safety decision."""
    rule, _message = dangerous_bash_result(
        command, recursive_delete_facts(command))
    if rule:
        return True
    return any(
        intent.operation in ("commit", "push")
        for intent in git_intent.git_delivery_intents(command)
    )
