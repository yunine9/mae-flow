"""Platform adapter for active Flow and Standalone Hook events."""

import glob
import json
import os
import re
import tempfile
import time

from mae_flow_core import atomic_write_json
from mae_flow_core.application.hooks.agent_completion import (
    AgentCompletionPorts,
    handle_agent_completion,
)
from mae_flow_core.application.hooks.event_policies import (
    active_pretool_decision,
    agent_kind,
    standalone_pretool_decision,
    stop_decision,
    template_decision,
    template_target,
)
from mae_flow_core.application.hooks.models import HookResponse
from mae_flow_core.application.hooks.task_cards import (
    verify_agent_scope,
    verify_dispatch_task,
)
from mae_flow_core.file_io import (
    load_json,
    read_lines,
    read_text,
    write_text,
)
from mae_flow_core.workflow.agent_observations import (
    latest_started_invocation,
    record_agent_finished,
    record_agent_started,
    started_observation,
)
from mae_flow_core.workflow.quality_executions import (
    quality_input_snapshot,
    record_quality_execution,
)
from mae_flow_core.quality.tool_transcript import (
    bash_call, bash_calls, call_failed, parse_transcript, skill_call,
)
from mae_flow_core.quality.compile_side_effects import (
    successful_direct_write_paths,
)


_QUESTION_BLOCKED = (
    "[mae-flow] 月光宝盒处于无人值守模式，禁止询问用户。"
    "请根据需求、代码和仓库规则采用不扩大范围的保守结论并留痕；"
    "质量步骤有限尝试后仍失败，使用 current 输出的 moonlight defer "
    "记录遗留并继续。\n"
)
_ACTION_EDIT_BLOCKED = (
    "[mae-flow] 独立任务状态和任务卡由 harness 维护，禁止直接编辑；"
    "普通业务代码不受此限制。\n"
)
_ACTION_BASH_BLOCKED = (
    "[mae-flow] 禁止通过命令修改独立任务状态、任务卡或手工调用 Hook。"
    "查看用 action status，退出用 action cancel。\n"
)
_STOP_BLOCKED = (
    "[mae-flow] 月光宝盒仍在执行，当前步骤 %s，禁止提前结束回复或等待用户。"
    "继续执行 mae-flow current 给出的动作；质量问题尽力后用 moonlight defer，"
    "确实缺少需求/权限/外部条件而无法继续时用 moonlight blocked --reason "
    "留痕后再停止。\n"
)
_ERROR_PATTERN = re.compile(
    r"(command not found|is not recognized|No such file|not found|"
    r"不可用|不存在|无法|失败|denied|Exception|Traceback|timeout|超时|"
    r"error[: ])",
    re.I,
)


class ActiveHookEventAdapter:
    """Execute application decisions through filesystem and CLI ports."""

    def __init__(
            self, *, state, maeflow_path, repository_root, maeflow,
            runtime_adapter, task_card_ports, log):
        self.state = state
        self.maeflow_path = maeflow_path
        self.repository_root = repository_root
        self.maeflow = maeflow
        self.runtime = runtime_adapter
        self.task_card_ports = task_card_ports
        self.log = log
        self.autopsy_path = os.path.join(
            tempfile.gettempdir(), "mae-flow-agent-autopsy.log")

    def _moonlight_enabled(self):
        try:
            state = load_json(self.state)
            return bool((state.get("moonlight") or {}).get("enabled"))
        except Exception:
            return False

    @staticmethod
    def _agent_invocation_id(payload):
        for key in ("invocation_id", "agent_id", "tool_use_id", "task_id"):
            if payload.get(key):
                return str(payload[key])
        return "agent-%s-%s" % (os.getpid(), time.time_ns())

    def _record_agent_start(self, payload, kind, state):
        try:
            record_agent_started(
                self.state, kind, state.get("current", ""),
                self._agent_invocation_id(payload),
                time.strftime("%Y-%m-%d %H:%M:%S"),
            )
        except Exception as exc:
            self.log("agent start observation EXC(fail-open): %s" % exc)

    def _gate_agent_dispatch(self, payload, tool_input):
        kind = agent_kind(tool_input)
        if not kind:
            return HookResponse()
        try:
            state = self.runtime._contract_state()
            decision = (
                verify_dispatch_task(kind, state, self.task_card_ports())
                if kind in (
                    "STORY", "REVIEWER", "CP_IMPLEMENT",
                    "COMPILE", "CODECHECK", "UT",
                    "GRILL", "GRILL_PREP", "GRILL_FINAL",
                )
                else None
            )
            response = (
                HookResponse()
                if decision is None or decision.accepted
                else HookResponse(exit_code=2, stderr=decision.reason + "\n")
            )
            if response.exit_code == 0:
                self._record_agent_start(payload, kind, state)
            return response
        except Exception as exc:
            self.log("agent dispatch gate EXC(fail-open): %s" % exc)
            return HookResponse()

    def pretool(self, payload):
        tool = payload.get("tool_name", "")
        tool_input = payload.get("tool_input") or {}
        decision = active_pretool_decision(
            tool, tool_input, self._moonlight_enabled())
        if decision.action == "agent":
            return self._gate_agent_dispatch(payload, tool_input)
        if decision.action == "block-question":
            return HookResponse(exit_code=2, stderr=_QUESTION_BLOCKED)
        if decision.action == "gate-edit":
            return HookResponse(
                exit_code=self.maeflow("gate", "edit", decision.value))
        if decision.action == "gate-bash":
            return HookResponse(
                exit_code=self.maeflow("gate", "bash", decision.value))
        return HookResponse()

    def standalone_pretool(self, payload):
        tool_input = payload.get("tool_input") or {}
        decision = standalone_pretool_decision(
            payload.get("tool_name", ""), tool_input)
        if decision.action == "agent":
            return self._gate_agent_dispatch(payload, tool_input)
        if decision.action == "block-edit":
            return HookResponse(exit_code=2, stderr=_ACTION_EDIT_BLOCKED)
        if decision.action == "block-bash":
            return HookResponse(exit_code=2, stderr=_ACTION_BASH_BLOCKED)
        return HookResponse()

    def _capture_prompt(self, payload):
        prompt = payload.get("prompt") or ""
        self.runtime._capture_moonlight_intent(prompt)
        self.runtime._capture_usermsg(prompt)
        return self.runtime._capture_exit_intent(prompt)

    def _exit_response(self, exit_intent):
        code = self.maeflow("exit", "--intent", exit_intent)
        if code == 0 and not os.path.exists(self.state):
            return HookResponse(stdout=(
                "[mae-flow] 用户已明确退出，本条消息开始按普通开发请求处理；"
                "不要再运行 current/done。\n"))
        return HookResponse(stderr=(
            "[mae-flow] 自动退出未完成(流程状态仍在)。不要重复要求用户确认；"
            "请执行 doctor 查看原因，用户始终可在真实终端运行 "
            "`mae-flow exit --interactive`；若插件脚本本身不可用,恢复插件后"
            "重试,或(确认放弃流程时)由用户手动删除项目根的 .mae-flow.json* "
            "文件。\n"))

    def _active_injection(self, session_start):
        self.maeflow("status", "--inject")
        if not session_start:
            return HookResponse()
        readme = os.path.abspath(
            os.path.join(self.repository_root, "README.md"))
        return HookResponse(stdout=(
            "[mae-flow] 存在进行中的交付流程。续跑先执行 python "
            "\"%s\" current 获取当前步骤指令。"
            "用户问 mae-flow 用法/流程类问题时,先读 \"%s\" "
            "再按其内容作答,禁止凭记忆即兴。\n"
            % (os.path.abspath(self.maeflow_path), readme)
        ))

    def _standalone_injection(self, action):
        output = (
            "[mae-flow] 当前有独立 %s 任务 %s；它不启用完整流程，也不限制普通改码。"
            "继续请执行 action status，完成后 action finish，随时可 action cancel。\n"
            % (str(action.get("kind", "")).upper(), action.get("id", "?"))
        )
        if action.get("status") == "awaiting_scope_confirmation":
            output += (
                "[mae-flow] 当前任务尚未执行，正在等待用户确认已展示的文件范围。"
                "用户确认范围后直接执行 action confirm-scope；"
                "命令会读取绑定当前范围指纹的回答。"
                "用户要求调整则 action cancel 后按新范围重开。\n"
            )
        return HookResponse(stdout=output)

    def inject(self, payload, session_start=False):
        if not session_start:
            exit_intent = self._capture_prompt(payload)
            if exit_intent:
                return self._exit_response(exit_intent)
        if os.path.exists(self.state):
            return self._active_injection(session_start)
        action = self.runtime._load_action()
        if action:
            return self._standalone_injection(action)
        if (
                session_start
                and (
                    os.path.isdir("openspec")
                    or os.path.isdir(".comet"))):
            script = os.path.abspath(self.maeflow_path)
            readme = os.path.abspath(
                os.path.join(self.repository_root, "README.md"))
            return HookResponse(stdout=(
                "[mae-flow] 本项目适用 mae-flow 交付流程:开新单直接说"
                "「交付 <单号> + SE 文档」或敲 /mae-flow:mae-flow;"
                "新手指南敲 /mae-flow:mae-flow help。"
                "(流程脚本: python \"%s\";"
                "用户问用法/流程类问题时,先读 \"%s\" "
                "再作答,禁止凭记忆即兴)\n" % (script, readme)
            ))
        return HookResponse()

    def _autopsy(self, path, assistants):
        turns = len(assistants)
        tails = [
            answer.strip().replace("\n", " ")[-160:]
            for answer in assistants[-2:] if answer.strip()
        ]
        errors = []
        try:
            full = "\n".join(assistants[-8:])
            for match in _ERROR_PATTERN.finditer(full):
                clue = full[
                    max(0, match.start() - 40):match.end() + 60
                ].replace("\n", " ")
                if clue not in errors:
                    errors.append(clue)
                if len(errors) >= 3:
                    break
        except Exception:
            pass
        clue = "约 %s 轮" % turns
        if errors:
            clue += ";检出报错特征: " + " | ".join(
                error[:90] for error in errors[:2])
        if tails:
            clue += ";临终输出: …" + tails[-1][:120]
        try:
            write_text(
                self.autopsy_path,
                "%s %s\n  turns=%s\n  tails=%s\n  errs=%s\n" % (
                    time.strftime("%Y-%m-%d %H:%M:%S"),
                    os.path.basename(path) or "?",
                    turns,
                    tails,
                    errors,
                ),
                mode="a",
            )
        except Exception:
            pass
        return clue

    @staticmethod
    def _latest_subagent_transcript(main_path):
        stem = os.path.splitext(main_path)[0]
        candidates = glob.glob(
            os.path.join(stem, "subagents", "agent-*.jsonl"))
        return max(candidates, key=os.path.getmtime) if candidates else ""

    @staticmethod
    def _load_agent_transcript(path):
        return [
            json.loads(line)
            for line in read_lines(path)
            if line.strip()
        ]

    def _agent_completion_ports(self):
        return AgentCompletionPorts(
            state_path=self.state,
            latest_started=lambda: latest_started_invocation(self.state),
            record_finished=lambda state_path, invocation_id, lifecycle, detail:
            record_agent_finished(
                state_path, invocation_id, lifecycle,
                time.strftime("%Y-%m-%d %H:%M:%S"), detail),
            record_execution=self._record_quality_execution,
            scope_violation=self._scope_violation,
            log=self.log,
        )

    @staticmethod
    def _explicit_transcript_path(payload):
        for key, value in payload.items():
            if (isinstance(value, str) and "transcript" in key.lower()
                    and "agent" in key.lower()):
                return value
        main = payload.get("transcript_path", "")
        return ActiveHookEventAdapter._latest_subagent_transcript(main)

    @staticmethod
    def _quality_call(kind, calls, config):
        if kind == "COMPILE":
            build = str(config.get("编译方式", "") or "")
            if "build-fix" in build.lower():
                return skill_call(calls, "build-fix")
            return bash_call(calls, build)
        if kind == "UT":
            return bash_call(calls, str(config.get("UT运行命令", "") or ""))
        if kind == "CODECHECK":
            matches = bash_calls(calls, "codecheck fullcheck")
            return matches[-1][0] if matches else None
        return None

    def _record_quality_execution(self, payload, invocation_id, lifecycle):
        started = started_observation(self.state, invocation_id) or {}
        kind = started.get("kind", "")
        if kind not in ("COMPILE", "CODECHECK", "UT"):
            return
        state = self.runtime._contract_state()
        path = self._explicit_transcript_path(payload)
        calls = ()
        if path:
            try:
                calls = parse_transcript(
                    self._load_agent_transcript(path)).tool_calls
            except Exception as exc:
                self.log("quality transcript EXC(fail-closed evidence): %s" % exc)
        call = self._quality_call(kind, calls, state.get("config", {}) or {})
        command = ""
        if call:
            value = call.input
            command = value.get("command", "") if isinstance(value, dict) else str(value)
            if call.name.lower() == "skill":
                command = "Skill:" + str(value)
        succeeded = bool(
            lifecycle == "returned" and call and not call_failed(call))
        record_quality_execution(
            self.state, kind, started.get("step", ""), invocation_id,
            command, succeeded,
            quality_input_snapshot(state, kind, started.get("step", "")),
            time.strftime("%Y-%m-%d %H:%M:%S"), lifecycle=lifecycle,
        )

    def _scope_violation(self, payload, invocation_id):
        """Check repository writes without interpreting the Agent response."""
        started = started_observation(self.state, invocation_id) or {}
        kind = str(started.get("kind", "") or "")
        if not kind:
            return ""
        state = self.runtime._contract_state()
        task = (state.get("agent_tasks", {}) or {}).get(kind, {}) or {}
        if not task:
            return ""
        direct_write_paths = ()
        path = self._explicit_transcript_path(payload)
        if path:
            try:
                calls = parse_transcript(
                    self._load_agent_transcript(path)).tool_calls
                direct_write_paths = successful_direct_write_paths(
                    calls, self.repository_root)
            except Exception as exc:
                self.log(
                    "scope transcript EXC(use repository facts): %s" % exc)
        decision = verify_agent_scope(
            kind,
            task,
            state,
            self.task_card_ports(),
            direct_write_paths=direct_write_paths,
        )
        return "" if decision.accepted else decision.reason

    def subagentstop(self, payload):
        return handle_agent_completion(
            payload, self._agent_completion_ports())

    def _template_response(self, path):
        target = template_target(path)
        if not target:
            return HookResponse()
        template_name, label = target
        template_path = os.path.join(
            self.repository_root,
            "skills",
            "mae-flow",
            "assets",
            template_name,
        )
        if not os.path.exists(template_path):
            self.log(label + " 模板缺失: " + template_path)
            return HookResponse()
        try:
            decision = template_decision(
                read_text(template_path), read_text(path))
        except Exception:
            return HookResponse()
        if decision.accepted:
            return HookResponse()
        return HookResponse(
            exit_code=2,
            stderr=(
                "[mae-flow] %s 结构与模板不符,缺少章节: %s。"
                "请补齐缺失章节(无内容的章节按约定标注,不可省略标题)。\n"
                % (label, " | ".join(decision.missing))
            ),
        )

    def posttool(self, payload):
        tool = payload.get("tool_name")
        tool_input = payload.get("tool_input") or {}
        if tool in ("Write", "Edit", "MultiEdit"):
            path = (
                tool_input.get("file_path", "")
                or tool_input.get("path", "")
                or ""
            )
            if path:
                self.runtime._record_agent_write(path)
        if tool == "AskUserQuestion":
            answer = self.runtime._text_of(payload.get("tool_response"))
            self.runtime._capture_usermsg(
                answer, askuser_input=tool_input)
            self.runtime._record_agent_token("ASKUSER", "CONFIRMED")
            return HookResponse()
        if tool == "Bash":
            self.runtime._finalize_git_authorization(
                tool_input.get("command", "") or "")
            self.runtime._maybe_utrun(payload)
            return HookResponse()
        path = (
            tool_input.get("file_path", "") or "").replace("\\", "/")
        return self._template_response(path)

    def stop(self, payload):
        try:
            state = load_json(self.state)
        except Exception:
            return HookResponse()
        initial = stop_decision(state, False, {})
        if initial.allow:
            return HookResponse()
        guard_path = self.state + ".stop-guard"
        try:
            guard = load_json(guard_path)
        except Exception:
            guard = {}
        decision = stop_decision(
            state, bool(payload.get("stop_hook_active")), guard)
        if decision.allow:
            self.log(
                "stop guard: revision=%s 连续 %s 次零进展,"
                "fail-open 放行(防死循环)"
                % (decision.revision, decision.blocks - 1))
            return HookResponse()
        try:
            atomic_write_json(guard_path, {
                "revision": decision.revision,
                "blocks": decision.blocks,
                "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
        except Exception:
            self.log("stop guard write failed — allow")
            return HookResponse()
        return HookResponse(
            exit_code=2,
            stderr=_STOP_BLOCKED % (state.get("current", "") or "未知"),
        )
