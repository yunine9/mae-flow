"""Validation for the test-only lean workflow exit pointer."""

from collections.abc import Mapping
import ntpath
import os
import posixpath
import re

from ..state_store import safe_read_json


_SNAPSHOT_NAME = re.compile(r"flow-[0-9]+(?:-[0-9]+)?\.json\Z")


def is_exit_snapshot_name(name):
    return bool(_SNAPSHOT_NAME.fullmatch(str(name or "")))


def explicit_exit(text):
    """Recognize an unambiguous natural-language workflow exit request."""
    if not isinstance(text, str):
        return False
    value = re.sub(r"\s+", " ", text).strip()
    if not value:
        return False
    if re.search(
            r"(?:[?？]|怎么|如何|能否|能不能|可以吗|会怎样|后会)",
            value, re.I):
        return False
    if re.search(r"(?:别|不要|不能|无需|不必)\s*(?:再)?(?:退出|停止|关闭)", value):
        return False
    if re.fullmatch(
            r"/mae-flow(?::mae-flow)?\s+(?:exit|direct)(?:\s+.*)?",
            value, re.I):
        return True
    chinese = re.fullmatch(
        r"(?:(?:请)(?:立即)?|我(?:现在)?(?:想|要|决定|需要)?|立即)?"
        r"(?:退出|停止|关闭)(?:使用)?\s*"
        r"(?:mae[- ]?flow|这个工作流|工作流)(?:吧|了)?"
        r"(?:[，,]\s*直接(?:开发|改代码))?[。！!]?",
        value,
        re.I,
    )
    stop_using = re.fullmatch(
        r"(?:我)?(?:现在)?不再(?:使用|走)\s*"
        r"(?:mae[- ]?flow|这个工作流|工作流)\s*(?:了)?[。！!]?",
        value,
        re.I,
    )
    english = re.fullmatch(
        r"(?:please\s+)?(?:exit|stop|disable)\s+"
        r"(?:mae[- ]?flow|this workflow)(?:\s+now)?[.!]?",
        value,
        re.I,
    )
    return bool(chinese or stop_using or english)


def _inside(parent, child):
    try:
        return os.path.commonpath((parent, child)) == parent
    except ValueError:
        return False


def _has_symlink_component(root, path):
    current = os.path.abspath(root)
    relative = os.path.relpath(path, current)
    for component in relative.split(os.sep):
        current = os.path.join(current, component)
        if os.path.islink(current):
            return True
    return False


def valid_exit_pointer(root, pointer_path, snapshot_dir):
    if os.path.islink(pointer_path):
        return None
    pointer, error = safe_read_json(pointer_path)
    if error or not isinstance(pointer, Mapping):
        return None
    relative = pointer.get("snapshot")
    if pointer.get("status") != "exited" or not isinstance(relative, str):
        return None

    normalized = relative.replace("\\", "/")
    drive, _unused_tail = ntpath.splitdrive(normalized)
    canonical = posixpath.normpath(normalized)
    expected_dir = os.path.relpath(snapshot_dir, root).replace("\\", "/")
    directory, name = posixpath.split(canonical)
    if (
            not normalized
            or drive
            or normalized.startswith("/")
            or canonical != normalized
            or directory != expected_dir
            or not is_exit_snapshot_name(name)):
        return None

    snapshot = os.path.join(root, *canonical.split("/"))
    if _has_symlink_component(root, snapshot) or not os.path.isfile(snapshot):
        return None
    real_root = os.path.normcase(os.path.realpath(root))
    real_dir = os.path.normcase(os.path.realpath(snapshot_dir))
    real_snapshot = os.path.normcase(os.path.realpath(snapshot))
    if not _inside(real_root, real_dir) or not _inside(
            real_dir, real_snapshot):
        return None
    result = dict(pointer)
    result["snapshot"] = canonical
    return result
