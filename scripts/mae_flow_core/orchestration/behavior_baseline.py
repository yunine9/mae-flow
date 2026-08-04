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
    for line in content.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 3 or cells[0] in {"领域", "Domain", "---"}:
            continue
        if set(cells[0]) == {"-"}:
            continue
        domain = _domain_name(cells[0])
        expected = "docs/specs/%s.md" % domain
        if cells[2].replace("\\", "/") != expected:
            continue
        keywords = tuple(
            keyword.strip() for keyword in cells[1].split(",")
            if keyword.strip())
        rows.append((domain, keywords, expected))
    return tuple(rows)


def load_relevant_domain_context(project_root, terms):
    root = os.path.abspath(os.fspath(project_root))
    index = os.path.join(root, "docs", "specs", "index.md")
    query = "\n".join(str(term) for term in terms).casefold()
    documents = []
    for domain, keywords, relative in _index_rows(_read(index)):
        if keywords and not any(
                keyword.casefold() in query for keyword in keywords):
            continue
        absolute = os.path.join(root, *relative.split("/"))
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
