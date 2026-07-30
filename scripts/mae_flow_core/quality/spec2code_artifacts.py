"""Pure contracts for local Spec2Code process artifacts."""

import re


_TICKET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_CP_RE = re.compile(r"^CP[1-6]$")
_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)
_COMMENT_PLAN_RE = re.compile(
    r"注释计划[：:]\s*(?:ADD|UPDATE|REMOVE|NONE)[：:]",
)

_BLUEPRINT_FIELDS = (
    "规格来源",
    "测试目的",
    "输入与前置状态",
    "执行动作",
    "可观察结果",
    "必须不存在的副作用",
    "分类",
    "建议测试层级",
    "允许替代的依赖",
    "必须使用真实组件的依赖",
    "禁止依赖的实现细节",
)
_ROADMAP_FIELDS = (
    "业务目标",
    "完成合同",
    "明确非目标",
    "Scenario 归属",
    "主要模块职责",
    "状态所有权",
    "前序接口",
    "后续接口",
    "延后事项及具体落点",
    "关键风险",
)
_PLAN_FIELDS = (
    "所属 CP",
    "目标",
    "创建/修改文件",
    "目标类、函数或接口",
    "精确函数签名",
    "输入、输出与错误语义",
    "主要控制流约束",
    "状态所有权",
    "必须复用",
    "禁止事项",
    "注释计划",
    "对应 UT 蓝图场景",
    "完成后的定向检查",
)
_REVIEW_FIELDS = (
    "位置",
    "依据",
    "证据",
    "实际影响",
    "最小改法",
    "处置",
    "状态",
)
_DISPOSITIONS = ("修改", "验证后修改", "人工裁决", "拒绝/暂缓")
_REVIEW_STATUSES = ("待处理", "已解决", "已拒绝")


def _safe(value, pattern, label):
    text = str(value or "")
    if not pattern.fullmatch(text) or ".." in text or "/" in text or "\\" in text:
        raise ValueError("%s 不安全: %s" % (label, text or "(空)"))
    return text


def artifact_path(kind, ticket, checkpoint="", mode=""):
    """Return the canonical git-ignored path for one process artifact."""
    ticket = _safe(ticket, _TICKET_RE, "单号")
    if kind == "blueprint":
        return ".mae-flow-work/test-blueprint-%s.md" % ticket
    if kind == "roadmap":
        return ".mae-flow-work/roadmap-%s.md" % ticket
    if kind == "plan":
        return ".mae-flow-work/plan-%s.md" % ticket
    if kind != "review":
        raise ValueError("未知过程件类型: " + str(kind))
    checkpoint = _safe(checkpoint, _CP_RE, "检查点")
    if mode not in ("plan", "code"):
        raise ValueError("review mode 只能是 plan 或 code")
    return ".mae-flow-work/reviews/%s/%s-%s.md" % (
        ticket,
        checkpoint,
        mode,
    )


def _sections(text, prefix):
    matches = list(_SECTION_RE.finditer(str(text or "")))
    return [
        (
            match.group(1).strip(),
            str(text or "")[
                match.end():(
                    matches[index + 1].start()
                    if index + 1 < len(matches)
                    else len(str(text or ""))
                )
            ],
        )
        for index, match in enumerate(matches)
        if match.group(1).strip().startswith(prefix)
    ]


def _required_fields(body, fields, label):
    return [
        "%s 缺少字段：%s" % (label, field)
        for field in fields
        if not re.search(r"(?:^|\n)\s*-\s*%s[：:]" % re.escape(field), body)
    ]


def validate_blueprint(text):
    errors = []
    scenarios = _sections(text, "Scenario:")
    if not scenarios:
        errors.append("UT 蓝图至少需要一个 ## Scenario: <ID>")
    for title, body in scenarios:
        errors.extend(_required_fields(body, _BLUEPRINT_FIELDS, title))
    return tuple(errors)


def validate_roadmap(text):
    errors = []
    checkpoints = [
        item for item in _sections(text, "CP")
        if re.match(r"CP[1-6](?:\s*[:：]|$)", item[0])
    ]
    if not checkpoints:
        errors.append("路线图至少需要一个 ## CPn")
    for title, body in checkpoints:
        errors.extend(_required_fields(body, _ROADMAP_FIELDS, title))
        deferral = re.search(
            r"(?:^|\n)\s*-\s*延后事项及具体落点[：:](.+)",
            body,
        )
        value = deferral.group(1) if deferral else ""
        if value and "无" not in value and not re.search(
                r"CP[1-6].*Task\s+[A-Za-z0-9._-]+", value):
            errors.append("%s 延后事项必须指向具体 CP/Task" % title)
    return tuple(errors)


def validate_plan(text, checkpoint=""):
    errors = []
    tasks = _sections(text, "Task ")
    if not tasks:
        errors.append("实现计划至少需要一个 ## Task <ID>")
    for title, body in tasks:
        errors.extend(_required_fields(body, _PLAN_FIELDS, title))
        if checkpoint and not re.search(
                r"(?:^|\n)\s*-\s*所属 CP[：:]\s*%s(?:[。\s]|$)"
                % re.escape(checkpoint),
                body):
            errors.append("%s 不属于当前检查点 %s" % (title, checkpoint))
        if "注释计划" in body and not _COMMENT_PLAN_RE.search(body):
            errors.append(
                "%s 注释计划必须使用 ADD/UPDATE/REMOVE/NONE" % title)
    return tuple(errors)


def _review_findings(text):
    return _sections(text, "Finding ")


def validate_review(text, mode, checkpoint):
    errors = []
    if str(mode).lower() not in ("plan", "code"):
        errors.append("Reviewer 模式只能是 PLAN 或 CODE")
    if not _CP_RE.fullmatch(str(checkpoint or "")):
        errors.append("Reviewer 检查点必须是 CP1-CP6")
    findings = _review_findings(text)
    if len(findings) > 5:
        errors.append("Reviewer 每轮最多五条发现")
    for title, body in findings:
        errors.extend(_required_fields(body, _REVIEW_FIELDS, title))
        disposition = re.search(
            r"(?:^|\n)\s*-\s*处置[：:]\s*(.+?)\s*$", body, re.M)
        if disposition and disposition.group(1).rstrip("。") not in _DISPOSITIONS:
            errors.append("%s 处置值无效" % title)
        status = re.search(
            r"(?:^|\n)\s*-\s*状态[：:]\s*(.+?)\s*$", body, re.M)
        if status and status.group(1).rstrip("。") not in _REVIEW_STATUSES:
            errors.append("%s 状态值无效" % title)
    return tuple(errors)


def review_requires_rework(text):
    """Return whether any accepted finding remains unresolved."""
    for _title, body in _review_findings(text):
        disposition = re.search(
            r"(?:^|\n)\s*-\s*处置[：:]\s*(.+?)\s*$", body, re.M)
        status = re.search(
            r"(?:^|\n)\s*-\s*状态[：:]\s*(.+?)\s*$", body, re.M)
        disposition_value = (
            disposition.group(1).rstrip("。") if disposition else "")
        status_value = status.group(1).rstrip("。") if status else ""
        if (
            disposition_value in ("修改", "验证后修改", "人工裁决")
            and status_value == "待处理"
        ):
            return True
    return False
