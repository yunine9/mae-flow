"""Production protocol and platform adapter for the lean Hook router."""

from collections.abc import Mapping
from dataclasses import dataclass
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
from ..application.hooks.capability_observation import (
    complete_git_posttool,
    reserve_git_pretool,
)
from ..application.hooks.models import HookResponse
from ..guard.command_policy import recursive_delete_facts
from ..guard.safety_kernel import (
    SafetyContext,
    decide_pretool,
    decide_stateless_pretool,
)
from ..orchestration import FlowState, flow_retry_options
from ..state_store import (
    ProjectStateLock,
    _replace_with_retry,
    atomic_write_json,
    safe_read_json,
    update_json,
)
from .hook_tool_inputs import apply_patch_targets
from .lean_exit import (
    effective_exit_pointer,
    explicit_exit,
    release_flow_state,
)


SUMMARY_BUDGET = 1200


def _empty_paths(_payload):
    return ()


@dataclass(frozen=True)
class LeanHookFactPorts:
    """Exact repository facts supplied at the production adapter boundary."""

    staged_files: object = _empty_paths
    commit_files: object = _empty_paths
    initial_dirty: object = _empty_paths
    current_dirty_fingerprints: object = _empty_paths
    safe_write_targets: object = _empty_paths
    task_owned_temp_dir: object = _empty_paths
    head_sha: object = _empty_paths
    destination_sha: object = _empty_paths
    head_commit_files: object = _empty_paths
    current_branch: object = _empty_paths


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


def _session_event(event):
    return isinstance(event, str) and re.sub(
        r"[ _-]+", "", event).casefold() == "sessionstart"


def _legacy_stop_event(event):
    return (
        isinstance(event, str)
        and bool(re.fullmatch(r"[A-Za-z _-]+", event))
        and re.sub(r"[ _-]+", "", event).casefold()
        in {"stop", "subagentstop"}
    )


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
    """Compose production lean Hook routing with bounded fail-open handling."""

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
        self.snapshot_writer = snapshot_writer
        self.pointer_writer = pointer_writer or atomic_write_json

    def _valid_pointer(self):
        return effective_exit_pointer(
            self.root, self.pointer_path, self.snapshot_dir, self.state_path)

    def _runtime(self):
        if self._valid_pointer() is not None:
            return SimpleNamespace(mode="direct"), None
        if os.path.isfile(self.state_path):
            raw, error = safe_read_json(self.state_path)
            if error:
                return SimpleNamespace(mode="corrupt"), None
            try:
                state = FlowState.from_dict(raw)
            except (TypeError, ValueError):
                return SimpleNamespace(mode="corrupt"), None
            return SimpleNamespace(mode="flow", flow=state), state
        return SimpleNamespace(mode="inactive"), None

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
        request = next((
            _clip(value, 240)
            for key, value in reversed(state.decisions)
            if key == "request.summary"
        ), "none")
        core_lines = [
            "[mae-flow] Recovery context",
            "Ticket: %s" % _clip(state.ticket, 100),
            "Request: %s" % request,
            "Mode: %s" % state.path.value,
            "Phase: %s" % state.phase.value,
            "CP: %s" % (_clip(state.current_cp, 100) or "none"),
        ]
        lines = core_lines + [
            "Artifacts: %s" % artifacts,
            "Unresolved risks: %s" % risks,
        ]
        if state.capabilities:
            fact = state.capabilities[-1]
            try:
                retry = flow_retry_options(state, fact.kind)
            except (TypeError, ValueError):
                retry_label = "unknown-do-not-retry"
            else:
                retry_label = (
                    "authorized-once-unconsumed"
                    if retry.allowed
                    else "needs-current-user-decision"
                )
            lines.append(
                "Last capability: %s | source=%s | environment=%s | "
                "outcome=%s | summary=%s | retry=%s" % (
                    _clip(fact.kind, 30),
                    _clip(fact.source_revision, 50),
                    _clip(fact.environment_revision, 50),
                    _clip(fact.outcome, 50),
                    _clip(fact.summary, 130),
                    retry_label,
                ))
        else:
            lines.append("Last capability: none")
        summary = "\n".join(lines) + "\n"
        if len(summary) > SUMMARY_BUDGET:
            summary = "\n".join(core_lines + lines[-1:]) + "\n"
        return HookResponse(stdout=summary)

    def _append_user_event(self, event, payload):
        captured_at_ns = self.clock_ns()
        try:
            with open(self.state_path, "rb") as stream:
                state_sha256 = hashlib.sha256(stream.read()).hexdigest()
        except OSError:
            state_sha256 = ""

        def append(current):
            rows = current if isinstance(current, list) else []
            identity = {
                "captured_at_ns": captured_at_ns,
                "event": event,
                "ordinal": len(rows),
                "payload": dict(payload),
                "state_sha256": state_sha256,
            }
            event_id = hashlib.sha256(json.dumps(
                identity,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8", errors="strict")).hexdigest()
            row = dict(identity, event_id=event_id)
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

    def _fact_text(self, port, payload):
        try:
            value = port(payload)
            return value if isinstance(value, str) else ""
        except (Exception, SystemExit):
            return ""

    def _git_facts(self, payload):
        return {
            "staged_files": self._fact_paths(self.facts.staged_files, payload),
            "commit_files": self._fact_paths(self.facts.commit_files, payload),
            "head_commit_files": self._fact_paths(
                self.facts.head_commit_files, payload),
            "head_sha": self._fact_text(self.facts.head_sha, payload),
            "destination_sha": self._fact_text(
                self.facts.destination_sha, payload),
        }

    def _pretool(self, state, payload):
        tool = payload.get("tool_name", "")
        tool_input = payload.get("tool_input", {})
        tool_input = apply_patch_targets(tool, tool_input)
        command = tool_input.get("command", "") if isinstance(
            tool_input, Mapping) else ""
        delete_targets = (
            recursive_delete_facts(command)
            if str(tool or "").casefold() == "bash"
            and isinstance(command, str)
            else ()
        )
        if delete_targets:
            tool_input = dict(tool_input)
            tool_input["recursive_delete_targets"] = delete_targets
        task_temp = self._fact_text(self.facts.task_owned_temp_dir, payload)
        if state is None:
            decision = decide_stateless_pretool(
                self.root, tool, tool_input, task_temp)
        else:
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
                task_owned_temp_dir=task_temp,
                current_branch=self._fact_text(
                    self.facts.current_branch, payload),
            )
            decision = decide_pretool(context, tool, tool_input)
        if decision.allow:
            reservation = reserve_git_pretool(
                payload, state, self._git_facts(payload), self._update_state)
            if reservation is not None:
                return reservation
            return HookResponse()
        return HookResponse(exit_code=2, stderr=(
            "[mae-flow] %s\n" % (decision.message or decision.rule)))

    def _update_state(self, mutate):
        with ProjectStateLock(self.root):
            raw, error = safe_read_json(self.state_path)
            if error or raw is None:
                raise ValueError(error or "active state is absent")
            state = FlowState.from_dict(raw)
            updated = mutate(state)
            atomic_write_json(self.state_path, updated.to_dict())
            return updated

    def _posttool(self, payload):
        git_result = complete_git_posttool(
            payload, self._git_facts(payload), self._update_state)
        if git_result is not None:
            return git_result
        return HookResponse()

    def _inactive(self, runtime, event, state):
        if event != "sessionstart":
            return HookResponse()
        if runtime.mode == "direct":
            return HookResponse(stdout=(
                "[mae-flow] Workflow exited; ordinary development is active.\n"))
        if runtime.mode == "corrupt":
            return HookResponse(stdout=(
                "[mae-flow] Workflow state is corrupt; safety gates fail "
                "open. Run current before recovery.\n"))
        if state is not None and state.status in {"complete", "exited"}:
            return HookResponse(stdout=(
                "[mae-flow] Workflow %s for ticket %s; no active gates.\n"
                % (state.status, state.ticket)))
        return HookResponse()

    def _release_takeover(self, reason=""):
        return release_flow_state(
            self.root,
            self.state_path,
            self.pointer_path,
            self.snapshot_dir,
            reason=reason,
            clock_ns=self.clock_ns,
            move_state=self.move_state,
            snapshot_writer=self.snapshot_writer,
            pointer_writer=self.pointer_writer,
        )

    def handle(self, event, raw_input):
        """Handle one raw Hook invocation and return protocol output."""
        if _legacy_stop_event(event):
            return HookResponse()
        try:
            raw = raw_input() if callable(raw_input) else raw_input
            payload = _decode_json(raw)
        except (Exception, SystemExit):
            return HookResponse()

        if _prompt_event(event) and explicit_exit(payload.get("prompt")):
            try:
                self._release_takeover(payload.get("prompt", ""))
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
            if runtime.mode == "corrupt" and _session_event(event):
                return self._inactive(runtime, "sessionstart", state)
            ports = LeanHookPorts(
                resume=lambda value: self._resume(state, value),
                prompt=lambda unused_value: HookResponse(),
                pretool=lambda value: self._pretool(state, value),
                posttool=self._posttool,
                inactive=lambda routed_event, unused_payload: self._inactive(
                    runtime, routed_event, state),
            )
            return handle_lean_hook_event(event, payload, runtime, ports)
        except (Exception, SystemExit):
            return HookResponse()
