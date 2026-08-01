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


def _inside(parent, child):
    try:
        return os.path.commonpath((parent, child)) == parent
    except ValueError:
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
    if os.path.islink(snapshot) or not os.path.isfile(snapshot):
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
