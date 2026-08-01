"""Test-only protocol and platform adapter for the lean Hook router."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
import hashlib
import json
import locale
import os
import re
import tempfile
import time
from types import SimpleNamespace

from ..application.hooks.lean_events import (
    LeanHookPorts,
    handle_lean_hook_event,
)
from ..application.hooks.models import HookResponse
from ..guard.safety_kernel import SafetyContext, decide_pretool
from ..orchestration import CapabilityAttempt, FlowState
from ..state_store import (
    ProjectStateLock,
    _replace_with_retry,
    atomic_write_json,
    safe_read_json,
    update_json,
)


SUMMARY_BUDGET = 1200


def _empty_paths(_payload):
    return ()


@dataclass(frozen=True)
class LeanHookFactPorts:
    """Exact repository facts supplied by the eventual production adapter."""

    staged_files: object = _empty_paths
    commit_files: object = _empty_paths
    initial_dirty: object = _empty_paths
    current_dirty_fingerprints: object = _empty_paths
    safe_write_targets: object = _empty_paths


def _decode_json(raw):
    if isinstance(raw, Mapping):
        return raw
    if isinstance(raw, str):
        value = json.loads(raw or "{}")
        if not isinstance(value, Mapping):
            raise ValueError("Hook payload must be an object")
        return value
    if not isinstance(raw, bytes):
        raise ValueError("Hook payload must be JSON bytes")
    encodings = ["utf-8-sig"]
    for encoding in (locale.getpreferredencoding(False), "gb18030"):
        normalized = str(encoding or "").lower().replace("-", "")
        if normalized and all(
                normalized != item.lower().replace("-", "")
                for item in encodings):
            encodings.append(encoding)
    error = None
    for encoding in encodings:
        try:
            value = json.loads(raw.decode(encoding, errors="strict") or "{}")
            if not isinstance(value, Mapping):
                raise ValueError("Hook payload must be an object")
            return value
        except (UnicodeDecodeError, LookupError, json.JSONDecodeError,
                ValueError) as exc:
            error = exc
    raise ValueError("Hook JSON could not be decoded: %s" % error)


def _prompt_event(event):
    return isinstance(event, str) and re.sub(
        r"[ _-]+", "", event).casefold() in {
            "userprompt", "userpromptsubmit",
        }


def _explicit_exit(text):
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


def _clip(value, maximum=240):
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return text if len(text) <= maximum else text[:maximum - 1] + "…"


def _brief_list(values, maximum, render):
    rendered = [render(value) for value in values[:maximum]]
    omitted = len(values) - len(rendered)
    if omitted:
        rendered.append("另有 %s 项" % omitted)
    return "；".join(rendered) or "none"


class LeanHookAdapter:
    """Compose lean Hook routing while treating adapter failures as ordinary."""

    def __init__(
            self, root, marker_root=None, fact_ports=None, event_sink=None,
            clock_ns=None, move_state=None, snapshot_writer=None,
            pointer_writer=None, local_marker_root=None):
        self.root = os.path.abspath(root)
        self.state_path = os.path.join(self.root, ".mae-flow.json")
        self.pointer_path = os.path.join(self.root, ".mae-flow.json.exited")
        self.events_path = os.path.join(
            self.root, ".mae-flow-work", "lean-hook-user-events.json")
        self.snapshot_dir = os.path.join(
            self.root, ".mae-flow-work", "exited")
        self.marker_root = marker_root or os.path.join(
            tempfile.gettempdir(), "mae-flow-lean-hook-sessions")
        self.local_marker_root = local_marker_root or os.path.join(
            self.root, ".mae-flow-work", ".lean-hook-sessions")
        self.facts = fact_ports or LeanHookFactPorts()
        self.event_sink = event_sink or self._append_user_event
        self.clock_ns = clock_ns or time.time_ns
        self.move_state = move_state or _replace_with_retry
        self.snapshot_writer = snapshot_writer or self._write_snapshot_bytes
        self.pointer_writer = pointer_writer or atomic_write_json

    def _valid_pointer(self):
        pointer, error = safe_read_json(self.pointer_path)
        if error or not isinstance(pointer, Mapping):
            return None
        relative = pointer.get("snapshot")
        if pointer.get("status") != "exited" or not isinstance(relative, str):
            return None
        normalized = relative.replace("\\", "/")
        if not normalized or normalized.startswith(("/", "../")):
            return None
        snapshot = os.path.abspath(os.path.join(
            self.root, *normalized.split("/")))
        try:
            if os.path.commonpath((self.root, snapshot)) != self.root:
                return None
        except ValueError:
            return None
        return pointer if os.path.isfile(snapshot) else None

    def _runtime(self):
        if self._valid_pointer() is not None:
            return SimpleNamespace(mode="inactive"), None
        if not os.path.isfile(self.state_path):
            return SimpleNamespace(mode="inactive"), None
        raw, error = safe_read_json(self.state_path)
        if error:
            return SimpleNamespace(mode="corrupt"), None
        try:
            state = FlowState.from_dict(raw)
        except (TypeError, ValueError):
            return SimpleNamespace(mode="corrupt"), None
        return SimpleNamespace(mode="flow", flow=state), state

    def _claim_session_marker(self, root, identity):
        marker = os.path.join(root, identity + ".seen")
        try:
            os.makedirs(root, exist_ok=True)
            if os.path.isfile(marker):
                return False
            with open(marker, "x", encoding="utf-8", newline="\n"):
                pass
            return True
        except FileExistsError:
            return False if os.path.isfile(marker) else None
        except OSError:
            return False if os.path.isfile(marker) else None

    def _session_due(self, payload, state):
        session = payload.get("session_id") or payload.get("sessionId")
        if not isinstance(session, str) or not session:
            session = "cursor\0%s\0%s\0%s\0%s" % (
                state.ticket,
                state.phase.value,
                state.current_cp,
                state.status,
            )
        identity = hashlib.sha256(
            (self.root + "\0" + session).encode(
                "utf-8", errors="replace")).hexdigest()
        primary = self._claim_session_marker(self.marker_root, identity)
        if primary is not None:
            return primary
        fallback = self._claim_session_marker(
            self.local_marker_root, identity)
        return bool(fallback)

    def _resume(self, state, payload):
        if state is None or not self._session_due(payload, state):
            return HookResponse()
        artifacts = _brief_list(
            state.artifacts,
            2,
            lambda item: "%s=%s" % (
                _clip(item[0], 24), _clip(item[1], 100)),
        )
        risks = _brief_list(
            state.risks, 2, lambda risk: _clip(risk, 100))
        lines = [
            "[mae-flow] Recovery context",
            "Mode: %s" % state.path.value,
            "Phase: %s" % state.phase.value,
            "CP: %s" % (_clip(state.current_cp, 100) or "none"),
            "Artifacts: %s" % artifacts,
            "Unresolved risks: %s" % risks,
        ]
        if state.capabilities:
            fact = state.capabilities[-1]
            lines.append(
                "Last capability: %s | source=%s | environment=%s | "
                "outcome=%s | summary=%s" % (
                    _clip(fact.kind, 30),
                    _clip(fact.source_revision, 50),
                    _clip(fact.environment_revision, 50),
                    _clip(fact.outcome, 50),
                    _clip(fact.summary, 130),
                ))
        else:
            lines.append("Last capability: none")
        summary = "\n".join(lines) + "\n"
        if len(summary) > SUMMARY_BUDGET:
            summary = "\n".join(lines[:4] + lines[-1:]) + "\n"
        return HookResponse(stdout=summary)

    def _append_user_event(self, event, payload):
        row = {
            "event": event,
            "payload": dict(payload),
            "captured_at_ns": self.clock_ns(),
        }

        def append(current):
            rows = current if isinstance(current, list) else []
            rows.append(row)
            return rows[-20:]

        update_json(
            self.events_path,
            append,
            default=[],
            project_root=self.events_path,
            recover_corrupt=True,
        )

    def _record_event(self, event, payload):
        try:
            self.event_sink(event, payload)
        except (Exception, SystemExit):
            pass

    def _fact_paths(self, port, payload):
        try:
            value = port(payload)
            return tuple(value or ())
        except (Exception, SystemExit):
            return ()

    def _pretool(self, state, payload):
        if state is None:
            return HookResponse(
                exit_code=2,
                stderr=(
                    "[mae-flow] Delivery is blocked because the exact "
                    "manifest state is unavailable.\n"),
            )
        context = SafetyContext(
            state=state,
            repository_root=self.root,
            staged_files=self._fact_paths(self.facts.staged_files, payload),
            commit_files=self._fact_paths(self.facts.commit_files, payload),
            initial_dirty=self._fact_paths(self.facts.initial_dirty, payload),
            current_dirty_fingerprints=self._fact_paths(
                self.facts.current_dirty_fingerprints, payload),
            safe_write_targets=self._fact_paths(
                self.facts.safe_write_targets, payload),
        )
        decision = decide_pretool(
            context,
            payload.get("tool_name", ""),
            payload.get("tool_input", {}),
        )
        if decision.allow:
            return HookResponse()
        return HookResponse(
            exit_code=2,
            stderr="[mae-flow] %s\n" % (decision.message or decision.rule),
        )

    def _update_state(self, mutate):
        with ProjectStateLock(self.root):
            raw, error = safe_read_json(self.state_path)
            if error or raw is None:
                raise ValueError(error or "active state is absent")
            state = FlowState.from_dict(raw)
            atomic_write_json(self.state_path, mutate(state).to_dict())

    def _posttool(self, payload):
        raw = payload.get("capability_fact")
        fields = {
            "kind", "source_revision", "environment_revision", "outcome",
            "summary",
        }
        if not isinstance(raw, Mapping) or set(raw) != fields:
            return HookResponse()
        if not all(isinstance(raw[field], str) for field in fields):
            return HookResponse()
        fact = CapabilityAttempt(
            raw["kind"], raw["source_revision"],
            raw["environment_revision"], raw["outcome"], raw["summary"])
        self._update_state(lambda state: replace(
            state, capabilities=(state.capabilities + (fact,))[-20:]))
        return HookResponse()

    def _existing_snapshot(self):
        pointer = self._valid_pointer()
        if pointer is not None:
            relative = pointer["snapshot"]
            path = os.path.join(self.root, *relative.split("/"))
            return relative, path, pointer
        try:
            names = sorted(
                name for name in os.listdir(self.snapshot_dir)
                if name.endswith(".json"))
        except OSError:
            names = []
        if not names:
            return "", "", None
        path = os.path.join(self.snapshot_dir, names[-1])
        return self._relative(path), path, None

    def _relative(self, path):
        return os.path.relpath(path, self.root).replace("\\", "/")

    def _snapshot_path(self):
        os.makedirs(self.snapshot_dir, exist_ok=True)
        stamp = self.clock_ns()
        snapshot = os.path.join(self.snapshot_dir, "flow-%s.json" % stamp)
        suffix = 2
        while os.path.exists(snapshot):
            snapshot = os.path.join(
                self.snapshot_dir, "flow-%s-%s.json" % (stamp, suffix))
            suffix += 1
        return snapshot, stamp

    def _write_snapshot_bytes(self, path, data):
        descriptor = None
        try:
            descriptor = os.open(
                path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
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
            try:
                os.unlink(path)
            except OSError:
                pass
            raise

    def _write_pointer(self, snapshot, stamp):
        data = {
            "status": "exited",
            "snapshot": self._relative(snapshot),
            "exited_at_ns": stamp,
        }
        self.pointer_writer(self.pointer_path, data)
        if self._valid_pointer() is None:
            raise OSError("exit pointer validation failed")
        return data

    def _normal_release(self):
        with ProjectStateLock(self.root, timeout=0):
            pointer = self._valid_pointer()
            if pointer is not None:
                return pointer
            if not os.path.exists(self.state_path):
                relative, _path, pointer = self._existing_snapshot()
                if pointer is not None:
                    return pointer
                if not relative:
                    raise OSError("no active state or recoverable snapshot")
                return self._write_pointer(_path, self.clock_ns())

            snapshot, stamp = self._snapshot_path()
            self.move_state(self.state_path, snapshot)
            return self._write_pointer(snapshot, stamp)

    def _fallback_release(self):
        pointer = self._valid_pointer()
        if pointer is not None:
            return pointer
        if os.path.isfile(self.state_path):
            with open(self.state_path, "rb") as stream:
                original = stream.read()
            snapshot, stamp = self._snapshot_path()
            self.snapshot_writer(snapshot, original)
        else:
            _relative, snapshot, _pointer = self._existing_snapshot()
            if not snapshot:
                raise OSError("no active state or recoverable snapshot")
            stamp = self.clock_ns()
        return self._write_pointer(snapshot, stamp)

    def _release_takeover(self):
        try:
            return self._normal_release()
        except (Exception, SystemExit):
            return self._fallback_release()

    def handle(self, event, raw_input):
        """Handle one raw Hook invocation and return protocol output."""
        try:
            raw = raw_input() if callable(raw_input) else raw_input
            payload = _decode_json(raw)
        except (Exception, SystemExit):
            return HookResponse()

        if _prompt_event(event) and _explicit_exit(payload.get("prompt")):
            try:
                self._release_takeover()
            except (Exception, SystemExit) as exc:
                return HookResponse(
                    exit_code=2,
                    stderr=(
                        "[mae-flow] exit could not release workflow control "
                        "(%s); retry the same exit request.\n"
                        % type(exc).__name__),
                )
            self._record_event(event, payload)
            return HookResponse()

        try:
            runtime, state = self._runtime()
            if _prompt_event(event) and runtime.mode in ("flow", "corrupt"):
                self._record_event(event, payload)
            ports = LeanHookPorts(
                resume=lambda value: self._resume(state, value),
                prompt=lambda unused_value: HookResponse(),
                pretool=lambda value: self._pretool(state, value),
                posttool=self._posttool,
                inactive=lambda unused_event, unused_payload: HookResponse(),
            )
            return handle_lean_hook_event(event, payload, runtime, ports)
        except (Exception, SystemExit):
            return HookResponse()
