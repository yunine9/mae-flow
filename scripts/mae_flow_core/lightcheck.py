"""Advisory, changed-code-only quality checks used before formal CodeCheck.

This module intentionally has no gate semantics.  It reports only high
confidence findings, skips uncertain/generated input, and lets every caller
fail open.  Function discovery and cyclomatic complexity come from the pinned
Lizard runtime; Mae-Flow owns the changed-scope, effective-line and reporting
semantics.
"""

from __future__ import annotations

import ast
import multiprocessing
import os
import re
import sys
import time
import tokenize
from io import StringIO


PARAMETER_LIMIT = 5
FUNCTION_LINE_LIMIT = 50
COMPLEXITY_LIMIT = 5
LINE_LENGTH_LIMIT = 120
TAB_WIDTH = 4
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 12 * 1024 * 1024
MAX_FILES = 100
MAX_REPORTED_ITEMS = 200

SUPPORTED_EXTENSIONS = (
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx",
    ".inl", ".ipp", ".tpp", ".java",
    ".js", ".jsx", ".cjs", ".mjs",
    ".ts", ".tsx", ".cts", ".mts", ".py", ".pyi",
)

_GENERATED_PATH_PARTS = {
    "build", "dist", "out", "node_modules", "vendor", "third_party",
    "third-party", "generated", "gen",
}
_GENERATED_MARKERS = re.compile(
    r"(?i)(?:@generated|auto[- ]generated|generated code|do not edit|"
    r"automatically generated)")
_DELIMITER_ONLY = re.compile(r"^[{}\[\]();,]+$")


def _load_lizard():
    vendor = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", "runtime", "vendor", "lizard"))
    if vendor not in sys.path:
        sys.path.insert(0, vendor)
    import lizard  # pylint: disable=import-outside-toplevel
    return lizard


def _normalized(path):
    return str(path or "").replace("\\", "/").lstrip("./")


def _generated_path(path):
    value = _normalized(path)
    parts = {part.lower() for part in value.split("/")}
    name = os.path.basename(value).lower()
    return bool(
        parts & _GENERATED_PATH_PARTS
        or name.endswith((".min.js", ".min.css"))
        or ".generated." in name
    )


def _looks_generated(source):
    return bool(_GENERATED_MARKERS.search("\n".join(source.splitlines()[:12])))


def _python_code_lines(source):
    """Return lines containing Python code, excluding comments and docstrings."""
    code_lines = _python_token_lines(source)
    if code_lines is None:
        return None
    return code_lines - _python_doc_lines(source)


def _is_docstring_statement(node):
    value = getattr(node, "value", None)
    return isinstance(node, ast.Expr) and isinstance(
        value, ast.Constant) and isinstance(value.value, str)


def _parse_python_tree(source):
    try:
        return ast.parse(source)
    except (SyntaxError, ValueError):
        return None


def _first_docstring(body):
    if not isinstance(body, list):
        return None
    if not body:
        return None
    return body[0] if _is_docstring_statement(body[0]) else None


def _python_doc_lines(source):
    doc_lines = set()
    tree = _parse_python_tree(source)
    if tree is None:
        return set()
    for node in ast.walk(tree):
        first = _first_docstring(getattr(node, "body", None))
        if first is not None:
            doc_lines.update(range(
                first.lineno, getattr(first, "end_lineno", first.lineno) + 1))
    return doc_lines


def _python_token_lines(source):
    code_lines = set()
    ignored = {
        tokenize.ENCODING, tokenize.ENDMARKER, tokenize.INDENT,
        tokenize.DEDENT, tokenize.NEWLINE, tokenize.NL, tokenize.COMMENT,
    }
    try:
        tokens = list(tokenize.generate_tokens(StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    for token in tokens:
        code_lines.update(_python_token_code_lines(token, ignored))
    return code_lines


def _python_token_code_lines(token, ignored):
    if token.type in ignored or not token.string.strip():
        return set()
    if token.type == tokenize.STRING and token.end[0] > token.start[0]:
        return {token.start[0], token.end[0]}
    return set(range(token.start[0], token.end[0] + 1))


class _CLikeScanner:
    """Small state machine for code-vs-comment line classification."""

    def __init__(self):
        self.in_block_comment = False
        self.quote = ""
        self.raw_end = ""
        self.escaped = False

    def _consume_raw(self, raw_line, index, visible):
        marker = self.raw_end
        end = raw_line.find(marker, index)
        if end < 0:
            return len(raw_line)
        visible.append("x")
        self.raw_end = ""
        return end + len(marker)

    def _consume_block_comment(self, raw_line, index):
        end = raw_line.find("*/", index)
        if end < 0:
            return len(raw_line)
        self.in_block_comment = False
        return end + 2

    def _consume_quote(self, raw_line, index, visible):
        char = raw_line[index]
        if self.escaped:
            self.escaped = False
        elif char == "\\":
            self.escaped = True
        elif char == self.quote:
            self.quote = ""
            visible.append("x")
        return index + 1

    def _consume_plain(self, raw_line, index, visible):
        raw_match = re.match(
            r'(?:u8|u|U|L)?R"([^ ()\\\t]{0,16})\(', raw_line[index:])
        if raw_match:
            visible.append("x")
            self.raw_end = ")" + raw_match.group(1) + '"'
            return index + raw_match.end()
        token = raw_line[index:index + 2]
        if token == "//":
            return len(raw_line)
        if token == "/*":
            self.in_block_comment = True
            return index + 2
        char = raw_line[index]
        if char in ('"', "'", "`"):
            self.quote = char
            visible.append("x")
            return index + 1
        visible.append(char)
        return index + 1

    def scan_line(self, raw_line):
        index = 0
        visible = []
        while index < len(raw_line):
            index = self._consume_state(raw_line, index, visible)
        compact = re.sub(r"\s+", "", "".join(visible))
        return compact if compact else ""

    def _consume_state(self, raw_line, index, visible):
        if self.raw_end:
            return self._consume_raw(raw_line, index, visible)
        if self.in_block_comment:
            return self._consume_block_comment(raw_line, index)
        if self.quote:
            return self._consume_quote(raw_line, index, visible)
        return self._consume_plain(raw_line, index, visible)

    def incomplete(self):
        return bool(self.in_block_comment or self.raw_end)


def _effective_compact_line(compact):
    if not compact:
        return False
    return not _DELIMITER_ONLY.fullmatch(compact)


def _clike_code_lines(source):
    """Lex comments/strings conservatively and return lines with real code."""
    code_lines = set()
    scanner = _CLikeScanner()
    for number, raw_line in enumerate(source.splitlines(), 1):
        compact = scanner.scan_line(raw_line)
        if _effective_compact_line(compact):
            code_lines.add(number)
    if scanner.incomplete():
        return None
    return code_lines


def _code_lines(path, source):
    if path.lower().endswith((".py", ".pyi")):
        return _python_code_lines(source)
    return _clike_code_lines(source)


def _quoted_step(char, quote_state):
    quote, escaped = quote_state
    if escaped:
        return quote, False
    if char == "\\":
        return quote, True
    if char == quote:
        return "", False
    return quote, False


class _ParenthesisCollector:
    def __init__(self):
        self.depth = 0
        self.quote = ""
        self.escaped = False
        self.content = []

    def consume(self, char):
        if self.quote:
            self.content.append(char)
            state = _quoted_step(char, (self.quote, self.escaped))
            self.quote, self.escaped = state
            return False
        if char in ('"', "'", "`"):
            self.quote = char
            self.content.append(char)
            return False
        if char == "(":
            self.depth += 1
            self.content.append(char)
            return False
        if char != ")":
            self.content.append(char)
            return False
        return self._close()

    def _close(self):
        if self.depth == 0:
            return True
        self.depth -= 1
        self.content.append(")")
        return False

    def collect(self, fragment):
        for char in fragment:
            if self.consume(char):
                return "".join(self.content).strip()
        return None


def _parenthesized_content(fragment):
    opening = fragment.find("(")
    if opening < 0:
        return None
    return _ParenthesisCollector().collect(fragment[opening + 1:])


_OPEN_TO_CLOSE = {"(": ")", "{": "}", "[": "]", "<": ">"}


class _ParameterCounter:
    def __init__(self):
        self.count = 1
        self.stack = []
        self.quote = ""
        self.escaped = False

    def consume(self, char):
        if self.quote:
            state = _quoted_step(char, (self.quote, self.escaped))
            self.quote, self.escaped = state
            return
        if char in ('"', "'", "`"):
            self.quote = char
            return
        self._consume_delimiter(char)

    def _consume_delimiter(self, char):
        if char in _OPEN_TO_CLOSE:
            self.stack.append(_OPEN_TO_CLOSE[char])
            return
        if self._closes_stack(char):
            self.stack.pop()
            return
        if char != ",":
            return
        if not self.stack:
            self.count += 1

    def _closes_stack(self, char):
        return bool(self.stack) and char == self.stack[-1]


def _top_level_parameter_count(value):
    if not value:
        return 0
    counter = _ParameterCounter()
    for index, char in enumerate(value):
        if char == "<" and not _type_angle_open(value, index):
            continue
        counter.consume(char)
    return counter.count


def _type_angle_open(value, index):
    """Recognize formatter-style TypeScript generic brackets, not `x < y`."""
    if not _type_angle_prefix(value, index):
        return False
    return _has_balanced_angle(value[index + 1:])


def _type_angle_prefix(value, index):
    if index < 1:
        return False
    previous = value[index - 1]
    return not previous.isspace() and bool(re.match(r"[\w\]>.]", previous))


def _has_balanced_angle(fragment):
    depth = 1
    for char in fragment:
        if char == "<":
            depth += 1
        elif char == ">":
            depth -= 1
            if depth == 0:
                return True
    return False


def _js_parameter_count(source, function):
    """Count JS/TS formal parameters without expanding destructuring fields."""
    lines = source.splitlines(True)
    start = max(0, int(function.start_line or 1) - 1)
    fragment = "".join(lines[start:start + 30])[:12000]
    content = _parenthesized_content(fragment)
    if content is None:
        # Parenthesis-free arrow functions are represented correctly by
        # Lizard, so retaining that count is safer than guessing.
        return function.parameter_count
    return _top_level_parameter_count(content)


def _parameter_count(path, source, function):
    parameters = list(function.parameters)
    if path.lower().endswith((".py", ".pyi")):
        if parameters and parameters[0] in ("self", "cls"):
            parameters = parameters[1:]
        return len(parameters)
    if path.lower().endswith((".js", ".jsx", ".ts", ".tsx")):
        return _js_parameter_count(source, function)
    return function.parameter_count


def _function_metrics(path, source, function, code_lines):
    parameter_count = _parameter_count(path, source, function)
    if parameter_count is None:
        return None
    if code_lines is None:
        return None
    start = max(1, int(function.start_line or 1))
    end = max(start, int(function.end_line or start))
    return {
        "parameter_count": parameter_count,
        "effective_lines": len(code_lines.intersection(range(start, end + 1))),
        "cyclomatic_complexity": int(function.cyclomatic_complexity),
    }


def _function_start(function):
    value = function.start_line
    return int(value) if value else 0


def _function_signature(function):
    return re.sub(r"\s+", "", str(
        getattr(function, "long_name", "") or ""))


def _pair_by_nearest(current, baseline, matches):
    remaining = list(baseline)
    for function in sorted(current, key=_function_start):
        if not remaining:
            return
        match = min(remaining, key=lambda item: abs(
            _function_start(item) - _function_start(function)))
        matches[id(function)] = match
        remaining.remove(match)


def _take_exact_baseline(function, unused):
    exact = [
        item for item in unused
        if item.name == function.name
        and _function_signature(item) == _function_signature(function)
    ]
    if not exact:
        return None
    return min(exact, key=lambda item: abs(
        _function_start(item) - _function_start(function)))


def _match_exact_functions(current_functions, baseline_functions):
    matches = {}
    unused = list(baseline_functions)
    for function in current_functions:
        match = _take_exact_baseline(function, unused)
        if match is not None:
            matches[id(function)] = match
            unused.remove(match)
    return matches, unused


def _unmatched_named_functions(name, functions, matches):
    return [
        item for item in functions
        if item.name == name and id(item) not in matches
    ]


def _named_functions(name, functions):
    return [
        item for item in functions
        if item.name == name
    ]


def _remove_used_baselines(unused, matches):
    used = {id(item) for item in matches.values()}
    unused[:] = [
        item for item in unused
        if id(item) not in used
    ]


def _match_remaining_name(name, current_functions, unused, matches):
    current = _unmatched_named_functions(
        name, current_functions, matches)
    if not current:
        return
    baseline = _named_functions(name, unused)
    if len(current) > len(baseline):
        return
    _pair_by_nearest(current, baseline, matches)
    _remove_used_baselines(unused, matches)


def _baseline_matches(current_functions, baseline_functions):
    """Build a one-to-one map so a new overload cannot borrow old debt."""
    matches, unused = _match_exact_functions(
        current_functions, baseline_functions)
    names = {item.name for item in current_functions}
    for name in names:
        _match_remaining_name(
            name, current_functions, unused, matches)
    return matches


def _finding(rule, path, line, actual, details):
    return {
        "rule": rule,
        "file": _normalized(path),
        "line": int(line),
        "function": details.get("function", ""),
        "actual": int(actual),
        "limit": int(details["limit"]),
        "message": details["message"],
    }


_FUNCTION_RULES = (
    ("MF-PARAM-5", "parameter_count", PARAMETER_LIMIT, "函数入参超过 5 个"),
    ("MF-FUNC-50", "effective_lines", FUNCTION_LINE_LIMIT,
     "函数有效代码行超过 50 行"),
    ("MF-CC-5", "cyclomatic_complexity", COMPLEXITY_LIMIT,
     "函数 McCabe 圈复杂度超过 5"),
)


def _empty_result(status="CLEAN", skipped=None, duration_ms=0):
    return {
        "status": status,
        "findings": [],
        "existing_debt": [],
        "skipped": list(skipped or []),
        "files": [],
        "functions_checked": 0,
        "duration_ms": int(duration_ms),
    }


def _valid_line_number(line_number, source_lines):
    return line_number >= 1 and line_number <= len(source_lines)


class _ChangedAnalyzer:
    def __init__(
            self, root, files, changed_lines, baseline_sources,
            current_sources=None):
        self.root = root
        self.files = list(dict.fromkeys(files))
        self.changed_lines = changed_lines
        self.baseline_sources = baseline_sources
        self.current_sources = current_sources or {}
        self.result = _empty_result()
        self.total_bytes = 0
        self.started = time.monotonic()
        self.lizard = None

    def _skip(self, message):
        self.result["skipped"].append(message)

    def _read_source(self, path):
        if path in self.current_sources:
            return self._read_snapshot_source(path)
        return self._read_worktree_source(path)

    def _within_budget(self, path, size, label):
        if size > MAX_FILE_BYTES:
            self._skip(path + ": " + label + "超过单文件轻量预算")
            return False
        if self.total_bytes + size > MAX_TOTAL_BYTES:
            self._skip(path + ": " + label + "超过本批轻量预算")
            return False
        self.total_bytes += size
        return True

    def _read_snapshot_source(self, path):
        source = self.current_sources[path]
        if source is None:
            self._skip(path + ": 提交快照中不存在")
            return None
        size = len(source.encode("utf-8", errors="replace"))
        return source if self._within_budget(path, size, "提交快照") else None

    def _read_worktree_source(self, path):
        absolute = os.path.join(self.root, path)
        try:
            size = os.path.getsize(absolute)
        except OSError as exc:
            self._skip(path + ": 无法安全读取(" + str(exc) + ")")
            return None
        if not self._within_budget(path, size, "工作区文件"):
            return None
        try:
            with open(absolute, encoding="utf-8", errors="replace") as stream:
                source = stream.read()
        except OSError as exc:
            self._skip(path + ": 无法安全读取(" + str(exc) + ")")
            return None
        return source

    def _changed_for(self, path):
        changed = set()
        for line in self.changed_lines.get(path, set()):
            try:
                changed.add(int(line))
            except (TypeError, ValueError):
                continue
        return changed

    def _parse(self, path, source):
        try:
            return self.lizard.analyze_file.analyze_source_code(path, source)
        except Exception as exc:
            self._skip(path + ": 语法分析失败(" + str(exc) + ")")
            return None

    def _baseline_data(self, path):
        source = self.baseline_sources.get(path)
        if source is None:
            return None, [], None
        info = self._parse(path, source)
        if info is None:
            return source, [], None
        return source, info.function_list, _code_lines(path, source)

    @staticmethod
    def _line_finding(path, source_lines, code_lines, line_number):
        if not _valid_line_number(line_number, source_lines):
            return None
        if code_lines is None:
            return None
        if line_number not in code_lines:
            return None
        actual = len(source_lines[line_number - 1].expandtabs(TAB_WIDTH))
        if actual <= LINE_LENGTH_LIMIT:
            return None
        details = {
            "limit": LINE_LENGTH_LIMIT,
            "message": "本次修改的代码行超过 120 字符；"
                       "按项目 formatter 和附近同类代码换行",
        }
        return _finding(
            "MF-LINE-120", path, line_number, actual, details)

    def _add_line_findings(self, path, source, code_lines, changed):
        source_lines = source.splitlines()
        for line_number in sorted(changed):
            item = self._line_finding(
                path, source_lines, code_lines, line_number)
            if item is not None:
                self.result["findings"].append(item)

    @staticmethod
    def _touches(function, changed):
        start = _function_start(function)
        end = max(start, int(function.end_line or start))
        return bool(changed.intersection(range(start, end + 1)))

    def _record_metric(self, path, function, metrics, old_metrics, rule_spec):
        rule, metric, limit, message = rule_spec
        actual = metrics[metric]
        if actual <= limit:
            return
        details = {
            "function": function.name,
            "limit": limit,
            "message": message,
        }
        item = _finding(
            rule, path, _function_start(function), actual, details)
        old = old_metrics.get(metric) if old_metrics else None
        if old is None:
            self.result["findings"].append(item)
            return
        item["baseline"] = int(old)
        if old > limit:
            item["message"] += "（基线已存在，仅留痕）"
            self.result["existing_debt"].append(item)
            return
        self.result["findings"].append(item)

    def _add_function(self, context, baseline_data, baseline, function):
        if not self._touches(function, context["changed"]):
            return
        metrics = _function_metrics(
            context["path"], context["source"], function,
            context["code_lines"])
        if metrics is None:
            self._skip("%s:%d %s: 有效行/参数解析不确定" % (
                context["path"], _function_start(function), function.name))
            return
        self.result["functions_checked"] += 1
        baseline_source, _baseline_functions, baseline_lines = baseline_data
        old_metrics = None
        if baseline is not None:
            old_metrics = _function_metrics(
                context["path"], baseline_source, baseline, baseline_lines)
        for rule_spec in _FUNCTION_RULES:
            self._record_metric(
                context["path"], function, metrics, old_metrics, rule_spec)

    def _analyze_source(self, path, source, changed):
        if _looks_generated(source):
            self._skip(path + ": 文件声明为自动生成")
            return
        current_info = self._parse(path, source)
        if current_info is None:
            return
        self.result["files"].append(path)
        code_lines = _code_lines(path, source)
        baseline_data = self._baseline_data(path)
        baseline_matches = _baseline_matches(
            current_info.function_list, baseline_data[1])
        self._add_line_findings(path, source, code_lines, changed)
        context = {
            "path": path, "source": source,
            "code_lines": code_lines, "changed": changed,
        }
        for function in current_info.function_list:
            self._add_function(
                context, baseline_data, baseline_matches.get(id(function)),
                function)

    def _analyze_file(self, raw_path):
        path = _normalized(raw_path)
        if _generated_path(path):
            self._skip(path + ": 生成/三方目录")
            return
        source = self._read_source(path)
        if source is None:
            return
        changed = self._changed_for(path)
        if not changed:
            return
        self._analyze_source(path, source, changed)

    def _finish(self):
        order = lambda item: (item["file"], item["line"], item["rule"])
        self.result["findings"].sort(key=order)
        self.result["existing_debt"].sort(key=order)
        self._truncate_result("findings", "本轮建议")
        self._truncate_result("existing_debt", "基线旧债")
        if self.result["findings"]:
            self.result["status"] = "FINDINGS"
        if not self.result["files"] and self.result["skipped"]:
            self.result["status"] = "SKIPPED"
        elapsed = time.monotonic() - self.started
        self.result["duration_ms"] = int(elapsed * 1000)
        return self.result

    def _truncate_result(self, key, label):
        items = self.result[key]
        if len(items) <= MAX_REPORTED_ITEMS:
            return
        omitted = len(items) - MAX_REPORTED_ITEMS
        self.result[key] = items[:MAX_REPORTED_ITEMS]
        self._skip("%s超过轻量报告上限，省略 %d 项" % (label, omitted))

    def run(self):
        try:
            self.lizard = _load_lizard()
        except BaseException as exc:
            return _empty_result(
                "TOOL_ERROR", ["分析器不可用: " + str(exc)])
        for path in self.files[:MAX_FILES]:
            if path.lower().endswith(SUPPORTED_EXTENSIONS):
                self._analyze_file(path)
        if len(self.files) > MAX_FILES:
            self._skip("文件数超过 %d，仅检查前 %d 个" % (
                MAX_FILES, MAX_FILES))
        return self._finish()


def analyze_changed(
        root, files, changed_lines, baseline_sources=None,
        current_sources=None):
    """Analyze current source while reporting only newly triggered rules."""
    analyzer = _ChangedAnalyzer(
        root, files, changed_lines, baseline_sources or {}, current_sources)
    return analyzer.run()


def _analyze_worker(connection, arguments):
    try:
        connection.send(analyze_changed(*arguments))
    except BaseException as exc:
        connection.send(_empty_result(
            "TOOL_ERROR", ["隔离分析进程异常: " + str(exc)]))
    finally:
        connection.close()


def _stop_process(process):
    if process.is_alive():
        process.terminate()
        process.join(2)


def _pipe_result(connection):
    try:
        return connection.recv()
    except (EOFError, OSError):
        return _empty_result(
            "TOOL_ERROR", ["轻量分析子进程未返回结果，已自动放行"])


def _process_context():
    method = "spawn"
    if os.name != "nt":
        method = "fork"
    return multiprocessing.get_context(method)


def _process_arguments(
        root, files, changed_lines, baseline_sources, current_sources):
    sources = baseline_sources
    if sources is None:
        sources = {}
    return root, files, changed_lines, sources, current_sources


def _await_analysis_result(receiver, process, timeout_seconds):
    if not receiver.poll(timeout_seconds):
        _stop_process(process)
        return _empty_result(
            "TOOL_ERROR",
            ["轻量分析超过 %s 秒，已自动放行" % timeout_seconds],
            timeout_seconds * 1000)
    result = _pipe_result(receiver)
    process.join(2)
    return result


def _close_sender(sender):
    if not sender.closed:
        sender.close()


def analyze_changed_with_timeout(
        root, files, changed_lines, baseline_sources=None,
        options=None):
    """Run the analyzer in an isolated process; timeout is always advisory."""
    options = options or {}
    current_sources = options.get("current_sources")
    timeout_seconds = options.get("timeout_seconds", 8)
    context = _process_context()
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_analyze_worker,
        args=(sender, _process_arguments(
            root, files, changed_lines, baseline_sources, current_sources)),
    )
    try:
        process.start()
        sender.close()
        return _await_analysis_result(
            receiver, process, timeout_seconds)
    except Exception as exc:
        return _empty_result(
            "TOOL_ERROR",
            ["轻量分析隔离启动失败，已自动放行: " + str(exc)])
    finally:
        _stop_process(process)
        receiver.close()
        _close_sender(sender)


def _report_header(result, scope):
    return [
        "# Mae-Flow 轻量编码预检",
        "",
        "- 定位：前置预防建议，不替代正式 CodeCheck，不产生流程门禁",
        "- 范围：" + str(scope or "本轮 Agent 实际修改"),
        "- 结果：" + result.get("status", "UNKNOWN"),
        "- 检查文件：%d" % len(result.get("files") or []),
        "- 检查函数：%d" % int(result.get("functions_checked", 0) or 0),
        "- 耗时：%dms" % int(result.get("duration_ms", 0) or 0),
        "",
    ]


def _report_findings(findings):
    if not findings:
        return ["本轮没有发现高置信问题。", ""]
    lines = ["## 建议本轮修复", ""]
    for item in findings:
        function = ("，函数 `" + item["function"] + "`"
                    if item.get("function") else "")
        baseline = ("，基线 %s" % item["baseline"]
                    if "baseline" in item else "")
        lines.append(
            "- `%s` `%s:%s`%s：%s（当前 %s，上限 %s%s）" % (
                item["rule"], item["file"], item["line"], function,
                item["message"], item["actual"], item["limit"], baseline))
    lines.append("")
    return lines


def _report_debt(debt):
    if not debt:
        return []
    lines = ["## 基线已有（不提示修复、不推动范围外重构）", ""]
    for item in debt:
        lines.append("- `%s` `%s:%s`：当前 %s，基线 %s" % (
            item["rule"], item["file"], item["line"],
            item["actual"], item.get("baseline", "?")))
    lines.append("")
    return lines


def _report_skipped(skipped):
    if not skipped:
        return []
    return ["## 安全降级", ""] + [
        "- " + item for item in skipped
    ] + [""]


def _report_rules():
    return [
        "## 固定口径",
        "",
        "- 参数 ≤ 5；Python 的 `self`/`cls` 不计入。",
        "- 函数有效代码行 ≤ 50；空行、纯注释、仅分隔括号/符号的行不计。",
        "- McCabe 圈复杂度 ≤ 5；嵌套通过其决策点体现，不另造阻塞规则。",
        "- 本次修改的代码行 ≤ 120 字符；不自动暴力换行，优先项目 formatter 和附近同类风格。",
        "",
    ]


def render_markdown(result, scope):
    lines = _report_header(result, scope)
    findings = result.get("findings") or []
    debt = result.get("existing_debt") or []
    skipped = result.get("skipped") or []
    lines += _report_findings(findings)
    lines += _report_debt(debt)
    lines += _report_skipped(skipped)
    lines += _report_rules()
    return "\n".join(lines)
