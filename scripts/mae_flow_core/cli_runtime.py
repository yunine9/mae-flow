"""Production composition root for the lean Mae-Flow CLI."""

import os
import sys

from . import command_dispatch
from .cli_commands import chain_workflow, lean_migration, lean_workflow
from .cli_parser import parse_args
from .runtime import find_project_root
from .state_store import safe_read_json


_HANDLERS = {
    name: getattr(lean_workflow, name)
    for name in (
        "cmd_lean_start",
        "cmd_lean_current",
        "cmd_lean_advance",
        "cmd_lean_decision",
        "cmd_lean_manifest",
        "cmd_lean_exit",
        "cmd_lean_toolbox",
        "cmd_lean_lightcheck",
    )
}
_HANDLERS["cmd_lean_chain"] = chain_workflow.cmd_lean_chain


def _state_schema(root):
    path = os.path.join(root, ".mae-flow.json")
    raw, error = safe_read_json(path)
    if error:
        return "corrupt"
    if not isinstance(raw, dict):
        return "missing"
    if raw.get("engine") == "lean-v1" and raw.get("schema_version") == 3:
        return "lean"
    if raw.get("schema_version") == 2:
        return "legacy"
    return "unsupported"


def main(argv=None):
    """Dispatch only lean commands, with one explicit schema-v2 reader."""
    args = parse_args(argv)
    root = find_project_root()
    if root != os.getcwd():
        os.chdir(root)
        print(
            "[mae-flow] 调用目录非项目根,已定位到: %s" % root,
            file=sys.stderr,
        )

    schema = _state_schema(root)
    if args.cmd == "migrate-flow":
        lean_migration.handle_early_state_command(args)
        return None
    if args.cmd == "current" and schema in {
            "legacy", "corrupt", "unsupported"}:
        if lean_migration.handle_early_state_command(args):
            return None

    route = command_dispatch.lean_route(args.cmd)
    if route is None:
        raise RuntimeError("unrouted lean command: %s" % args.cmd)
    return command_dispatch.invoke(
        route, _HANDLERS, root=root, args=args)
