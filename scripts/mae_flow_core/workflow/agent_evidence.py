"""Agent lifecycle and review-snapshot Evidence rules."""

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
    finished_observation: object
    askuser_tokens: object
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
            "它只放行当前步骤的该 Agent 生命周期证据，其他机器检查仍照常执行。"
        )

    def _blocked(self, kind, expired, message):
        return EvidenceResult(
            False, message + " " + self._risk_option(kind, expired))

    def agent_ran(self, spec, state):
        kind = spec["agent"]
        if kind == "ASKUSER" and self.ports.moonlight(state):
            return EvidenceResult(True, "")
        entered = self.ports.step_entered(state)
        accepted, accepted_why = self.ports.risk_acceptance(
            kind, state)
        if accepted:
            return EvidenceResult(True, "")
        if kind == "ASKUSER":
            token = self.ports.askuser_tokens().get(kind, "")
            timestamp = (
                token.get("at", "") if isinstance(token, dict) else token)
            if timestamp and timestamp >= entered:
                return EvidenceResult(True, "")
            return self._blocked(
                kind,
                accepted_why,
                "本步内未发生过真实的 AskUserQuestion 用户交互"
                "(最近令牌: %s;本步始于 %s)。待确认项必须用 "
                "AskUserQuestion 真实呈现给用户拍板——"
                "自行改写标注/口头声称已确认均无效。"
                % (timestamp or "无", entered),
            )
        observation = self.ports.finished_observation(
            kind, state.get("current", ""), entered)
        if observation:
            return EvidenceResult(True, "")
        return self._blocked(
            kind,
            accepted_why,
            "本步内未检测到 %s 子 Agent 已返回（本步始于 %s）。"
            "请启动对应专项 Agent；返回内容可以使用任意自然语言格式。"
            % (kind, entered),
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
