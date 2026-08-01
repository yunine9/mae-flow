#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test-only command harness for the lean orchestration engine."""

import argparse
import json
import os
import sys


SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.orchestration.guidance import render_guidance  # noqa: E402
from mae_flow_core.orchestration.models import (  # noqa: E402
    CommitPace,
    DeliveryPath,
    FlowState,
)
from mae_flow_core.orchestration.state_schema import (  # noqa: E402
    decode_flow_state,
    encode_flow_state,
)
from mae_flow_core.orchestration.transitions import (  # noqa: E402
    AdvanceRequest,
    advance_flow,
)


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, help="caller-owned state path")
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start")
    start.add_argument("ticket")
    start.add_argument("path", choices=[item.value for item in DeliveryPath])
    start.add_argument("pace", choices=[item.value for item in CommitPace])

    commands.add_parser("current")

    advance = commands.add_parser("advance")
    advance.add_argument("event")
    advance.add_argument("--key", default="")
    advance.add_argument("--value", default="")

    decision = commands.add_parser("decision")
    decision.add_argument("key")
    decision.add_argument("value")

    commands.add_parser("exit")
    return parser


def _load(path):
    with open(path, encoding="utf-8") as stream:
        return decode_flow_state(json.load(stream))


def _save(path, state):
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent):
        raise ValueError("state parent directory does not exist")
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(
            encode_flow_state(state), stream, ensure_ascii=False,
            indent=2, sort_keys=True)
        stream.write("\n")


def _execute(args):
    if args.command == "start":
        if os.path.exists(args.state):
            raise ValueError("state path already exists")
        state = FlowState.new(
            args.ticket, DeliveryPath(args.path), CommitPace(args.pace))
        _save(args.state, state)
        return state, "The lean flow started."

    state = _load(args.state)
    if args.command == "current":
        return state, "Current recovery context."
    if args.command == "decision":
        if not args.key.strip() or not args.value.strip():
            raise ValueError("decision key and value must be non-empty")
        state = state.with_decision(args.key.strip(), args.value.strip())
        _save(args.state, state)
        return state, "The natural-language decision was recorded."

    request = AdvanceRequest("exit") if args.command == "exit" else AdvanceRequest(
        args.event, args.key, args.value)
    result = advance_flow(state, request)
    _save(args.state, result.state)
    return result.state, result.reason


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        state, reason = _execute(args)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    print(reason)
    print(render_guidance(state), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
