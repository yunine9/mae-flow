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


def _braced_enum_spans(path, classified):
    result = {}
    depth = 0
    enum_depth = None
    pending = False
    member_section = False
    is_java = path.lower().endswith(".java")
    for line in sorted(classified):
        code = classified[line].code
        if enum_depth is None and not pending and _ENUM_DECLARATION.search(code):
            pending = True
        start = 0
        if pending and "{" in code and enum_depth is None:
            start = code.find("{") + 1
            enum_depth = depth + 1
            pending = False
            member_section = True
        if enum_depth is not None and member_section:
            end = len(code)
            closing = code.find("}", start)
            if closing >= 0:
                end = min(end, closing)
            separator = code.find(";", start) if is_java else -1
            if separator >= 0:
                end = min(end, separator)
                member_section = False
            if end > start and _enum_member_segment(
                    code[start:end], is_java):
                result.setdefault(line, []).append((start, end))
        depth += code.count("{") - code.count("}")
        if enum_depth is not None and depth < enum_depth:
            enum_depth = None
            pending = False
            member_section = False
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


def _is_constant_declaration(path, code):
    if _DEFINE.search(code):
        return True
    equals = code.find("=")
    if equals < 0:
        return False
    if path.lower().endswith((".py", ".pyi")):
        return bool(_PYTHON_CONSTANT.search(code))
    return bool(_CONSTANT_WORD.search(code[:equals]))


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
    findings = []
    for line in sorted(set(changed_lines)):
        facts = classified.get(line)
        if facts is None:
            continue
        if _has_explanation(facts.comment):
            continue
        if _is_constant_declaration(path, facts.code):
            continue
        for match in _NUMBER.finditer(facts.code):
            if _is_enum_member_number(enum_spans, line, match):
                continue
            literal = match.group(0)
            findings.append(MagicNumberFinding(
                line=line,
                literal=literal,
                reason=("数值字面量 %s 直接用于业务逻辑；请改用命名常量或同行说明意图"
                        % literal),
            ))
    return findings
