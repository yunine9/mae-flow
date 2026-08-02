"""Lean command-line surface for the Mae-Flow production driver."""

import argparse
import os
import sys


class MFParser(argparse.ArgumentParser):
    """Turn argument errors into copyable lean-runtime guidance."""

    def error(self, message):
        me = os.path.abspath(sys.argv[0])
        print("[mae-flow] 参数错误: " + message, file=sys.stderr)
        print(
            "正确用法(高频命令,直接复制):\n"
            '  python "%s" current\n'
            '  python "%s" start --ticket REQ-123 --path focused '
            '--pace continuous\n'
            '  python "%s" decision startup-confirmed "用户的自然语言决定"\n'
            "其余生产命令: advance|capability-record|manifest|exit|"
            "ut|codecheck|grill|story|chain；内部轻量建议: lightcheck。\n"
            "旧状态只用 migrate-flow 单向迁移。" % (me, me, me),
            file=sys.stderr,
        )
        self.exit(2)


def parse_args(argv=None):
    parser = MFParser(prog="mae-flow")
    sub = parser.add_subparsers(dest="cmd", required=True)

    start = sub.add_parser("start")
    start.add_argument("--ticket", required=True)
    start.add_argument("--path", choices=["full", "focused"], required=True)
    start.add_argument(
        "--pace", choices=["continuous", "staged"], required=True)
    start.add_argument("--request", default="")
    start.add_argument("--moonlight", action="store_true")
    start.add_argument("--business-file", action="append", default=[])
    start.add_argument("--allow-commit", action="store_true")
    start.add_argument("--allow-push", action="store_true")

    advance = sub.add_parser("advance")
    advance.add_argument("event")
    advance.add_argument("--decision", default="")
    advance.add_argument("--key", default="")

    decision = sub.add_parser("decision")
    decision.add_argument("event")
    decision.add_argument("text")
    decision.add_argument("--key", default="")

    capability_record = sub.add_parser("capability-record")
    capability_record.add_argument(
        "kind", choices=[
            "build", "ut", "codecheck", "reviewer", "grill", "story"])
    capability_record.add_argument(
        "outcome", choices=[
            "returned", "failed-to-start", "timed-out", "not-observed"])
    capability_record.add_argument("--source", required=True)
    capability_record.add_argument("--environment", required=True)
    capability_record.add_argument("--summary", default="")

    manifest = sub.add_parser("manifest")
    manifest.add_argument("--file", action="append", required=True)
    manifest.add_argument("--adopt-dirty", action="append", default=[])
    manifest.add_argument("--conditional-document", action="append", default=[])
    manifest.add_argument("--moonlight-refresh", action="store_true")
    manifest.add_argument("--allow-commit", action="store_true")
    manifest.add_argument("--allow-push", action="store_true")
    manifest.add_argument("--checkpoint")
    manifest.add_argument("--final", action="store_true")
    manifest.add_argument("--commit-message")
    manifest.add_argument("--decision")
    manifest.add_argument("--remote")
    manifest.add_argument("--destination-ref")
    manifest.add_argument("--expected-destination-sha")
    manifest.add_argument("--new-branch", action="store_true")

    for toolbox_kind in ("ut", "codecheck", "grill", "story", "chain"):
        toolbox = sub.add_parser(toolbox_kind)
        toolbox.add_argument("--request", default="")
        toolbox.add_argument("--file", action="append", default=[])

    lightcheck = sub.add_parser("lightcheck")
    lightcheck.add_argument("--file", action="append", default=[])
    lightcheck.add_argument("--quiet", action="store_true")

    sub.add_parser("current")
    sub.add_parser(
        "migrate-flow",
        help="内部升级命令：安全地把 schema-v2 在途状态迁移为 lean schema-v3",
    )
    exit_command = sub.add_parser("exit")
    exit_command.add_argument("--reason")

    return parser.parse_args(argv)
