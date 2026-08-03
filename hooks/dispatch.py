#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bounded, fail-open process boundary for the lean Mae-Flow Hooks."""

import json
import locale
import os
import shlex
import sys
import tempfile
import threading
import time


HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.abspath(os.path.join(HERE, "..", "scripts"))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from mae_flow_core import find_project_root
from mae_flow_core.adapters.lean_hook import (
    LeanHookAdapter,
    LeanHookFactPorts,
)
from mae_flow_core.adapters.hook_git_facts import (
    head_commit_files,
    head_sha,
    git_text,
    push_destination_sha,
    push_commit_files as _push_commit_files,
    staged_files,
)


for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


LOG = os.path.join(tempfile.gettempdir(), "mae-flow-hook.log")
WATCHDOG_SECS = 12
STDIN_SECS = 3
_T0 = time.time()
_INPUT_ENCODING = ""
_STDIN_THREAD = None


def _log(message):
    """Best-effort UTF-8 log append that also works on Windows."""
    try:
        try:
            if os.path.getsize(LOG) > 5 * 1024 * 1024:
                os.replace(LOG, LOG + ".old")
        except OSError:
            pass
        with open(LOG, "a", encoding="utf-8") as stream:
            stream.write(
                "%s pid=%s %s\n" % (
                    time.strftime("%Y-%m-%d %H:%M:%S"),
                    os.getpid(),
                    message,
                ))
    except Exception:
        pass


def _arm_watchdog():
    def force_allow():
        _log("WATCHDOG timeout(%ss) - force exit 0(fail-open)" % WATCHDOG_SECS)
        os._exit(0)

    timer = threading.Timer(WATCHDOG_SECS, force_allow)
    timer.daemon = True
    timer.start()


def _persist_codeagent_plugin_root():
    """Expose the Hook-only plugin root to later CodeAgent Bash calls."""
    target = os.environ.get("CODEAGENT3_ENV_FILE", "").strip()
    if not target:
        _log("CODEAGENT3_ENV_FILE unavailable; bin launcher remains primary")
        return
    root = os.environ.get("CODEAGENT3_PLUGIN_ROOT", "").strip() or os.path.abspath(
        os.path.join(HERE, ".."))
    try:
        with open(target, "a", encoding="utf-8", newline="\n") as stream:
            stream.write(
                "export CODEAGENT3_PLUGIN_ROOT=%s\n" % shlex.quote(root))
    except (OSError, UnicodeError) as exc:
        _log("CODEAGENT3_ENV_FILE write failed: %s" % type(exc).__name__)


def _decode_hook_json(raw):
    """Strictly decode host JSON as UTF-8, system text, or GB18030."""
    global _INPUT_ENCODING
    if isinstance(raw, str):
        _INPUT_ENCODING = getattr(sys.stdin, "encoding", "") or "text"
        return json.loads(raw or "{}")
    encodings = ["utf-8-sig"]
    preferred = locale.getpreferredencoding(False)
    for encoding in (preferred, "gb18030"):
        normalized = str(encoding or "").lower().replace("-", "")
        if normalized and all(
                normalized != item.lower().replace("-", "")
                for item in encodings):
            encodings.append(encoding)
    error = None
    for encoding in encodings:
        try:
            text = raw.decode(encoding, errors="strict")
            value = json.loads(text or "{}")
            _INPUT_ENCODING = encoding
            if encoding != "utf-8-sig":
                _log("stdin decoded with fallback encoding=" + encoding)
            return value
        except (UnicodeDecodeError, LookupError, json.JSONDecodeError) as exc:
            error = exc
    raise ValueError(
        "hook JSON cannot be decoded as UTF-8/system encoding: %s" % error)


def read_input():
    """Read one Hook payload without waiting indefinitely for host EOF."""
    box = {}

    def read():
        try:
            stream = getattr(sys.stdin, "buffer", sys.stdin)
            data = stream.readline()
            try:
                box["payload"] = _decode_hook_json(data)
                return
            except Exception:
                pass
            box["payload"] = _decode_hook_json(data + stream.read())
        except Exception as exc:
            box["payload"] = {}
            box["error"] = type(exc).__name__

    global _STDIN_THREAD
    thread = threading.Thread(target=read, daemon=True)
    thread.start()
    thread.join(STDIN_SECS)
    _STDIN_THREAD = thread
    if "payload" not in box:
        _log("stdin read timeout(%ss) - empty payload" % STDIN_SECS)
        return {}
    if box.get("error"):
        _log("stdin invalid - fail-open (%s)" % box["error"])
    return box["payload"]


def _chdir_root(payload):
    base = payload.get("cwd") if isinstance(payload, dict) else ""
    root = find_project_root(base or os.getcwd())
    try:
        if root != os.getcwd():
            _log("chdir project root: " + root)
        os.chdir(root)
    except Exception:
        pass


def _lean_adapter():
    root = os.path.abspath(os.getcwd())
    facts = LeanHookFactPorts(
        staged_files=lambda unused_payload: staged_files(root),
        commit_files=lambda payload: _push_commit_files(root, payload),
        head_sha=lambda payload: head_sha(root, payload),
        destination_sha=lambda payload: push_destination_sha(root, payload),
        head_commit_files=lambda payload: head_commit_files(root, payload),
        current_branch=lambda unused_payload: git_text(
            root, ("branch", "--show-current")),
    )
    return LeanHookAdapter(root, fact_ports=facts)


def _finish(exit_code):
    if _STDIN_THREAD is not None and _STDIN_THREAD.is_alive():
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(exit_code if isinstance(exit_code, int) else 0)
    raise SystemExit(exit_code if isinstance(exit_code, int) else 0)


def main(argv=None):
    arguments = sys.argv if argv is None else argv
    event = arguments[1] if len(arguments) > 1 else ""
    normalized = "".join(
        character for character in str(event)
        if character not in " _-"
    ).casefold()
    if normalized in {"stop", "subagentstop"}:
        raise SystemExit(0)
    if normalized == "sessionstart":
        _persist_codeagent_plugin_root()
    _arm_watchdog()
    _log("start " + event)
    exit_code = 0
    try:
        payload = read_input()
        _chdir_root(payload)
        response = _lean_adapter().handle(event, payload)
        if response.stdout:
            print(response.stdout, end="")
        if response.stderr:
            print(response.stderr, end="", file=sys.stderr)
        exit_code = response.exit_code
    except SystemExit as error:
        exit_code = error.code if isinstance(error.code, int) else 0
    except Exception as error:
        _log("EXC %s: %s" % (type(error).__name__, error))
        exit_code = 0
    _log(
        "end %s rc=%s %dms" % (
            event, exit_code, int((time.time() - _T0) * 1000)))
    _finish(exit_code)


if __name__ == "__main__":
    main()
