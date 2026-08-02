"""Portable startup configuration and repository-default resolution."""

import json
import os
import re

from .models import StartupConfig


DEFAULTS_NAME = ".mae-flow-defaults.json"
_ALIASES = {
    "worker": ("worker", "工号"),
    "ticket_type": ("ticket_type", "单号类型"),
    "requirement_source": (
        "requirement_source", "requirement", "需求文档"),
    "base_branch": ("base_branch", "基线分支"),
    "working_branch": ("working_branch", "分支名"),
    "build_method": ("build_method", "编译方式"),
    "ut_method": ("ut_method", "UT生成方式"),
    "ut_command": ("ut_command", "UT运行命令"),
}
_UNSAFE_BRANCH_COMPONENT = re.compile(r"[\\\s~^:?*\[\];&|`$<>()\"']")


def load_startup_defaults(root):
    """Return recognized string defaults plus a non-blocking read error."""
    path = os.path.join(root, DEFAULTS_NAME)
    if not os.path.isfile(path):
        return {}, ""
    try:
        with open(path, encoding="utf-8-sig") as stream:
            raw = json.load(stream)
    except (OSError, UnicodeError, ValueError) as exc:
        return {}, "%s: %s" % (type(exc).__name__, exc)
    if not isinstance(raw, dict):
        return {}, "defaults must be a JSON object"
    resolved = {}
    for field, aliases in _ALIASES.items():
        for alias in aliases:
            if alias not in raw:
                continue
            value = raw[alias]
            if not isinstance(value, str):
                return {}, "%s must be a string" % alias
            resolved[field] = value.strip()
            break
    return resolved, ""


def _worker(value):
    value = (value or "").strip()
    if "\\" in value:
        value = value.rsplit("\\", 1)[-1]
    return value


def derive_working_branch(base_branch, worker, ticket):
    values = tuple((value or "").strip() for value in (
        base_branch, _worker(worker), ticket))
    if not all(values) or any(_UNSAFE_BRANCH_COMPONENT.search(value)
                              for value in values):
        return ""
    return "_".join(values)


def resolve_startup_config(ticket, explicit, defaults=None,
                           current_branch="", user_name=""):
    """Resolve CLI values over repository defaults and safe Git fallbacks."""
    defaults = dict(defaults or {})
    explicit = dict(explicit or {})

    def value(field, fallback=""):
        candidate = explicit.get(field)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
        default = defaults.get(field)
        if isinstance(default, str) and default.strip():
            return default.strip()
        return fallback.strip() if isinstance(fallback, str) else ""

    worker = _worker(value("worker", user_name))
    ticket_type = value("ticket_type").lower()
    base_branch = value("base_branch", current_branch)
    working_branch = value("working_branch") or derive_working_branch(
        base_branch, worker, ticket)
    return StartupConfig(
        worker=worker,
        ticket_type=ticket_type,
        requirement_source=value("requirement_source"),
        base_branch=base_branch,
        working_branch=working_branch,
        build_method=value("build_method"),
        ut_method=value("ut_method"),
        ut_command=value("ut_command"),
    )
