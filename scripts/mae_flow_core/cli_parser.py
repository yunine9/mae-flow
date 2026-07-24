"""Command-line surface for the Mae-Flow driver.

Keeping the parser out of the state machine makes user-facing command growth
visible and prevents routing code from being buried under argparse plumbing.
"""

import argparse
import os
import sys


class MFParser(argparse.ArgumentParser):
    """Turn argument errors into copyable guidance for weaker models."""

    def error(self, message):
        me = os.path.abspath(sys.argv[0])
        print("[mae-flow] 参数错误: " + message, file=sys.stderr)
        print(
            "正确用法(高频三条,直接复制):\n"
            '  python "%s" current\n'
            '  python "%s" done --ack "用户原话" [--choice 值] [--set 键=值]\n'
            '  python "%s" init\n'
            "其余子命令: status|doctor|report|envcheck|skip|goto|unlock|template|"
            "agent-task|accept-risk|moonlight|action|messages|requirement-record|"
            "codecheck-scan|codecheck-record|approve-exemption|exit"
            "(用法见 current/exit 指令)。\n"
            "注意:子命令不带连字符(是 current 不是 --current);"
            "done 的 --set 可重复,值含空格要加引号。" % (me, me, me),
            file=sys.stderr)
        sys.exit(2)


def parse_args(argv=None):
    parser = MFParser(prog="mae-flow")
    sub = parser.add_subparsers(dest="cmd", required=True)
    init = sub.add_parser("init")
    init.add_argument("--ack")
    sub.add_parser("current")
    done = sub.add_parser("done")
    done.add_argument("--ack")
    done.add_argument("--choice")
    done.add_argument("--set", action="append")
    skip = sub.add_parser("skip")
    skip.add_argument("--reason")
    status = sub.add_parser("status")
    status.add_argument("--inject", action="store_true")
    gate = sub.add_parser("gate")
    gate.add_argument("what", choices=["edit", "bash"])
    gate.add_argument("arg")
    goto = sub.add_parser("goto")
    goto.add_argument("step")
    goto.add_argument("--force", action="store_true")
    goto.add_argument("--ack")
    unlock = sub.add_parser("unlock")
    unlock.add_argument("what", choices=["source"])
    unlock.add_argument("--reason")
    unlock.add_argument("--ack")
    risk = sub.add_parser("accept-risk")
    risk.add_argument(
        "agent", help="当前步骤报错中显示的 Agent 名称，如 compile/codecheck/ut")
    risk.add_argument("--reason", required=True)
    risk.add_argument("--ack", required=True)
    moonlight = sub.add_parser("moonlight")
    moonlight.add_argument("action", choices=[
        "on", "continue", "off", "report", "push-failed",
        "unlock-source", "defer", "blocked", "repair", "finalize"])
    moonlight.add_argument("--reason")
    moonlight.add_argument("--ack")
    exit_cmd = sub.add_parser("exit")
    exit_cmd.add_argument("--reason")
    exit_cmd.add_argument("--ack")
    exit_cmd.add_argument("--intent", help=argparse.SUPPRESS)
    exit_cmd.add_argument(
        "--interactive", action="store_true",
        help="Hook/ack 损坏时，由用户在真实终端输入 EXIT 的紧急出口")

    action = sub.add_parser("action")
    actions = action.add_subparsers(dest="action", required=True)
    action_start = actions.add_parser("start")
    action_start.add_argument("kind", choices=["ut", "codecheck", "grill"])
    action_start.add_argument("--request")
    action_start.add_argument("--source")
    action_start.add_argument("--files", action="append")
    action_start.add_argument("--build")
    action_start.add_argument("--generator")
    action_start.add_argument("--ut-command")
    action_start.add_argument("--check-only", action="store_true")
    confirm_scope = actions.add_parser("confirm-scope")
    confirm_scope.add_argument("--ack", required=True)
    actions.add_parser("status")
    critic = actions.add_parser("critic")
    critic.add_argument("--stage", choices=["prep", "final"], required=True)
    critic.add_argument("--document", required=True)
    finish = actions.add_parser("finish")
    finish.add_argument("--report")
    actions.add_parser("cancel")

    sub.add_parser("messages")
    requirement = sub.add_parser("requirement-record")
    requirement.add_argument("--message-id")
    requirement.add_argument("--source")
    requirement.add_argument("--ticket")
    requirement.add_argument("--replace", action="store_true")
    reloaded = sub.add_parser("reloaded")
    reloaded.add_argument("--ack")
    doctor = sub.add_parser("doctor")
    doctor.add_argument(
        "--repair-state", action="store_true",
        help="仅修复损坏的辅助状态；绝不覆盖完整流程断点")
    sub.add_parser("envcheck")
    report = sub.add_parser("report")
    report.add_argument("--all", action="store_true")
    template = sub.add_parser("template")
    template.add_argument(
        "kind", nargs="?", default="story",
        choices=["story", "chain", "grill", "review"])
    task = sub.add_parser("agent-task")
    task.add_argument("kind", choices=["compile", "codecheck", "ut"])
    task.add_argument("--scope", help="批次/单告警范围说明；写入受指纹保护的任务卡")
    sub.add_parser("codecheck-scan")
    record = sub.add_parser("codecheck-record")
    record.add_argument("--count", required=True, type=int)
    record.add_argument("--diagnostic", required=True)
    record.add_argument("--reason", required=True)
    record.add_argument("--ack", required=True)
    exemption = sub.add_parser("approve-exemption")
    exemption.add_argument("--rule", required=True)
    exemption.add_argument("--file", required=True)
    exemption.add_argument("--reason", required=True)
    exemption.add_argument("--ack", required=True)
    return parser.parse_args(argv)
