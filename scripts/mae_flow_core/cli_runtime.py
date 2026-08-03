"""Production composition root for the lean Mae-Flow CLI."""

import os
import sys

from . import command_dispatch
from .cli_commands import chain_workflow, lean_migration, lean_workflow
from .cli_parser import parse_args
from .runtime import find_project_root
from .state_store import safe_read_json


_PLUGIN_ROOT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", ".."))
_RESOURCE_FILES = (
    ("runtime/guidance/grill.md", "guidance/grill.md"),
    ("runtime/guidance/construction.md", "guidance/construction.md"),
    ("runtime/guidance/quality.md", "guidance/quality.md"),
    ("runtime/guidance/review.md", "guidance/review.md"),
    ("runtime/guidance/story-design.md", "guidance/story-design.md"),
    ("skills/mae-flow/assets/BEHAVIOR-TEMPLATE.md",
     "assets/BEHAVIOR-TEMPLATE.md"),
    ("skills/mae-flow/assets/CHAIN-TEMPLATE.md",
     "assets/CHAIN-TEMPLATE.md"),
    ("skills/mae-flow/assets/GRILL-PREP-TEMPLATE.md",
     "assets/GRILL-PREP-TEMPLATE.md"),
    ("skills/mae-flow/assets/REVIEW-TEMPLATE.md",
     "assets/REVIEW-TEMPLATE.md"),
    ("skills/mae-flow/assets/STORY-TEMPLATE.md",
     "assets/STORY-TEMPLATE.md"),
)


_HANDLERS = {
    name: getattr(lean_workflow, name)
    for name in (
        "cmd_lean_start",
        "cmd_lean_configure",
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


def _materialize_plugin_resources(root):
    """Expose immutable plugin guidance without leaking its install path."""
    target_root = os.path.join(
        root, ".mae-flow-work", "plugin-resources")
    for source_relative, target_relative in _RESOURCE_FILES:
        source = os.path.join(
            _PLUGIN_ROOT, *source_relative.split("/"))
        target = os.path.join(
            target_root, *target_relative.split("/"))
        try:
            with open(source, "rb") as stream:
                content = stream.read()
        except OSError as exc:
            raise RuntimeError(
                "插件资源缺失，请刷新或重装 Mae-Flow: %s"
                % source_relative) from exc
        try:
            with open(target, "rb") as stream:
                if stream.read() == content:
                    continue
        except OSError:
            pass
        os.makedirs(os.path.dirname(target), exist_ok=True)
        temporary = target + ".tmp-%s" % os.getpid()
        try:
            with open(temporary, "wb") as stream:
                stream.write(content)
            os.replace(temporary, target)
        finally:
            try:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            except OSError:
                pass


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
    try:
        _materialize_plugin_resources(root)
    except (OSError, RuntimeError) as exc:
        print("[mae-flow] %s" % exc, file=sys.stderr)
        raise SystemExit(2)

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
