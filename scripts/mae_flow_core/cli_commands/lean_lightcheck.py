"""Exact-file, fail-open Lightcheck adapter for the lean CLI."""

import os
import re
import subprocess
import sys

from mae_flow_core.lightcheck import (
    SUPPORTED_EXTENSIONS,
    analyze_changed_with_timeout,
    render_markdown,
)
from mae_flow_core.orchestration.models import Phase
from mae_flow_core.state_store import atomic_write_text


REPORT_PATH = os.path.join(
    ".mae-flow-work", "lightcheck", "latest.md")


def _normal(path):
    value = str(path or "").replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return value


def _inside_repository(repository, absolute, path_module=os.path):
    try:
        return path_module.normcase(path_module.commonpath(
            [repository, absolute])) == path_module.normcase(repository)
    except ValueError:
        return False


def _repository_file(path, root):
    repository = os.path.realpath(root)
    absolute = os.path.realpath(path)
    if (not _inside_repository(repository, absolute)
            or not os.path.isfile(absolute)):
        return ""
    return _normal(os.path.relpath(absolute, repository))


def _git(arguments):
    try:
        result = subprocess.run(
            ["git"] + list(arguments),
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout if result.returncode == 0 else ""


def _hunk_lines(line, deletion_anchor):
    match = re.match(
        r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
    if not match:
        return set()
    start = int(match.group(1))
    count = int(match.group(2) if match.group(2) is not None else "1")
    if count == 0:
        return {start} if deletion_anchor else set()
    return set(range(start, start + count))


def _changed_lines(files, deletion_anchor=True):
    result = {path: set() for path in files}
    output = _git([
        "diff", "-U0", "--no-renames", "HEAD", "--", *files])
    current = ""
    for line in output.splitlines():
        if line.startswith("+++ "):
            current = _normal(line[4:].strip())
            if current.startswith("b/"):
                current = current[2:]
            continue
        if current in result and line.startswith("@@ "):
            result[current].update(
                _hunk_lines(line, deletion_anchor))
    tracked = set(_normal(path) for path in _git(
        ["ls-files", "--", *files]).splitlines())
    for path in files:
        if path not in tracked:
            try:
                with open(path, encoding="utf-8", errors="replace") as stream:
                    result[path] = set(range(1, len(stream.read().splitlines()) + 1))
            except OSError:
                result[path] = set()
    return result, tracked


def _baseline_sources(files, tracked):
    sources = {}
    for path in files:
        sources[path] = (
            _git(["show", "HEAD:" + path]) if path in tracked else None)
    return sources


def _tool_error(reason):
    return {
        "status": "TOOL_ERROR",
        "findings": [],
        "existing_debt": [],
        "skipped": [reason],
        "files": [],
        "functions_checked": 0,
        "duration_ms": 0,
    }


def _skipped(reason):
    result = _tool_error(reason)
    result["status"] = "SKIPPED"
    return result


def _save(result):
    try:
        atomic_write_text(
            REPORT_PATH,
            render_markdown(result, "提交前：精确本次修改代码"),
        )
        return _normal(os.path.abspath(REPORT_PATH))
    except Exception as exc:
        result.setdefault("skipped", []).append("报告写入失败: " + str(exc))
        return ""


def _print(result, quiet):
    findings = result.get("findings", [])
    report = result.get("report_path", "")
    if findings:
        print(
            "[mae-flow] ⚠ 轻量编码预检发现 %d 个本轮新触发问题（建议修复，不阻断）:"
            % len(findings),
            file=sys.stderr,
        )
        for item in findings[:12]:
            function = (" " + item["function"]) if item.get("function") else ""
            print(
                "  %s %s:%s%s — %s (%s > %s)" % (
                    item["rule"], item["file"], item["line"], function,
                    item["message"], item["actual"], item["limit"]),
                file=sys.stderr,
            )
        if report:
            print("  人类可读报告: " + report, file=sys.stderr)
        return
    if quiet:
        return
    print("[mae-flow] 轻量编码预检 %s（建议项，不替代正式 CodeCheck）"
          % result.get("status", "SKIPPED"))
    if report:
        print("[mae-flow] 报告: " + report)


def run_exact_lightcheck(files, quiet=False):
    """Analyze only caller-supplied code files and always return success."""
    root = os.getcwd()
    candidates = tuple(dict.fromkeys(
        relative for relative in (
            _repository_file(path, root) for path in files)
        if relative.lower().endswith(SUPPORTED_EXTENSIONS)
    ))
    if not candidates:
        result = _skipped("没有可安全检查的精确仓库内代码文件")
        result["report_path"] = _save(result)
        _print(result, quiet)
        return 0
    try:
        changed, tracked = _changed_lines(candidates)
        magic_changed, unused_tracked = _changed_lines(
            candidates, deletion_anchor=False)
        result = analyze_changed_with_timeout(
            root,
            candidates,
            changed,
            baseline_sources=_baseline_sources(candidates, tracked),
            options={"magic_changed_lines": magic_changed},
        )
    except Exception as exc:
        result = _tool_error("轻量检查异常，已自动放行: " + str(exc))
    result["report_path"] = _save(result)
    _print(result, quiet)
    return 0


def run_cli_lightcheck(root, files, quiet, state_loader, die):
    """Reject an empty active Construction scope; otherwise stay fail-open."""
    if files:
        return run_exact_lightcheck(files, quiet=quiet)
    try:
        state = state_loader(root)
    except ValueError:
        state = None
    if state is not None and state.phase == Phase.CONSTRUCTION:
        die(
            "活跃编码阶段的 Lightcheck 必须提供精确范围："
            "lightcheck --file <精确本次修改文件>"
            " [--file <更多精确文件>]")
    print("[mae-flow] 轻量编码预检未提供精确本次修改文件，已自动放行。")
    return 0
