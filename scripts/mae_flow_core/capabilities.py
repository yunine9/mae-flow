"""Self-contained capability runtime for Mae-Flow.

All workflow methodology and deterministic helpers live under ``runtime/vendor``.
The host only needs the same Python, Git and Node runtimes already required to run
CodeAgent itself.  No project-local Skill installation or reload is involved.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

from .state_store import atomic_write_json, atomic_write_text


PLUGIN_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
VENDOR_ROOT = os.path.join(PLUGIN_ROOT, "runtime", "vendor")
OPENSPEC_ENTRY = os.path.join(
    VENDOR_ROOT, "openspec", "dist", "core", "artifact-graph", "openspec.mjs")
COMET_SCRIPT_ROOT = os.path.join(VENDOR_ROOT, "comet", "comet", "scripts")
MANIFEST_PATH = os.path.join(VENDOR_ROOT, "manifest.json")
CODECHECK_PACKAGE = "@baize/codecheckcli"
CODECHECK_REGISTRY = (
    "https://cmc.centralrepo.rnd.huawei.com/artifactory/api/npm/product_npm/")


CAPABILITY_PACKS = {
    "open": [
        (
            "Comet 开启阶段规则",
            "comet/comet-open/SKILL.md",
            [
                "### 0. 输出语言约束",
                "### 1a. PRD 拆分预检（阻塞点）",
                "### 1c. Change 名称确认（阻塞点）",
                "### 2. 创建 Change 结构 + 初始化状态",
                "### 4. 内容完整性检查",
            ],
        ),
        ("OpenSpec 需求探索", "openspec/skills/openspec-explore/SKILL.md"),
        ("OpenSpec 变更创建", "openspec/skills/openspec-new-change/SKILL.md"),
    ],
    "hotfix-open": [
        (
            "Comet 问题修复规则",
            "comet/comet-hotfix/SKILL.md",
            [
                "### 0. 输出语言约束",
                "### 1. 快速开启（preset open）",
                "## 升级条件",
            ],
        ),
        ("OpenSpec 变更创建", "openspec/skills/openspec-new-change/SKILL.md"),
    ],
    "tweak-open": [
        (
            "Comet 小改规则",
            "comet/comet-tweak/SKILL.md",
            [
                "### 0. 输出语言约束",
                "### 1. 快速开启（preset open）",
                "## 升级条件",
            ],
        ),
        ("OpenSpec 变更创建", "openspec/skills/openspec-new-change/SKILL.md"),
    ],
    "design": [
        (
            "Comet 设计阶段规则",
            "comet/comet-design/SKILL.md",
            [
                "### 1a. 生成 OpenSpec → Superpowers 交接包",
                "### 1b. 执行 Brainstorming（带上下文）",
                "### 1c. 用户确认设计方案（阻塞点）",
                "### 1d. Brainstorming 检查点定稿",
                "### 2. 创建 Design Doc",
            ],
        ),
        ("Superpowers 方案讨论", "superpowers/skills/brainstorming/SKILL.md"),
    ],
    "build": [
        (
            "Comet 构建阶段规则",
            "comet/comet-build/SKILL.md",
            [
                "### 1. 制定计划（Subagent Offload）",
                "### 3b. 执行中异常调试（异常调试协议）",
                "### 4. Spec 增量更新",
                "### 5. 上下文管理",
            ],
        ),
        (
            "Comet 问题修复根因检查",
            "comet/comet-hotfix/SKILL.md",
            ["### 3. 根因消除检查"],
        ),
        ("Superpowers 实现计划", "superpowers/skills/writing-plans/SKILL.md"),
        ("Superpowers 连续执行", "superpowers/skills/executing-plans/SKILL.md"),
        ("Superpowers 系统化调试",
         "superpowers/skills/systematic-debugging/SKILL.md"),
        ("Ponytail 精简纪律", "ponytail/skills/ponytail/SKILL.md"),
    ],
    "review-fix": [
        ("Superpowers 评审意见处理",
         "superpowers/skills/receiving-code-review/SKILL.md"),
        ("Superpowers 系统化调试",
         "superpowers/skills/systematic-debugging/SKILL.md"),
        ("Ponytail 精简纪律", "ponytail/skills/ponytail/SKILL.md"),
    ],
    "tweak-build": [
        ("Superpowers 系统化调试",
         "superpowers/skills/systematic-debugging/SKILL.md"),
        ("Ponytail 精简纪律", "ponytail/skills/ponytail/SKILL.md"),
    ],
    "ponytail-review": [
        ("Ponytail 复杂度审查", "ponytail/skills/ponytail-review/SKILL.md"),
    ],
    "verify": [
        (
            "Comet 验证阶段规则",
            "comet/comet-verify/SKILL.md",
            [
                "### 1. 改动规模评估",
                "### 1b. 验证失败决策（阻塞点）",
                "### 2. 产物上下文加载（Hash 按需读）",
                "### 2a. 轻量验证（小改动）",
                "### 2b. 完整验证（大改动）",
                "### 4. 记录验证证据",
            ],
        ),
        ("Superpowers 完成前验证",
         "superpowers/skills/verification-before-completion/SKILL.md"),
        ("Superpowers 正确性审查",
         "superpowers/skills/requesting-code-review/SKILL.md"),
        ("OpenSpec 规格符合检查",
         "openspec/skills/openspec-verify-change/SKILL.md"),
    ],
    "archive": [
        (
            "Comet 归档阶段规则",
            "comet/comet-archive/SKILL.md",
            [
                "### 1. 归档前最终确认（阻塞点）",
                "### 2. 执行归档",
                "### 3. 生命周期闭环",
            ],
        ),
    ],
}

class CapabilityError(RuntimeError):
    """A bundled capability cannot run safely."""


def _strip_frontmatter(text):
    return re.sub(r"\A---\s*\n.*?\n---\s*\n", "", text, count=1, flags=re.S)


def _extract_markdown_sections(text, wanted):
    """Extract exact upstream heading sections, including their children."""
    if not wanted:
        return text
    lines = text.splitlines()
    wanted = set(wanted)
    selected = []
    active_level = None
    found = set()
    for line in lines:
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            level = len(heading.group(1))
            normalized = "%s %s" % (heading.group(1), heading.group(2))
            if normalized in wanted:
                active_level = level
                found.add(normalized)
            elif active_level is not None and level <= active_level:
                active_level = None
        if active_level is not None:
            selected.append(line)
    missing = wanted - found
    if missing:
        raise CapabilityError(
            "内嵌源码章节缺失: " + ", ".join(sorted(missing)))
    return "\n".join(selected).strip() + "\n"


def _adapt_embedded_method(body, maeflow):
    """Keep upstream methodology while removing its host-level orchestration."""
    embedded = 'python "%s" capability openspec -- ' % maeflow
    body = re.sub(
        r"(?m)^(\s*)openspec\s+",
        lambda match: match.group(1) + embedded,
        body)
    body = body.replace("`openspec ", "`" + embedded)

    # The pinned Comet skills assume they own the whole host and can discover
    # global Skill installations. Mae-Flow owns orchestration instead. Remove
    # only those bootstrap blocks; the phase methodology remains verbatim.
    body = re.sub(
        r"```(?:bash|sh)?\s*\n(?:(?!```).)*?"
        r"(?:COMET_ENV|Ensure the comet skill is installed)"
        r"(?:(?!```).)*?```\s*",
        "[Mae-Flow 已内嵌并校验 Comet 运行时，无需查找或安装外部 Skill。]\n",
        body,
        flags=re.S)
    command_prefixes = {
        r'"\$COMET_BASH"\s+"\$COMET_STATE"\s+':
            'python "%s" capability comet-state -- ' % maeflow,
        r'"\$COMET_BASH"\s+"\$COMET_GUARD"\s+':
            'python "%s" capability comet-guard -- ' % maeflow,
        r'"\$COMET_BASH"\s+"\$COMET_HANDOFF"\s+':
            'python "%s" capability comet-handoff -- ' % maeflow,
        r'"\$COMET_BASH"\s+"\$COMET_ARCHIVE"\s+':
            'python "%s" capability comet-archive -- ' % maeflow,
    }
    for pattern, replacement in command_prefixes.items():
        # A Windows plugin path such as ``C:\Users\...`` is not a valid
        # ``re.sub`` replacement string: the regex engine interprets ``\U``
        # and backreferences before inserting it. A callable replacement is
        # returned literally on every platform.
        body = re.sub(
            pattern,
            lambda _match, value=replacement: value,
            body)
    body = re.sub(
        r"```(?:bash|sh)?\s*\n(?:(?!```).)*?capability\s+comet-"
        r"(?:(?!```).)*?```\s*",
        "[状态初始化、校验和阶段迁移只执行 Mae-Flow 本步骤正文给出的命令。]\n",
        body,
        flags=re.S)
    body = re.sub(
        r'`python\s+"[^"]*mae-flow\.py"\s+capability\s+comet-[^`]+`',
        "Mae-Flow 本步骤正文中的状态命令",
        body)

    body = re.sub(
        r"(?<![\w.-])`?/(?:comet(?:-(?:open|design|build|verify|archive|hotfix|tweak))?"
        r"|opsx:[a-z-]+)`?",
        "Mae-Flow 对应步骤",
        body)
    body = re.sub(
        r"`?/ponytail\s+(?:lite\|full\|ultra|lite|full|ultra)`?",
        "使用 Mae-Flow 当前步骤已经指定的 Ponytail 档位",
        body,
        flags=re.I)

    # Upstream methods hand off through the host Skill registry. All referenced
    # open-source methods are already in this generated pack, so weak models
    # should continue locally instead of escaping to an external installation.
    body = re.sub(
        r"(?:使用 Skill 工具加载|内联加载)\s+(?:Superpowers\s+)?"
        r"`?([a-zA-Z0-9:_-]+)`?(?:\s*(?:技能|skill))?",
        r"直接执行本能力包中内嵌的 \1 方法",
        body)
    body = re.sub(
        r"(?i)\b(use|invoke|load|call)\s+(?:the\s+)?"
        r"(?:`[^`]+`|[a-z0-9:_-]+)\s+skill\b",
        "继续执行当前 Mae-Flow 步骤中已经内嵌的方法",
        body)
    body = body.replace(
        "`comet/reference/decision-point.md`",
        "Mae-Flow 当前步骤的用户确认协议")
    body = body.replace(
        "`comet/reference/debug-gate.md`",
        "Mae-Flow 当前步骤的系统化调试协议")
    body = body.replace(
        "`comet/reference/dirty-worktree.md`",
        "Mae-Flow 当前步骤的工作区保护规则")
    body = re.sub(
        r"`comet/reference/[^`]+`",
        "Mae-Flow 当前步骤的对应规则",
        body)
    body = body.replace(
        "`/<SKILL>`", "Mae-Flow 后续步骤")
    body = re.sub(
        r"^.*(?:技能|Skill).*不可用.*(?:安装|启用).*$",
        "[该方法已固定内嵌，不存在外部安装或启用分支。]",
        body,
        flags=re.M)
    superpower_routes = {
        "superpowers:using-git-worktrees": "Mae-Flow 已确认的分支隔离方式",
        "superpowers:subagent-driven-development": "Mae-Flow 本步骤已选定的执行方式",
        "superpowers:executing-plans": "当前能力包中的执行计划方法",
        "superpowers:finishing-a-development-branch": "Mae-Flow 后续验证与推送步骤",
    }
    for upstream, embedded_name in superpower_routes.items():
        body = body.replace(upstream, embedded_name)
    body = body.replace(
        "`skills/brainstorming/visual-companion.md`",
        "`%s`" % os.path.join(
            VENDOR_ROOT, "superpowers", "skills", "brainstorming",
            "visual-companion.md"))
    # 同款问题的其余三处:上游 SKILL 的目录内相对引用在渲染语境不可达,
    # 评审模板/调试支撑技术会退化成现场即兴。全部改写为 vendored 绝对路径。
    body = body.replace(
        "](code-reviewer.md)",
        "](%s)" % os.path.join(
            VENDOR_ROOT, "superpowers", "skills", "requesting-code-review",
            "code-reviewer.md"))
    for rel in ("root-cause-tracing.md", "defense-in-depth.md",
                "condition-based-waiting.md"):
        body = body.replace(
            "`%s`" % rel,
            "`%s`" % os.path.join(
                VENDOR_ROOT, "superpowers", "skills", "systematic-debugging", rel))
    return body


def render_pack(name):
    """Return the exact, pinned upstream instructions for one Mae-Flow phase."""
    entries = CAPABILITY_PACKS.get(name)
    if not entries:
        raise CapabilityError("未知内嵌能力包: " + str(name))
    sections = [
        "以下规则随 Mae-Flow 插件内嵌，当前会话已经加载。",
        "不要调用同名外部 Skill，不要安装插件，也不要执行 reload；"
        "直接把这些规则与本步骤上方更具体的公司约束一起执行。"
        "两者冲突时，以本步骤上方的 Mae-Flow 约束为准。",
    ]
    for entry in entries:
        title, relative = entry[:2]
        wanted_sections = entry[2] if len(entry) > 2 else None
        path = os.path.join(VENDOR_ROOT, *relative.split("/"))
        try:
            with open(path, encoding="utf-8") as stream:
                body = stream.read()
        except OSError as exc:
            raise CapabilityError("%s 缺失: %s" % (title, exc))
        maeflow = os.path.join(PLUGIN_ROOT, "scripts", "mae-flow.py")
        body = _extract_markdown_sections(
            _strip_frontmatter(body), wanted_sections)
        body = _adapt_embedded_method(body, maeflow)
        sections.extend(("\n## 内嵌能力：" + title, _strip_frontmatter(body).rstrip()))
    sections.extend((
        "\n## 内嵌方法收口",
        "上面的原始方法只提供本步骤需要的思考与执行纪律。不要按其中的“下一步”、"
        "“调用其他 Skill”或“结束工作流”自行跳转；完成后回到本步骤正文，"
        "由 `mae-flow.py done` 决定下一步。",
    ))
    return "\n".join(sections).rstrip()


def _run(command, cwd=None, timeout=120, env=None):
    try:
        return subprocess.run(
            command, cwd=cwd, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CapabilityError("%s: %s" % (" ".join(command), exc))


def _run_host_cli(command, timeout=120, windows=None):
    """Run a host CLI, respecting Windows npm/codecheck .cmd launch rules."""
    use_windows = os.name == "nt" if windows is None else bool(windows)
    kwargs = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout,
    }
    if (use_windows and command and str(command[0]).lower().endswith(
            (".cmd", ".bat"))):
        return subprocess.run(
            subprocess.list2cmdline(command), shell=True, **kwargs)
    return subprocess.run(command, **kwargs)


def _python():
    executable = os.path.abspath(sys.executable or "")
    if not executable or not os.path.isfile(executable):
        raise CapabilityError(
            "找不到当前 Python 解释器。请从能够正常运行 Python 3 的终端启动 CodeAgent。")
    if sys.version_info < (3, 8):
        raise CapabilityError(
            "Python 版本过低（当前 %s）；Mae-Flow 至少需要 Python 3.8。"
            % ".".join(str(item) for item in sys.version_info[:3]))
    return executable


def _git(windows=None):
    git = shutil.which("git") or shutil.which("git.exe")
    if git:
        return git
    use_windows = os.name == "nt" if windows is None else bool(windows)
    if use_windows:
        candidates = []
        for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            value = os.environ.get(variable, "")
            if not value:
                continue
            if variable == "LOCALAPPDATA":
                candidates.extend((
                    os.path.join(value, "Programs", "Git", "cmd", "git.exe"),
                    os.path.join(value, "Programs", "Git", "bin", "git.exe"),
                ))
            else:
                candidates.extend((
                    os.path.join(value, "Git", "cmd", "git.exe"),
                    os.path.join(value, "Git", "bin", "git.exe"),
                ))
        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate
    raise CapabilityError(
        "找不到 Git。Windows 请安装 Git for Windows，并确认 `git --version` 可执行。")


def _node(windows=None):
    node = shutil.which("node") or shutil.which("node.exe")
    if node:
        return node
    use_windows = os.name == "nt" if windows is None else bool(windows)
    if use_windows:
        candidates = []
        for variable in (
                "CODEAGENT_NODE_PATH", "NODE_EXE", "NVM_SYMLINK",
                "ProgramFiles", "LOCALAPPDATA"):
            value = os.environ.get(variable, "")
            if not value:
                continue
            if value.lower().endswith("node.exe"):
                candidates.append(value)
            elif variable == "NVM_SYMLINK":
                candidates.append(os.path.join(value, "node.exe"))
            elif variable == "ProgramFiles":
                candidates.append(os.path.join(value, "nodejs", "node.exe"))
            elif variable == "LOCALAPPDATA":
                candidates.append(os.path.join(
                    value, "Programs", "nodejs", "node.exe"))
        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate
    raise CapabilityError(
        "找不到 Node.js。CodeAgent 本身通常已经携带或依赖 Node；"
        "请确认启动 CodeAgent 的终端中 `node --version` 可执行。")


def _bash(windows=None):
    bash = shutil.which("bash") or shutil.which("bash.exe")
    if bash:
        return bash
    use_windows = os.name == "nt" if windows is None else bool(windows)
    if use_windows:
        candidates = []
        try:
            git = _git(windows=True)
            git_dir = os.path.dirname(os.path.abspath(git))
            candidates.extend((
                os.path.normpath(os.path.join(git_dir, "..", "bin", "bash.exe")),
                os.path.normpath(os.path.join(
                    git_dir, "..", "usr", "bin", "bash.exe")),
            ))
        except CapabilityError:
            pass
        for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            value = os.environ.get(variable, "")
            if not value:
                continue
            candidates.append(os.path.join(value, "Git", "bin", "bash.exe"))
            if variable == "LOCALAPPDATA":
                candidates.append(os.path.join(
                    value, "Programs", "Git", "bin", "bash.exe"))
        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate
    raise CapabilityError(
        "找不到 Git Bash。项目开发需要 Git，Windows 请确认 Git for Windows 的 bash.exe 在 PATH。")


def _version_detail(executable, arguments):
    result = _run([executable, *arguments], timeout=30)
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    first_line = output.splitlines()[0].strip() if output else "未返回版本信息"
    if result.returncode != 0:
        raise CapabilityError(
            "%s %s 执行失败（退出码 %s）: %s" % (
                executable, " ".join(arguments), result.returncode,
                first_line))
    return "%s — %s" % (first_line, os.path.abspath(executable))


def _host_runtime_checks():
    """Probe the small host runtime Mae-Flow actually depends on."""
    checks = []

    def probe(key, name, resolver, arguments=None, detail=None):
        try:
            executable = resolver()
            rendered = detail(executable) if detail else _version_detail(
                executable, arguments or [])
            checks.append({
                "key": key,
                "name": name,
                "ok": True,
                "detail": rendered,
                "path": executable,
            })
        except CapabilityError as exc:
            checks.append({
                "key": key,
                "name": name,
                "ok": False,
                "detail": str(exc),
                "path": "",
            })

    probe(
        "python", "Python", _python,
        detail=lambda executable: "Python %s — %s" % (
            ".".join(str(item) for item in sys.version_info[:3]),
            executable))
    probe("git", "Git", _git, ["--version"])
    probe("node", "Node.js", _node, ["--version"])
    probe("bash", "Git Bash", _bash, ["--version"])
    return checks


def _require_host_runtime():
    checks = _host_runtime_checks()
    failed = [item for item in checks if not item["ok"]]
    if failed:
        raise CapabilityError(
            "基础依赖不可用: " + "；".join(
                "%s: %s" % (item["name"], item["detail"])
                for item in failed))
    return {item["key"]: item for item in checks}


def run_openspec(arguments, cwd=None, timeout=120):
    if not os.path.isfile(OPENSPEC_ENTRY):
        raise CapabilityError("插件内嵌 OpenSpec 运行时缺失: " + OPENSPEC_ENTRY)
    env = os.environ.copy()
    env.setdefault("DO_NOT_TRACK", "1")
    env.setdefault("OPENSPEC_TELEMETRY", "0")
    return _run([_node(), OPENSPEC_ENTRY, *arguments], cwd=cwd, timeout=timeout, env=env)


def run_comet(script_name, arguments, cwd=None, timeout=180):
    names = {
        "state": "comet-state.sh",
        "guard": "comet-guard.sh",
        "handoff": "comet-handoff.sh",
        "archive": "comet-archive.sh",
        "validate": "comet-yaml-validate.sh",
    }
    filename = names.get(script_name)
    if not filename:
        raise CapabilityError("未知 Comet 内嵌脚本: " + str(script_name))
    script = os.path.join(COMET_SCRIPT_ROOT, filename)
    if not os.path.isfile(script):
        raise CapabilityError("插件内嵌脚本缺失: " + script)
    env = os.environ.copy()
    env.update({
        "COMET_BASH": _bash(),
        "COMET_STATE": os.path.join(COMET_SCRIPT_ROOT, "comet-state.sh"),
        "COMET_GUARD": os.path.join(COMET_SCRIPT_ROOT, "comet-guard.sh"),
        "COMET_HANDOFF": os.path.join(COMET_SCRIPT_ROOT, "comet-handoff.sh"),
        "COMET_ARCHIVE": os.path.join(COMET_SCRIPT_ROOT, "comet-archive.sh"),
        "COMET_OPENSPEC": os.path.join(PLUGIN_ROOT, "runtime", "bin", "openspec"),
        "MAE_FLOW_NODE": _node(),
        "DO_NOT_TRACK": "1",
        "OPENSPEC_TELEMETRY": "0",
    })
    # 维护者修复逃生口不能从调用方环境静默继承:带着它,comet-state 的
    # phase 直写保护(transition 前置校验)会被整体绕过。
    env.pop("COMET_FORCE_PHASE", None)
    return _run([env["COMET_BASH"], script, *arguments],
                cwd=cwd, timeout=timeout, env=env)


def configure_comet_build(change_name, cwd=None):
    """Write Mae-Flow's fixed full-workflow build choices deterministically."""
    decisions = (
        ("isolation", "branch"),
        ("build_mode", "executing-plans"),
        ("subagent_dispatch", "null"),
        ("tdd_mode", "direct"),
        ("direct_override", "true"),
        ("review_mode", "standard"),
    )
    applied = []
    for field, value in decisions:
        result = run_comet(
            "state", ["set", change_name, field, value], cwd=cwd, timeout=60)
        if result.returncode:
            detail = ((result.stdout or "") + (result.stderr or "")).strip()
            raise CapabilityError(
                "写入构建约定失败(%s=%s): %s" % (
                    field, value, detail[-1000:]))
        applied.append({"field": field, "value": value})
    return applied


def _ensure_yaml_scalar(path, key, value):
    if os.path.isfile(path):
        with open(path, encoding="utf-8", errors="replace") as stream:
            text = stream.read()
    else:
        text = ""
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    pattern = re.compile(r"^%s\s*:" % re.escape(key))
    positions = [i for i, line in enumerate(lines) if pattern.match(line)]
    wanted = "%s: %s" % (key, value)
    if positions:
        first = positions[0]
        lines[first] = wanted
        duplicates = set(positions[1:])
        lines = [line for i, line in enumerate(lines) if i not in duplicates]
    else:
        lines.append(wanted)
    updated = newline.join(lines).rstrip() + newline
    if updated != text:
        atomic_write_text(path, updated)


def prepare_project(project_root):
    """Prepare deterministic project metadata before flow state is activated.

    This operation deliberately creates no ``.cac``/``.claude`` content and does
    not install global packages.  Failure occurs before ``.mae-flow.json`` exists,
    so Hooks remain in their normal fail-open inactive mode.
    """
    root = os.path.abspath(project_root)
    runtime = _require_host_runtime()
    if not os.path.isdir(root):
        raise CapabilityError("项目目录不存在: " + root)
    if not os.path.exists(os.path.join(root, ".git")):
        raise CapabilityError("当前目录不是 Git 项目根（缺少 .git）: " + root)
    git_root = _run(
        [runtime["git"]["path"], "-C", root, "rev-parse", "--show-toplevel"],
        timeout=30)
    discovered_root = (git_root.stdout or "").strip().splitlines()
    if git_root.returncode != 0 or not discovered_root:
        raise CapabilityError(
            "Git 仓库检查失败: "
            + ((git_root.stdout or "") + (git_root.stderr or "")).strip()[-600:])
    actual_root = os.path.abspath(discovered_root[-1])
    if os.path.normcase(os.path.realpath(actual_root)) != os.path.normcase(
            os.path.realpath(root)):
        raise CapabilityError(
            "请在 Git 项目根目录启动 Mae-Flow。当前目录: %s；项目根: %s"
            % (root, actual_root))

    version = run_openspec(["--version"], cwd=root, timeout=30)
    if version.returncode != 0 or "1.6.0" not in (version.stdout + version.stderr):
        raise CapabilityError(
            "插件内嵌 OpenSpec 自检失败: "
            + (version.stdout + version.stderr).strip()[-600:])

    config = os.path.join(root, "openspec", "config.yaml")
    if not os.path.isfile(config):
        result = run_openspec(
            ["init", root, "--tools", "none", "--profile", "core"],
            cwd=root, timeout=90)
        if result.returncode != 0 or not os.path.isfile(config):
            raise CapabilityError(
                "无法创建项目规格目录: "
                + (result.stdout + result.stderr).strip()[-1200:])

    comet_config = os.path.join(root, ".comet", "config.yaml")
    os.makedirs(os.path.dirname(comet_config), exist_ok=True)
    _ensure_yaml_scalar(comet_config, "auto_transition", "false")
    _ensure_yaml_scalar(comet_config, "review_mode", "standard")
    _ensure_yaml_scalar(comet_config, "context_compression", "off")

    return {
        "openspec": "1.6.0",
        "comet": "0.3.9-embedded",
        "project": root,
        "python": runtime["python"]["detail"],
        "git": runtime["git"]["detail"],
        "node": runtime["node"]["detail"],
        "bash": runtime["bash"]["detail"],
        "created_project_skills": False,
    }


def _probe_codecheck(path):
    if not path:
        return False, ""
    command = [path, "fullcheck", "--help"]
    try:
        result = _run_host_cli(command, timeout=45)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    output = (result.stdout or "") + (result.stderr or "")
    return "fullcheck" in output.lower(), output.strip()


def locate_codecheck():
    candidates = []
    direct = shutil.which("codecheck") or shutil.which("codecheck.cmd")
    if direct:
        candidates.append(direct)
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(os.path.join(appdata, "npm", "codecheck.cmd"))
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if npm:
        try:
            probe = _run_host_cli([npm, "prefix", "-g"], timeout=30)
            prefix = (probe.stdout or "").strip()
            if prefix:
                if os.name == "nt":
                    candidates.append(os.path.join(prefix, "codecheck.cmd"))
                else:
                    candidates.append(os.path.join(prefix, "bin", "codecheck"))
        except (OSError, subprocess.TimeoutExpired):
            pass
    seen = set()
    for candidate in candidates:
        key = os.path.normcase(os.path.abspath(candidate))
        if key in seen or not os.path.isfile(candidate):
            continue
        seen.add(key)
        ok, output = _probe_codecheck(candidate)
        if ok:
            return os.path.abspath(candidate), output
    return "", ""


def _capability_state_path():
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".mae-flow")
    return os.path.join(base, "mae-flow", "capabilities.json")


def _tree_sha256(path):
    digest = hashlib.sha256()
    files = []
    for base, directories, names in os.walk(path):
        directories.sort()
        files.extend(os.path.join(base, name) for name in names)
    files.sort(key=lambda item: os.path.relpath(
        item, path).replace(os.sep, "/"))
    for filename in files:
        relative = os.path.relpath(filename, path).replace(os.sep, "/")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with open(filename, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def ensure_codecheck(install=True):
    """Locate CodeCheck and, when requested, make one best-effort install."""
    path, output = locate_codecheck()
    if path:
        return {"available": True, "path": path, "installed": False,
                "detail": output[-500:]}
    if not install:
        return {"available": False, "path": "", "installed": False,
                "detail": "未找到 codecheck/fullcheck"}

    # A failed internal-registry install can be slow. Do not repeat it at every
    # scan/done gate; a manual install is still detected by locate_codecheck
    # above. The next process may retry after the short cooling window.
    state_path = _capability_state_path()
    try:
        with open(state_path, encoding="utf-8") as stream:
            previous = json.load(stream)
        stamp = time.mktime(time.strptime(
            previous.get("attempted_at", ""), "%Y-%m-%d %H:%M:%S"))
        if not previous.get("available") and time.time() - stamp < 1800:
            previous["cooldown"] = True
            return previous
    except (OSError, ValueError, TypeError):
        pass

    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        return {"available": False, "path": "", "installed": False,
                "detail": "未找到 npm，无法自动安装公司 CodeCheck CLI"}
    command = [
        npm, "install", "-g", CODECHECK_PACKAGE,
        "--registry=" + CODECHECK_REGISTRY,
    ]
    try:
        result = _run_host_cli(command, timeout=600)
        install_output = ((result.stdout or "") + (result.stderr or "")).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        install_output = str(exc)
        result = None

    path, probe_output = locate_codecheck()
    record = {
        "available": bool(path),
        "path": path,
        "installed": bool(path),
        "attempted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "package": CODECHECK_PACKAGE,
        "detail": (probe_output if path else install_output)[-2000:],
    }
    try:
        atomic_write_json(state_path, record)
    except OSError:
        pass
    return record


def diagnostics(project_root=None, include_codecheck=False):
    checks = []

    def add(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)})

    for runtime_check in _host_runtime_checks():
        add(
            runtime_check["name"],
            runtime_check["ok"],
            runtime_check["detail"])
    add("内嵌 OpenSpec", os.path.isfile(OPENSPEC_ENTRY), OPENSPEC_ENTRY)
    add("内嵌 Comet 脚本", os.path.isfile(
        os.path.join(COMET_SCRIPT_ROOT, "comet-state.sh")), COMET_SCRIPT_ROOT)
    for pack in sorted(CAPABILITY_PACKS):
        try:
            render_pack(pack)
            add("内嵌规则 " + pack, True, "已加载")
        except CapabilityError as exc:
            add("内嵌规则 " + pack, False, exc)
    try:
        result = run_openspec(["--version"], cwd=project_root, timeout=30)
        add("OpenSpec 可执行", result.returncode == 0 and "1.6.0" in result.stdout,
            (result.stdout + result.stderr).strip())
    except CapabilityError as exc:
        add("OpenSpec 可执行", False, exc)
    if include_codecheck:
        codecheck = ensure_codecheck(install=False)
        add("CodeCheck", codecheck["available"], codecheck["detail"])
    if os.path.isfile(MANIFEST_PATH):
        try:
            with open(MANIFEST_PATH, encoding="utf-8") as stream:
                manifest = json.load(stream)
            add("版本清单", manifest.get("schema") == 1, MANIFEST_PATH)
            for component, metadata in sorted(
                    manifest.get("components", {}).items()):
                expected = metadata.get("sha256", "")
                component_root = os.path.join(VENDOR_ROOT, component)
                actual = _tree_sha256(component_root) if os.path.isdir(
                    component_root) else ""
                add(
                    "源码完整性 " + component,
                    bool(expected) and actual == expected,
                    "sha256=" + (actual or "missing"))
        except (OSError, ValueError) as exc:
            add("版本清单", False, exc)
    else:
        add("版本清单", False, MANIFEST_PATH)
    wrapper = os.path.join(PLUGIN_ROOT, "runtime", "bin", "openspec")
    add("OpenSpec 脚本入口", os.path.isfile(wrapper) and os.access(
        wrapper, os.X_OK), wrapper)
    return checks
