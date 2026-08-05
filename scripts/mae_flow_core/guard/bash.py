"""Pure general Bash and Git Gate policies."""

from dataclasses import dataclass
import re

from ..foundation.git_execution import executed_git_invocations
from .gate import GateDecision


@dataclass(frozen=True)
class BashGateContext:
    command: str
    has_internal_state_path: bool
    branch_name: str
    branch_creating: bool
    step: str
    wanted_branch: str
    base_branch: str
    ticket: str
    commit_message_present: bool
    commit_message: str
    current_branch: str
    add_paths: tuple
    recursive_delete_targets: tuple
    state_active: bool


def _absolute(rule, message):
    return GateDecision("absolute", rule=rule, message=message)


def _block(rule, message):
    return GateDecision("block", rule=rule, message=message)


def _pre_repository(context):
    if context.has_internal_state_path:
        return _absolute(
            "bash-internal-state-read",
            "流程状态、令牌、历史账本、待重启标记和月光宝盒报告禁止经 Bash "
            "直接访问；查看请执行 current 输出中的 status/doctor/moonlight report 命令，"
            "修改只能走对应子命令。")
    baseline_checkout = (
        context.step == "branch_create"
        and not context.branch_creating
        and context.base_branch
        and context.branch_name == context.base_branch)
    if (
        context.branch_name
        and context.wanted_branch
        and context.branch_name != context.wanted_branch
        and not baseline_checkout
    ):
        return _block(
            "bash-branch-name",
            "分支名 %s 不符合约定 %s(内部流程建议的 feature/xx 命名一律拒绝)。"
            % (context.branch_name, context.wanted_branch),
        )
    return None


def _pre_wide_add(context):
    command = context.command
    if re.search(r"git\s+add\s+(-A\b|--all\b|\.(\s|$))", command):
        return _absolute(
            "bash-wide-add",
            "禁止宽提交(git add -A / --all / .):会把无关文件与不入库产物卷进"
            "交付分支(实战:STORY 选了不入库仍被卷进 MR)。git add 必须精确到"
            "文件/明确的产物目录。")
    return None


def _pre_commit_format(context):
    if not context.commit_message_present:
        return None
    message = context.commit_message
    if (
        context.ticket
        and not re.match(
            r"^\[" + re.escape(context.ticket)
            + r"\]\[(feat|fix)\]", message)
    ):
        return _block(
            "bash-commit-format",
            "commit message「%s」不符合 [%s][feat|fix]描述 格式。"
            % (message, context.ticket),
        )
    return None


def decide_commit_branch(context):
    if (
        not context.commit_message_present
        or not context.wanted_branch
        or context.step in (
            "config_confirm", "workflow_select",
            "code_reviewer_ask", "branch_create")
        or not context.current_branch
        or context.current_branch == context.wanted_branch
    ):
        return GateDecision("allow")
    return _block(
        "bash-commit-branch",
        "提交前拦截:当前分支 %s != 本单约定分支 %s。"
        "先 git checkout %s 再提交;在错分支上积累提交,done 时才发现要整步返工。"
        % (
            context.current_branch,
            context.wanted_branch,
            context.wanted_branch,
        ),
    )


def decide_pre_commit(context):
    for evaluator in (
        _pre_repository,
        _pre_wide_add,
        _pre_commit_format,
    ):
        decision = evaluator(context)
        if decision is not None:
            return decision
    return GateDecision("allow")


def _post_early(context):
    command = context.command
    if any(
            operation == "push" and any(
                argument == "-f"
                or argument.startswith("--force")
                or argument.startswith("+")
                for argument in arguments)
            for operation, arguments in executed_git_invocations(command)):
        return _absolute(
            "bash-force-push",
            "禁止 force push(含 +refspec 形式)。")
    if re.search(r"dispatch\.py", command):
        return _absolute(
            "bash-manual-dispatch",
            "hook 分发器(dispatch.py)由 harness 自动调用,禁止手动执行——"
            "这是伪造 agent 收尾令牌的通道。")
    if re.search(
            r"mae-flow\.py[^;&|]*\bexit\b[^;&|]*--interactive\b",
            command, re.I):
        return _absolute(
            "bash-agent-interactive-exit",
            "exit --interactive 是 Hook/ack 全坏时给用户的真实终端逃生口，"
            "Agent 的 Bash 禁止调用或代答；把完整命令展示给用户手动执行。")
    return None


def _post_repository(context):
    command = context.command
    if any(
        re.sub(r"/+$", "", path) == "openspec"
        for path in context.add_paths
    ):
        return _block(
            "bash-wide-openspec-add",
            "禁止整目录 git add openspec/：它会把其他单遗留的 change/STORY "
            "一起卷入提交。open/design 只 add 当前 "
            "openspec/changes/{CHANGE_NAME}；archive 只 add spec archive "
            "输出的本次精确产物清单。",
        )
    mkdir = re.search(
        r"(?:^|[\s;&|(])(?:mkdir|md|new-item)\b"
        r"((?:\s+(?:-\S+|\"[^\"]*\"|'[^']*'|[^\s;|&]+))*)",
        command,
        re.I,
    )
    if mkdir and any(
        re.search(r"(^|/)openspec/", token, re.I)
        for token in re.split(
            r"""[\s;|&()<>'"]+""", mkdir.group(1) or "")
        if token and not token.startswith("-")
    ):
        return _block(
            "bash-mkdir-openspec",
            "禁止手动创建 openspec 目录：change 必须由 current 输出的 spec new 命令创建，"
            "它会在建目录的同时登记当前单与阶段；手搓空目录没有状态登记，"
            "后续证据校验会失败。先执行 current，并照本步骤给出的 spec 命令处理。",
        )
    return None


def _git_clean_ignored(git_commands):
    return any(
        operation == "clean" and any(
            argument.startswith("-")
            and not argument.startswith("--")
            and "x" in argument[1:].casefold()
            for argument in arguments)
        for operation, arguments in git_commands
    )


def _git_wipes_worktree(git_commands):
    return (
        any(
            operation == "reset" and "--hard" in arguments
            for operation, arguments in git_commands)
        or any(
            operation in ("checkout", "restore")
            and any(argument in (".", ":/") for argument in arguments)
            for operation, arguments in git_commands)
    )


def _git_adds_worktree(git_commands):
    return any(
        operation == "worktree" and "add" in arguments
        for operation, arguments in git_commands)


def _post_dangerous(context):
    command = context.command
    if re.search(r"\bcomet\s+init\b", command):
        return _absolute(
            "bash-comet-init",
            "禁止执行全局 comet init：它会初始化无关平台并污染项目。"
            "Mae-Flow 已内嵌所需运行时，执行 current 给出的 capability 命令即可，"
            "无需人工初始化。")
    if re.search(
        r"(curl|wget|iwr|invoke-webrequest)[^|&;]*\|\s*"
        r"(sudo\s+)?(sh|bash|zsh|iex|powershell)",
        command,
        re.I,
    ):
        return _absolute(
            "bash-remote-script-pipe",
            "危险命令拦截:管道执行远程脚本(供应链风险)。确需执行请用户手动运行。")
    git_commands = executed_git_invocations(command)
    if _git_clean_ignored(git_commands):
        return _absolute(
            "bash-git-clean-ignored",
            "危险命令拦截:git clean -x 会删除 ignore 文件(含 mae-flow 状态与令牌)。")
    if context.state_active and _git_wipes_worktree(git_commands):
        return _block(
            "bash-wipe-worktree",
            "全树不可逆清除拦截(git reset --hard / checkout -- .):未提交的"
            "工作区改动会全部蒸发。回退越权改动请精确到文件:"
            "git checkout HEAD -- <文件>;确需全树清除,把风险展示给用户裁决。",
        )
    if context.recursive_delete_targets:
        return _absolute(
            "bash-recursive-delete",
            "危险命令拦截:对「%s」的递归删除。确需执行请用户手动运行。"
            % context.recursive_delete_targets[0])
    if (
        context.state_active
        and _git_adds_worktree(git_commands)
    ):
        return _block(
            "bash-worktree",
            "本流程约定 branch 隔离,worktree 会使 mae-flow 状态机失联"
            "(新目录无状态文件,gate 全拦)。若是为并行另一单开工作区:"
            "请用户手动建 worktree 并在新目录另起会话独立 init,"
            "本流程内不执行该命令。",
        )
    return None


def decide_post_commit(context):
    for evaluator in (
        _post_early,
        _post_repository,
        _post_dangerous,
    ):
        decision = evaluator(context)
        if decision is not None:
            return decision
    return GateDecision("allow")
