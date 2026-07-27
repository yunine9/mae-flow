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
            '  python "%s" done [--choice 值] [--set 键=值]\n'
            '  python "%s" init\n'
            "其余子命令: status|doctor|report|envcheck|skip|goto|unlock|allow|spec|template|"
            "agent-task|accept-risk|moonlight|action|messages|config-review|requirement-record|"
            "codecheck-scan|codecheck-scope|codecheck-record|approve-exemption|exit"
            "(用法见 current/exit 指令)。\n"
            "注意:子命令不带连字符(是 current 不是 --current);"
            "done 的 --set 可重复,值含空格要加引号；"
            "--ack 仅用于报错明确要求的高风险裁决。" % (me, me, me),
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
    spec = sub.add_parser("spec")
    spec_actions = spec.add_subparsers(dest="spec_action", required=True)
    spec_actions.add_parser("init")
    spec_actions.add_parser("show")
    spec_new = spec_actions.add_parser("new")
    spec_new.add_argument("value", nargs="?", help="变更目录英文短名")
    spec_instr = spec_actions.add_parser("instructions")
    spec_instr.add_argument(
        "value", help="change(v5 四合一,新单唯一入口) | "
                      "proposal | specs | design | tasks(旧布局在途单)")
    spec_actions.add_parser("validate")
    spec_actions.add_parser("archive")
    spec_set = spec_actions.add_parser("set")
    spec_set.add_argument("field", help="design_doc | plan | verification_report")
    spec_set.add_argument("value", help="产物真实路径（登记时校验存在）")
    spec_phase = spec_actions.add_parser("phase")
    spec_phase.add_argument("value", help="open|design|build|verify|archive")
    spec_verify_pass = spec_actions.add_parser("verify-pass")
    spec_verify_pass.add_argument(
        "--report", default="",
        help="可选:验证报告路径,等价于先执行 spec set verification_report")
    allow = sub.add_parser("allow")
    allow.add_argument(
        "block_id", help="gate 三振升级报错中给出的拦截编号(不要自行构造)")
    allow.add_argument("--ack", required=True)
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

    messages = sub.add_parser("messages")
    messages.add_argument("--full", action="store_true")
    messages.add_argument("--id")
    config_review = sub.add_parser("config-review")
    config_review.add_argument("--set", action="append", required=True)
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
    sub.add_parser("steps")  # 工作流全景:各交付方式的步骤链与可裁环节
    capability = sub.add_parser("capability")
    capabilities = capability.add_subparsers(
        dest="capability_action", required=True)
    cap_status = capabilities.add_parser("status")
    cap_status.add_argument("--codecheck", action="store_true")
    capabilities.add_parser("prepare")
    cap_openspec = capabilities.add_parser("openspec")
    cap_openspec.add_argument("arguments", nargs=argparse.REMAINDER)
    for action in (
            "comet-state", "comet-guard", "comet-handoff",
            "comet-archive", "comet-validate"):
        cap_comet = capabilities.add_parser(action)
        cap_comet.add_argument("arguments", nargs=argparse.REMAINDER)
    cap_codecheck = capabilities.add_parser("codecheck")
    cap_codecheck.add_argument(
        "--install", action="store_true",
        help="缺失时从公司内网仓库尽力安装")
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
    codecheck_scope = sub.add_parser("codecheck-scope")
    codecheck_scope.add_argument(
        "--include", default="",
        help="用户确认涉及本次修改的候选编号，逗号分隔，如 W1,W3")
    codecheck_scope.add_argument(
        "--none", action="store_true",
        help="用户确认所有疑似范围外候选均不涉及本次修改")
    codecheck_scope.add_argument("--ack", required=True)
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
