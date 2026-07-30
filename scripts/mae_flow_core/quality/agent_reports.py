"""Pure parsing for flexible Agent final reports."""

import re


REPORT_FIELDS = (
    "TASK_CARD_SHA256", "GENERATOR_USED", "EXECUTED_UT",
    "EXECUTED_BUILD", "EXECUTED_COMMAND", "TESTS_TOTAL",
    "TESTS_PASSED", "TESTS_FAILED", "AC_COVERAGE",
    "BLUEPRINT_SHA256", "BLUEPRINT_MAPPING",
    "PENDING_QUESTIONS", "KNOWN_FAILURES", "SUSPECTED_BUGS",
    "FOUND", "FIXED", "REMAINING_COUNT", "STAGE", "GAPS_FOUND",
    "MISSING_BRANCHES",
)


def report_field(report, name):
    """Read a flexible field without requiring one field per line."""
    fields = "|".join(re.escape(field) for field in REPORT_FIELDS)
    match = re.search(
        r"(?:^|(?<=[\s,;]))(?:[-*]\s*)?" + re.escape(name)
        + r"\s*:\s*(.*?)(?=(?:\s+|,\s*)(?:[-*]\s*)?(?:"
        + fields + r")\s*:|\Z)",
        report,
        re.I | re.S,
    )
    return match.group(1).strip(" \t\r\n`") if match else None


def report_number(report, name):
    value = report_field(report, name)
    match = re.match(r"(\d+)\b", value or "")
    return int(match.group(1)) if match else None


def report_section(report, name):
    match = re.search(
        r"^\s*" + re.escape(name)
        + r":\s*(.*?)(?=^\s*[A-Z][A-Z0-9_]+:\s*|\Z)",
        report,
        re.M | re.S,
    )
    return match.group(1).strip() if match else None


def empty_section(value):
    return value is not None and re.sub(
        r"[\s`*_-]+", "", value
    ).lower() in ("无", "none", "0", "暂无")


def _markdown_rows(coverage):
    rows = []
    for raw in coverage.splitlines():
        line = raw.strip()
        if not line.startswith("|") or "|" not in line[1:]:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) >= 2:
            rows.append(cells)
    return rows


def _separator_row(cells):
    return all(re.fullmatch(
        r":?-{3,}:?", cell.replace(" ", "")) for cell in cells)


def _markdown_table_has_mapping(rows):
    for index, cells in enumerate(rows):
        if not _separator_row(cells):
            continue
        if index == 0 or index + 1 >= len(rows):
            continue
        for data in rows[index + 1:]:
            if (
                    len(data) >= 2
                    and data[0]
                    and data[1]
                    and not _separator_row(data)):
                return True
    return False


def ac_coverage_has_mapping(coverage):
    """Accept an arrow mapping or a Markdown table with a data row."""
    return bool(
        re.search(r"(->|→|=>)", coverage)
        or _markdown_table_has_mapping(_markdown_rows(coverage))
    )
