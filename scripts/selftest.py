#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One fresh release regression for the final lean Mae-Flow runtime."""

import json
import os
import sys


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
TESTS = os.path.join(HERE, "tests")
if TESTS not in sys.path:
    sys.path.insert(0, TESTS)

from selftest_suites import execute_refactor_safety_suites  # noqa: E402


for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


failures = []
checks = 0


def check(name, ok, detail=""):
    global checks
    checks += 1
    print(("✅ " if ok else "❌ ") + name)
    if not ok:
        failures.append((name, detail))
        if detail:
            print(detail)


def _python_sources():
    roots = (
        os.path.join(ROOT, "scripts"),
        os.path.join(ROOT, "hooks"),
    )
    for base in roots:
        for current, directories, files in os.walk(base):
            directories[:] = [
                name for name in directories
                if name not in {"__pycache__", ".mae-flow-work"}
            ]
            for name in sorted(files):
                if name.endswith(".py"):
                    yield os.path.join(current, name)


def _syntax_check():
    errors = []
    sources = list(_python_sources())
    for path in sources:
        try:
            with open(path, encoding="utf-8") as stream:
                compile(stream.read(), path, "exec")
        except Exception as exc:
            errors.append("%s: %s" % (
                os.path.relpath(path, ROOT), exc))
    check("Python sources compile (%d)" % len(sources), not errors,
          "\n".join(errors))


def _json_check():
    files = (
        "hooks/hooks.json",
        "runtime/vendor/manifest.json",
        "runtime/guidance/capability-preservation.json",
        "scripts/tests/architecture_baseline.json",
        "scripts/tests/refactor_completion_contract.json",
    )
    errors = []
    for relative in files:
        try:
            with open(os.path.join(ROOT, relative), encoding="utf-8") as stream:
                json.load(stream)
        except Exception as exc:
            errors.append("%s: %s" % (relative, exc))
    check("Runtime JSON documents load (%d)" % len(files), not errors,
          "\n".join(errors))


def _retained_sources_check():
    required = (
        "runtime/vendor/openspec/LICENSE",
        "runtime/vendor/comet/LICENSE",
        "runtime/vendor/superpowers/LICENSE",
        "runtime/vendor/ponytail/LICENSE",
        "runtime/vendor/lizard/LICENSE.txt",
        "runtime/vendor/lizard/LICENSE-APACHE-2.0.txt",
        "runtime/THIRD_PARTY_NOTICES.md",
        "scripts/mae_flow_core/capability_shared.py",
        "scripts/mae_flow_core/capability_packs.py",
        "scripts/mae_flow_core/workflow/evidence.py",
        "scripts/mae_flow_core/workflow/agent_evidence.py",
        "scripts/mae_flow_core/quality/agent_contracts.py",
        "scripts/mae_flow_core/orchestration/migration.py",
    )
    missing = [
        relative for relative in required
        if not os.path.isfile(os.path.join(ROOT, relative))
    ]
    check("Reference, license, and migration sources remain", not missing,
          "missing: " + ", ".join(missing))


_syntax_check()
_json_check()
_retained_sources_check()
execute_refactor_safety_suites(
    ROOT, sys.executable, report=check)

if failures:
    print("\n失败 %d/%d 项 ❌" % (len(failures), checks))
    raise SystemExit(1)
print("\n全部通过 %d 项 ✅" % checks)
