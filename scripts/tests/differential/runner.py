#!/usr/bin/env python3
"""Run isolated Mae-Flow scenarios and compare full observable snapshots."""

import argparse
import difflib
import hashlib
import json
import os
import subprocess
import sys
import tempfile

TESTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if TESTS not in sys.path:
    sys.path.insert(0, TESTS)

from differential.normalize import normalize_value
from differential.scenarios import SCENARIOS
from differential.snapshot import Snapshot


DEFAULT_GOLDENS = os.path.join(
    os.path.dirname(__file__), "goldens", "phase2.json")


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _capture_files(root):
    result = {}
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(
            name for name in dirs
            if name not in {".git", "__pycache__"})
        for name in sorted(files):
            absolute = os.path.join(current, name)
            relative = os.path.relpath(absolute, root).replace("\\", "/")
            result[relative] = {
                "sha256": _sha256(absolute),
                "size": os.path.getsize(absolute),
            }
    return result


def _read_states(root):
    result = {}
    for name in sorted(os.listdir(root)):
        if not name.startswith(".mae-flow"):
            continue
        path = os.path.join(root, name)
        if not os.path.isfile(path) or name.endswith(".jsonl"):
            continue
        try:
            with open(path, encoding="utf-8-sig") as stream:
                result[name] = json.load(stream)
        except Exception as exc:
            result[name] = {
                "__unreadable__": "%s: %s" % (
                    type(exc).__name__, exc),
            }
    return result


def _git(root, *args):
    return subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    ).stdout.strip()


def run_scenario(implementation_root, scenario_name):
    if scenario_name not in SCENARIOS:
        raise ValueError("unknown scenario: " + scenario_name)
    implementation_root = os.path.abspath(implementation_root)
    with tempfile.TemporaryDirectory(prefix="mae-flow-diff-") as project:
        invocation, replacements = SCENARIOS[scenario_name](
            project, implementation_root)
        completed = subprocess.run(
            invocation["argv"],
            cwd=project,
            input=invocation.get("stdin", ""),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            env=invocation["env"],
            timeout=30,
        )
        replacements = dict(replacements)
        replacements[project.replace("\\", "/")] = "<PROJECT>"
        replacements[os.path.realpath(project).replace(
            "\\", "/")] = "<PROJECT>"
        replacements[implementation_root.replace("\\", "/")] = (
            "<IMPLEMENTATION>")
        replacements[os.path.realpath(implementation_root).replace(
            "\\", "/")] = "<IMPLEMENTATION>"
        snapshot = Snapshot(
            stdout=completed.stdout,
            stderr=completed.stderr,
            returncode=completed.returncode,
            files=_capture_files(project),
            state=_read_states(project),
            git={
                "branch": _git(project, "branch", "--show-current"),
                "head": _git(project, "rev-parse", "--verify", "HEAD"),
                "status": _git(
                    project,
                    "-c",
                    "core.quotepath=false",
                    "status",
                    "--porcelain",
                    "--untracked-files=all",
                ),
            },
        )
        return Snapshot.from_dict(
            normalize_value(snapshot.to_dict(), replacements))


def load_goldens(path):
    with open(path, encoding="utf-8") as stream:
        raw = json.load(stream)
    return {
        name: Snapshot.from_dict(value)
        for name, value in raw.items()
    }


def assert_matches_golden(testcase, name, actual, goldens):
    testcase.assertIn(name, goldens)
    testcase.assertEqual(goldens[name], actual)


def _snapshot_map(implementation_root):
    return {
        name: run_scenario(os.path.abspath(implementation_root), name)
        for name in sorted(SCENARIOS)
    }


def _serialize(snapshots):
    return {
        name: snapshot.to_dict()
        for name, snapshot in snapshots.items()
    }


def _json_text(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _write_goldens(path, snapshots):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(_json_text(_serialize(snapshots)))


def _compare(path, snapshots):
    expected = _serialize(load_goldens(path))
    actual = _serialize(snapshots)
    mismatches = 0
    for name in sorted(set(expected) | set(actual)):
        if expected.get(name) == actual.get(name):
            continue
        mismatches += 1
        print("".join(difflib.unified_diff(
            _json_text(expected.get(name)).splitlines(True),
            _json_text(actual.get(name)).splitlines(True),
            fromfile="golden/" + name,
            tofile="actual/" + name,
        )), end="")
    return mismatches


def _parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--implementation-root", required=True)
    parser.add_argument("--write-goldens")
    parser.add_argument("--goldens", default=DEFAULT_GOLDENS)
    return parser.parse_args()


if __name__ == "__main__":
    _ARGS = _parse_args()
    _SNAPSHOTS = _snapshot_map(_ARGS.implementation_root)
    if _ARGS.write_goldens:
        _write_goldens(_ARGS.write_goldens, _SNAPSHOTS)
        raise SystemExit(0)
    raise SystemExit(1 if _compare(_ARGS.goldens, _SNAPSHOTS) else 0)
