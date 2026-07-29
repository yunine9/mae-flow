"""Pure COMPILE Agent final-report contract."""

import re

from mae_flow_core.quality.agent_contracts import (
    accept,
    build_summary_matches,
    embedded_build_command,
    reject,
    required_skill,
)
from mae_flow_core.quality.agent_reports import (
    empty_section,
    report_section,
)
from mae_flow_core.quality.tool_transcript import (
    bash_call,
    call_failed,
    skill_call,
)


def _line_field(report, name):
    match = re.search(
        r"^\s*" + re.escape(name) + r":\s*(.+?)\s*$",
        report,
        re.M,
    )
    return match.group(1).strip() if match else ""


def _successful_bash_evidence(calls, expected):
    call = bash_call(calls, expected)
    if not call:
        return None, (
            "transcript 中没有真实执行配置的编译命令；echo/文字提及不算执行。")
    if not call.result_seen:
        return None, (
            "最后一次编译命令缺少 tool_result，无法证明执行完成；"
            "请恢复完整 transcript，旧宿主无法提供时由用户走 accept-risk 裁决。")
    if call_failed(call):
        return None, "最后一次编译命令的工具结果明确失败，不能报告成功。"
    return call, ""


def _execution_decision(context, build_config):
    need = required_skill(build_config)
    if need:
        call = skill_call(context.calls, need)
        if not call:
            return reject(
                "%s Skill,但 transcript 中没有对应 Skill 工具调用。"
                % ("编译配置要求 " + need))
        if context.status != "BLOCKED" and call_failed(call):
            return reject(
                "%s Skill 的工具结果明确失败，不能报告编译成功。" % need)
        return accept()
    expected = embedded_build_command(build_config) or build_config
    if context.status == "BLOCKED":
        if not bash_call(context.calls, expected):
            return reject(
                "标记 BLOCKED 但 transcript 中没有配置编译命令的真实调用"
                "——弃权也必须先真实尝试过编译。")
        return accept()
    _call, reason = _successful_bash_evidence(context.calls, expected)
    return reject(reason) if reason else accept()


def evaluate_compile_contract(context):
    """Return the existing COMPILE decision without performing I/O."""
    if context.status == "FAIL":
        return accept()
    if not re.search(r"EXECUTED_BUILD", context.report):
        return reject(
            "必须包含 EXECUTED_BUILD(实际执行的编译方式与输出摘录)。")
    build_config = context.config.get("编译方式", "")
    if not build_summary_matches(
            _line_field(context.report, "EXECUTED_BUILD"),
            build_config):
        return reject(
            "EXECUTED_BUILD 与配置确认的编译方式不一致,"
            "禁止自行猜测或替换编译命令。")
    execution = _execution_decision(context, build_config)
    if not execution.accepted:
        return execution
    match = re.search(
        r"^\s*BUILD_ERRORS:\s*(\d+)", context.report, re.M)
    if not match:
        return reject("缺少 BUILD_ERRORS: <数字>(最终一次编译的 error 数)。")
    errors = int(match.group(1))
    if context.status == "OK" and errors != 0:
        return reject(
            "标记 OK 但 BUILD_ERRORS=%s,自相矛盾。" % errors)
    if context.status == "BLOCKED" and errors == 0:
        return reject(
            "标记 BLOCKED 但 BUILD_ERRORS=0,自相矛盾(编译已过应报 OK)。")
    shrink = report_section(context.report, "SHRINK_EXEMPT")
    if (
            context.compile_net < 0
            and (shrink is None or empty_section(shrink))):
        return reject(
            "代码净删 %s 行(git 亲算:未提交+修复编译 commit)"
            "且无 SHRINK_EXEMPT 声明——禁止删代码/注释代码换编译通过;"
            "确属合理精简须逐项声明并接受下游评审复核。"
            % -context.compile_net
        )
    return accept()
