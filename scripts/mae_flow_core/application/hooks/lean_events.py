"""Pure routing for the four lean workflow Hook events."""

from collections.abc import Mapping
from dataclasses import dataclass
import re
import shlex
from typing import Callable

from mae_flow_core.application.hooks.models import HookResponse
from mae_flow_core.foundation.git_intent import (
    git_delivery_intents,
    shell_command_groups,
)


@dataclass(frozen=True)
class LeanHookPorts:
    resume: Callable
    prompt: Callable
    pretool: Callable
    posttool: Callable
    inactive: Callable


_EVENTS = {
    "sessionstart": "sessionstart",
    "userpromptsubmit": "userprompt",
    "userprompt": "userprompt",
    "pretooluse": "pretooluse",
    "posttooluse": "posttooluse",
    "stop": "stop",
    "subagentstop": "subagentstop",
}
_ROUTES = {
    "sessionstart": "resume",
    "userprompt": "prompt",
    "pretooluse": "pretool",
    "posttooluse": "posttool",
}
_ACTIVE = {"active", "paused", "flow"}
_INACTIVE = {"inactive", "complete", "completed", "exited", "direct"}


def _word(value):
    if not isinstance(value, str):
        return ""
    return "".join(char.lower() for char in value if char.isalnum())


def _event_name(event):
    return _EVENTS.get(_word(event), "")


def _state_status(value):
    if isinstance(value, Mapping):
        return value.get("status", "")
    return getattr(value, "status", "")


def _runtime_status(runtime):
    if isinstance(runtime, str):
        candidate = runtime
    else:
        candidate = _state_status(runtime)
        if not candidate:
            mode = (
                runtime.get("mode", "")
                if isinstance(runtime, Mapping)
                else getattr(runtime, "mode", "")
            )
            if _word(mode) == "flow":
                flow = (
                    runtime.get("flow")
                    if isinstance(runtime, Mapping)
                    else getattr(runtime, "flow", None)
                )
                candidate = _state_status(flow) or mode
            else:
                candidate = mode
    status = _word(candidate)
    if status in _ACTIVE:
        return "active"
    if status in _INACTIVE:
        return "inactive"
    if status == "corrupt":
        return "corrupt"
    return ""


def _git_executable(token):
    name = re.split(r"[\\/]", str(token or ""))[-1].lower()
    return name in ("git", "git.exe")


def _command_index(group):
    index = 0
    assignment = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
    while index < len(group) and assignment.match(group[index]):
        index += 1
    if index >= len(group):
        return index

    executable = re.split(r"[\\/]", group[index])[-1].lower()
    if executable in ("command", "command.exe", "exec", "exec.exe"):
        index += 1
        while index < len(group) and group[index].startswith("-"):
            index += 1
    elif executable in ("sudo", "sudo.exe"):
        index += 1
        while index < len(group) and group[index].startswith("-"):
            index += 1
    elif executable in ("env", "env.exe"):
        index += 1
        while index < len(group):
            token = group[index]
            if assignment.match(token):
                index += 1
            elif token in ("-u", "--unset", "-C", "--chdir", "-S",
                          "--split-string"):
                index += 2
            elif token.startswith("-"):
                index += 1
            else:
                break
    return index


def _env_split_command(group):
    index = 0
    assignment = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
    while index < len(group) and assignment.match(group[index]):
        index += 1
    if index >= len(group):
        return ""
    executable = re.split(r"[\\/]", group[index])[-1].lower()
    if executable not in ("env", "env.exe"):
        return ""
    for option_index in range(index + 1, len(group)):
        option = group[option_index]
        if option in ("-S", "--split-string"):
            return (
                group[option_index + 1]
                if option_index + 1 < len(group) else "")
        if option.startswith("--split-string="):
            return option.split("=", 1)[1]
    return ""


def _contains_delivery(command):
    spellings = (command, command.replace("\\", "/"))
    for spelling in dict.fromkeys(spellings):
        if _contains_delivery_spelling(spelling):
            return True
    return False


def _contains_delivery_spelling(command):
    for group in shell_command_groups(command):
        split_command = _env_split_command(group)
        if split_command and _contains_delivery(split_command):
            return True
        index = _command_index(group)
        if index >= len(group):
            continue
        executable = re.split(r"[\\/]", group[index])[-1].lower()
        if _git_executable(group[index]):
            direct = " ".join(
                shlex.quote(token) for token in group[index:])
            if any(
                    intent.operation in ("commit", "push")
                    for intent in git_delivery_intents(direct)):
                return True
            continue

        single_payload_options = {
            "sh": ("-c",), "sh.exe": ("-c",),
            "bash": ("-c",), "bash.exe": ("-c",),
            "zsh": ("-c",), "zsh.exe": ("-c",),
            "fish": ("-c",), "fish.exe": ("-c",),
        }
        joined_payload_options = {
            "powershell": ("-command", "-c"),
            "powershell.exe": ("-command", "-c"),
            "pwsh": ("-command", "-c"),
            "pwsh.exe": ("-command", "-c"),
            "cmd": ("/c",), "cmd.exe": ("/c",),
        }
        options = (
            single_payload_options.get(executable)
            or joined_payload_options.get(executable, ()))
        if (
                options
                and index + 2 < len(group)
                and group[index + 1].lower() in options):
            payload = (
                group[index + 2]
                if executable in single_payload_options
                else " ".join(group[index + 2:]))
            if _contains_delivery(payload):
                return True
    return False


def _delivery_command(payload):
    if _word(payload.get("tool_name", "")) != "bash":
        return False
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, Mapping):
        return False
    command = tool_input.get("command", "")
    if not isinstance(command, str):
        return False
    return _contains_delivery(command)


def handle_lean_hook_event(event, payload, runtime, ports):
    """Route one decoded lean Hook event, failing open at every boundary."""
    allow = HookResponse()
    try:
        normalized = _event_name(event)
        if normalized in ("stop", "subagentstop"):
            return allow
        if normalized not in _ROUTES or not isinstance(payload, Mapping):
            return allow

        status = _runtime_status(runtime)
        if not status:
            return allow
        if status == "inactive":
            return ports.inactive(normalized, payload)
        if status == "corrupt":
            if normalized == "pretooluse" and _delivery_command(payload):
                return ports.pretool(payload)
            return allow

        return getattr(ports, _ROUTES[normalized])(payload)
    except Exception:
        return allow
