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


def line_count(path):
    with open(path, encoding="utf-8") as stream:
        return sum(1 for _line in stream)


def _parse(path):
    with open(path, encoding="utf-8") as stream:
        return ast.parse(stream.read(), filename=path)


def module_imports(path):
    imports = set()
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imports.add("." * node.level + module)
    return imports


def _attribute_name(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def forbidden_calls(path):
    calls = []
    for node in ast.walk(_parse(path)):
        if not isinstance(node, ast.Call):
            continue
        name = (
            node.func.id
            if isinstance(node.func, ast.Name)
            else _attribute_name(node.func)
        )
        if name in FORBIDDEN_CALLS:
            calls.append("%s:%d" % (name, node.lineno))
    return calls


def _import_nodes(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            yield node.module or "", node.lineno


def assert_foundation_dependencies(root):
    root_path = Path(root)
    foundation = root_path / "scripts" / "mae_flow_core" / "foundation"
    violations = []
    if not foundation.exists():
        return violations
    for path in sorted(foundation.rglob("*.py")):
        relative = path.relative_to(root_path).as_posix()
        tree = _parse(os.fspath(path))
        for name, line in _import_nodes(tree):
            if name.startswith(FORBIDDEN_IMPORT_PREFIXES):
                violations.append(
                    "%s:%d: forbidden import %s" % (
                        relative, line, name))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else _attribute_name(node.func)
            )
            if name in FORBIDDEN_CALLS:
                violations.append(
                    "%s:%d: forbidden call %s" % (
                        relative, node.lineno, name))
    return sorted(violations)
