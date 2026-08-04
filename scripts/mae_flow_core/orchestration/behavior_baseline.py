"""Relevant-only domain context and durable documentation reconciliation."""

from dataclasses import dataclass
import os
import re


_DOMAIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL", "INDEX"}
    | {"COM%d" % number for number in range(1, 10)}
    | {"LPT%d" % number for number in range(1, 10)}
)
REQUIRED_DOMAIN_SECTIONS = (
    "领域目标与边界",
    "核心术语与不变量",
    "可观察行为与业务规则",
    "对外及跨组件契约",
    "数据、状态与兼容性",
    "性能、容量与资源限制",
    "异常、降级与恢复",
    "验证方式与测试关注点",
    "代码落点索引",
    "明确不包含的范围",
)
_PLACEHOLDER_CONTENT = frozenset({
    "", "无", "暂无", "待定", "待补充", "todo", "tbd", "n/a", "na",
})


@dataclass(frozen=True)
class DomainDocument:
    domain: str
    keywords: tuple
    path: str
    content: str


@dataclass(frozen=True)
class DomainContext:
    index_path: str
    documents: tuple


@dataclass(frozen=True)
class ReconcileResult:
    domain: str
    path: str
    absolute_path: str
    action: str
    content: str

    @property
    def manifest_eligible(self):
        return self.action in {"new", "updated"}


def _domain_name(domain):
    value = str(domain or "").strip()
    if (
            not _DOMAIN.fullmatch(value)
            or value.split(".", 1)[0].upper() in _RESERVED):
        raise ValueError("domain must be one portable docs/specs name")
    return value


def _read(path):
    try:
        with open(path, encoding="utf-8") as stream:
            return stream.read()
    except OSError:
        return ""


def _index_rows(content):
    rows = []
    domains = {}
    keyword_owners = {}
    for line_number, line in enumerate(content.splitlines(), 1):
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 3 or cells[0] in {"领域", "Domain", "---"}:
            continue
        if set(cells[0]) == {"-"}:
            continue
        try:
            domain = _domain_name(cells[0])
        except ValueError as exc:
            raise ValueError(
                "领域索引第 %d 行的领域名无效: %s" % (line_number, exc))
        expected = "docs/specs/%s.md" % domain
        if cells[2].replace("\\", "/") != expected:
            raise ValueError(
                "领域索引第 %d 行路径必须是 %s" % (line_number, expected))
        keywords = tuple(
            keyword.strip() for keyword in cells[1].split(",")
            if keyword.strip())
        if not keywords:
            raise ValueError("领域索引第 %d 行至少需要一个关键词" % line_number)
        folded_domain = domain.casefold()
        if folded_domain in domains:
            raise ValueError(
                "领域索引第 %d 行重复定义领域 %s" % (line_number, domain))
        domains[folded_domain] = line_number
        for keyword in keywords:
            folded_keyword = keyword.casefold()
            owner = keyword_owners.get(folded_keyword)
            if owner is not None and owner != folded_domain:
                raise ValueError(
                    "领域索引第 %d 行关键词 %s 已由其他领域使用"
                    % (line_number, keyword))
            keyword_owners[folded_keyword] = folded_domain
        rows.append((domain, keywords, expected))
    return tuple(rows)


def validate_domain_document(content):
    """Return deterministic validation errors for one durable domain truth."""
    if not isinstance(content, str) or not content.strip():
        return ("领域文档不能为空",)
    headings = {}
    current = None
    body = []
    for line in content.splitlines():
        match = re.match(r"^##\s+(?:\d+[.、]\s*)?(.+?)\s*$", line)
        if match:
            if current is not None:
                headings[current] = "\n".join(body).strip()
            current = match.group(1).strip()
            body = []
        elif current is not None:
            body.append(line)
    if current is not None:
        headings[current] = "\n".join(body).strip()
    errors = []
    for section in REQUIRED_DOMAIN_SECTIONS:
        value = headings.get(section, "").strip()
        compact = re.sub(r"[\s`*_#>-]+", "", value).casefold()
        if section not in headings:
            errors.append("缺少章节: %s" % section)
        elif compact in _PLACEHOLDER_CONTENT or len(compact) < 8:
            errors.append("章节内容不完整: %s" % section)
    return tuple(errors)


def load_relevant_domain_context(project_root, terms):
    root = os.path.abspath(os.fspath(project_root))
    index = os.path.join(root, "docs", "specs", "index.md")
    query = "\n".join(str(term) for term in terms).casefold()
    documents = []
    for domain, keywords, relative in _index_rows(_read(index)):
        absolute = os.path.join(root, *relative.split("/"))
        if not os.path.isfile(absolute):
            raise ValueError("领域索引引用的文档不存在: %s" % relative)
        if keywords and not any(
                keyword.casefold() in query for keyword in keywords):
            continue
        content = _read(absolute)
        if content:
            documents.append(DomainDocument(
                domain=domain,
                keywords=keywords,
                path=relative,
                content=content,
            ))
    return DomainContext(
        index_path="docs/specs/index.md",
        documents=tuple(documents),
    )


def plan_domain_reconciliation(project_root, domain, candidate_content):
    name = _domain_name(domain)
    if not isinstance(candidate_content, str) or not candidate_content.strip():
        raise ValueError("domain candidate must be non-empty text")
    relative = "docs/specs/%s.md" % name
    absolute = os.path.join(
        os.path.abspath(os.fspath(project_root)), *relative.split("/"))
    current = _read(absolute)
    action = (
        "new" if not current
        else "unchanged" if current == candidate_content
        else "updated"
    )
    return ReconcileResult(
        domain=name,
        path=relative,
        absolute_path=absolute,
        action=action,
        content=candidate_content,
    )


def apply_domain_reconciliation(result, keywords=()):
    if not isinstance(result, ReconcileResult):
        raise TypeError("result must be a ReconcileResult")
    if result.action == "unchanged":
        return result
    os.makedirs(os.path.dirname(result.absolute_path), exist_ok=True)
    temporary = result.absolute_path + ".tmp-%s" % os.getpid()
    try:
        with open(temporary, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(result.content)
        os.replace(temporary, result.absolute_path)
    finally:
        try:
            if os.path.exists(temporary):
                os.unlink(temporary)
        except OSError:
            pass
    _ensure_index_entry(
        os.path.dirname(result.absolute_path), result.domain, keywords)
    return result


def _ensure_index_entry(specs_root, domain, keywords):
    index = os.path.join(specs_root, "index.md")
    content = _read(index)
    rows = _index_rows(content)
    if any(row[0].casefold() == domain.casefold() for row in rows):
        return
    if not content.strip():
        content = (
            "# 领域文档索引\n\n"
            "| 领域 | 关键词 | 文档 |\n"
            "| --- | --- | --- |\n"
        )
    keyword_text = ", ".join(
        str(keyword).strip() for keyword in keywords if str(keyword).strip())
    keyword_text = keyword_text or domain
    content = content.rstrip() + (
        "\n| %s | %s | docs/specs/%s.md |\n"
        % (domain, keyword_text, domain))
    temporary = index + ".tmp-%s" % os.getpid()
    try:
        with open(temporary, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        os.replace(temporary, index)
    finally:
        try:
            if os.path.exists(temporary):
                os.unlink(temporary)
        except OSError:
            pass
