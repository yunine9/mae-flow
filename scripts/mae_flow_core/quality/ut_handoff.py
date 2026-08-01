"""Append-only local construction notes and final UT Skill context."""

import os
from pathlib import Path


def _text(value, field, allow_empty=False):
    if not isinstance(value, str):
        raise TypeError("%s must be natural-language text" % field)
    if not allow_empty and not value:
        raise ValueError("%s must not be empty" % field)
    return value


def _path_text(value, field):
    try:
        path = os.fspath(value)
    except TypeError as exc:
        raise TypeError("%s must be a path" % field) from exc
    if not isinstance(path, str) or not path:
        raise ValueError("%s must be a non-empty text path" % field)
    if "\n" in path or "\r" in path:
        raise ValueError("%s must be a single-line path" % field)
    return path


def _normalized_entry(entry):
    normalized = _text(entry, "entry", allow_empty=True).replace(
        "\r\n", "\n").replace("\r", "\n")
    return normalized if normalized.endswith("\n") else normalized + "\n"


def append_ut_handoff(path, entry):
    """Append unconstrained CP prose as UTF-8/LF without consulting Git.

    The prose can record incremental testable behavior, seams or extracted
    deterministic logic, stable framework boundaries not to mock, and actual
    implementation deviations.  None is a required field or heading.
    """
    target = Path(_path_text(path, "handoff path"))
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = _normalized_entry(entry).encode("utf-8")
    prefix = b""
    with target.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell():
            stream.seek(-1, os.SEEK_END)
            final_byte = stream.read(1)
            if final_byte == b"\r":
                prefix = b"\n"
            elif final_byte != b"\n":
                prefix = b"\n"
        stream.write(prefix + payload)


def _diff_paths(values):
    if isinstance(values, (str, bytes)):
        raise TypeError("diff_paths must be an iterable of paths")
    try:
        raw_paths = tuple(values)
    except TypeError as exc:
        raise TypeError("diff_paths must be iterable") from exc
    return tuple(
        _path_text(value, "diff path")
        for value in raw_paths
    )


def _artifact_path_line(label, value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return "%s path: not provided; continue with available context." % label
    return "%s path (exact): %s" % (label, _path_text(value, label + " path"))


def render_ut_context(spec_path, story_path, handoff_text, diff_paths):
    """Render facts and ownership for the final, self-contained UT action."""
    spec_line = _artifact_path_line("Spec", spec_path)
    story_line = _artifact_path_line("Story", story_path)
    handoff = _text(handoff_text, "handoff_text", allow_empty=True)
    paths = _diff_paths(diff_paths)
    handoff_section = (
        handoff
        if handoff
        else "No construction handoff text was recorded; continue from the final implementation."
    )
    diff_section = (
        "\n".join("- " + path for path in paths)
        if paths
        else "No paths are present in the final diff; continue with the supplied context."
    )
    return "\n".join((
        spec_line,
        story_line,
        "",
        "Cumulative construction handoff:",
        handoff_section,
        "",
        "Final diff paths:",
        diff_section,
        "",
        "The cumulative construction handoff is historical coverage guidance only; "
        "it may be outdated and is not an authority or deviation baseline.",
        "Treat the final implementation and final diff as authoritative.",
        "Review coverage against them and compare with the confirmed Spec and Story "
        "when provided.",
        "The UT Skill owns the complete action: write UT, compile UT, and run UT.",
        "Do not prescribe a language or test framework output format.",
        "Do not require mocks of a database connection or stable execution framework; "
        "prioritize directly testable business query conditions, mapping, and other "
        "deterministic logic.",
    )) + "\n"
