"""Static architecture checks for Mae-Flow refactoring."""

import ast
import os
import re
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

PRODUCTION_PYTHON_ROOTS = RUNTIME_ENTRYPOINTS

RETIRED_PRODUCTION_IMPORTS = (
    "mae_flow_core.capabilities",
    "mae_flow_core.capability_codecheck",
    "mae_flow_core.capability_packs",
    "mae_flow_core.capability_shared",
    "mae_flow_core.adapters.hook_active_events",
    "mae_flow_core.adapters.hook_runtime",
    "mae_flow_core.adapters.hook_runtime_contract_support",
    "mae_flow_core.adapters.hook_runtime_contracts",
    "mae_flow_core.adapters.hook_runtime_dependencies",
    "mae_flow_core.adapters.hook_runtime_source",
    "mae_flow_core.application.quality.codecheck",
    "mae_flow_core.application.quality.codecheck_state",
    "mae_flow_core.application.hooks.agent_completion",
    "mae_flow_core.application.hooks.receipts",
    "mae_flow_core.application.hooks.task_cards",
    "mae_flow_core.application.quality.role_task_documents",
    "mae_flow_core.application.quality.task_cards",
    "mae_flow_core.application.quality.task_card_documents",
    "mae_flow_core.cli_commands.agent_task",
    "mae_flow_core.cli_commands.evidence_registry",
    "mae_flow_core.cli_commands.role_task",
    "mae_flow_core.codecheck_log",
    "mae_flow_core.delivery.evidence",
    "mae_flow_core.quality.agent_contracts",
    "mae_flow_core.quality.agent_reports",
    "mae_flow_core.quality.codecheck",
    "mae_flow_core.quality.codecheck_contract",
    "mae_flow_core.quality.compile_side_effects",
    "mae_flow_core.quality.compile_contract",
    "mae_flow_core.quality.evidence",
    "mae_flow_core.quality.grill_contract",
    "mae_flow_core.quality.role_tasks",
    "mae_flow_core.quality.spec2code_artifacts",
    "mae_flow_core.quality.spec2code_recovery",
    "mae_flow_core.quality.task_cards",
    "mae_flow_core.quality.tool_transcript",
    "mae_flow_core.quality.unit_test_contract",
    "mae_flow_core.quality.unit_test_execution",
    "mae_flow_core.workflow.agent_evidence",
    "mae_flow_core.workflow.evidence",
    "mae_flow_core.workflow.evidence_rules",
)

RETIRED_PRODUCTION_NAMES = {
    "CAPABILITY_PACKS",
    "CodeCheckRunPorts",
    "CodeCheckRunResult",
    "CodeCheckScan",
    "CodeCheckScope",
    "CodeCheckWarning",
    "CompletedScan",
    "ContractMarker",
    "DeliveryEvidencePorts",
    "DeliveryEvidenceRules",
    "EvidenceRegistry",
    "ExecutionRootPlan",
    "ExecutionRootPorts",
    "ManualRecords",
    "QualityEvidencePorts",
    "QualityEvidenceRules",
    "ReceiptContext",
    "TaskCardArtifact",
    "TaskCardDocument",
    "TaskCardPorts",
    "TaskCardStorePorts",
    "TaskFileGroups",
    "ToolCall",
    "Transcript",
    "AgentEvidenceRules",
    "AgentEvidencePorts",
    "AgentContractContext",
    "WorkflowEvidencePorts",
    "WorkflowEvidenceRules",
    "ROLE_STEPS",
    "append_codecheck_event",
    "askuser_receipt",
    "build_evidence_registry",
    "codecheck_log_path",
    "compile_side_effect_paths",
    "ensure_codecheck",
    "evaluate_codecheck_contract",
    "evaluate_compile_contract",
    "evaluate_grill_contract",
    "evaluate_step_evidence",
    "evaluate_unit_test_contract",
    "legacy_result",
    "parse_transcript",
    "plan_codecheck_build_receipt",
    "plan_codecheck_fullcheck_receipt",
    "plan_compile_run_receipt",
    "plan_ut_generator_receipt",
    "plan_ut_run_receipt",
    "prepare_project",
    "recovery_guidance",
    "report_field",
    "report_number",
    "report_section",
    "reported_bash_call",
    "reusable_codecheck_build_receipt",
    "reusable_codecheck_fullcheck_receipt",
    "reusable_compile_run_receipt",
    "reusable_ut_receipt",
    "role_allowed",
    "select_contract_marker",
    "store_task_card",
    "verify_agent_scope",
    "verify_completion_task",
    "verify_dispatch_task",
}

RETIRED_PRODUCTION_TEXT = (
    ("accept-risk", "accept-risk token"),
    ("task_card", "task-card contract"),
    ("task-card", "task-card contract"),
    ("_RESULT:", "agent report token"),
    ("parse_agent_report", "agent report parser"),
)

MIGRATION_ONLY_TEXT = {
    "scripts/mae_flow_core/orchestration/migration.py": {
        "task-card contract",
    },
}

RETIRED_GUIDANCE_PATTERNS = (
    (r"\bCAPABILITY_PACKS\b", "CAPABILITY_PACKS"),
    (r"\baccept-risk\b", "accept-risk token"),
    (r"\btask[_ -]?card\b", "task-card contract"),
    (r"\b(?:COMPILE|UT|CODECHECK|GRILL|STORY)_RESULT:\b",
     "agent report token"),
    (r"\bopenspec\s+(?:new|status|instructions|validate|archive|show|list|schemas)\b",
     "OpenSpec lifecycle command"),
    (r"/(?:opsx|comet)(?::|-)\w+", "old lifecycle command"),
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


def _module_file(root_path, module):
    if not module or not module.startswith("mae_flow_core"):
        return ""
    relative = module.replace(".", "/")
    candidates = (
        root_path / "scripts" / (relative + ".py"),
        root_path / "scripts" / relative / "__init__.py",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.relative_to(root_path).as_posix()
    return ""


def _module_name(relative):
    if not relative.startswith("scripts/mae_flow_core/"):
        return ""
    value = relative[len("scripts/"):-3].replace("/", ".")
    return value[:-9] if value.endswith(".__init__") else value


def _resolved_import_modules(relative, tree):
    current = _module_name(relative)
    package = (
        current if relative.endswith("/__init__.py")
        else current.rpartition(".")[0]
    )
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level:
            parts = package.split(".") if package else []
            keep = max(0, len(parts) - node.level + 1)
            prefix = parts[:keep]
            if node.module:
                prefix.extend(node.module.split("."))
            module = ".".join(prefix)
        else:
            module = node.module or ""
        if module:
            modules.add(module)
        for alias in node.names:
            if alias.name != "*":
                modules.add(".".join(
                    part for part in (module, alias.name) if part))
    return modules


def production_reachable_python_files(root):
    """Return local Python files imported from the production adapters."""
    root_path = Path(root)
    pending = list(PRODUCTION_PYTHON_ROOTS)
    reachable = set()
    while pending:
        relative = pending.pop()
        if relative in reachable:
            continue
        path = root_path / relative
        if not path.is_file():
            continue
        reachable.add(relative)
        tree = _parse(os.fspath(path))
        for module in _resolved_import_modules(relative, tree):
            imported = _module_file(root_path, module)
            if imported and imported not in reachable:
                pending.append(imported)
            parts = module.split(".")
            for index in range(1, len(parts)):
                package = _module_file(root_path, ".".join(parts[:index]))
                if package and package not in reachable:
                    pending.append(package)
    return tuple(sorted(reachable))


def production_reachability_violations(root):
    """Reject retired protocol contracts anywhere in the production graph."""
    root_path = Path(root)
    violations = []
    for relative in production_reachable_python_files(root):
        path = root_path / relative
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=os.fspath(path))
        for module, line in _import_nodes(tree):
            if any(
                    module == retired or module.startswith(retired + ".")
                    for retired in RETIRED_PRODUCTION_IMPORTS):
                violations.append(
                    "%s:%d: retired import %s" % (relative, line, module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in RETIRED_PRODUCTION_NAMES:
                violations.append(
                    "%s:%d: retired name %s" % (
                        relative, node.lineno, node.id))
            elif isinstance(node, ast.Attribute) and node.attr in RETIRED_PRODUCTION_NAMES:
                violations.append(
                    "%s:%d: retired name %s" % (
                        relative, node.lineno, node.attr))
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                for token, label in RETIRED_PRODUCTION_TEXT:
                    if (token in node.value and label not in
                            MIGRATION_ONLY_TEXT.get(relative, set())):
                        violations.append(
                            "%s:%d: retired %s" % (
                                relative, node.lineno, label))
                if re.search(
                        r"\bopenspec\s+(?:new|status|instructions|validate|"
                        r"archive|show|list|schemas)\b",
                        node.value,
                        flags=re.I):
                    violations.append(
                        "%s:%d: retired OpenSpec lifecycle command" % (
                            relative, node.lineno))
    return sorted(set(violations))


def retired_guidance_violations(root):
    """Reject legacy machine protocols in native phase guidance."""
    root_path = Path(root)
    violations = []
    guidance = root_path / "runtime" / "guidance"
    for path in sorted(guidance.glob("*.md")):
        relative = path.relative_to(root_path).as_posix()
        for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1):
            for pattern, label in RETIRED_GUIDANCE_PATTERNS:
                if re.search(pattern, line, flags=re.I):
                    violations.append(
                        "%s:%d: retired %s" % (
                            relative, line_number, label))
    return violations


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
