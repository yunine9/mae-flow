import os
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from mae_flow_core.lightcheck import (
    MAX_FILE_BYTES,
    MAX_REPORTED_ITEMS,
    analyze_changed,
    analyze_changed_with_timeout,
    render_markdown,
)


def _write(root, path, text):
    absolute = os.path.join(root, path)
    os.makedirs(os.path.dirname(absolute) or root, exist_ok=True)
    with open(absolute, "w", encoding="utf-8") as stream:
        stream.write(text)


def _long_body(indent, declaration, condition):
    lines = [declaration]
    lines.extend(indent + condition.format(index=index) for index in range(6))
    lines.extend(indent + "value_%d = %d;" % (index, index) for index in range(45))
    lines.append(indent + "return " + " + ".join(["value_0"] * 18) + ";")
    lines.append("}")
    return "\n".join(lines) + "\n"


class LightCheckTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="mae-flow-lightcheck-")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def analyze(self, path, source, changed=None, baseline=None):
        _write(self.root, path, source)
        lines = changed or set(range(1, len(source.splitlines()) + 1))
        baselines = {path: baseline} if baseline is not None else {}
        return analyze_changed(
            self.root, [path], {path: lines}, baseline_sources=baselines)

    def assert_all_rules(self, path, source):
        result = self.analyze(path, source)
        self.assertEqual(result["status"], "FINDINGS", result)
        self.assertEqual(
            {item["rule"] for item in result["findings"]},
            {"MF-PARAM-5", "MF-FUNC-50", "MF-CC-5", "MF-LINE-120"},
            result,
        )

    def test_cpp_java_javascript_python_cover_all_four_rules(self):
        cpp = _long_body(
            "  ",
            "int heavy(int a, int b, int c, int d, int e, int f) {",
            "if (value_{index}) value_{index}++;",
        )
        java_body = _long_body(
            "    ",
            "  int heavy(int a, int b, int c, int d, int e, int f) {",
            "if (value_{index} > 0) value_{index}++;",
        )
        java = "class Demo {\n" + java_body.replace(
            "\n}", "\n  }\n}", 1)
        javascript = _long_body(
            "  ",
            "function heavy(a, b, c, d, e, f) {",
            "if (value_{index}) value_{index}++;",
        )
        python_lines = [
            "def heavy(self, a, b, c, d, e, f):",
            *["    if value_%d:" % index for index in range(6)],
            *["        value_%d += 1" % index for index in range(6)],
            *["    value_%d = %d" % (index, index) for index in range(45)],
            "    return " + " + ".join(["value_0"] * 24),
            "",
        ]
        for path, source in (
                ("src/heavy.cpp", cpp),
                ("src/Demo.java", java),
                ("src/heavy.js", javascript),
                ("src/heavy.py", "\n".join(python_lines))):
            with self.subTest(path=path):
                self.assert_all_rules(path, source)

    def test_python_self_and_javascript_destructuring_are_formal_parameter_safe(self):
        python = "def safe(self, a, b, c, d, e):\n    return a\n"
        javascript = "function safe({a, b}, c, d, e, f) {\n  return a;\n}\n"
        for path, source in (
                ("safe.py", python), ("safe.js", javascript)):
            result = self.analyze(path, source)
            self.assertNotIn(
                "MF-PARAM-5",
                {item["rule"] for item in result["findings"]},
                result,
            )

    def test_exact_parameter_line_and_complexity_limits_are_allowed(self):
        lines = [
            "int boundary(int a, int b, int c, int d, int e) {",
            *["  if (v%d) v%d++;" % (index, index) for index in range(4)],
            *["  int value%d = %d;" % (index, index) for index in range(44)],
            "  return 0;",
            "}",
            "",
        ]
        result = self.analyze("boundary.cpp", "\n".join(lines))
        self.assertEqual(result["status"], "CLEAN", result)
        self.assertEqual(result["findings"], [], result)

    def test_comment_blank_and_delimiter_only_lines_do_not_count(self):
        lines = ["int safe() {"]
        for index in range(49):
            lines += ["  // explanation", "", "  {", "  }", "  value%d++;" % index]
        lines += ["}"]
        source = "\n".join(lines) + "\n"
        result = self.analyze("safe.cpp", source)
        self.assertNotIn(
            "MF-FUNC-50",
            {item["rule"] for item in result["findings"]},
            result,
        )

    def test_existing_violation_without_regression_is_only_logged(self):
        baseline_lines = [
            "int oldDebt(int a, int b, int c, int d, int e, int f) {",
            *["  if (v%d) v%d++;" % (index, index) for index in range(6)],
            *["  int value%d = %d;" % (index, index) for index in range(45)],
            "  return 0;",
            "}",
            "",
        ]
        baseline = "\n".join(baseline_lines)
        current_lines = list(baseline_lines)
        current_lines.insert(2, "  // changed explanation only")
        current = "\n".join(current_lines)
        result = self.analyze(
            "legacy.cpp", current, changed={3}, baseline=baseline)
        self.assertEqual(result["findings"], [], result)
        self.assertEqual(
            {item["rule"] for item in result["existing_debt"]},
            {"MF-PARAM-5", "MF-FUNC-50", "MF-CC-5"},
            result,
        )

    def test_new_complexity_threshold_crossing_is_reported(self):
        baseline = "\n".join([
            "int changed(int a) {",
            "  if (a > 0) a++;",
            "  if (a > 1) a++;",
            "  if (a > 2) a++;",
            "  if (a > 3) a++;",
            "  return a;",
            "}",
            "",
        ])
        current = baseline.replace(
            "  return a;", "  if (a > 4) a++;\n  return a;")
        result = self.analyze(
            "changed.cpp", current, changed={7}, baseline=baseline)
        self.assertEqual(
            [item["rule"] for item in result["findings"]],
            ["MF-CC-5"],
            result,
        )
        self.assertEqual(result["findings"][0]["baseline"], 5)

    def test_only_changed_long_lines_are_reported(self):
        old_long = "  int old_line = " + "1 + " * 40 + "0;"
        new_long = "  int new_line = " + "2 + " * 40 + "0;"
        source = "\n".join([
            "int lines() {", old_long, new_long, "  return 0;", "}", "",
        ])
        result = self.analyze("lines.cpp", source, changed={3})
        line_findings = [
            item for item in result["findings"]
            if item["rule"] == "MF-LINE-120"
        ]
        self.assertEqual(len(line_findings), 1, result)
        self.assertEqual(line_findings[0]["line"], 3)

    def test_untouched_bad_function_is_outside_scope(self):
        source = "\n".join([
            "int safe() {", "  return 1;", "}", "",
            "int untouched(int a, int b, int c, int d, int e, int f) {",
            *["  if (v%d) v%d++;" % (index, index) for index in range(6)],
            *["  int value%d = %d;" % (index, index) for index in range(45)],
            "  return 0;", "}", "",
        ])
        result = self.analyze("scope.cpp", source, changed={2})
        self.assertEqual(result["findings"], [], result)
        self.assertEqual(result["functions_checked"], 1, result)

    def test_comment_markers_inside_strings_do_not_corrupt_line_classification(self):
        source = "\n".join([
            "const char* text() {",
            '  auto a = \"// not a comment\";',
            '  auto b = R\"tag(/* not a comment */)tag\";',
            "  return a;",
            "}",
            "",
        ])
        result = self.analyze("strings.cpp", source)
        self.assertEqual(result["status"], "CLEAN", result)
        self.assertFalse(result["skipped"], result)

    def test_python_stub_uses_python_parameter_semantics(self):
        source = (
            "class Demo:\n"
            "    def create(cls, a: int, b: int, c: int, d: int, e: int) -> None: ...\n"
        )
        result = self.analyze("demo.pyi", source)
        self.assertNotIn(
            "MF-PARAM-5",
            {item["rule"] for item in result["findings"]},
            result,
        )

    def test_multiline_literal_content_does_not_inflate_function_lines(self):
        content = "\n".join(
            "literal content %d" % index for index in range(55))
        fixtures = {
            "template.py": (
                'def render():\n    value = """\n' + content
                + '\n    """\n    return value\n'),
            "template.js": (
                "function render() {\n  const value = `\n" + content
                + "\n`;\n  return value;\n}\n"),
            "Template.java": (
                'class Template {\n String render() {\n  String value = """\n'
                + content + '\n  """;\n  return value;\n }\n}\n'),
        }
        for path, source in fixtures.items():
            with self.subTest(path=path):
                result = self.analyze(path, source)
                self.assertNotIn(
                    "MF-FUNC-50",
                    {item["rule"] for item in result["findings"]},
                    result,
                )

    def test_javascript_comparison_and_typescript_generics_count_parameters(self):
        comparison = (
            "function compare(a = x < y, b, c, d, e, f) {\n"
            "  return a;\n"
            "}\n")
        result = self.analyze("compare.js", comparison)
        self.assertIn(
            "MF-PARAM-5",
            {item["rule"] for item in result["findings"]},
            result,
        )
        generic = (
            "function safe(value: Map<string, number>, a, b, c, d) {\n"
            "  return value;\n"
            "}\n")
        result = self.analyze("safe.ts", generic)
        self.assertNotIn(
            "MF-PARAM-5",
            {item["rule"] for item in result["findings"]},
            result,
        )

    def test_new_overload_cannot_borrow_existing_overload_debt(self):
        baseline = (
            "int overloaded(int a, int b, int c, int d, int e, int f) {\n"
            "  return a;\n"
            "}\n")
        current = baseline + (
            "int overloaded(int a, int b, int c, int d, int e, int f, int g) {\n"
            "  return a;\n"
            "}\n")
        result = self.analyze(
            "overload.cpp", current, changed={4, 5, 6}, baseline=baseline)
        self.assertEqual(
            [item["actual"] for item in result["findings"]
             if item["rule"] == "MF-PARAM-5"],
            [7],
            result,
        )

    def test_common_module_and_cpp_template_extensions_are_checked(self):
        fixtures = {
            "module.mjs": "function bad(a, b, c, d, e, f) { return a; }\n",
            "module.cjs": "function bad(a, b, c, d, e, f) { return a; }\n",
            "module.mts": (
                "function bad(a: number, b: number, c: number, d: number, "
                "e: number, f: number) { return a; }\n"),
            "module.cts": (
                "function bad(a: number, b: number, c: number, d: number, "
                "e: number, f: number) { return a; }\n"),
            "inline.inl": "int bad(int a,int b,int c,int d,int e,int f) {}\n",
            "inline.ipp": "int bad(int a,int b,int c,int d,int e,int f) {}\n",
            "inline.tpp": "int bad(int a,int b,int c,int d,int e,int f) {}\n",
        }
        for path, source in fixtures.items():
            with self.subTest(path=path):
                result = self.analyze(path, source)
                self.assertIn(
                    "MF-PARAM-5",
                    {item["rule"] for item in result["findings"]},
                    result,
                )

    def test_large_result_returns_capped_findings_instead_of_timing_out(self):
        path = "many.js"
        source = "\n".join(
            "const value_%d = '%s';" % (index, "x" * 130)
            for index in range(500)
        ) + "\n"
        _write(self.root, path, source)
        result = analyze_changed_with_timeout(
            self.root, [path], {path: set(range(1, 501))},
            options={"timeout_seconds": 3})
        self.assertEqual(result["status"], "FINDINGS", result)
        self.assertEqual(len(result["findings"]), MAX_REPORTED_ITEMS)
        self.assertTrue(any(
            "省略 300 项" in item for item in result["skipped"]), result)

    def test_generated_and_unparseable_input_fail_open(self):
        generated = self.analyze(
            "generated/model.cpp",
            "int generated(int a, int b, int c, int d, int e, int f) {}\n")
        self.assertFalse(generated["findings"], generated)
        self.assertTrue(generated["skipped"], generated)
        malformed = self.analyze("broken.py", "def broken(\n")
        self.assertFalse(malformed["findings"], malformed)
        self.assertIn(malformed["status"], ("CLEAN", "SKIPPED"))

    def test_oversized_input_and_isolated_runner_fail_open(self):
        oversized = "// " + ("x" * (MAX_FILE_BYTES + 10))
        result = self.analyze("huge.cpp", oversized)
        self.assertFalse(result["findings"], result)
        self.assertEqual(result["status"], "SKIPPED", result)

        path = "small.py"
        source = "def small(a):\n    return a\n"
        _write(self.root, path, source)
        isolated = analyze_changed_with_timeout(
            self.root, [path], {path: {1, 2}},
            options={"timeout_seconds": 3})
        self.assertEqual(isolated["status"], "CLEAN", isolated)

    def test_report_is_human_readable_and_states_advisory_contract(self):
        result = self.analyze(
            "line.js",
            "const value = '" + ("x" * 130) + "';\n",
        )
        report = render_markdown(result, "test scope")
        self.assertIn("# Mae-Flow 轻量编码预检", report)
        self.assertIn("不替代正式 CodeCheck", report)
        self.assertIn("MF-LINE-120", report)
        self.assertNotIn('{"status"', report)

    def test_cli_reports_findings_but_returns_success(self):
        repo = os.path.join(self.root, "repo")
        os.makedirs(repo)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(
            ["git", "config", "user.email", "lightcheck@test.invalid"],
            cwd=repo, check=True)
        subprocess.run(
            ["git", "config", "user.name", "Light Check"],
            cwd=repo, check=True)
        path = "logic.py"
        _write(repo, path, "def safe(a):\n    return a\n")
        subprocess.run(["git", "add", path], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
        _write(
            repo, path,
            "def changed(a, b, c, d, e, f):\n"
            "    return '" + ("x" * 130) + "'\n")
        environment = dict(os.environ)
        environment["PYTHONPYCACHEPREFIX"] = os.path.join(
            self.root, "pycache")
        run = subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts", "mae-flow.py"),
             "lightcheck", "--quiet"],
            cwd=repo, text=True, capture_output=True, env=environment,
            timeout=20,
        )
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("建议修复，不阻断", run.stderr)
        report = os.path.join(
            repo, ".mae-flow-work", "lightcheck", "latest.md")
        self.assertTrue(os.path.isfile(report))
        with open(report, encoding="utf-8") as stream:
            self.assertIn("MF-PARAM-5", stream.read())


if __name__ == "__main__":
    unittest.main()
