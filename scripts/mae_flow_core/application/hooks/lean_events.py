"""Pure routing for the four lean workflow Hook events."""

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Callable

from mae_flow_core.application.hooks.models import HookResponse
from mae_flow_core.foundation.git_intent import executes_git_commit_or_push


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
_FLOW_STATUS = {
    "active": "active",
    "paused": "active",
    "complete": "inactive",
    "exited": "inactive",
}
_MISSING = object()


def _event_name(event):
    if (
            not isinstance(event, str)
            or not re.fullmatch(r"[A-Za-z _-]+", event)):
        return ""
    normalized = re.sub(r"[ _-]+", "", event).lower()
    return _EVENTS.get(normalized, "")


def _field(value, name):
    if isinstance(value, Mapping):
        return value[name] if name in value else _MISSING
    return getattr(value, name, _MISSING)


def _flow_status(value):
    if _field(value, "mode") is not _MISSING:
        return ""
    status = _field(value, "status")
    return _FLOW_STATUS.get(status, "") if isinstance(status, str) else ""


def _runtime_status(runtime):
    mode = _field(runtime, "mode")
    if mode is _MISSING:
        return _flow_status(runtime)
    if _field(runtime, "status") is not _MISSING or not isinstance(mode, str):
        return ""

    flow = _field(runtime, "flow")
    if mode == "flow":
        return "" if flow in (_MISSING, None) else _flow_status(flow)
    if flow not in (_MISSING, None):
        return ""
    if mode in ("inactive", "direct"):
        return "inactive"
    if mode == "corrupt":
        return "corrupt"
    return ""


def _delivery_command(payload):
    tool = payload.get("tool_name", "")
    if not isinstance(tool, str) or tool.lower() != "bash":
        return False
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, Mapping):
        return False
    command = tool_input.get("command", "")
    if not isinstance(command, str):
        return False
    return executes_git_commit_or_push(command)


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
    # Hook ports may adapt CLI handlers that use SystemExit.  Fail open for
    # those exits and ordinary exceptions, but do not swallow operator
    # interrupts such as KeyboardInterrupt.
    except (Exception, SystemExit):
        return allow
