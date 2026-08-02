"""Validation for the test-only lean workflow exit pointer."""

from collections.abc import Mapping
import hashlib
import ntpath
import os
import posixpath
import re
import time

from ..state_store import (
    ProjectStateLock,
    _replace_with_retry,
    atomic_write_json,
    remove_with_retry,
    safe_read_json,
)


_SNAPSHOT_NAME = re.compile(r"flow-[0-9]+(?:-[0-9]+)?\.json\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


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


def _read_bytes(path):
    with open(path, "rb") as stream:
        return stream.read()


def _digest(data):
    return hashlib.sha256(data).hexdigest()


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
    state_sha = result.get("state_sha256")
    if not isinstance(state_sha, str) or not _SHA256.fullmatch(state_sha):
        return None
    try:
        if _digest(_read_bytes(snapshot)) != state_sha:
            return None
    except OSError:
        return None
    result["snapshot"] = canonical
    return result


def effective_exit_pointer(root, pointer_path, snapshot_dir, state_path):
    """Return a pointer that safely owns the current state bytes, if any."""
    pointer = valid_exit_pointer(root, pointer_path, snapshot_dir)
    if pointer is None or not os.path.isfile(state_path):
        return pointer
    state_sha = pointer.get("state_sha256")
    if not isinstance(state_sha, str):
        return None
    try:
        return pointer if _digest(_read_bytes(state_path)) == state_sha else None
    except OSError:
        return None


def _write_exclusive(path, data):
    descriptor = None
    created = False
    try:
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(data)
            stream.flush()
            try:
                os.fsync(stream.fileno())
            except OSError:
                pass
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        if created:
            try:
                os.unlink(path)
            except OSError:
                pass
        raise


def exclusive_backup_bytes(path, raw, label):
    """Publish immutable recovery bytes without ever replacing a prior copy."""
    if not isinstance(raw, bytes):
        raise TypeError("backup data must be bytes")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = "%s.%s.%s.%s.%s" % (
        path, label, stamp, os.getpid(), time.time_ns())
    candidate = base
    suffix = 2
    while True:
        try:
            _write_exclusive(candidate, raw)
            return candidate
        except FileExistsError:
            candidate = "%s.%s" % (base, suffix)
            suffix += 1


def archive_file_exclusive(path, label, backup_base=None):
    """Copy one control file to an immutable backup, then remove the source."""
    raw = _read_bytes(path)
    backup = exclusive_backup_bytes(backup_base or path, raw, label)
    remove_with_retry(path)
    return backup


def _relative(root, path):
    return os.path.relpath(path, root).replace("\\", "/")


def _snapshot_path(snapshot_dir, stamp):
    os.makedirs(snapshot_dir, exist_ok=True)
    base = os.path.join(snapshot_dir, "flow-%s.json" % stamp)
    candidate = base
    suffix = 2
    while os.path.exists(candidate):
        candidate = os.path.join(
            snapshot_dir, "flow-%s-%s.json" % (stamp, suffix))
        suffix += 1
    return candidate


def _existing_snapshot(root, pointer_path, snapshot_dir):
    pointer = valid_exit_pointer(root, pointer_path, snapshot_dir)
    if pointer is not None:
        path = os.path.join(root, *pointer["snapshot"].split("/"))
        return path
    try:
        names = tuple(
            name for name in os.listdir(snapshot_dir)
            if is_exit_snapshot_name(name))
    except OSError:
        names = ()
    if not names:
        return ""
    name = max(names, key=lambda value: tuple(
        int(item) for item in re.findall(r"[0-9]+", value)))
    return os.path.join(snapshot_dir, name)


def _publish_pointer(
        root, state_path, pointer_path, snapshot_dir, snapshot, stamp,
        data, reason, pointer_writer):
    pointer = {
        "status": "exited",
        "snapshot": _relative(root, snapshot),
        "state_sha256": _digest(data),
        "exited_at_ns": stamp,
    }
    if reason:
        pointer["reason"] = reason
    pointer_writer(pointer_path, pointer)
    effective = effective_exit_pointer(
        root, pointer_path, snapshot_dir, state_path)
    if effective is None:
        raise OSError("exit pointer validation failed")
    return effective


def _release_once(
        root, state_path, pointer_path, snapshot_dir, reason, clock_ns,
        move_state, snapshot_writer, pointer_writer, move_active):
    pointer = effective_exit_pointer(
        root, pointer_path, snapshot_dir, state_path)
    if pointer is not None:
        return pointer
    stamp = clock_ns()
    if os.path.isfile(state_path):
        snapshot = _snapshot_path(snapshot_dir, stamp)
        if move_active:
            move_state(state_path, snapshot)
            data = _read_bytes(snapshot)
        else:
            data = _read_bytes(state_path)
            snapshot_writer(snapshot, data)
    else:
        snapshot = _existing_snapshot(root, pointer_path, snapshot_dir)
        if not snapshot:
            raise OSError("no active state or recoverable snapshot")
        data = _read_bytes(snapshot)
    return _publish_pointer(
        root, state_path, pointer_path, snapshot_dir, snapshot, stamp,
        data, reason, pointer_writer)


def release_flow_state(
        root, state_path, pointer_path, snapshot_dir, reason="",
        clock_ns=None, move_state=None, snapshot_writer=None,
        pointer_writer=None):
    """Release active control into one validated snapshot/pointer model."""
    clock_ns = clock_ns or time.time_ns
    move_state = move_state or _replace_with_retry
    snapshot_writer = snapshot_writer or _write_exclusive
    pointer_writer = pointer_writer or atomic_write_json
    try:
        with ProjectStateLock(root, timeout=0):
            return _release_once(
                root, state_path, pointer_path, snapshot_dir, reason,
                clock_ns, move_state, snapshot_writer, pointer_writer, True)
    except (Exception, SystemExit):
        return _release_once(
            root, state_path, pointer_path, snapshot_dir, reason,
            clock_ns, move_state, snapshot_writer, pointer_writer, False)
