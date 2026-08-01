"""High-confidence magic-number findings for changed source lines."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from .lightcheck_source import (
    _classified_lines, _normalized, _parse_python_tree, ast,
)


@dataclass(frozen=True)
class MagicNumberFinding:
    line: int
    literal: str
    reason: str


_NUMBER = re.compile(
    r"(?<![\w])(?:"
    r"0[xX][0-9A-Fa-f_]+|0[bB][01_]+|0[oO][0-7_]+|"
    r"(?:\d[\d_]*\.\d*|\.\d[\d_]*|\d[\d_]*)"
    r"(?:[eE][+-]?\d[\d_]*)?"
    r")(?:[uUlLfFdDmM]+)?(?![\w])"
)
_TEST_PARTS = {
    "test", "tests", "__tests__", "fixture", "fixtures",
    "testdata", "test-data", "test_data",
}
_TEST_FILE = re.compile(
    r"(?i)(?:^test_|\.(?:test|spec)\.|"
    r"(?:^|[._-])tests?(?:[._-]|$)|"
    r"(?:^|[._-])fixtures?(?:[._-]|$)|"
    r"(?:^|[._-])test[_-]?data(?:[._-]|$))")
_CONSTANT_WORD = re.compile(
    r"\b(?:const|constexpr|readonly)\b|\bstatic\s+final\b")
_DEFINE = re.compile(r"^\s*#\s*define\s+[A-Za-z_]\w*(?:\s|$)")
_PYTHON_CONSTANT = re.compile(
    r"^\s*[A-Z][A-Z0-9_]*(?:\s*:\s*[^=]+)?\s*=(?!=)")
_DIRECTIVE = re.compile(
    r"(?i)^\s*(?:todo|fixme|xxx|hack|noqa|nosonar|nolint|"
    r"lint(?:[-_: ]|$)|eslint(?:[-_: ]|$)|pylint(?:[-_: ]|$)|"
    r"stylelint(?:[-_: ]|$)|tslint(?:[-_: ]|$)|noinspection|"
    r"prettier-ignore|istanbul\s+ignore|c8\s+ignore)\b")
_COMMENT_WORD = re.compile(r"[A-Za-z][A-Za-z_-]*")
_COMMENT_CJK = re.compile(r"[\u3400-\u9fff]")
_ENUM_DECLARATION = re.compile(
    r"^\s*(?:(?:typedef|public|protected|private|internal|static|export|"
    r"declare|const)\s+)*enum\b(?:\s+(?:class|struct))?"
    r"(?:\s+[A-Za-z_]\w*)?")
_JAVA_ENUM_MEMBER = re.compile(r"(?:^|,)\s*[A-Za-z_]\w*\s*\(")
_ENUM_TAIL = re.compile(
    r"^\s*(?:(?::\s*[A-Za-z_][\w:<>,.\s]*)|"
    r"(?:implements\s+[A-Za-z_][\w<>,.\s]*))?\s*$")
_ASSIGNMENT = re.compile(r"(?<![=!<>])=(?!=)")
_MAX_DECLARATION_LINES = 32


def _is_test_data_path(path):
    normalized = _normalized(path)
    parts = {part.lower() for part in normalized.split("/")[:-1]}
    return bool(
        parts & _TEST_PARTS
        or _TEST_FILE.search(os.path.basename(normalized)))


def _python_enum_spans(source, classified):
    tree = _parse_python_tree(source)
    if tree is None:
        return None
    result = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or not _is_enum_class(node):
            continue
        for statement in node.body:
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                for line in range(
                        statement.lineno,
                        getattr(statement, "end_lineno", statement.lineno) + 1):
                    code = classified.get(line)
                    if code is not None:
                        result.setdefault(line, []).append((0, len(code.code)))
    return result


def _is_enum_class(node):
    names = {"Enum", "IntEnum", "Flag", "IntFlag"}
    for base in node.bases:
        name = getattr(base, "id", None) or getattr(base, "attr", None)
        if name in names:
            return True
    return False


def _enum_member_segment(segment, is_java):
    return bool("=" in segment or (
        is_java and _JAVA_ENUM_MEMBER.search(segment)))


def _enum_declaration_opening(code):
    declaration = _ENUM_DECLARATION.search(code)
    if declaration is None:
        return None
    opening = code.find("{", declaration.end())
    tail_end = len(code) if opening < 0 else opening
    if not _ENUM_TAIL.fullmatch(code[declaration.end():tail_end]):
        return None
    return opening


def _add_span(result, line, start, end):
    if end > start:
        result.setdefault(line, []).append((start, end))


def _continued_enum_span(
        result, line, code, start, end, continuation):
    if continuation is None:
        return None
    _add_span(result, line, start, end)
    kind, depth, remaining = continuation
    segment = code[start:end]
    depth += segment.count("(") - segment.count(")")
    remaining -= 1
    if remaining <= 0:
        return None
    if kind == "java" and depth <= 0:
        return None
    if kind == "clike" and depth <= 0 and "," in segment:
        return None
    return kind, depth, remaining


def _new_enum_continuation(segment, is_java):
    if is_java:
        member = _JAVA_ENUM_MEMBER.search(segment)
        if member is None:
            return None
        depth = segment[member.start():].count("(") - segment[member.start():].count(")")
        if depth > 0:
            return "java", depth, _MAX_DECLARATION_LINES
        return None
    if "=" not in segment or "," in segment:
        return None
    value = segment.split("=", 1)[1]
    depth = value.count("(") - value.count(")")
    return "clike", depth, _MAX_DECLARATION_LINES


def _braced_enum_spans(path, classified):
    result = {}
    depth = 0
    enum_depth = None
    pending = False
    pending_tail = ""
    pending_lines = 0
    member_section = False
    continuation = None
    is_java = path.lower().endswith(".java")
    for line in sorted(classified):
        code = classified[line].code
        started_pending = False
        if enum_depth is None and not pending:
            opening = _enum_declaration_opening(code)
            if opening is not None:
                if opening < 0:
                    pending = True
                    started_pending = True
                    pending_tail = ""
                    pending_lines = _MAX_DECLARATION_LINES
                else:
                    enum_depth = depth + 1
                    member_section = True
                    start = opening + 1
        start = 0
        if enum_depth is not None and code.find("{") >= 0 and depth < enum_depth:
            start = code.find("{") + 1
        elif pending and "{" in code:
            opening = code.find("{")
            pending_tail += " " + code[:opening]
            if _ENUM_TAIL.fullmatch(pending_tail):
                start = opening + 1
                enum_depth = depth + 1
                member_section = True
            pending = False
            pending_tail = ""
        elif pending and not started_pending:
            pending_tail += " " + code
            pending_lines -= 1
            if pending_lines <= 0 or not _ENUM_TAIL.fullmatch(pending_tail):
                pending = False
                pending_tail = ""
        if enum_depth is not None and member_section:
            end = len(code)
            closing = code.find("}", start)
            if closing >= 0:
                end = min(end, closing)
            separator = code.find(";", start) if is_java else -1
            if separator >= 0:
                end = min(end, separator)
                member_section = False
            continuation = _continued_enum_span(
                result, line, code, start, end, continuation)
            segment = code[start:end]
            if continuation is None and _enum_member_segment(
                    segment, is_java):
                _add_span(result, line, start, end)
                continuation = _new_enum_continuation(segment, is_java)
        depth += code.count("{") - code.count("}")
        if enum_depth is not None and depth < enum_depth:
            enum_depth = None
            pending = False
            member_section = False
            continuation = None
        elif pending and enum_depth is None and ";" in code:
            pending = False
    return result


def _enum_member_spans(path, source, classified):
    if path.lower().endswith((".py", ".pyi")):
        return _python_enum_spans(source, classified)
    return _braced_enum_spans(path, classified)


def _is_enum_member_number(spans, line, match):
    return any(
        start <= match.start() and match.end() <= end
        for start, end in spans.get(line, ()))


def _statement_start(code, position):
    return max(
        code.rfind(";", 0, position),
        code.rfind("{", 0, position),
        code.rfind("}", 0, position),
    ) + 1


def _constant_initializer_start(path, code, offset=0):
    for assignment in _ASSIGNMENT.finditer(code, offset):
        start = _statement_start(code, assignment.start())
        declaration = code[start:assignment.start()]
        if path.lower().endswith((".py", ".pyi")):
            if _PYTHON_CONSTANT.search(declaration + "="):
                return assignment.end()
        elif _CONSTANT_WORD.search(declaration):
            return assignment.end()
    return None


def _constant_initializer_spans(path, classified):
    result = {}
    active = False
    remaining = 0
    is_python = path.lower().endswith((".py", ".pyi"))
    for line in sorted(classified):
        code = classified[line].code
        cursor = 0
        if _DEFINE.search(code):
            macro = _DEFINE.search(code)
            _add_span(result, line, macro.end(), len(code))
            continue
        if active:
            terminator = code.find(";")
            end = len(code) if terminator < 0 else terminator
            _add_span(result, line, 0, end)
            remaining -= 1
            if terminator < 0 and remaining > 0:
                continue
            active = False
            cursor = end + (terminator >= 0)
        while cursor < len(code):
            initializer = _constant_initializer_start(path, code, cursor)
            if initializer is None:
                break
            terminator = code.find(";", initializer)
            if terminator >= 0:
                _add_span(result, line, initializer, terminator)
                cursor = terminator + 1
                continue
            _add_span(result, line, initializer, len(code))
            if not is_python:
                active = True
                remaining = _MAX_DECLARATION_LINES
            break
    return result


def _is_masked_number(spans, line, match):
    return any(
        start <= match.start() and match.end() <= end
        for start, end in spans.get(line, ()))


def _has_explanation(comment):
    if not comment or _DIRECTIVE.search(comment):
        return False
    if len(_COMMENT_CJK.findall(comment)) >= 4:
        return True
    return len(_COMMENT_WORD.findall(comment)) >= 3


def find_magic_numbers(path, source, changed_lines):
    """Return changed-line findings, or None when tokenization is uncertain."""
    if _is_test_data_path(path):
        return []
    classified = _classified_lines(path, source)
    if classified is None:
        return None
    enum_spans = _enum_member_spans(path, source, classified)
    if enum_spans is None:
        return None
    constant_spans = _constant_initializer_spans(path, classified)
    findings = []
    for line in sorted(set(changed_lines)):
        facts = classified.get(line)
        if facts is None:
            continue
        if _has_explanation(facts.comment):
            continue
        for match in _NUMBER.finditer(facts.code):
            if _is_enum_member_number(enum_spans, line, match):
                continue
            if _is_masked_number(constant_spans, line, match):
                continue
            literal = match.group(0)
            findings.append(MagicNumberFinding(
                line=line,
                literal=literal,
                reason=("数值字面量 %s 直接用于业务逻辑；请改用命名常量或同行说明意图"
                        % literal),
            ))
    return findings
