"""Privacy-safe diagnostics for intentional Hook policy blocks."""

import hashlib
import os
import re


_GATE_RULE_PATTERN = re.compile(
    r"^\[mae-flow-rule=([a-z0-9-]+)\]\r?\n?", re.I)


class HookBlockDiagnostics:
    """Carry private CLI metadata into one attributed Hook log record."""

    def __init__(self):
        self.gate_rule = ""

    def subprocess_environment(self):
        self.gate_rule = ""
        environment = dict(os.environ)
        environment["MAE_FLOW_HOOK_TRACE"] = "1"
        return environment

    def sanitize_stderr(self, stderr):
        """Remove the internal gate marker before stderr reaches the host."""
        text = str(stderr or "")
        prefix = "[mae-flow] " if text.startswith("[mae-flow] ") else ""
        body = text[len(prefix):]
        match = _GATE_RULE_PATTERN.match(body)
        if not match:
            return text
        self.gate_rule = match.group(1).lower()
        return prefix + body[match.end():]

    def log_pretool_decision(self, event, payload, response, log):
        """Attribute a block without persisting command or response text."""
        if event != "pretooluse" or response.exit_code != 2:
            return
        tool = str(payload.get("tool_name", "") or "unknown")
        fields = [
            "decision",
            "event=pretooluse",
            "tool=" + re.sub(r"[^A-Za-z0-9_.-]", "_", tool),
            "result=blocked",
            "source=mae-flow",
            "rule=" + re.sub(
                r"[^a-z0-9-]", "-", self.gate_rule or "hook-policy"),
        ]
        if tool == "Bash":
            command = str(
                (payload.get("tool_input") or {}).get("command", "") or "")
            fields.append(
                "command_sha256="
                + hashlib.sha256(command.encode("utf-8")).hexdigest())
        log(" ".join(fields))
