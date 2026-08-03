"""Side-effect-free routing contracts for the lean production CLI."""

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class CommandRoute:
    handler: str
    arguments: tuple


LEAN_ROUTES = MappingProxyType({
    "start": CommandRoute("cmd_lean_start", ("root", "args")),
    "current": CommandRoute("cmd_lean_current", ("root", "args")),
    "advance": CommandRoute("cmd_lean_advance", ("root", "args")),
    "decision": CommandRoute("cmd_lean_decision", ("root", "args")),
    "manifest": CommandRoute("cmd_lean_manifest", ("root", "args")),
    "exit": CommandRoute("cmd_lean_exit", ("root", "args")),
    "ut": CommandRoute("cmd_lean_toolbox", ("root", "args")),
    "codecheck": CommandRoute("cmd_lean_toolbox", ("root", "args")),
    "grill": CommandRoute("cmd_lean_toolbox", ("root", "args")),
    "story": CommandRoute("cmd_lean_toolbox", ("root", "args")),
    "chain": CommandRoute("cmd_lean_chain", ("root", "args")),
    "lightcheck": CommandRoute("cmd_lean_lightcheck", ("root", "args")),
})


def lean_route(command):
    return LEAN_ROUTES.get(command)


def invoke(route, handlers, **context):
    handler = handlers.get(route.handler)
    if not callable(handler):
        raise RuntimeError(
            "unknown Mae-Flow command handler: %s" % route.handler)
    return handler(*(context[name] for name in route.arguments))
