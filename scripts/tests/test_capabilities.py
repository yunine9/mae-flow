#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for Mae-Flow's self-contained capability runtime."""

import glob
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROOT = os.path.abspath(os.path.join(SCRIPTS, ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core import (  # noqa: E402
    CAPABILITY_PACKS,
    configure_comet_build,
    prepare_project,
    render_pack,
    run_comet,
    run_openspec,
)
from mae_flow_core import capabilities  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


class EmbeddedCapabilityTests(unittest.TestCase):
    def test_all_phase_packs_are_pinned_and_host_safe(self):
        expected = {
            "open", "hotfix-open", "tweak-open", "design", "build",
            "review-fix", "tweak-build", "ponytail-review", "verify",
            "archive",
        }
        self.assertEqual(expected, set(CAPABILITY_PACKS))
        forbidden = (
            "/comet-open", "/comet-design", "/comet-build",
            "/comet-verify", "/comet-archive", "/comet-hotfix",
            "/comet-tweak", "/opsx:", "COMET_ENV", "$COMET_",
            "使用 Skill 工具加载", "comet/reference/", "/<SKILL>",
            "superpowers:", "安装或启用 Superpowers",
        )
        for name in sorted(CAPABILITY_PACKS):
            with self.subTest(pack=name):
                text = render_pack(name)
                self.assertGreater(len(text), 1000)
                for needle in forbidden:
                    self.assertNotIn(needle, text)
                self.assertNotRegex(text, r"(?m)^\s*openspec\s+")
                self.assertIn("mae-flow.py", text)

        self.assertIn("PRD 拆分预检", render_pack("open"))
        self.assertIn("根因分析", render_pack("hotfix-open"))
        self.assertIn("升级条件", render_pack("tweak-open"))
        self.assertIn("OpenSpec → Superpowers 交接包", render_pack("design"))
        self.assertIn("Spec 增量更新", render_pack("build"))
        self.assertIn("根因消除检查", render_pack("build"))
        self.assertIn("验证失败决策", render_pack("verify"))
        self.assertIn("生命周期闭环", render_pack("archive"))
        checks = capabilities.diagnostics(ROOT)
        integrity = [
            item for item in checks
            if item["name"].startswith("源码完整性 ")]
        self.assertEqual(4, len(integrity))
        self.assertTrue(all(item["ok"] for item in integrity), integrity)

    def test_prepare_and_full_embedded_lifecycle_in_unicode_path(self):
        with tempfile.TemporaryDirectory(prefix="mae flow 中文 ") as root:
            subprocess.run(
                ["git", "init", "-q", root],
                check=True, capture_output=True, text=True)
            prepared = prepare_project(root)
            self.assertEqual("1.6.0", prepared["openspec"])
            self.assertIn("Python ", prepared["python"])
            self.assertIn("git version", prepared["git"].lower())
            self.assertIn("node", prepared)
            self.assertIn("bash", prepared)
            self.assertFalse(prepared["created_project_skills"])
            self.assertFalse(os.path.exists(os.path.join(root, ".cac")))
            self.assertFalse(os.path.exists(os.path.join(root, ".claude")))
            with open(
                    os.path.join(root, ".comet", "config.yaml"),
                    encoding="utf-8") as stream:
                config = stream.read()
            self.assertIn("auto_transition: false", config)
            self.assertIn("review_mode: standard", config)

            created = run_openspec(
                ["new", "change", "embedded-smoke"], cwd=root)
            self.assertEqual(0, created.returncode, created.stderr)
            self.assertEqual(
                1, created.stdout.count("Created change 'embedded-smoke'"))

            change = os.path.join(
                root, "openspec", "changes", "embedded-smoke")
            write(
                os.path.join(change, "proposal.md"),
                "# Proposal\n\n## Why\n\nRuntime smoke.\n\n"
                "## What Changes\n\nUse bundled runtime.\n")
            write(
                os.path.join(change, "design.md"),
                "# Design\n\nUse the pinned embedded runtime.\n")
            write(
                os.path.join(change, "tasks.md"),
                "# Tasks\n\n- [x] 1. Embedded runtime works\n")
            write(
                os.path.join(change, "specs", "runtime", "spec.md"),
                "# Runtime Specification\n\n"
                "## ADDED Requirements\n\n"
                "### Requirement: Embedded runtime\n"
                "The system SHALL execute the bundled runtime.\n\n"
                "#### Scenario: Runtime starts\n"
                "- **WHEN** a project starts Mae-Flow\n"
                "- **THEN** the embedded runtime is available\n")

            result = run_comet(
                "state", ["init", "embedded-smoke", "full"], cwd=root)
            self.assertEqual(0, result.returncode, result.stderr)
            result = run_comet(
                "guard", ["embedded-smoke", "open", "--apply"], cwd=root)
            self.assertEqual(0, result.returncode, result.stderr)
            result = run_comet(
                "handoff", ["embedded-smoke", "design", "--write"], cwd=root)
            self.assertEqual(0, result.returncode, result.stderr)

            design_doc = os.path.join(
                root, "docs", "superpowers", "specs", "embedded-design.md")
            write(
                design_doc,
                "---\n"
                "comet_change: embedded-smoke\n"
                "role: technical-design\n"
                "canonical_spec: openspec\n"
                "---\n"
                "# Embedded Design\n")
            result = run_comet(
                "state",
                ["set", "embedded-smoke", "design_doc",
                 "docs/superpowers/specs/embedded-design.md"],
                cwd=root)
            self.assertEqual(0, result.returncode, result.stderr)
            result = run_comet(
                "guard", ["embedded-smoke", "design", "--apply"], cwd=root)
            self.assertEqual(0, result.returncode, result.stderr)

            applied = configure_comet_build("embedded-smoke", cwd=root)
            self.assertEqual(6, len(applied))
            result = run_comet(
                "state",
                ["transition", "embedded-smoke", "build-complete"],
                cwd=root)
            self.assertEqual(0, result.returncode, result.stderr)

            report = os.path.join(
                root, "docs", "superpowers", "reports",
                "embedded-verify.md")
            write(report, "# Verification\n\nAll checks passed.\n")
            for field, value in (
                    ("verification_report",
                     "docs/superpowers/reports/embedded-verify.md"),
                    ("branch_status", "handled")):
                result = run_comet(
                    "state", ["set", "embedded-smoke", field, value],
                    cwd=root)
                self.assertEqual(0, result.returncode, result.stderr)
            result = run_comet(
                "state", ["transition", "embedded-smoke", "verify-pass"],
                cwd=root)
            self.assertEqual(0, result.returncode, result.stderr)

            archived = run_comet(
                "archive", ["embedded-smoke"], cwd=root, timeout=180)
            self.assertEqual(
                0, archived.returncode,
                (archived.stdout or "") + (archived.stderr or ""))
            self.assertFalse(os.path.exists(change))
            archived_dirs = glob.glob(os.path.join(
                root, "openspec", "changes", "archive",
                "*-embedded-smoke"))
            self.assertEqual(1, len(archived_dirs))
            with open(
                    os.path.join(archived_dirs[0], ".comet.yaml"),
                    encoding="utf-8") as stream:
                archived_state = stream.read()
            self.assertIn("archived: true", archived_state)
            self.assertTrue(os.path.isfile(os.path.join(
                root, "openspec", "specs", "runtime", "spec.md")))

    def test_host_runtime_diagnostics_show_versions_and_paths(self):
        checks = {
            item["name"]: item
            for item in capabilities.diagnostics(ROOT)
        }
        for name in ("Python", "Git", "Node.js", "Git Bash"):
            with self.subTest(runtime=name):
                self.assertIn(name, checks)
                self.assertTrue(checks[name]["ok"], checks[name])
                self.assertIn(" — ", checks[name]["detail"])

    def test_prepare_accepts_git_worktree_dot_git_file(self):
        with tempfile.TemporaryDirectory(prefix="mae worktree ") as base:
            repository = os.path.join(base, "main")
            worktree = os.path.join(base, "分支 worktree")
            subprocess.run(
                ["git", "init", "-q", repository],
                check=True, capture_output=True, text=True)
            write(os.path.join(repository, "README.md"), "runtime test\n")
            subprocess.run(
                ["git", "-C", repository, "add", "README.md"],
                check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "-C", repository, "-c", "user.name=Mae Flow",
                 "-c", "user.email=mae-flow@example.invalid",
                 "commit", "-q", "-m", "init"],
                check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "-C", repository, "worktree", "add", "-q",
                 "-b", "runtime-test", worktree],
                check=True, capture_output=True, text=True)
            self.assertTrue(os.path.isfile(os.path.join(worktree, ".git")))
            prepared = prepare_project(worktree)
            self.assertEqual(os.path.abspath(worktree), prepared["project"])

    def test_missing_host_dependency_fails_before_project_files_are_written(self):
        with tempfile.TemporaryDirectory() as root:
            subprocess.run(
                ["git", "init", "-q", root],
                check=True, capture_output=True, text=True)
            with mock.patch.object(
                    capabilities, "_git",
                    side_effect=capabilities.CapabilityError("找不到 Git")):
                with self.assertRaisesRegex(
                        capabilities.CapabilityError, "基础依赖不可用.*Git"):
                    prepare_project(root)
            self.assertFalse(os.path.exists(os.path.join(root, "openspec")))
            self.assertFalse(os.path.exists(os.path.join(root, ".comet")))

    def test_codecheck_install_is_one_shot_and_does_not_mutate_npm_config(self):
        with tempfile.TemporaryDirectory() as root:
            state_path = os.path.join(root, "capabilities.json")
            completed = mock.Mock(stdout="installed", stderr="", returncode=0)
            with mock.patch.object(
                    capabilities, "_capability_state_path",
                    return_value=state_path), mock.patch.object(
                        capabilities, "locate_codecheck",
                        side_effect=[
                            ("", ""),
                            ("C:\\npm\\codecheck.cmd", "fullcheck"),
                        ]), mock.patch.object(
                            capabilities.shutil, "which",
                            side_effect=lambda name: (
                                "C:\\npm\\npm.cmd"
                                if name in ("npm", "npm.cmd") else None)), \
                    mock.patch.object(
                        capabilities.subprocess, "run",
                        return_value=completed) as runner:
                result = capabilities.ensure_codecheck(install=True)
            self.assertTrue(result["available"])
            command = runner.call_args.args[0]
            self.assertEqual(
                ["C:\\npm\\npm.cmd", "install", "-g",
                 "@baize/codecheckcli"],
                command[:4])
            self.assertTrue(
                any(item.startswith("--registry=") for item in command))
            self.assertNotIn("config", command)

            write(
                state_path,
                json.dumps({
                    "available": False,
                    "attempted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "detail": "registry unavailable",
                }, ensure_ascii=False))
            with mock.patch.object(
                    capabilities, "_capability_state_path",
                    return_value=state_path), mock.patch.object(
                        capabilities, "locate_codecheck",
                        return_value=("", "")), mock.patch.object(
                            capabilities.subprocess, "run") as runner:
                cooled = capabilities.ensure_codecheck(install=True)
            self.assertTrue(cooled["cooldown"])
            runner.assert_not_called()

    def test_windows_cmd_launch_uses_pathex_compatible_shell(self):
        completed = mock.Mock(stdout="ok", stderr="", returncode=0)
        with mock.patch.object(
                capabilities.subprocess, "run",
                return_value=completed) as runner:
            result = capabilities._run_host_cli(
                [r"C:\Users\dev\AppData\Roaming\npm\npm.cmd",
                 "prefix", "-g"],
                windows=True)
        self.assertIs(result, completed)
        command = runner.call_args.args[0]
        self.assertIsInstance(command, str)
        self.assertIn("npm.cmd", command)
        self.assertTrue(runner.call_args.kwargs["shell"])

    def test_windows_runtime_discovers_git_bash_and_node_off_path(self):
        env = {
            "ProgramFiles": r"C:\Program Files",
            "NVM_SYMLINK": r"C:\tools\node",
        }
        expected_bash = os.path.join(
            env["ProgramFiles"], "Git", "bin", "bash.exe")
        expected_git = os.path.join(
            env["ProgramFiles"], "Git", "cmd", "git.exe")
        expected_node = os.path.join(env["NVM_SYMLINK"], "node.exe")
        existing = {
            os.path.normpath(expected_bash),
            os.path.normpath(expected_git),
            os.path.normpath(expected_node),
        }
        with mock.patch.object(
                capabilities.shutil, "which", return_value=None), \
                mock.patch.dict(capabilities.os.environ, env, clear=True), \
                mock.patch.object(
                    capabilities.os.path, "isfile",
                    side_effect=lambda value: os.path.normpath(value) in existing):
            self.assertEqual(
                os.path.normpath(expected_bash),
                os.path.normpath(capabilities._bash(windows=True)))
            self.assertEqual(
                os.path.normpath(expected_node),
                os.path.normpath(capabilities._node(windows=True)))
            self.assertEqual(
                os.path.normpath(expected_git),
                os.path.normpath(capabilities._git(windows=True)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
