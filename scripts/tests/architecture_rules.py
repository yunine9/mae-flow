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
LEGACY_OVERSIZED_CORE_MODULES = set()
RUNTIME_ENTRYPOINTS = (
    "scripts/mae-flow.py",
    "hooks/dispatch.py",
    "scripts/comet_compat.py",
    "scripts/statusline.py",
)


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


def unmanaged_runtime_open_violations(root):
    root_path = Path(root)
    violations = []
    for relative in RUNTIME_ENTRYPOINTS:
        path = root_path / relative
        tree = _parse(os.fspath(path))
        managed_calls = {
            call
            for node in ast.walk(tree)
            if isinstance(node, (ast.With, ast.AsyncWith))
            for item in node.items
            for call in ast.walk(item.context_expr)
            if isinstance(call, ast.Call)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "open"
                and node not in managed_calls
            ):
                violations.append(
                    "%s:%d: unmanaged open()" % (relative, node.lineno)
                )
    return sorted(violations)


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


def assert_guard_dependencies(root):
    root_path = Path(root)
    guard = root_path / "scripts" / "mae_flow_core" / "guard"
    violations = []
    if not guard.exists():
        return violations
    for path in sorted(guard.rglob("*.py")):
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


def assert_quality_dependencies(root):
    root_path = Path(root)
    violations = []
    directories = (
        root_path / "scripts" / "mae_flow_core" / "quality",
        root_path / "scripts" / "mae_flow_core" / "application" / "quality",
    )
    for quality in directories:
        if not quality.exists():
            continue
        for path in sorted(quality.rglob("*.py")):
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


def _quality_directories(root_path):
    return (
        root_path / "scripts" / "mae_flow_core" / "quality",
        root_path / "scripts" / "mae_flow_core" / "application" / "quality",
    )


def assert_delivery_dependencies(root):
    root_path = Path(root)
    violations = []
    directories = (
        root_path / "scripts" / "mae_flow_core" / "delivery",
        root_path / "scripts" / "mae_flow_core" / "application" / "delivery",
    )
    for delivery in directories:
        if not delivery.exists():
            continue
        for path in sorted(delivery.rglob("*.py")):
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


def assert_hook_application_dependencies(root):
    """Hook application use cases sequence effects but never perform them."""
    root_path = Path(root)
    hooks = (
        root_path / "scripts" / "mae_flow_core" / "application" / "hooks")
    violations = []
    if not hooks.exists():
        return violations
    for path in sorted(hooks.rglob("*.py")):
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


def private_hook_import_violations(root):
    """Find business tests that dynamically load the Hook entrypoint."""
    root_path = Path(root)
    tests = root_path / "scripts" / "tests"
    allowed = {"test_hook_protocol.py"}
    violations = []
    for path in sorted(tests.glob("test_*.py")):
        if path.name in allowed:
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=os.fspath(path))
        aliases = _import_aliases(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _resolved_call_name(node.func, aliases)
            if name not in {
                    "importlib.util.spec_from_file_location",
                    "runpy.run_path"}:
                continue
            fragment = ast.get_source_segment(source, node) or ""
            if "dispatch.py" in fragment:
                violations.append(
                    "%s:%d: private Hook entrypoint import"
                    % (path.relative_to(root_path).as_posix(), node.lineno)
                )
    return sorted(violations)


def private_cli_import_violations(root):
    """Find business tests that dynamically load the CLI entrypoint."""
    root_path = Path(root)
    tests = root_path / "scripts" / "tests"
    violations = []
    for path in sorted(tests.glob("test_*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=os.fspath(path))
        aliases = _import_aliases(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _resolved_call_name(node.func, aliases)
            if name not in {
                    "importlib.util.spec_from_file_location",
                    "runpy.run_path"}:
                continue
            fragment = ast.get_source_segment(source, node) or ""
            if "mae-flow.py" in fragment:
                violations.append(
                    "%s:%d: private CLI entrypoint import"
                    % (path.relative_to(root_path).as_posix(), node.lineno)
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


class _ComplexityVisitor(ast.NodeVisitor):
    def __init__(self):
        self.value = 1

    def visit_If(self, node):
        self.value += 1
        self.generic_visit(node)

    def visit_For(self, node):
        self.value += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node):
        self.value += 1
        self.generic_visit(node)

    def visit_While(self, node):
        self.value += 1
        self.generic_visit(node)

    def visit_IfExp(self, node):
        self.value += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node):
        self.value += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node):
        self.value += max(0, len(node.values) - 1)
        self.generic_visit(node)

    def visit_comprehension(self, node):
        self.value += 1 + len(node.ifs)
        self.visit(node.target)
        self.visit(node.iter)
        for condition in node.ifs:
            self.visit(condition)

    def visit_FunctionDef(self, node):
        return

    def visit_AsyncFunctionDef(self, node):
        return

    def visit_Lambda(self, node):
        return

    def visit_ClassDef(self, node):
        return


def _node_complexity(node):
    visitor = _ComplexityVisitor()
    for statement in node.body:
        visitor.visit(statement)
    return visitor.value


def function_complexity(path, function_name):
    tree = _parse(path)
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function_name
        ):
            return _node_complexity(node)
    raise ValueError(
        "function %s not found in %s" % (function_name, path)
    )


def workflow_complexity_violations(root, maximum=15):
    root_path = Path(root)
    workflow = root_path / "scripts" / "mae_flow_core" / "workflow"
    violations = []
    if not workflow.exists():
        return violations
    for path in sorted(workflow.rglob("*.py")):
        relative = path.relative_to(root_path).as_posix()
        tree = _parse(os.fspath(path))
        functions = [
            node
            for node in ast.walk(tree)
            if isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef),
            )
        ]
        for node in sorted(functions, key=lambda item: item.lineno):
            complexity = _node_complexity(node)
            if complexity > maximum:
                violations.append(
                    "%s:%d: %s complexity %d exceeds %d"
                    % (
                        relative,
                        node.lineno,
                        node.name,
                        complexity,
                        maximum,
                    )
                )
    return violations


def guard_complexity_violations(root, maximum=15):
    root_path = Path(root)
    guard = root_path / "scripts" / "mae_flow_core" / "guard"
    violations = []
    if not guard.exists():
        return violations
    for path in sorted(guard.rglob("*.py")):
        relative = path.relative_to(root_path).as_posix()
        for node in ast.walk(_parse(os.fspath(path))):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            complexity = _node_complexity(node)
            if complexity > maximum:
                violations.append(
                    "%s:%d: %s complexity %d exceeds %d"
                    % (relative, node.lineno, node.name, complexity, maximum)
                )
    return violations


def quality_complexity_violations(root, maximum=15):
    root_path = Path(root)
    violations = []
    for quality in _quality_directories(root_path):
        if not quality.exists():
            continue
        for path in sorted(quality.rglob("*.py")):
            relative = path.relative_to(root_path).as_posix()
            for node in ast.walk(_parse(os.fspath(path))):
                if not isinstance(
                        node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                complexity = _node_complexity(node)
                if complexity > maximum:
                    violations.append(
                        "%s:%d: %s complexity %d exceeds %d"
                        % (
                            relative, node.lineno, node.name,
                            complexity, maximum,
                        )
                    )
    return violations


def delivery_complexity_violations(root, maximum=15):
    root_path = Path(root)
    violations = []
    directories = (
        root_path / "scripts" / "mae_flow_core" / "delivery",
        root_path / "scripts" / "mae_flow_core" / "application" / "delivery",
    )
    for delivery in directories:
        if not delivery.exists():
            continue
        for path in sorted(delivery.rglob("*.py")):
            relative = path.relative_to(root_path).as_posix()
            for node in ast.walk(_parse(os.fspath(path))):
                if not isinstance(
                        node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                complexity = _node_complexity(node)
                if complexity > maximum:
                    violations.append(
                        "%s:%d: %s complexity %d exceeds %d"
                        % (
                            relative, node.lineno, node.name,
                            complexity, maximum,
                        )
                    )
    return violations


def hook_complexity_violations(root, maximum=15):
    root_path = Path(root)
    hooks = (
        root_path / "scripts" / "mae_flow_core" / "application" / "hooks")
    violations = []
    if not hooks.exists():
        return violations
    for path in sorted(hooks.rglob("*.py")):
        relative = path.relative_to(root_path).as_posix()
        for node in ast.walk(_parse(os.fspath(path))):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            complexity = _node_complexity(node)
            if complexity > maximum:
                violations.append(
                    "%s:%d: %s complexity %d exceeds %d"
                    % (relative, node.lineno, node.name, complexity, maximum)
                )
    return violations


def _relative_import_module(node, package):
    """Resolve ``from . import x`` / ``from ..y import z`` to a module name."""
    parts = package.split(".")
    base = ".".join(parts[:len(parts) - (node.level - 1)])
    return (base + "." + node.module) if node.module else base


def _imported_core_modules(path, package, root_path):
    """Collect ``mae_flow_core`` modules a single file statically imports."""
    imported = set()
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.Import):
            imported.update(
                alias.name for alias in node.names
                if alias.name.startswith("mae_flow_core"))
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        module = (
            _relative_import_module(node, package)
            if node.level else (node.module or ""))
        if not module.startswith("mae_flow_core"):
            continue
        imported.add(module)
        # ``from pkg.mod import name`` may import a submodule, not an object.
        imported.update(module + "." + alias.name for alias in node.names)
    return {
        module for module in imported
        if _module_file(module, root_path) is not None
    }


def _module_file(module, root_path):
    base = root_path / "scripts" / Path(*module.split("."))
    if (base / "__init__.py").is_file():
        return base / "__init__.py"
    candidate = base.with_suffix(".py")
    return candidate if candidate.is_file() else None


def unreachable_core_modules(root):
    """Return production modules no runtime entrypoint can ever import.

    Dead runtime code is a live hazard here rather than mere clutter: a
    maintainer chasing a Hook defect can spend a session "fixing" an adapter
    the dispatcher never loads, with the whole suite staying green.
    """
    root_path = Path(root)
    queue = []
    for relative in RUNTIME_ENTRYPOINTS:
        path = root_path / relative
        if path.is_file():
            queue.extend(
                _imported_core_modules(
                    os.fspath(path), "mae_flow_core", root_path))
    reached = set()
    while queue:
        module = queue.pop()
        if module in reached:
            continue
        path = _module_file(module, root_path)
        if path is None:
            continue
        reached.add(module)
        package = (
            module if path.name == "__init__.py"
            else module.rsplit(".", 1)[0])
        queue.extend(
            _imported_core_modules(os.fspath(path), package, root_path))
    # Importing a submodule executes every ancestor ``__init__.py``, so those
    # packages are reached even without a statement naming them.
    for module in tuple(reached):
        parts = module.split(".")
        for depth in range(1, len(parts)):
            reached.add(".".join(parts[:depth]))
    package_root = root_path / "scripts" / "mae_flow_core"
    everything = set()
    for path in sorted(package_root.rglob("*.py")):
        relative = path.relative_to(root_path / "scripts").as_posix()
        module = relative[:-len(".py")].replace("/", ".")
        everything.add(
            module[:-len(".__init__")] if module.endswith(".__init__")
            else module)
    return sorted(everything - reached)
