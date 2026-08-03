"""Small Chain-specific recovery helpers for the lean Hook adapter."""

import hashlib
import os
from types import SimpleNamespace

from ..application.hooks.models import HookResponse
from ..cli_commands.chain_workflow import (
    POINTER_RELATIVE,
    load_active_chain,
)


def load_chain_runtime(root):
    pointer = os.path.join(root, *POINTER_RELATIVE.split("/"))
    if not os.path.isfile(pointer):
        return None, None
    try:
        state_path, chain = load_active_chain(root)
    except (OSError, TypeError, ValueError):
        return SimpleNamespace(mode="corrupt", owner="chain"), None
    return SimpleNamespace(
        mode="chain", chain=chain, state_path=state_path), chain


def _clip(value, maximum):
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return text if len(text) <= maximum else text[:maximum - 1] + "…"


def resume_chain(
        root, state, payload, marker_root, local_marker_root, claim_marker):
    session = payload.get("session_id") or payload.get("sessionId")
    if not isinstance(session, str) or not session:
        session = "chain\0%s\0%s" % (state.ticket, state.status)
    identity = hashlib.sha256(
        (root + "\0" + session).encode(
            "utf-8", errors="replace")).hexdigest()
    primary = claim_marker(marker_root, identity)
    if primary is False:
        return HookResponse()
    if primary is None and not claim_marker(local_marker_root, identity):
        return HookResponse()
    repositories = sum(
        1 for item in state.records if item.kind == "repository")
    questions = sum(1 for item in state.records if item.kind == "question")
    return HookResponse(stdout="\n".join((
        "[mae-flow] Chain recovery context",
        "Ticket: %s" % _clip(state.ticket, 100),
        "Request: %s" % _clip(state.request, 240),
        "Status: %s" % state.status,
        "Repositories: %s" % repositories,
        "Questions: %s" % questions,
        "Document: %s" % _clip(state.document_path, 200),
        "",
    )))
