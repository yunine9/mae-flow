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
    r"(?i)(?:^test_|[_-]tests?\.|\.(?:test|spec)\.|fixture|test[_-]?data)")
_CONSTANT_WORD = re.compile(
    r"\b(?:const|constexpr|readonly)\b|\bstatic\s+final\b")
_DEFINE = re.compile(r"^\s*#\s*define\s+[A-Za-z_]\w*")
_PYTHON_CONSTANT = re.compile(
    r"^\s*[A-Z][A-Z0-9_]*(?:\s*:\s*[^=]+)?\s*=")
_EXPLANATION = re.compile(r"[A-Za-z_\u0080-\uffff]")


def _is_test_data_path(path):
    normalized = _normalized(path)
    parts = {part.lower() for part in normalized.split("/")[:-1]}
    return bool(
        parts & _TEST_PARTS
        or _TEST_FILE.search(os.path.basename(normalized)))


def _python_enum_lines(source):
    tree = _parse_python_tree(source)
    if tree is None:
        return None
    result = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or not _is_enum_class(node):
            continue
        for statement in node.body:
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                result.update(range(
                    statement.lineno,
                    getattr(statement, "end_lineno", statement.lineno) + 1))
    return result


def _is_enum_class(node):
    names = {"Enum", "IntEnum", "Flag", "IntFlag"}
    for base in node.bases:
        name = getattr(base, "id", None) or getattr(base, "attr", None)
        if name in names:
            return True
    return False


def _braced_enum_lines(classified):
    result = set()
    depth = 0
    enum_depth = None
    pending = False
    for line in sorted(classified):
        code = classified[line].code
        if re.search(r"\benum\b", code):
            pending = True
        if pending and "{" in code and enum_depth is None:
            enum_depth = depth + 1
        if enum_depth is not None or pending:
            result.add(line)
        depth += code.count("{") - code.count("}")
        if enum_depth is not None and depth < enum_depth:
            enum_depth = None
            pending = False
        elif pending and enum_depth is None and ";" in code:
            pending = False
    return result


def _enum_lines(path, source, classified):
    if path.lower().endswith((".py", ".pyi")):
        return _python_enum_lines(source)
    return _braced_enum_lines(classified)


def _is_direct_constant(path, code, match):
    prefix = code[:match.start()]
    suffix = code[match.end():]
    equals = prefix.rfind("=")
    if equals < 0:
        return False
    between = prefix[equals + 1:].strip()
    if between not in ("", "+", "-"):
        return False
    if suffix.lstrip()[:1] not in ("", ";", ",", "}"):
        return False
    declaration = prefix[:equals]
    if path.lower().endswith((".py", ".pyi")):
        return bool(_PYTHON_CONSTANT.search(declaration + "="))
    if _DEFINE.search(code):
        return True
    return bool(_CONSTANT_WORD.search(declaration))


def _has_explanation(comment):
    return bool(comment and _EXPLANATION.search(comment))


def find_magic_numbers(path, source, changed_lines):
    """Return changed-line findings, or None when tokenization is uncertain."""
    if _is_test_data_path(path):
        return []
    classified = _classified_lines(path, source)
    if classified is None:
        return None
    enum_lines = _enum_lines(path, source, classified)
    if enum_lines is None:
        return None
    findings = []
    for line in sorted(set(changed_lines)):
        facts = classified.get(line)
        if facts is None or line in enum_lines:
            continue
        if _has_explanation(facts.comment):
            continue
        for match in _NUMBER.finditer(facts.code):
            if _is_direct_constant(path, facts.code, match):
                continue
            literal = match.group(0)
            findings.append(MagicNumberFinding(
                line=line,
                literal=literal,
                reason=("数值字面量 %s 直接用于业务逻辑；请改用命名常量或同行说明意图"
                        % literal),
            ))
    return findings
