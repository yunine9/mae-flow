"""Agent-token and review-snapshot Evidence rules."""

import os
from dataclasses import dataclass

from ..foundation.models import EvidenceResult


@dataclass(frozen=True)
class AgentEvidencePorts:
    moonlight: object
    step_entered: object
    risk_acceptance: object
    script_path: object
    risk_labels: object
    tokens: object
    rejections: object
    source_snapshot_since: object
    source_changed_since: object
    changed_source_files: object
    shell_output: object
    argv_output: object
    blocking_dirty_source_paths: object


class AgentEvidenceRules:
    def __init__(self, ports):
        self.ports = ports

    def _risk_option(self, kind, expired=""):
        risk = self.ports.risk_labels.get(
            kind, "%s 专项 Agent 没有可验证的质量证据" % kind)
        prefix = (
            "已有风险确认已失效(" + expired + ")。"
            if expired else "")
        return (
            prefix
            + "如果不想继续重跑，可把以下风险原样展示给用户并让用户明确选择："
            + risk
            + "。用户确认承担风险后执行: python \""
            + os.path.abspath(self.ports.script_path())
            + "\" accept-risk "
            + kind.lower()
            + " --reason \""
            + risk
            + "\" --message-id <messages输出的ID>；"
            "它只放行当前步骤的该 Agent 令牌，其他机器检查仍照常执行。"
        )

    def _blocked(self, kind, expired, message):
        return EvidenceResult(
            False, message + " " + self._risk_option(kind, expired))

    def _token_binding_rejection(self, state, kind, token):
        token_step = token.get("step", "")
        if token_step and token_step != state.get("current"):
            return (
                "%s 令牌属于步骤 %s，当前是 %s。每个步骤必须重新执行，"
                "不能复用上一关同一秒签发的令牌。"
                % (kind, token_step, state.get("current"))
            )
        task = (state.get("agent_tasks", {}) or {}).get(kind, {}) or {}
        task_digest = str(task.get("sha256", "") or "")
        task_issuance = str(task.get("issuance_id", "") or "")
        if (
                kind == "COMPILE"
                and (
                    task_digest
                    and str(token.get("task_sha256", "") or "") != task_digest
                    or task_issuance
                    and str(
                        token.get("task_issuance_id", "") or ""
                    ) != task_issuance
                )):
            return (
                "%s 令牌不属于当前任务卡。重新完成当前任务；"
                "旧任务或未绑定任务卡的令牌不能复用。" % kind
            )
        return ""

    def _token_status_rejection(self, spec, kind, token):
        status = token.get("status", "")
        wanted = (
            spec.get("statuses")
            or ([spec["status"]] if spec.get("status") else [])
        )
        if wanted and status not in wanted:
            return (
                "%s 子 agent 虽已收尾,但结果为 %s,本步只接受 %s。"
                "FAIL/BLOCKED/NEEDS_INPUT 是有效上报,但不是质量通过证据;"
                "处理报告中的问题后重启 agent。"
                % (
                    kind,
                    status or "旧令牌未记录状态",
                    "/".join(wanted),
                )
            )
        return ""

    def _token_source_rejection(self, state, kind, token):
        head = token.get("head", "")
        snapshot = token.get("source_snapshot")
        if head and isinstance(snapshot, dict):
            current = self.ports.source_snapshot_since(head, state)
            if current != snapshot:
                return (
                    "%s 证据已过期:令牌签发后的未提交代码快照已变化。"
                    "重新启动对应 agent 对当前工作区收尾；"
                    "旧证据不能背书另一份 diff。" % kind
                )
        elif head:
            changed, error = self.ports.source_changed_since(
                head, state)
            if error:
                return (
                    "%s 证据新鲜度无法核实(%s)。重新启动对应 agent"
                    "(ASKUSER 则重新向用户提问)签发绑定当前代码状态的新令牌。"
                    % (kind, error)
                )
            if changed:
                more = "…" if len(changed) > 5 else ""
                return (
                    "%s 证据已过期:令牌签发后源码发生变更(%s%s)。"
                    "变更若属本单成果先按规范 commit,然后重新启动对应 agent"
                    "(ASKUSER 则重新向用户确认)对最新代码收尾——"
                    "旧证据对新代码无效。"
                    % (kind, "、".join(changed[:5]), more)
                )
        return ""

    def _fresh_token_result(
            self, spec, state, kind, token, accepted_why):
        rejections = (
            self._token_binding_rejection(state, kind, token),
            self._token_status_rejection(spec, kind, token),
            self._token_source_rejection(state, kind, token),
        )
        for reason in rejections:
            if reason:
                return self._blocked(kind, accepted_why, reason)
        return EvidenceResult(True, "")

    def agent_ran(self, spec, state):
        kind = spec["agent"]
        if kind == "ASKUSER" and self.ports.moonlight(state):
            return EvidenceResult(True, "")
        entered = self.ports.step_entered(state)
        accepted, accepted_why = self.ports.risk_acceptance(
            kind, state)
        if accepted:
            return EvidenceResult(True, "")
        token = self.ports.tokens().get(kind, "")
        timestamp = (
            token.get("at", "") if isinstance(token, dict) else token)
        if timestamp and timestamp >= entered:
            value = token if isinstance(token, dict) else {}
            return self._fresh_token_result(
                spec, state, kind, value, accepted_why)
        if kind == "ASKUSER":
            return self._blocked(
                kind,
                accepted_why,
                "本步内未发生过真实的 AskUserQuestion 用户交互"
                "(最近令牌: %s;本步始于 %s)。待确认项必须用 "
                "AskUserQuestion 真实呈现给用户拍板——"
                "自行改写标注/口头声称已确认均无效。"
                % (timestamp or "无", entered),
            )
        rejections = self.ports.rejections()
        rejected = (
            rejections.get(kind, {})
            or rejections.get("SUBAGENT", {})
        )
        if (
            rejected.get("at", "") >= entered
            and rejected.get("step") in ("", state.get("current"))
        ):
            return self._blocked(
                kind,
                accepted_why,
                "%s 子 agent 已运行但未签发令牌。真实拒签原因: %s "
                "如果只是最终报告写法不合规且已有执行凭证，"
                "保持源码不变后重答即可复用；只有缺少真实执行证据"
                "或源码又变化时才需要重跑。"
                % (kind, rejected.get("reason", "未知")),
            )
        return self._blocked(
            kind,
            accepted_why,
            "本步内未检测到 %s 子 agent 的合法收尾"
            "(最近令牌: %s;本步始于 %s)。请启动对应专项 agent，"
            "并让它在最终回复中给出唯一的 XXX_RESULT: 标记。"
            "主会话代写或口头汇报不算执行证据。"
            % (kind, timestamp or "无", entered),
        )

    def agent_or_no_source(self, spec, state):
        files, error = self.ports.changed_source_files(state)
        if error:
            return EvidenceResult(False, error)
        if not files:
            return EvidenceResult(True, "")
        return self.agent_ran(spec, state)

    def review_agent_or_no_code(self, spec, state):
        return self.agent_or_no_source(spec, state)

    def review_snapshot(self, spec, state):
        step = state.get("current", "")
        entered = (
            (state.get("step_heads", {}) or {}).get(step, ""))
        current = self.ports.shell_output(
            "git rev-parse --verify HEAD")
        if (
            not entered
            or self.ports.argv_output(
                ["git", "cat-file", "-t", entered]) != "commit"
        ):
            return EvidenceResult(
                False,
                "缺少 %s 的检视入口 HEAD，无法确定用户看到的是哪版代码"
                % step,
            )
        if current != entered:
            return EvidenceResult(
                False,
                "检视期间 HEAD 已从 %s 变为 %s。旧展示已失效；"
                "回到对应编码环节，重新编译后再让用户检视。"
                % (entered[:10], current[:10] or "未知"),
            )
        base_step = spec.get("base_step", "")
        base = (
            (state.get("step_heads", {}) or {}).get(base_step, ""))
        if (
            not base
            or self.ports.argv_output(
                ["git", "cat-file", "-t", base]) != "commit"
        ):
            return EvidenceResult(
                False,
                "缺少 %s 的入口 HEAD，无法生成本轮完整代码差异"
                % base_step,
            )
        if self.ports.argv_output(
                ["git", "merge-base", base, current]) != base:
            return EvidenceResult(
                False,
                "本轮检视基点 %s 已不在当前 HEAD 历史上，可能发生了 "
                "rebase/reset。必须重新进入编码和编译环节建立可信范围。"
                % base[:10],
            )
        dirty = self.ports.blocking_dirty_source_paths(state)
        if dirty:
            return EvidenceResult(
                False,
                "用户检视期间源码/测试/构建文件又发生未提交变化: "
                + "、".join(dirty[:8])
                + "。旧编译和检视收据均已失效；"
                "先回到对应编码环节处理。",
            )
        return EvidenceResult(True, "")
