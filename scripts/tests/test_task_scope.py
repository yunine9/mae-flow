import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from mae_flow_core.foundation import source_paths

SPEC = importlib.util.spec_from_file_location(
    "mae_flow_task_scope_test", os.path.join(ROOT, "scripts", "mae-flow.py"))
mf = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mf)
FLOW = json.load(open(os.path.join(ROOT, "flow", "flow.json"), encoding="utf-8"))
mf.FLOW = FLOW


def git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, text=True,
        capture_output=True).stdout.strip()


def write(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(text)


class TaskScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mae-flow-task-scope-")
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "task-scope@test.invalid")
        git(self.repo, "config", "user.name", "Task Scope Test")
        write(os.path.join(self.repo, "services/anr/CMakeLists.txt"),
              "add_library(anr src/Logic.cpp)\n")
        write(os.path.join(self.repo, "services/anr/src/Logic.cpp"),
              "int changedFunction() {\n  return 1;\n}\n\n"
              "int untouchedFunction() {\n  return 9;\n}\n")
        write(os.path.join(self.repo, "services/anr/tests/LogicTest.cpp"),
              "int existing_test = 1;\n")
        write(os.path.join(self.repo, "README.md"), "# base\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "base")
        self.base = git(self.repo, "rev-parse", "HEAD")
        self.old_cwd = os.getcwd()
        os.chdir(self.repo)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def state(self, current, base=None):
        return {
            "current": current,
            "config": {
                "单号": "REQ-SCOPE", "单号类型": "fix",
                "基线分支": base or self.base,
                "编译方式": "mcde build", "UT生成方式": "AutoUT",
                "UT运行命令": "mcde test",
            },
            "choices": {"workflow": "full"},
            "history": [], "started": "2026-07-29 00:00:00",
            "initial_dirty": [], "initial_dirty_fingerprints": {},
        }

    def task(self, state, kind, scope=None):
        mf.save_state(state)
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_agent_task(
                FLOW, state, types.SimpleNamespace(
                    kind=kind, scope=scope, checkpoint=None))
        saved = mf.load_state()
        task = saved["agent_tasks"][kind.upper()]
        with open(task["path"], encoding="utf-8") as stream:
            return stream.read(), task

    def commit(self, message):
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", message)

    def test_shared_source_classifier_contract(self):
        patterns = [r"(^|/)src/", r"(^|/)include/", r"^module/"]
        cases = [
            ("src/main.cpp", True),
            ("include/api.hpp", True),
            ("CMakeLists.txt", True),
            ("package-lock.json", True),
            ("src/README.md", False),
            ("docs/design.md", False),
            ("module/custom.file", True),
        ]
        for path, expected in cases:
            with self.subTest(path=path):
                self.assertEqual(
                    expected,
                    source_paths.is_source_path(path, patterns),
                )

        source = os.path.join(self.repo, "services", "anr", "src",
                              "Logic.cpp")
        self.assertEqual(
            "services/anr/src/Logic.cpp",
            source_paths.repo_relative_for_match(source, self.repo),
        )
        outside = os.path.abspath(
            os.path.join(self.repo, "..", "outside.py"))
        self.assertIsNone(
            source_paths.repo_relative_for_match(outside, self.repo))
        self.assertFalse(source_paths.is_source_path(
            outside,
            [r"(^|/)src/"],
            project_root=self.repo,
            require_membership=True,
        ))

        self.assertEqual(
            "src/Main.cpp",
            source_paths.repo_relative_for_match(
                r"C:\Repo\src\Main.cpp", r"c:\repo"),
        )
        self.assertTrue(source_paths.is_source_path(
            r"C:\Repo\src\Main.cpp",
            patterns,
            project_root=r"c:\repo",
            require_membership=True,
        ))
        self.assertFalse(source_paths.is_source_path(
            r"D:\outside\Main.cpp",
            patterns,
            project_root=r"c:\repo",
            require_membership=True,
        ))

        for path, expected in cases:
            with self.subTest(adapter=path):
                self.assertEqual(
                    expected,
                    mf._is_source_path(
                        path,
                        {"config": {"源码路径": r"^module/"}},
                        {"source_patterns": patterns[:-1]},
                    ),
                )

    def test_ut_card_filters_docs_and_freezes_function_and_module_scope(self):
        write("services/anr/src/Logic.cpp",
              "int changedFunction() {\n  return 2;\n}\n\n"
              "int untouchedFunction() {\n  return 9;\n}\n")
        write("README.md", "# changed process notes\n")
        self.commit("code and docs")

        card, task = self.task(self.state("verify_ut"), "ut")

        self.assertIn("services/anr/src/Logic.cpp", card)
        self.assertNotIn("- README.md", card)
        self.assertIn("UT覆盖目标（硬边界，不等于整个文件）", card)
        self.assertIn("changedFunction", card)
        self.assertIn("编译/UT执行目录:\n- services/anr（检测到 CMakeLists.txt）", card)
        self.assertEqual(task["task_files"], ["services/anr/src/Logic.cpp"])
        self.assertEqual(task["execution_roots"], ["services/anr"])
        targets = task["ut_targets"]["services/anr/src/Logic.cpp"]
        self.assertTrue(targets)
        self.assertTrue(any("changedFunction" in item["context"] for item in targets))

    def test_document_only_is_machine_skipped_at_all_quality_entries(self):
        write("README.md", "# docs only\n")
        self.commit("docs only")
        for current, kind in (
                ("build", "compile"), ("verify_post_ponytail_compile", "compile"),
                ("verify_recompile", "compile"), ("verify_ut", "ut"),
                ("tw_compile", "compile"), ("tw_ut", "ut"),
                ("rf_compile", "compile"), ("rf_ut", "ut")):
            state = self.state(current)
            self.assertTrue(mf.ev_agent_or_no_source({}, state)[0], current)
            with self.assertRaises(SystemExit) as caught:
                with contextlib.redirect_stderr(io.StringIO()):
                    mf.cmd_agent_task(
                        FLOW, state, types.SimpleNamespace(
                            kind=kind, scope=None, checkpoint=None))
            self.assertEqual(caught.exception.code, 2, current)
        self.assertTrue(mf.ev_review_codecheck(
            {}, self.state("verify_codecheck"))[0])
        for step in ("build", "verify_post_ponytail_compile",
                     "verify_recompile", "verify_ut"):
            evidence = FLOW["steps"][step]["evidence"]
            matching = [item for item in evidence
                        if item.get("agent") in ("COMPILE", "UT")]
            self.assertEqual(matching[0]["type"], "agent_or_no_source", step)

    def test_test_only_ut_does_not_authorize_stock_business_coverage(self):
        write("services/anr/tests/LogicTest.cpp", "int existing_test = 2;\n")
        self.commit("test only")
        card, task = self.task(self.state("verify_ut"), "ut")
        self.assertIn("本轮无业务源码修改", card)
        self.assertIn("禁止为任意存量业务函数新增覆盖", card)
        self.assertNotIn("services/anr/src/Logic.cpp", task["task_files"])
        self.assertEqual(task["ut_targets"], {})

    def test_deleted_source_stays_in_scope_without_expanding_other_functions(self):
        os.remove("services/anr/src/Logic.cpp")
        git(self.repo, "add", "-u")
        git(self.repo, "commit", "-qm", "delete source")
        card, task = self.task(self.state("verify_ut"), "ut")
        self.assertIn("services/anr/src/Logic.cpp", task["task_files"])
        self.assertIn("只验证本次移除或迁移行为", card)
        self.assertNotIn("untouchedFunction", card)

    def test_multiple_modules_are_listed_separately_and_never_folded_to_root(self):
        write("services/billing/CMakeLists.txt", "add_library(billing src/Bill.cpp)\n")
        write("services/billing/src/Bill.cpp", "int bill() { return 1; }\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "add billing base")
        base = git(self.repo, "rev-parse", "HEAD")
        write("services/anr/src/Logic.cpp",
              "int changedFunction() { return 3; }\n"
              "int untouchedFunction() { return 9; }\n")
        write("services/billing/src/Bill.cpp", "int bill() { return 2; }\n")
        self.commit("two modules")
        card, task = self.task(self.state("verify_ut", base), "ut")
        self.assertEqual(
            task["execution_roots"], ["services/anr", "services/billing"])
        self.assertIn("涉及多个模块", card)
        self.assertIn("禁止退回项目根", card)

    def test_checkpoint_compile_card_only_contains_current_batch(self):
        write("services/anr/src/Logic.cpp",
              "int changedFunction() { return 2; }\n"
              "int untouchedFunction() { return 9; }\n")
        self.commit("checkpoint one")
        checkpoint_one = git(self.repo, "rev-parse", "HEAD")
        write("services/anr/tests/LogicTest.cpp", "int existing_test = 2;\n")
        self.commit("checkpoint two")
        state = self.state("build")
        state["development_review"] = {
            "version": 1, "mode": "staged", "current_index": 1,
            "checkpoints": [
                {"id": "CP1", "status": "accepted", "fixed_base": self.base},
                {"id": "CP2", "status": "coding", "fixed_base": checkpoint_one},
            ],
        }
        mf.save_state(state)
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_agent_task(
                FLOW, state, types.SimpleNamespace(
                    kind="compile", scope="第二批测试", checkpoint="CP2"))
        task = mf.load_state()["agent_tasks"]["COMPILE"]
        self.assertEqual(task["task_files"], ["services/anr/tests/LogicTest.cpp"])
        with open(task["path"], encoding="utf-8") as stream:
            card = stream.read()
        self.assertIn(checkpoint_one + "..HEAD", card)
        self.assertNotIn("- services/anr/src/Logic.cpp", card)

    def test_precommit_checkpoint_card_uses_tracked_and_untracked_worktree(self):
        write("services/anr/src/Logic.cpp",
              "int changedFunction() { return 3; }\n")
        write("services/anr/src/NewLogic.cpp",
              "int newFunction() { return 4; }\n")
        state = self.state("build")
        state["development_review"] = {
            "version": 1, "status": "active", "mode": "staged",
            "review_before_commit": True, "current_index": 0,
            "delivery_base": self.base, "last_reviewed_head": self.base,
            "task_structure_sha256": "",
            "checkpoints": [{
                "id": "CP1", "title": "worktree batch",
                "status": "coding", "fixed_base": self.base,
            }],
        }
        mf.save_state(state)
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_agent_task(
                FLOW, state, types.SimpleNamespace(
                    kind="compile", scope="未提交批次", checkpoint="CP1"))
        task = mf.load_state()["agent_tasks"]["COMPILE"]
        self.assertTrue(task["precommit_review"])
        self.assertEqual(
            set(task["task_files"]),
            {"services/anr/src/Logic.cpp", "services/anr/src/NewLogic.cpp"})
        self.assertIn(
            "services/anr/src/NewLogic.cpp", task["source_snapshot"])
        with open(task["path"], encoding="utf-8") as stream:
            card = stream.read()
        self.assertIn("先检视、后提交", card)
        self.assertIn("禁止 git commit、git push", card)

    def test_precommit_lightcheck_only_reads_exact_commit_candidates(self):
        other = "services/anr/src/Other.cpp"
        write(other, "int other() { return 1; }\n")
        self.commit("add second source")
        write(
            "services/anr/src/Logic.cpp",
            "int changedFunction(int a, int b, int c, int d, int e, int f) {\n"
            "  return a;\n"
            "}\n")
        write(
            other,
            "int unrelated(int a, int b, int c, int d, int e, int f) {\n"
            "  return a;\n"
            "}\n")
        result = mf._working_lightcheck_scope(
            self.state("build"), ["services/anr/src/Logic.cpp"])
        self.assertEqual(
            {item["file"] for item in result["findings"]},
            {"services/anr/src/Logic.cpp"},
            result,
        )

    def test_precommit_lightcheck_reads_index_instead_of_unstaged_overlay(self):
        path = "services/anr/src/Logic.cpp"
        write(
            path,
            "int staged(int a, int b, int c, int d, int e, int f) {\n"
            "  return a;\n"
            "}\n")
        git(self.repo, "add", path)
        write(path, "int changedFunction() {\n  return 1;\n}\n")
        snapshot = mf._pending_commit_candidates(
            'git commit -m "[REQ-SCOPE][fix]test"')
        result = mf._pending_lightcheck_scope(
            self.state("build"), snapshot)
        self.assertEqual(snapshot["working_paths"], set())
        self.assertEqual(
            [(item["file"], item["rule"]) for item in result["findings"]],
            [(path, "MF-PARAM-5")],
            result,
        )

    def test_commit_candidate_modes_use_the_content_git_will_commit(self):
        path = "services/anr/src/Logic.cpp"
        write(
            path,
            "int changed(int a, int b, int c, int d, int e, int f) {\n"
            "  return a;\n"
            "}\n")
        commands = (
            'git commit -am "[REQ-SCOPE][fix]test"',
            'git commit --all -m "[REQ-SCOPE][fix]test"',
            'git commit services/anr/src/Logic.cpp -m "[REQ-SCOPE][fix]test"',
            'git add -u && git commit -m "[REQ-SCOPE][fix]test"',
        )
        for command in commands:
            with self.subTest(command=command):
                snapshot = mf._pending_commit_candidates(command)
                self.assertEqual(snapshot["paths"], [path])
                self.assertEqual(snapshot["working_paths"], {path})

    def test_committed_diff_lightcheck_ignores_dirty_worktree_overlay(self):
        path = "services/anr/src/Logic.cpp"
        write(
            path,
            "int committed(int a, int b, int c, int d, int e, int f) {\n"
            "  return a;\n"
            "}\n")
        self.commit("commit violation")
        write(path, "int changedFunction() {\n  return 1;\n}\n")
        result = mf._run_lightcheck_diff(
            self.base + "..HEAD", [path], "test")
        self.assertEqual(
            [(item["file"], item["rule"]) for item in result["findings"]],
            [(path, "MF-PARAM-5")],
            result,
        )

    def test_lightcheck_prompt_covers_every_main_source_edit_route(self):
        expected = {
            "build", "rf_fix", "tw_change", "verify_ponytail",
            "verify_ut", "rf_ut", "tw_ut",
        }
        for step in expected:
            with self.subTest(step=step):
                self.assertIn(
                    "轻量编码预防",
                    mf._with_lightcheck_prompt(step, "BASE"))
        self.assertEqual(
            mf._with_lightcheck_prompt("verify_codecheck", "BASE"),
            "BASE")

    def test_codecheck_keeps_same_changed_function_but_not_stock_function(self):
        path = "services/anr/src/LongLogic.cpp"
        write(path, "\n".join([
            "int changedFunction() {",
            "  int a = 1;",
            "  int b = 2;",
            "  int c = 3;",
            "  int d = 4;",
            "  int e = 5;",
            "  int f = 6;",
            "  return a + b + c + d + e + f;",
            "}",
            "",
            "int untouchedFunction() {",
            "  return 9;",
            "}",
            "",
        ]))
        self.commit("long function base")
        base = git(self.repo, "rev-parse", "HEAD")
        write(path, "\n".join([
            "int changedFunction() {",
            "  int a = 1;",
            "  int b = 2;",
            "  int c = 3;",
            "  int d = 4;",
            "  int e = 5;",
            "  int f = 6;",
            "  return a + b + c + d + e + f + 1;",
            "}",
            "",
            "int untouchedFunction() {",
            "  return 9;",
            "}",
            "",
        ]))
        self.commit("change deep function line")
        state = self.state("verify_codecheck", base)
        classified, candidates = mf._scope_classify_codecheck({
            "total": 2,
            "pairs": [
                ("R.SIGNATURE", path, 1),
                ("R.STOCK", path, 12),
            ],
            "commands": ["codecheck fullcheck -f " + path],
        }, state, [path])
        self.assertEqual(classified["pairs"], [("R.SIGNATURE", path, 1)])
        self.assertEqual(candidates, [("R.STOCK", path, 12)])
        self.assertIn("本次变更函数", classified["scope_reasons"][0]["reason"])

        state["quality"] = {"codecheck_scan": {
            "step": "verify_codecheck",
            "head": git(self.repo, "rev-parse", "HEAD"),
            "count": 1, "files": [path],
            "pairs": classified["pairs"],
            "commands": classified["commands"],
            "scope_reasons": classified["scope_reasons"],
        }}
        card, _task = self.task(state, "codecheck")
        self.assertIn("CodeCheck修复目标（硬边界，仅以下告警）", card)
        self.assertIn("R.SIGNATURE", card)
        self.assertNotIn("R.STOCK", card)
        self.assertIn("同一文件还有其他告警也不得顺手处理", card)

    def test_codecheck_function_scope_matrix_cpp_java_js_python(self):
        fixtures = {
            "matrix/Logic.cpp": (
                "int changedFunction() {\n%s}\n\n"
                "int untouchedFunction() {\n  return 9;\n}\n",
                "  return 7;\n", "  return 8;\n", 1, 12),
            "matrix/Logic.java": (
                "class Logic {\n  int changedFunction() {\n%s  }\n\n"
                "  int untouchedFunction() {\n    return 9;\n  }\n}\n",
                "    return 7;\n", "    return 8;\n", 2, 13),
            "matrix/logic.js": (
                "function changedFunction() {\n%s}\n\n"
                "function untouchedFunction() {\n  return 9;\n}\n",
                "  return 7;\n", "  return 8;\n", 1, 12),
            "matrix/logic.py": (
                "def changed_function():\n%s\n\n\n"
                "def untouched_function():\n    return 9\n",
                "    return 7\n", "    return 8\n", 1, 13),
        }

        def long_body(return_line):
            return "".join(
                "  int v%d = %d;\n" % (index, index)
                for index in range(1, 7)) + return_line

        def python_body(return_line):
            return "".join(
                "    v%d = %d\n" % (index, index)
                for index in range(1, 7)) + return_line

        for path, (template, old_return, _new_return, _sig, _stock) in fixtures.items():
            body = python_body(old_return) if path.endswith(".py") else long_body(old_return)
            write(path, template % body)
        self.commit("language matrix base")
        base = git(self.repo, "rev-parse", "HEAD")
        for path, (template, _old_return, new_return, _sig, _stock) in fixtures.items():
            body = python_body(new_return) if path.endswith(".py") else long_body(new_return)
            write(path, template % body)
        self.commit("language matrix changes")
        state = self.state("verify_codecheck", base)
        scanned_files, scan_error = mf._biz_changed_files(state)
        self.assertFalse(scan_error)
        self.assertTrue(set(fixtures).issubset(set(scanned_files)))

        for path, (_template, _old, _new, signature_line, stock_line) in fixtures.items():
            classified, candidates = mf._scope_classify_codecheck({
                "total": 2,
                "pairs": [
                    ("R.SIGNATURE", path, signature_line),
                    ("R.STOCK", path, stock_line),
                ],
                "commands": ["codecheck fullcheck -f " + path],
            }, state, [path])
            self.assertEqual(
                classified["pairs"], [("R.SIGNATURE", path, signature_line)],
                path)
            self.assertEqual(candidates, [("R.STOCK", path, stock_line)], path)
            self.assertIn("本次变更函数", classified["scope_reasons"][0]["reason"])
            self.assertTrue(path.lower().endswith(mf.CODE_EXTS))

    def test_unresolved_root_does_not_silently_become_project_root(self):
        os.makedirs("build")
        write("root.cpp", "int root_value = 1;\n")
        root, reason = mf._execution_root_for_file("root.cpp")
        self.assertEqual(root, "")
        self.assertIn("未找到", reason)
        write("module/src/Nested.cpp", "int nested = 1;\n")
        root, reason = mf._execution_root_for_file("module/src/Nested.cpp")
        self.assertEqual(root, "module/src")
        self.assertIn("源码所在目录", reason)

    def test_standalone_scope_rejects_build_only_and_codecheck_non_code(self):
        config = {}
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                mf._action_target_files(
                    ["services/anr/CMakeLists.txt"], "ut", config, FLOW)
        self.assertEqual(
            mf._action_target_files(
                ["services/anr/CMakeLists.txt"], "codecheck", config, FLOW),
            [])
        self.assertTrue(mf._is_source_path("pyproject.toml", {}, FLOW))
        self.assertTrue(mf._is_source_path("requirements-dev.txt", {}, FLOW))
        self.assertTrue(mf._is_build_path("WORKSPACE.bazel"))


if __name__ == "__main__":
    unittest.main()
