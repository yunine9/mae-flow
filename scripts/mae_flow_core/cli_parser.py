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
            "正确用法(高频命令,直接复制):\n"
            '  python "%s" current\n'
            '  python "%s" start --ticket REQ-123 --path focused '
            '--pace continuous\n'
            '  python "%s" decision startup-confirmed "用户的自然语言决定"\n'
            "其余生产命令: advance|capability-record|manifest|exit|"
            "ut|codecheck|grill|story|chain；内部轻量建议: lightcheck。\n"
            "旧状态只用 migrate-flow 单向迁移；不再使用固定 ACK、消息 ID、"
            "任务卡或证据令牌。" % (me, me, me),
            file=sys.stderr)
        sys.exit(2)


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
    manifest.add_argument(
        "--adopt-dirty", action="append", default=[],
        metavar="FILE=自然语言归属决定")
    manifest.add_argument("--conditional-document", action="append", default=[])
    manifest.add_argument("--moonlight-refresh", action="store_true")
    manifest.add_argument("--allow-commit", action="store_true")
    manifest.add_argument("--allow-push", action="store_true")
    manifest.add_argument("--checkpoint")
    manifest.add_argument("--final", action="store_true")
    manifest.add_argument("--commit-message")
    manifest.add_argument("--decision")

    for toolbox_kind in ("ut", "codecheck", "grill", "story", "chain"):
        toolbox = sub.add_parser(toolbox_kind)
        toolbox.add_argument("--request", default="")
        toolbox.add_argument("--file", action="append", default=[])
    init = sub.add_parser("init")
    init.add_argument("--ack")
    init.add_argument(
        "--message-id",
        help="直接模式下 messages 输出的真实用户消息 ID，避免把长原话重新塞进 shell")
    init.add_argument(
        "--new", action="store_true",
        help="保留已退出的旧现场并开启另一轮流程；未指定时恢复原流程")
    sub.add_parser("current")
    sub.add_parser(
        "migrate-flow",
        help="内部升级命令：安全地把 schema-v2 在途状态迁移为 lean schema-v3")
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
    goto.add_argument("--message-id", required=True)
    unlock = sub.add_parser("unlock")
    unlock.add_argument("what", choices=["source"])
    unlock.add_argument("--reason")
    unlock.add_argument("--message-id", required=True)
    risk = sub.add_parser("accept-risk")
    risk.add_argument(
        "agent", help="当前步骤报错中显示的 Agent 名称，如 compile/codecheck/ut")
    risk.add_argument("--reason", required=True)
    risk.add_argument("--message-id", required=True)
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
    allow.add_argument("--message-id", required=True)
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
    story_localize = sub.add_parser("story-localize")
    story_localize.add_argument(
        "--ticket", required=True,
        help="用户选择不入库的 STORY 单号；把文档移入本地过程区")
    task = sub.add_parser("agent-task")
    task.add_argument("kind", choices=["compile", "codecheck", "ut"])
    task.add_argument("--scope", help="批次/单告警范围说明；写入受指纹保护的任务卡")
    task.add_argument(
        "--checkpoint",
        help="编译任务所属检查点，如 CP1；仅开发节奏已确认的编码步骤使用")
    quality_artifact = sub.add_parser("quality-artifact")
    quality_artifact_actions = quality_artifact.add_subparsers(
        dest="quality_action", required=True)
    quality_register = quality_artifact_actions.add_parser("register")
    quality_register.add_argument(
        "kind", choices=["blueprint", "roadmap", "plan"])
    quality_register.add_argument("path")
    quality_present = quality_artifact_actions.add_parser("present")
    quality_present.add_argument(
        "kind", choices=["blueprint", "plan"])
    quality_artifact_actions.add_parser("show")
    role_task = sub.add_parser("role-task")
    role_task.add_argument("role", choices=[
        "test-design",
        "task-analysis",
        "craft-plan",
        "cp-implement",
        "craft-code",
    ])
    role_task.add_argument("--checkpoint")
    lightcheck = sub.add_parser("lightcheck")
    lightcheck.add_argument(
        "--file", action="append", default=[],
        help="精确本次修改代码文件；可重复")
    lightcheck.add_argument(
        "--quiet", action="store_true",
        help="CLEAN/安全降级时静默；仅发现高置信问题才提示")
    checkpoint = sub.add_parser("checkpoint")
    checkpoint_actions = checkpoint.add_subparsers(
        dest="checkpoint_action", required=True)
    checkpoint_plan = checkpoint_actions.add_parser("plan")
    checkpoint_plan.add_argument(
        "--item", action="append", default=[],
        help="按顺序给出检查点标题/范围；可重复 1-6 次")
    checkpoint_plan.add_argument("--roadmap")
    checkpoint_plan.add_argument("--plan")
    checkpoint_actions.add_parser("status")
    checkpoint_ready = checkpoint_actions.add_parser("ready")
    checkpoint_ready.add_argument("checkpoint_id", help="当前检查点，如 CP1")
    checkpoint_prepare = checkpoint_actions.add_parser("prepare")
    checkpoint_prepare.add_argument("checkpoint_id", help="当前检查点，如 CP1")
    checkpoint_prepare.add_argument("--plan", required=True)
    checkpoint_prepare.add_argument("--review", required=True)
    checkpoint_plan_decide = checkpoint_actions.add_parser("plan-decide")
    checkpoint_plan_decide.add_argument(
        "choice", choices=["continue", "revise"])
    checkpoint_craft = checkpoint_actions.add_parser("craft-reviewed")
    checkpoint_craft.add_argument("checkpoint_id", help="当前检查点，如 CP1")
    checkpoint_craft.add_argument("--review", required=True)
    checkpoint_craft_decide = checkpoint_actions.add_parser("craft-decide")
    checkpoint_craft_decide.add_argument(
        "checkpoint_id", help="当前检查点，如 CP1")
    checkpoint_craft_decide.add_argument("--review", required=True)
    checkpoint_actions.add_parser("final")
    checkpoint_decide = checkpoint_actions.add_parser("decide")
    checkpoint_decide.add_argument(
        "choice", choices=["continue", "revise", "continuous"])
    sub.add_parser("codecheck-scan")
    codecheck_scope = sub.add_parser("codecheck-scope")
    codecheck_scope.add_argument(
        "--include", default="",
        help="用户确认涉及本次修改的候选编号，逗号分隔，如 W1,W3")
    codecheck_scope.add_argument(
        "--none", action="store_true",
        help="用户确认所有疑似范围外候选均不涉及本次修改")
    codecheck_scope.add_argument("--message-id", required=True)
    record = sub.add_parser("codecheck-record")
    record.add_argument("--count", required=True, type=int)
    record.add_argument("--diagnostic", required=True)
    record.add_argument("--reason", required=True)
    record.add_argument("--message-id", required=True)
    exemption = sub.add_parser("approve-exemption")
    exemption.add_argument("--rule", required=True)
    exemption.add_argument("--file", required=True)
    exemption.add_argument("--reason", required=True)
    exemption.add_argument("--message-id", required=True)
    return parser.parse_args(argv)
