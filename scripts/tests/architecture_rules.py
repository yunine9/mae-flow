"""Static architecture checks for Mae-Flow refactoring."""

import ast
import os
from pathlib import Path


FORBIDDEN_IMPORT_PREFIXES = (
    "mae_flow_core.workflow",
    "mae_flow_core.delivery",
    "mae_flow_core.quality",
    "mae_flow_core.guard",
)
FORBIDDEN_CALLS = {
    "print",
    "sys.exit",
    "os.chdir",
    "subprocess.run",
    "subprocess.Popen",
    "subprocess.call",
}
LEGACY_OVERSIZED_CORE_MODULES = {
    "scripts/mae_flow_core/capabilities.py",
    "scripts/mae_flow_core/lightcheck.py",
    "scripts/mae_flow_core/specengine.py",
}


def line_count(path):
    with open(path, encoding="utf-8") as stream:
        return sum(1 for _line in stream)


def _parse(path):
    with open(path, encoding="utf-8") as stream:
        return ast.parse(stream.read(), filename=path)


def module_imports(path):
    return {
        name for name, _line in _import_nodes(_parse(path))
    }


def _attribute_name(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def forbidden_calls(path):
    tree = _parse(path)
    aliases = _import_aliases(tree)
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _resolved_call_name(node.func, aliases)
        if name in FORBIDDEN_CALLS:
            calls.append("%s:%d" % (name, node.lineno))
    return calls


def _relative_module(node):
    package = ["mae_flow_core", "foundation"]
    keep = max(0, len(package) - max(0, node.level - 1))
    parts = package[:keep]
    if node.module:
        parts.extend(node.module.split("."))
    return ".".join(parts)


def _import_nodes(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            module = (
                _relative_module(node)
                if node.level else node.module or "")
            if module:
                yield module, node.lineno
            if not module.startswith(FORBIDDEN_IMPORT_PREFIXES):
                for alias in node.names:
                    if alias.name != "*":
                        yield ".".join(
                            part for part in (module, alias.name) if part
                        ), node.lineno


def _import_aliases(tree):
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                aliases[local] = (
                    alias.name if alias.asname else local)
        elif isinstance(node, ast.ImportFrom):
            module = (
                _relative_module(node)
                if node.level else node.module or "")
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                aliases[local] = ".".join(
                    part for part in (module, alias.name) if part)
    return aliases


def _resolved_call_name(function, aliases):
    raw = (
        function.id
        if isinstance(function, ast.Name)
        else _attribute_name(function)
    )
    head, separator, tail = raw.partition(".")
    resolved = aliases.get(head, head)
    return resolved + (separator + tail if separator else "")


def assert_foundation_dependencies(root):
    root_path = Path(root)
    foundation = root_path / "scripts" / "mae_flow_core" / "foundation"
    violations = []
    if not foundation.exists():
        return violations
    for path in sorted(foundation.rglob("*.py")):
        relative = path.relative_to(root_path).as_posix()
        tree = _parse(os.fspath(path))
        aliases = _import_aliases(tree)
        for name, line in _import_nodes(tree):
            if name.startswith(FORBIDDEN_IMPORT_PREFIXES):
                violations.append(
                    "%s:%d: forbidden import %s" % (
                        relative, line, name))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _resolved_call_name(node.func, aliases)
            if name in FORBIDDEN_CALLS:
                violations.append(
                    "%s:%d: forbidden call %s" % (
                        relative, node.lineno, name))
    return sorted(violations)


def assert_policy_dependencies(root):
    root_path = Path(root)
    workflow = root_path / "scripts" / "mae_flow_core" / "workflow"
    violations = []
    if not workflow.exists():
        return violations
    for path in sorted(workflow.rglob("*.py")):
        relative = path.relative_to(root_path).as_posix()
        tree = _parse(os.fspath(path))
        aliases = _import_aliases(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _resolved_call_name(node.func, aliases)
            if name in FORBIDDEN_CALLS:
                violations.append(
                    "%s:%d: forbidden call %s"
                    % (relative, node.lineno, name)
                )
    return sorted(violations)


def new_module_size_violations(root, maximum=500):
    root_path = Path(root)
    core = root_path / "scripts" / "mae_flow_core"
    violations = []
    if not core.exists():
        return violations
    for path in sorted(core.rglob("*.py")):
        relative = path.relative_to(root_path).as_posix()
        if (
            path.name == "__init__.py"
            or relative in LEGACY_OVERSIZED_CORE_MODULES
        ):
            continue
        count = line_count(os.fspath(path))
        if count > maximum:
            violations.append(
                "%s: %d lines exceeds %d"
                % (relative, count, maximum)
            )
    return violations
