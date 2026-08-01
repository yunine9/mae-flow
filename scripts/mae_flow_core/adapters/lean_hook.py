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
from ..foundation.git_intent import executes_git_commit_or_push
from ..guard.safety_kernel import SafetyContext, decide_pretool
from ..orchestration import CapabilityAttempt, FlowState
from ..state_store import (
    ProjectStateLock,
    _replace_with_retry,
    atomic_write_json,
    safe_read_json,
    update_json,
)


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


class LeanHookAdapter:
    """Compose lean Hook routing while treating adapter failures as ordinary."""

    def __init__(
            self, root, marker_root=None, fact_ports=None, event_sink=None,
            clock_ns=None):
        self.root = os.path.abspath(root)
        self.state_path = os.path.join(self.root, ".mae-flow.json")
        self.pointer_path = os.path.join(self.root, ".mae-flow.json.exited")
        self.events_path = os.path.join(
            self.root, ".mae-flow-work", "lean-hook-user-events.json")
        self.snapshot_dir = os.path.join(
            self.root, ".mae-flow-work", "exited")
        self.marker_root = marker_root or os.path.join(
            tempfile.gettempdir(), "mae-flow-lean-hook-sessions")
        self.facts = fact_ports or LeanHookFactPorts()
        self.event_sink = event_sink or self._append_user_event
        self.clock_ns = clock_ns or time.time_ns

    def _runtime(self):
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

    def _session_due(self, payload):
        session = payload.get("session_id") or payload.get("sessionId")
        if not isinstance(session, str) or not session:
            return True
        identity = hashlib.sha256(
            (self.root + "\0" + session).encode(
                "utf-8", errors="replace")).hexdigest()
        marker = os.path.join(self.marker_root, identity + ".seen")
        try:
            os.makedirs(self.marker_root, exist_ok=True)
            with open(marker, "x", encoding="utf-8", newline="\n"):
                pass
            return True
        except FileExistsError:
            return False
        except OSError:
            return True

    def _resume(self, state, payload):
        if state is None or not self._session_due(payload):
            return HookResponse()
        artifacts = ", ".join(
            "%s=%s" % (_clip(kind, 60), _clip(path))
            for kind, path in state.artifacts[:5]
        ) or "none"
        risks = "; ".join(_clip(risk) for risk in state.risks[:5]) or "none"
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
                    _clip(fact.kind, 60),
                    _clip(fact.source_revision, 100),
                    _clip(fact.environment_revision, 100),
                    _clip(fact.outcome, 100),
                    _clip(fact.summary),
                ))
        else:
            lines.append("Last capability: none")
        return HookResponse(stdout="\n".join(lines) + "\n")

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
            project_root=self.root,
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
        tool_input = payload.get("tool_input", {})
        command = (
            tool_input.get("command", "")
            if isinstance(tool_input, Mapping) else "")
        if (
                not decision.allow
                and decision.rule in {"git_commit", "git_publish"}
                and isinstance(command, str)
                and not executes_git_commit_or_push(command)):
            return HookResponse()
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
        pointer, error = safe_read_json(self.pointer_path)
        if not error and isinstance(pointer, Mapping):
            relative = pointer.get("snapshot")
            if isinstance(relative, str) and relative:
                path = os.path.join(self.root, *relative.split("/"))
                if os.path.isfile(path):
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

    def _release_takeover(self):
        with ProjectStateLock(self.root):
            if not os.path.exists(self.state_path):
                relative, _path, pointer = self._existing_snapshot()
                if pointer is not None:
                    return pointer
                data = {
                    "status": "exited",
                    "snapshot": relative,
                    "exited_at_ns": self.clock_ns(),
                }
                atomic_write_json(self.pointer_path, data)
                return data

            os.makedirs(self.snapshot_dir, exist_ok=True)
            stamp = self.clock_ns()
            snapshot = os.path.join(
                self.snapshot_dir, "flow-%s.json" % stamp)
            suffix = 2
            while os.path.exists(snapshot):
                snapshot = os.path.join(
                    self.snapshot_dir, "flow-%s-%s.json" % (stamp, suffix))
                suffix += 1
            _replace_with_retry(self.state_path, snapshot)
            data = {
                "status": "exited",
                "snapshot": self._relative(snapshot),
                "exited_at_ns": stamp,
            }
            atomic_write_json(self.pointer_path, data)
            return data

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
            except (Exception, SystemExit):
                pass
            self._record_event(event, payload)
            return HookResponse()

        try:
            runtime, state = self._runtime()
            if _prompt_event(event) and os.path.isfile(self.state_path):
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
