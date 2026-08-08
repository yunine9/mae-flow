#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""codespec 规格引擎 adapter:规格引擎插槽的第二个 adapter。

契约(用桩二进制钉死,不依赖真 codespec):
- 仓库预设「规格引擎: codespec」才启用;默认 builtin,零行为变化;
- new/validate/archive 走 CLI 真实执行,每次调用记进 engine_runs 与 history;
- archive 用树差推导 archive_name 与 merged,CLI 失败现场保持原样并给出路;
- 命令缺失抛 SpecEngineError(带「规格引擎命令」提示),不是裸 Traceback;
- codespec 仓的 openspec/ 工作区不被目录归一搬走。
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TESTS = os.path.abspath(os.path.dirname(__file__))
SCRIPTS = os.path.abspath(os.path.join(TESTS, ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core import specengine  # noqa: E402
from mae_flow_core.cli_commands import codespec_engine  # noqa: E402
from mae_flow_core.cli_commands.lean_migration import (  # noqa: E402
    migrate_legacy_spec_workspace,
)

STUB = r'''
import os, shutil, sys
args = sys.argv[1:]

def write(path, body):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(body)

if args[:1] == ["init"]:
    write("openspec/config.yaml", "schema: spec-driven\n")
    os.makedirs("openspec/changes/archive", exist_ok=True)
    os.makedirs("openspec/specs", exist_ok=True)
elif args[:2] == ["new", "change"]:
    name = args[2]
    base = "openspec/changes/" + name
    if os.path.isdir(base):
        sys.stderr.write("change exists\n")
        sys.exit(1)
    write(base + "/.openspec.yaml", "schema: spec-driven\ncreated: 2026-08-08\n")
    write(base + "/proposal.md", "# Proposal\n")
    write(base + "/tasks.md", "- [ ] 1. do\n")
elif args[:1] == ["validate"]:
    sys.exit(1 if "bad" in args[1] else 0)
elif args[:1] == ["archive"]:
    name = args[1]
    target = "openspec/changes/archive/2026-08-08-" + name
    shutil.move("openspec/changes/" + name, target)
    write("openspec/specs/dom/spec.md", "# dom\nupdated by archive\n")
sys.exit(0)
'''


class CodespecEngineTests(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="codespec-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        stub = os.path.join(self.root, "codespec-stub.py")
        with open(stub, "w", encoding="utf-8") as stream:
            stream.write(STUB)
        with open(os.path.join(self.root, ".mae-flow-defaults.json"),
                  "w", encoding="utf-8") as stream:
            json.dump({"规格引擎": "codespec",
                       "规格引擎命令": [sys.executable, stub]}, stream,
                      ensure_ascii=False)
        self.before = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self.before)
        self.state = {"current": "open", "config": {"单号": "REQ-1"}}

    def test_disabled_without_preset(self):
        os.remove(".mae-flow-defaults.json")
        self.assertFalse(codespec_engine.spec_engine_enabled())

    def test_new_initializes_workspace_and_records_runs(self):
        self.assertTrue(codespec_engine.spec_engine_enabled())
        info = codespec_engine.codespec_new(self.state, "req-x", "full")
        self.assertEqual("codespec", info["engine"])
        self.assertEqual("legacy", info["layout"])
        self.assertTrue(os.path.isdir("openspec/changes/req-x"))
        runs = self.state["spec"]["engine_runs"]
        self.assertEqual(["init", "new"], [run["action"] for run in runs])
        self.assertTrue(all(run["exit"] == 0 for run in runs))
        self.assertEqual("codespec", self.state["spec"]["engine"])
        # 重复创建:CLI 报错 → SpecEngineError,与内置引擎同语义
        with self.assertRaises(specengine.SpecEngineError):
            codespec_engine.codespec_new(self.state, "req-x", "full")

    def test_validate_pass_and_fail(self):
        codespec_engine.codespec_new(self.state, "req-ok", "full")
        ok, _messages = codespec_engine.codespec_validate(self.state, "req-ok")
        self.assertTrue(ok)
        codespec_engine.codespec_new(self.state, "req-bad", "full")
        ok, _messages = codespec_engine.codespec_validate(self.state, "req-bad")
        self.assertFalse(ok)
        validates = [run for run in self.state["spec"]["engine_runs"]
                     if run["action"] == "validate"]
        self.assertEqual([0, 1], [run["exit"] for run in validates])

    def test_archive_derives_name_and_merged_from_tree_diff(self):
        codespec_engine.codespec_new(self.state, "req-x", "full")
        info = codespec_engine.codespec_archive(self.state, "req-x")
        self.assertEqual("2026-08-08-req-x", info["archive_name"])
        self.assertEqual(["openspec/specs/dom/spec.md"], info["merged"])
        self.assertFalse(os.path.isdir("openspec/changes/req-x"))
        self.assertTrue(os.path.isdir(
            "openspec/changes/archive/2026-08-08-req-x"))

    def test_missing_binary_is_specengine_error_with_hint(self):
        with open(".mae-flow-defaults.json", "w", encoding="utf-8") as stream:
            json.dump({"规格引擎": "codespec",
                       "规格引擎命令": "/no/such/codespec"}, stream,
                      ensure_ascii=False)
        with self.assertRaises(specengine.SpecEngineError) as ctx:
            codespec_engine.codespec_new(self.state, "req-x", "full")
        self.assertIn("规格引擎命令", str(ctx.exception))

    def test_workspace_relocation_skipped_for_codespec_repos(self):
        subprocess.run(["git", "-C", self.root, "init", "-q"], check=True)
        codespec_engine.codespec_new(self.state, "req-x", "full")
        moved, _note = migrate_legacy_spec_workspace(self.root)
        self.assertFalse(moved)
        self.assertTrue(os.path.isdir("openspec/changes/req-x"))


if __name__ == "__main__":
    unittest.main()
