"""Structured subprocess suites for the final lean production runtime."""

import os
import subprocess


REFACTOR_SAFETY_SUITES = (
    ("Lean state contract", ("scripts/tests/test_lean_state.py",), 90, 4000),
    ("Lean migration mapping", ("scripts/tests/test_lean_migration.py",), 90, 4000),
    ("Lean migration CLI", ("scripts/tests/test_lean_migration_cli.py",), 90, 4000),
    ("Lean transition contract", ("scripts/tests/test_lean_transitions.py",), 90, 4000),
    ("Lean guidance and harness", ("scripts/tests/test_lean_guidance.py",), 90, 4000),
    ("Native guidance semantics", ("scripts/tests/test_native_guidance.py",), 90, 5000),
    ("Lean composition", ("scripts/tests/test_lean_composition.py",), 90, 4000),
    ("Lean semantic scenarios", ("scripts/tests/test_lean_semantic_scenarios.py",), 90, 6000),
    ("Windows lean runtime", ("scripts/tests/test_windows_lean_runtime.py",), 90, 6000),
    ("Lean delivery policy", ("scripts/tests/test_lean_delivery.py",), 90, 4000),
    ("Lean document paths", ("scripts/tests/test_lean_documents.py",), 90, 4000),
    ("Lean moonlight policy", ("scripts/tests/test_lean_moonlight.py",), 90, 4000),
    ("Lean toolbox selection", ("scripts/tests/test_lean_toolbox.py",), 90, 4000),
    ("Exact delivery manifest", ("scripts/tests/test_delivery_manifest.py",), 90, 4000),
    ("Lean safety kernel", ("scripts/tests/test_lean_safety_kernel.py",), 90, 5000),
    ("Lean Hook event router", ("scripts/tests/test_lean_hook_events.py",), 90, 4000),
    ("Lean Hook protocol adapter", ("scripts/tests/test_lean_hook_adapter.py",), 90, 5000),
    ("Real Hook registration protocol", ("scripts/tests/test_hook_protocol.py",), 90, 5000),
    ("Lean production CLI", ("scripts/tests/test_lean_cli.py",), 90, 5000),
    ("Opaque capability policy", ("scripts/tests/test_lean_capabilities.py",), 90, 4000),
    ("Reference source integrity", ("scripts/tests/test_capabilities.py",), 90, 4000),
    ("Reference prompt sources", ("scripts/tests/test_spec2code_prompt_resources.py",), 90, 4000),
    ("Lightcheck advisory", ("scripts/tests/test_lightcheck.py",), 90, 5000),
    ("Production architecture", ("scripts/tests/test_architecture.py",), 90, 5000),
    ("Managed file handles", ("scripts/tests/test_file_io.py",), 90, 4000),
    ("Final refactor contract", ("scripts/tests/test_refactor_completion.py",), 90, 4000),
    ("Atomic failure injection", ("scripts/tests/test_fault_injection.py",), 90, 4000),
)


def execute_refactor_safety_suites(
        root, python_executable, report, run=None):
    """Execute every registered suite and report every result immediately."""
    run = run or subprocess.run
    for label, command, timeout, output_limit in REFACTOR_SAFETY_SUITES:
        result = run(
            [
                python_executable,
                os.path.join(root, command[0]),
                *command[1:],
            ],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=timeout,
        )
        report(
            label,
            result.returncode == 0,
            (result.stdout + result.stderr)[-output_limit:],
        )
