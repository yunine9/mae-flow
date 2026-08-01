#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test-only process boundary for the lean Hook adapter."""

import argparse
import os
import sys


SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.adapters.lean_hook import LeanHookAdapter  # noqa: E402


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event")
    parser.add_argument("--root", required=True)
    parser.add_argument("--marker-root")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    response = LeanHookAdapter(
        args.root,
        marker_root=args.marker_root,
    ).handle(args.event, stream.read)
    if response.stdout:
        print(response.stdout, end="")
    if response.stderr:
        print(response.stderr, end="", file=sys.stderr)
    return response.exit_code


if __name__ == "__main__":
    sys.exit(main())
