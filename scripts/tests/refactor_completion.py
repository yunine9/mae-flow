"""Validation helpers for the Mae-Flow refactor completion contract."""

import json
import os

from architecture_rules import production_reachable_python_files


APPROVED_FINAL_TARGETS = {
    "max_entrypoint_lines": {
        "scripts/mae-flow.py": 1500,
        "hooks/dispatch.py": 800,
    },
    "max_business_module_lines": 500,
    "max_policy_complexity": 15,
    "private_monolith_test_imports": 0,
    "production_reachable_python_files": 66,
}

APPROVED_RELEASE_SUITE_COMMANDS = [
    "python scripts/tests/test_lean_state.py",
    "python scripts/tests/test_lean_migration.py",
    "python scripts/tests/test_lean_migration_cli.py",
    "python scripts/tests/test_lean_transitions.py",
    "python scripts/tests/test_lean_guidance.py",
    "python scripts/tests/test_native_guidance.py",
    "python scripts/tests/test_lean_composition.py",
    "python scripts/tests/test_lean_semantic_scenarios.py",
    "python scripts/tests/test_windows_lean_runtime.py",
    "python scripts/tests/test_lean_delivery.py",
    "python scripts/tests/test_lean_documents.py",
    "python scripts/tests/test_lean_moonlight.py",
    "python scripts/tests/test_lean_toolbox.py",
    "python scripts/tests/test_delivery_manifest.py",
    "python scripts/tests/test_lean_safety_kernel.py",
    "python scripts/tests/test_lean_hook_events.py",
    "python scripts/tests/test_lean_hook_adapter.py",
    "python scripts/tests/test_hook_protocol.py",
    "python scripts/tests/test_lean_cli.py",
    "python scripts/tests/test_lean_capabilities.py",
    "python scripts/tests/test_capabilities.py",
    "python scripts/tests/test_spec2code_prompt_resources.py",
    "python scripts/tests/test_lightcheck.py",
    "python scripts/tests/test_architecture.py",
    "python scripts/tests/test_file_io.py",
    "python scripts/tests/test_refactor_completion.py",
    "python scripts/tests/test_fault_injection.py",
]

APPROVED_REQUIRED_VERIFICATIONS = {
    "release_suites": APPROVED_RELEASE_SUITE_COMMANDS,
    "selftest": [
        "python scripts/selftest.py",
    ],
}


def load_contract(path):
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def reachability_target_errors(target, baseline_files, actual_files):
    """Bind the contract cap to both exact reachability representations."""
    errors = []
    baseline = tuple(baseline_files)
    actual = tuple(actual_files)
    if len(baseline) != target:
        errors.append(
            "production reachability baseline count %d does not match "
            "contract target %d" % (len(baseline), target))
    if len(actual) != target:
        errors.append(
            "production reachability actual count %d does not match "
            "contract target %d" % (len(actual), target))
    added = sorted(set(actual) - set(baseline))
    removed = sorted(set(baseline) - set(actual))
    if added:
        errors.append("production reachability added: " + ", ".join(added))
    if removed:
        errors.append(
            "production reachability removed: " + ", ".join(removed))
    return errors


def validate_contract(root, contract):
    errors = []
    if contract.get("schema") != 1:
        errors.append("schema must be 1")
    if contract.get("behavior_baseline") != "phase9":
        errors.append("behavior_baseline must be phase9")
    if contract.get("final_targets") != APPROVED_FINAL_TARGETS:
        errors.append(
            "final_targets must match the approved completion thresholds")
    if (contract.get("required_verifications")
            != APPROVED_REQUIRED_VERIFICATIONS):
        errors.append(
            "required_verifications must match the approved release gates")
    stages = contract.get("stages", [])
    if [item.get("id") for item in stages] != list(range(10)):
        errors.append("stages must be ordered 0 through 9")

    baseline_path = os.path.join(
        root, "scripts", "tests", "architecture_baseline.json")
    with open(baseline_path, encoding="utf-8") as stream:
        baseline = json.load(stream)
    reachability_target = contract.get("final_targets", {}).get(
        "production_reachable_python_files")
    if isinstance(reachability_target, int) and reachability_target >= 0:
        errors.extend(reachability_target_errors(
            reachability_target,
            baseline.get("production_reachable_python_files", []),
            production_reachable_python_files(root),
        ))
    targets = contract.get("final_targets", {}).get(
        "max_entrypoint_lines", {})
    for relative, maximum in sorted(targets.items()):
        current = baseline.get("max_lines", {}).get(relative)
        if current is None:
            errors.append(relative + ": missing current architecture baseline")
        elif not isinstance(maximum, int) or maximum <= 0:
            errors.append(
                "%s: final target %s must be a positive integer"
                % (relative, maximum))

    required_domains = {
        "runtime", "workflow", "evidence", "gate", "ownership",
        "delivery", "quality", "hook", "state", "platform",
    }
    if set(contract.get("domains", [])) != required_domains:
        errors.append("domains do not match the completion roadmap")
    if set(contract.get("observables", [])) != {
            "stdout", "stderr", "returncode", "files", "state", "git"}:
        errors.append("observable dimensions are incomplete")
    return errors
