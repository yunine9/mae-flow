# -*- coding: utf-8 -*-
"""OpenSpec CLI 内化：spec-driven 工作流的纯 Python 引擎。

行为真相源是插件内嵌的 Node CLI（openspec 1.6.0，
``runtime/vendor/openspec/dist/core/artifact-graph/openspec.mjs``）。
本模块把其中 Mae-Flow 实际用到的五个能力重写为纯 Python：

- ``ensure_config``  —— 对应 ``openspec init``（只保留目录 + config.yaml 部分）
- ``new_change``     —— 对应 ``openspec new change <name>``
- ``instructions``   —— 对应 ``openspec instructions <artifact> --change <name>``
- ``validate``       —— 对应 ``openspec validate <change>``（默认非 strict）
- ``archive``        —— 对应 ``openspec archive <change> --yes``
- ``status``         —— 对应 ``openspec status --change <name>`` 的核心信息

对拍纪律（tests/test_specengine.py 差分测试保证）：

- 校验宽严与 CLI 完全一致——CLI 放过的不拦、CLI 拦的必拦；
- archive 合并后的 ``openspec/`` 目录树与 CLI 逐字节一致（统一行尾后比较）；
- 错误“文案”用中文重写（可执行、指到文件与块），但触发条件与 CLI 相同。

与 CLI 的已知刻意差异（均有依据，详见各处注释）：

1. 半成功免疫：CLI 在 spec 合并写盘“之后”才检查归档目标是否已存在，
   目标冲突时会留下 specs 已改、change 未移走的半成功现场（旧
   comet-archive 的实战痛点）。本引擎把该检查提前到任何写盘之前，
   并对写盘失败做回滚——要么全成，要么原样，可重跑。
2. change 名称校验采用接口契约给定的 ``^[a-zA-Z0-9_-]+$``（与
   comet-archive.sh 的 validate_change_name 相同），比 CLI 的
   kebab-case 规则宽（CLI 拒绝大写与下划线）。Mae-Flow 的 change 名
   历史上允许下划线，收紧会破坏既有流程；引擎自身闭环后不再依赖
   CLI 对名称的接受度。
3. 吸收 comet-archive.sh 的 ``verify_main_specs_clean`` 语义：归档前
   预检所有主 specs 不得残留 ``## ADDED/MODIFIED/... Requirements``
   字样（CLI 只检查本次触达的域）。CLI+comet 组合下污染现场会在归档
   “之后”FATAL；引擎把它提前为归档前拒绝，避免又一种半成功。

v5 轻量布局（本插件自有，上游 CLI 无此概念）：change 目录只有一个四合一
change.md（# 为什么 / # 规格条目：<域> / # 方案 / # 实现清单），规格条目
节体=标准 delta spec 原格式。delta 解析与合并核心（_parse_delta_spec /
_build_updated_spec）对两种布局完全同一份代码，v5 只改"内容从哪来"
（specs/<域>/spec.md 文件 → change.md 的规格条目节）与 new_change 的产物
（.openspec.yaml → change.md 骨架）。布局按 change.md 存在性探测；两种
布局标志并存判混用拒绝。上面的对拍纪律只约束 legacy 路径（CLI 不认识
v5）；v5 的守护是等价性测试——同一 delta 内容在两种布局下归档，主 specs
真相源必须逐字节一致。

Windows 军规：对外返回的路径一律正斜杠归一；写盘统一走
``state_store.atomic_write_text``（tmp + os.replace + 杀软重试）；
不使用 ``os.path.relpath`` 做任何可能跨盘的换算。
"""

import os
import re
import shutil
import time
from datetime import datetime, timezone

from .state_store import atomic_write_text

PLUGIN_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
VENDOR_SCHEMAS_DIR = os.path.join(
    PLUGIN_ROOT, "runtime", "vendor", "openspec", "schemas")
DEFAULT_SCHEMA = "spec-driven"

# CLI 的 SHALL/MUST 检查是无 u 标志的 JS 正则 \b(SHALL|MUST)\b，
# 词边界按 ASCII 词字符判定。Python 默认 \b 按 Unicode（汉字算词字符，
# “系统SHALL支持”会判不中），必须加 re.ASCII 才与 CLI 等价。
_SHALL_RE = re.compile(r"\b(SHALL|MUST)\b", re.ASCII)
# delta spec 里的 requirement 头（### 后允许无空格，大小写不敏感）。
_REQ_HEADER_RE = re.compile(r"^###\s*Requirement:\s*(.+)\s*$", re.I)
# 主 spec 结构检查用的 requirement 头（### 后必须有空白，与 CLI 两处正则的差异一致）。
_REQ_HEADER_STRICT_RE = re.compile(r"^###\s+Requirement:\s*(.+)\s*$", re.I)
_REQUIREMENTS_SECTION_RE = re.compile(r"^##\s+Requirements\s*$", re.I)
_TOP_LEVEL_SECTION_RE = re.compile(r"^##\s+")
_DELTA_HEADER_RE = re.compile(
    r"^##\s+(ADDED|MODIFIED|REMOVED|RENAMED)\s+Requirements\s*$", re.I)
# archive 判断“是否存在 delta spec”的探测正则（区分大小写、无行尾锚，与 CLI 一致）。
_HAS_DELTA_RE = re.compile(
    r"^##\s+(ADDED|MODIFIED|REMOVED|RENAMED)\s+Requirements", re.M)
# comet verify_main_specs_clean 的泄漏检查（区分大小写、精确行）。
_LEAK_RE = re.compile(r"^## (ADDED|MODIFIED|REMOVED|RENAMED) Requirements$", re.M)
_SCENARIO_ANY_RE = re.compile(r"^####\s+")            # 计数场景：任意四井号头
_SCENARIO_NAMED_RE = re.compile(r"^####\s*Scenario:\s*(.+)\s*$")  # 场景名（区分大小写）
_METADATA_LINE_RE = re.compile(r"^\*\*[^*]+\*\*:")
_HEADER_LINE_RE = re.compile(r"^#{1,6}\s")
_ANY_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_SECTION_H2_RE = re.compile(r"^(##)\s+(.+)$")
_REMOVED_BULLET_RE = re.compile(r"^\s*-\s*`?###\s*Requirement:\s*(.+?)`?\s*$")
_RENAME_FROM_RE = re.compile(r"^\s*-?\s*FROM:\s*`?###\s*Requirement:\s*(.+?)`?\s*$")
_RENAME_TO_RE = re.compile(r"^\s*-?\s*TO:\s*`?###\s*Requirement:\s*(.+?)`?\s*$")
_TASK_RE = re.compile(r"^[-*]\s+\[[\sx]\]", re.I)
_TASK_DONE_RE = re.compile(r"^[-*]\s+\[x\]", re.I)
_CHANGE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# ``openspec init`` 写出的 config.yaml 模板（serializeConfig 的逐行镜像；
# 该模板在 CLI 里同样是代码内嵌常量，不属于“禁止硬编码”的指令正文）。
_CONFIG_TEMPLATE_LINES = (
    "schema: %s",
    "",
    "# Project context (optional)",
    "# This is shown to AI when creating artifacts.",
    "# Add your tech stack, conventions, style guides, domain knowledge, etc.",
    "# Example:",
    "#   context: |",
    "#     Tech stack: TypeScript, React, Node.js",
    "#     We use conventional commits",
    "#     Domain: e-commerce platform",
    "",
    "# Per-artifact rules (optional)",
    "# Add custom rules for specific artifacts.",
    "# Example:",
    "#   rules:",
    "#     proposal:",
    "#       - Keep proposals under 500 words",
    '#       - Always include a "Non-goals" section',
    "#     tasks:",
    "#       - Break tasks into chunks of max 2 hours",
)


class SpecEngineError(RuntimeError):
    """spec 引擎不能安全继续时抛出（入参错、格式错、归档冲突等）。"""


# ---------------------------------------------------------------------------
# 基础小工具
# ---------------------------------------------------------------------------

def _posix(path):
    """路径正斜杠归一（Windows-only 生产军规）。"""
    return str(path).replace("\\", "/")


def _read_text(path):
    with open(path, "r", encoding="utf-8") as stream:
        return stream.read()


def _read_text_utf8(path):
    """读 UTF-8 文本；编码坏时抛带指引的引擎错误。

    审计实锤：裸 UnicodeDecodeError 会以 traceback 穿透 validate/archive/
    has_delta 直到 CLI（违背"流畅易用不卡死"）。OSError 原样抛出，由调用方
    按各自语义处理（缺失容忍/报错）。"""
    try:
        return _read_text(path)
    except UnicodeDecodeError as exc:
        raise SpecEngineError(
            "%s 读取失败（文件须为 UTF-8 编码）：%s" % (_posix(path), exc))


def _utc_today():
    """CLI 的日期一律取 ``new Date().toISOString()`` 前段，即 UTC 日期。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _norm_newlines(text):
    """CLI 的 normalizeLineEndings：CRLF/裸 CR 统一为 LF。"""
    return re.sub(r"\r\n?", "\n", text)


def _rel_under(path, base):
    """base 目录内的相对 posix 路径（前缀剥离，避免 relpath 的跨盘语义）。"""
    path = _posix(os.path.abspath(path))
    base = _posix(os.path.abspath(base))
    if path == base:
        return ""
    if path.startswith(base + "/"):
        return path[len(base) + 1:]
    return path


def _openspec_dir(root):
    return os.path.join(os.path.abspath(root), "openspec")


def _changes_dir(root):
    return os.path.join(_openspec_dir(root), "changes")


def _archive_dir(root):
    return os.path.join(_changes_dir(root), "archive")


def _main_specs_dir(root):
    return os.path.join(_openspec_dir(root), "specs")


def _change_dir(root, change):
    return os.path.join(_changes_dir(root), change)


def _validate_change_name(name):
    """接口契约规定的名称门（同 comet-archive.sh；比 CLI 的 kebab 规则宽，见模块注释差异 2）。"""
    if not name or not isinstance(name, str):
        raise SpecEngineError("change 名称不能为空")
    if ".." in name:
        raise SpecEngineError("change 名称不能包含 '..'：%s" % name)
    if not _CHANGE_NAME_RE.match(name):
        raise SpecEngineError(
            "change 名称只允许字母、数字、连字符和下划线（^[a-zA-Z0-9_-]+$）：%s" % name)
    return name


def _list_active_changes(root):
    """openspec/changes 下的活跃 change 目录（排除 archive 与点目录），排序。"""
    result = []
    try:
        for entry in os.listdir(_changes_dir(root)):
            if entry == "archive" or entry.startswith("."):
                continue
            if os.path.isdir(os.path.join(_changes_dir(root), entry)):
                result.append(entry)
    except OSError:
        return []
    return sorted(result)


def _require_change_dir(root, change):
    _validate_change_name(change)
    change_dir = _change_dir(root, change)
    if not os.path.isdir(change_dir):
        available = _list_active_changes(root)
        hint = ("；当前可用 change：" + ", ".join(available)) if available else (
            "；当前没有任何活跃 change")
        raise SpecEngineError("change '%s' 不存在%s" % (change, hint))
    return change_dir


# ---------------------------------------------------------------------------
# 最小 YAML 子集解析（只覆盖 vendored schema.yaml / config.yaml / .openspec.yaml
# 实际使用的形态：标量、引号标量、行内 [] 列表、块列表、嵌套映射、"|" 字面块）。
# 解析结果通过差分测试对拍验证（instructions 输出等价 <=> 块标量解析等价）。
# ---------------------------------------------------------------------------

def _yaml_unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _yaml_scalar(value):
    value = value.strip()
    if value == "[]":
        return []
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_yaml_unquote(part) for part in inner.split(",")]
    return _yaml_unquote(value)


def _yaml_indent(line):
    return len(line) - len(line.lstrip(" "))


def _yaml_is_noise(line):
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _yaml_block_scalar(lines, index, key_indent):
    """读取 ``key: |`` 的字面块（clip 语义：内部空行保留，结尾归一为单个换行）。"""
    body = []
    block_indent = None
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            body.append("")
            index += 1
            continue
        indent = _yaml_indent(line)
        if indent <= key_indent:
            break
        if block_indent is None:
            block_indent = indent
        body.append(line[block_indent:] if indent >= block_indent else line.lstrip(" "))
        index += 1
    while body and body[-1] == "":
        body.pop()
    return ("\n".join(body) + "\n") if body else "", index


def _yaml_parse_mapping(lines, index, min_indent):
    result = {}
    while index < len(lines):
        line = lines[index]
        if _yaml_is_noise(line):
            index += 1
            continue
        indent = _yaml_indent(line)
        if indent < min_indent:
            break
        stripped = line.strip()
        if stripped.startswith("- "):
            break  # 列表项交由上层处理
        if ":" not in stripped:
            index += 1  # 容错：无法识别的行直接跳过（CLI 用真 YAML，这里保守忽略）
            continue
        key, _, rest = stripped.partition(":")
        key = _yaml_unquote(key)
        rest = rest.strip()
        index += 1
        if rest == "|" or rest == "|-":
            value, index = _yaml_block_scalar(lines, index, indent)
            result[key] = value
        elif rest == "":
            value, index = _yaml_parse_value(lines, index, indent + 1)
            result[key] = value
        else:
            result[key] = _yaml_scalar(rest)
    return result, index


def _yaml_parse_list(lines, index, min_indent):
    result = []
    while index < len(lines):
        line = lines[index]
        if _yaml_is_noise(line):
            index += 1
            continue
        indent = _yaml_indent(line)
        if indent < min_indent:
            break
        stripped = line.strip()
        if not stripped.startswith("-"):
            break
        item_body = stripped[1:].lstrip()
        if not item_body:
            index += 1
            value, index = _yaml_parse_value(lines, index, indent + 1)
            result.append(value)
            continue
        if ":" in item_body and not item_body.startswith(("'", '"')):
            # ``- id: proposal`` 形式：把本行改写成去掉 "- " 的映射行并继续读同级键。
            inner_indent = indent + (len(stripped) - len(item_body))
            rewritten = [" " * inner_indent + item_body]
            index += 1
            while index < len(lines):
                nxt = lines[index]
                if _yaml_is_noise(nxt):
                    rewritten.append(nxt)
                    index += 1
                    continue
                nxt_indent = _yaml_indent(nxt)
                if nxt_indent <= indent or nxt.strip().startswith("- ") and nxt_indent == indent:
                    break
                rewritten.append(nxt)
                index += 1
            value, _ = _yaml_parse_mapping(rewritten, 0, inner_indent)
            result.append(value)
        else:
            result.append(_yaml_scalar(item_body))
            index += 1
    return result, index


def _yaml_parse_value(lines, index, min_indent):
    while index < len(lines) and _yaml_is_noise(lines[index]):
        index += 1
    if index >= len(lines):
        return None, index
    line = lines[index]
    indent = _yaml_indent(line)
    if indent < min_indent:
        return None, index
    if line.strip().startswith("-"):
        return _yaml_parse_list(lines, index, indent)
    return _yaml_parse_mapping(lines, index, indent)


def _yaml_load(text):
    lines = _norm_newlines(text).split("\n")
    value, _ = _yaml_parse_mapping(lines, 0, 0)
    return value


# ---------------------------------------------------------------------------
# schema / config / change 元数据
# ---------------------------------------------------------------------------

def _list_vendored_schemas():
    names = []
    try:
        for entry in os.listdir(VENDOR_SCHEMAS_DIR):
            if os.path.isfile(os.path.join(VENDOR_SCHEMAS_DIR, entry, "schema.yaml")):
                names.append(entry)
    except OSError:
        pass
    return sorted(names)


def _load_schema(name):
    """加载 vendored schema（指令与模板的唯一来源，不做任何正文硬编码）。"""
    schema_path = os.path.join(VENDOR_SCHEMAS_DIR, name, "schema.yaml")
    if not os.path.isfile(schema_path):
        raise SpecEngineError(
            "未知 schema '%s'；插件内嵌可用：%s"
            % (name, ", ".join(_list_vendored_schemas()) or "(无)"))
    data = _yaml_load(_read_text(schema_path))
    artifacts = []
    for item in data.get("artifacts") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        artifacts.append({
            "id": str(item.get("id")),
            "generates": str(item.get("generates", "")),
            "description": str(item.get("description", "")),
            "template": str(item.get("template", "")),
            "instruction": item.get("instruction") or "",
            "requires": [str(x) for x in (item.get("requires") or [])],
        })
    if not artifacts:
        raise SpecEngineError("schema 损坏（没有 artifacts）：" + _posix(schema_path))
    return {
        "name": name,
        "dir": os.path.join(VENDOR_SCHEMAS_DIR, name),
        "artifacts": artifacts,
        "apply": data.get("apply") or {},
    }


def _load_template(schema, template_name):
    path = os.path.join(schema["dir"], "templates", template_name)
    if not os.path.isfile(path):
        raise SpecEngineError("schema 模板缺失：" + _posix(path))
    # 行尾归一(CI 实锤):Windows CRLF checkout 下模板带 \r\n,引擎输出与
    # CLI(stdout 经 universal newlines 归一)不一致;引擎行为不能赌 checkout 配置。
    return _norm_newlines(_read_text(path))


def _config_path(root):
    yaml_path = os.path.join(_openspec_dir(root), "config.yaml")
    if os.path.isfile(yaml_path):
        return yaml_path
    yml_path = os.path.join(_openspec_dir(root), "config.yml")
    if os.path.isfile(yml_path):
        return yml_path
    return None


def _read_project_config(root):
    """镜像 readProjectConfig 的宽容语义：坏字段忽略而不是报错。"""
    path = _config_path(root)
    if path is None:
        return {}
    try:
        raw = _yaml_load(_read_text(path))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    config = {}
    schema = raw.get("schema")
    if isinstance(schema, str) and schema.strip():
        config["schema"] = schema.strip()
    context = raw.get("context")
    if isinstance(context, str):
        config["context"] = context
    rules = raw.get("rules")
    if isinstance(rules, dict):
        cleaned = {}
        for artifact_id, items in rules.items():
            if isinstance(items, list):
                values = [x for x in items if isinstance(x, str) and x]
                if values:
                    cleaned[artifact_id] = values
        if cleaned:
            config["rules"] = cleaned
    return config


def _read_change_metadata(change_dir):
    """读取 .openspec.yaml；返回 (metadata_dict_or_None, error_or_None)。"""
    path = os.path.join(change_dir, ".openspec.yaml")
    if not os.path.isfile(path):
        return None, None
    try:
        raw = _yaml_load(_read_text(path))
    except Exception as exc:
        return None, ".openspec.yaml 解析失败：%s" % exc
    if not isinstance(raw, dict):
        return None, ".openspec.yaml 不是映射"
    schema = raw.get("schema")
    if not isinstance(schema, str) or not schema.strip():
        return None, ".openspec.yaml 缺少 schema 字段"
    created = raw.get("created")
    if created is not None and (
            not isinstance(created, str) or not _DATE_RE.match(created)):
        return None, ".openspec.yaml 的 created 必须是 YYYY-MM-DD"
    return {"schema": schema.strip(), "created": created}, None


def _resolve_schema_name(root, change_dir, strict):
    """镜像 resolveSchemaForChange：change 元数据 → config → 默认。

    strict=True（instructions/status 路径）时元数据损坏要报错；
    strict=False（archive 的任务计数路径）时按 CLI 的 try/catch 静默回退。
    """
    metadata, err = _read_change_metadata(change_dir)
    if err and strict:
        raise SpecEngineError("change 元数据无效（%s）：%s"
                              % (err, _posix(os.path.join(change_dir, ".openspec.yaml"))))
    if metadata and metadata.get("schema"):
        return metadata["schema"]
    config = _read_project_config(root)
    if config.get("schema"):
        return config["schema"]
    return DEFAULT_SCHEMA


# ---------------------------------------------------------------------------
# Markdown 解析核心（与 CLI 逐条对齐；引用处标注上游函数名）
# ---------------------------------------------------------------------------

def _build_code_fence_mask(lines):
    """镜像 buildCodeFenceMask：围栏行与围栏内行标 True。"""
    mask = [False] * len(lines)
    active = None
    for i, line in enumerate(lines):
        fence = re.match(r"^\s*(`{3,}|~{3,})", line)
        if active is None:
            if fence:
                active = (fence.group(1)[0], len(fence.group(1)))
                mask[i] = True
            continue
        mask[i] = True
        closing = re.match(r"^\s*(`{3,}|~{3,})\s*$", line)
        if closing and closing.group(1)[0] == active[0] and len(closing.group(1)) >= active[1]:
            active = None
    return mask


def _strip_fenced_blocks_preserving_lines(content):
    """镜像 stripFencedCodeBlocksPreservingLines：围栏区间替换为空行，行号不变。"""
    lines = content.split("\n")
    output = []
    active = None
    for line in lines:
        fence = re.match(r"^\s*(`{3,}|~{3,})(.*)$", line)
        if active is None:
            if fence:
                active = (fence.group(1)[0], len(fence.group(1)))
                output.append("")
            else:
                output.append(line)
            continue
        output.append("")
        closing = re.match(r"^\s*(`{3,}|~{3,})\s*$", line)
        if closing and closing.group(1)[0] == active[0] and len(closing.group(1)) >= active[1]:
            active = None
    return "\n".join(output)


def _contains_shall_or_must(text):
    return bool(_SHALL_RE.search(text))


def _extract_requirement_body(body_lines):
    """镜像 extractRequirementBody：取正文非空行（元数据行兜底），遇任何标题行停。"""
    mask = _build_code_fence_mask(body_lines)
    captured = []
    metadata = []
    for i, line in enumerate(body_lines):
        if mask[i]:
            continue
        if _HEADER_LINE_RE.match(line):
            break
        trimmed = line.strip()
        if not trimmed:
            continue
        if _METADATA_LINE_RE.match(trimmed):
            metadata.append(trimmed)
            continue
        captured.append(trimmed)
    if captured:
        return "\n".join(captured)
    return "\n".join(metadata)


def _count_scenarios(body_lines):
    """镜像 countScenarios：非围栏内、任意 ``#### `` 头都计数（恰好四个井号）。"""
    mask = _build_code_fence_mask(body_lines)
    count = 0
    for i, line in enumerate(body_lines):
        if not mask[i] and _SCENARIO_ANY_RE.match(line):
            count += 1
    return count


def _split_top_level_sections(content):
    """镜像 splitTopLevelSections：仅二级标题分节；重名节保留首位置、正文取末次。"""
    lines = content.split("\n")
    headers = []
    for i, line in enumerate(lines):
        match = _SECTION_H2_RE.match(line)
        if match:
            headers.append((match.group(2).strip(), i))
    sections = {}
    order = []
    for pos, (title, index) in enumerate(headers):
        end = headers[pos + 1][1] if pos + 1 < len(headers) else len(lines)
        body = "\n".join(lines[index + 1:end])
        if title not in sections:
            order.append(title)
        sections[title] = {"body": body, "body_start_line": index + 2}
    return [(title, sections[title]) for title in order]


def _section_case_insensitive(sections, desired):
    target = desired.lower()
    for title, info in sections:
        if title.lower() == target:
            return {"title": title, "body": info["body"],
                    "body_start_line": info["body_start_line"], "found": True}
    return {"title": desired, "body": "", "body_start_line": 0, "found": False}


def _parse_requirement_blocks(section_body, section_title, body_start_line, sink):
    """镜像 parseRequirementBlocksFromSection。

    注意：与 CLI 相同，块识别不看围栏；围栏掩码只用于“被忽略的三级标题”记录。
    块边界 = 下一个 ``### Requirement:`` 或任何二级标题。
    """
    if not section_body:
        return []
    lines = _norm_newlines(section_body).split("\n")
    mask = _build_code_fence_mask(lines) if sink is not None else None

    def record_skipped(index):
        if sink is None or mask[index]:
            return
        h3 = re.match(r"^###\s+(.+?)\s*$", lines[index])
        if h3 and not _REQ_HEADER_RE.match(lines[index]):
            sink.append({
                "header": h3.group(1).strip(),
                "section": section_title,
                "line": body_start_line + index,
            })

    blocks = []
    i = 0
    while i < len(lines):
        while i < len(lines) and not _REQ_HEADER_RE.match(lines[i]):
            record_skipped(i)
            i += 1
        if i >= len(lines):
            break
        header_line = lines[i]
        name = _REQ_HEADER_RE.match(header_line).group(1).strip()
        buf = [header_line]
        i += 1
        while i < len(lines) and not _REQ_HEADER_RE.match(lines[i]) \
                and not re.match(r"^##\s+", lines[i]):
            record_skipped(i)
            buf.append(lines[i])
            i += 1
        blocks.append({
            "header_line": header_line,
            "name": name,
            "raw": "\n".join(buf).rstrip(),
        })
    return blocks


def _parse_removed_names(section_body):
    if not section_body:
        return []
    names = []
    for line in _norm_newlines(section_body).split("\n"):
        match = _REQ_HEADER_RE.match(line)
        if match:
            names.append(match.group(1).strip())
            continue
        bullet = _REMOVED_BULLET_RE.match(line)
        if bullet:
            names.append(bullet.group(1).strip())
    return names


def _parse_renamed_pairs(section_body):
    if not section_body:
        return []
    pairs = []
    current = {}
    for line in _norm_newlines(section_body).split("\n"):
        from_match = _RENAME_FROM_RE.match(line)
        to_match = _RENAME_TO_RE.match(line)
        if from_match:
            current["from"] = from_match.group(1).strip()
        elif to_match:
            current["to"] = to_match.group(1).strip()
            if current.get("from") and current.get("to"):
                pairs.append({"from": current["from"], "to": current["to"]})
                current = {}
    return pairs


def _parse_delta_spec(content):
    """镜像 parseDeltaSpec：四个分节 → added/modified 块、removed 名、renamed 对。"""
    normalized = _norm_newlines(content)
    sections = _split_top_level_sections(normalized)
    added_sec = _section_case_insensitive(sections, "ADDED Requirements")
    modified_sec = _section_case_insensitive(sections, "MODIFIED Requirements")
    removed_sec = _section_case_insensitive(sections, "REMOVED Requirements")
    renamed_sec = _section_case_insensitive(sections, "RENAMED Requirements")
    skipped = []
    added = _parse_requirement_blocks(
        added_sec["body"], added_sec["title"], added_sec["body_start_line"], skipped)
    modified = _parse_requirement_blocks(
        modified_sec["body"], modified_sec["title"], modified_sec["body_start_line"],
        skipped)
    removed = _parse_removed_names(removed_sec["body"])
    renamed = _parse_renamed_pairs(renamed_sec["body"])
    skipped.sort(key=lambda item: item["line"])
    return {
        "added": added,
        "modified": modified,
        "removed": removed,
        "renamed": renamed,
        "skipped": skipped,
        "presence": {
            "added": added_sec["found"],
            "modified": modified_sec["found"],
            "removed": removed_sec["found"],
            "renamed": renamed_sec["found"],
        },
    }


def _find_main_spec_structure_issues(content):
    """镜像 findMainSpecStructureIssues：主 spec 里的 delta 头 / 越界 requirement 头。"""
    normalized = _norm_newlines(content)
    stripped = _strip_fenced_blocks_preserving_lines(normalized)
    lines = stripped.split("\n")
    issues = []
    req_header_index = -1
    for i, line in enumerate(lines):
        if _REQUIREMENTS_SECTION_RE.match(line):
            req_header_index = i
            break
    req_end_index = len(lines)
    if req_header_index != -1:
        for i in range(req_header_index + 1, len(lines)):
            if _TOP_LEVEL_SECTION_RE.match(lines[i]):
                req_end_index = i
                break
    for i, line in enumerate(lines):
        trimmed = line.strip()
        if not trimmed:
            continue
        if _DELTA_HEADER_RE.match(line):
            issues.append({
                "line": i + 1,
                "message": "主 spec 出现 delta 专用分节头 \"%s\"；该类头只允许出现在 "
                           "openspec/changes/<name>/specs/<域>/spec.md 里" % trimmed,
            })
            continue
        if not _REQ_HEADER_STRICT_RE.match(line):
            continue
        inside = req_header_index != -1 and req_header_index < i < req_end_index
        if not inside:
            issues.append({
                "line": i + 1,
                "message": "requirement 头 \"%s\" 出现在 \"## Requirements\" 分节之外，"
                           "校验/归档都看不到它" % trimmed,
            })
    return issues


def _extract_requirements_section(content):
    """镜像 extractRequirementsSection：拆出 before/标题行/前言/块列表/after。

    保留 CLI 的两个怪癖：
    - 找不到 ``## Requirements`` 时，before 用原始（未归一行尾）内容 trimEnd；
    - before 非空时补一个换行，after 不以换行开头时补一个换行。
    """
    normalized = _norm_newlines(content)
    lines = normalized.split("\n")
    req_index = -1
    for i, line in enumerate(lines):
        if _REQUIREMENTS_SECTION_RE.match(line):
            req_index = i
            break
    if req_index == -1:
        before = content.rstrip()
        return {
            "before": (before + "\n\n") if before else "",
            "header_line": "## Requirements",
            "preamble": "",
            "body_blocks": [],
            "after": "\n",
        }
    end_index = len(lines)
    for i in range(req_index + 1, len(lines)):
        if re.match(r"^##\s+", lines[i]):
            end_index = i
            break
    before = "\n".join(lines[:req_index])
    header_line = lines[req_index]
    body_lines = lines[req_index + 1:end_index]
    blocks = []
    cursor = 0
    preamble_lines = []
    while cursor < len(body_lines) and not _REQ_HEADER_RE.match(body_lines[cursor]):
        preamble_lines.append(body_lines[cursor])
        cursor += 1
    while cursor < len(body_lines):
        header_candidate = body_lines[cursor]
        match = _REQ_HEADER_RE.match(header_candidate)
        if not match:
            cursor += 1
            continue
        name = match.group(1).strip()
        cursor += 1
        block_lines = [header_candidate]
        while cursor < len(body_lines) and not _REQ_HEADER_RE.match(body_lines[cursor]) \
                and not re.match(r"^##\s+", body_lines[cursor]):
            block_lines.append(body_lines[cursor])
            cursor += 1
        blocks.append({
            "header_line": header_candidate,
            "name": name,
            "raw": "\n".join(block_lines).rstrip(),
        })
    after = "\n".join(lines[end_index:])
    return {
        "before": (before + "\n") if before.rstrip() else before,
        "header_line": header_line,
        "preamble": "\n".join(preamble_lines).rstrip(),
        "body_blocks": blocks,
        "after": after if after.startswith("\n") else "\n" + after,
    }


def _parse_scenario_blocks(requirement_raw):
    """镜像 parseScenarioBlocks：按 ``#### Scenario: 名`` 切块（区分大小写）。"""
    lines = _norm_newlines(requirement_raw).split("\n")
    scenarios = []
    index = 0
    while index < len(lines):
        match = _SCENARIO_NAMED_RE.match(lines[index])
        if not match:
            index += 1
            continue
        name = match.group(1).strip()
        index += 1
        while index < len(lines) and not _SCENARIO_NAMED_RE.match(lines[index]):
            index += 1
        scenarios.append(name)
    return scenarios


# --- 主 spec 的层级解析（镜像 MarkdownParser，用于重建结果的 spec 级校验） ---

def _parse_section_tree(content):
    normalized = _norm_newlines(content)
    lines = normalized.split("\n")
    mask = _build_code_fence_mask(lines)

    def content_until_next_header(start, level):
        collected = []
        for i in range(start, len(lines)):
            header = None if mask[i] else re.match(r"^(#{1,6})\s+", lines[i])
            if header and len(header.group(1)) <= level:
                break
            collected.append(lines[i])
        return "\n".join(collected).strip()

    sections = []
    stack = []
    for i, line in enumerate(lines):
        if mask[i]:
            continue
        match = _ANY_HEADER_RE.match(line)
        if not match:
            continue
        level = len(match.group(1))
        section = {
            "level": level,
            "title": match.group(2).strip(),
            "content": content_until_next_header(i + 1, level),
            "children": [],
        }
        while stack and stack[-1]["level"] >= level:
            stack.pop()
        if stack:
            stack[-1]["children"].append(section)
        else:
            sections.append(section)
        stack.append(section)
    return sections


def _find_section(sections, title):
    """镜像 findSection：先序深度优先，标题整体不区分大小写精确匹配。"""
    target = title.lower()
    for section in sections:
        if section["title"].lower() == target:
            return section
        child = _find_section(section["children"], title)
        if child is not None:
            return child
    return None


def _validate_main_spec_content(spec_name, content):
    """镜像 validateSpecContent + applySpecRules：返回 (level, message) 列表。

    归档前对重建后的主 spec 内容做该校验，任何 ERROR 都会中止归档且不写盘。
    """
    issues = []
    try:
        tree = _parse_section_tree(content)
        purpose_sec = _find_section(tree, "Purpose")
        purpose = purpose_sec["content"] if purpose_sec else ""
        requirements_sec = _find_section(tree, "Requirements")
        if not purpose:
            raise SpecEngineError(
                "spec 缺少 \"## Purpose\" 分节（或该分节为空）")
        if requirements_sec is None:
            raise SpecEngineError("spec 缺少 \"## Requirements\" 分节")
        overview = purpose.strip()
        requirements = []
        for child in requirements_sec["children"]:
            body_lines = child["content"].split("\n")
            text = _extract_requirement_body(body_lines) or child["title"].strip()
            scenarios = [
                grandchild for grandchild in child["children"]
                if grandchild["content"].strip()
            ]
            requirements.append(
                {"title": child["title"], "text": text, "scenarios": scenarios})
        # —— zod SpecSchema 等价检查 ——
        if not overview:
            issues.append(("ERROR", "%s：Purpose 分节内容为空" % spec_name))
        if not requirements:
            issues.append(("ERROR", "%s：\"## Requirements\" 下没有任何 requirement"
                           % spec_name))
        for idx, req in enumerate(requirements):
            if not req["text"]:
                issues.append(("ERROR", "%s：第 %d 个 requirement 正文为空"
                               % (spec_name, idx + 1)))
            if not req["scenarios"]:
                issues.append(("ERROR",
                               "%s：requirement \"%s\" 没有任何非空 \"#### Scenario:\" 场景"
                               % (spec_name, req["title"])))
        # —— applySpecRules 等价检查 ——
        for structural in _find_main_spec_structure_issues(content):
            issues.append(("ERROR", "%s：第 %d 行：%s"
                           % (spec_name, structural["line"], structural["message"])))
        if len(overview) < 50:
            issues.append(("WARNING", "%s：Purpose 太简略（不足 50 字符）" % spec_name))
        for idx, req in enumerate(requirements):
            if len(req["text"]) > 500:
                issues.append(("INFO", "%s：第 %d 个 requirement 正文超过 500 字符，"
                               "考虑拆分" % (spec_name, idx + 1)))
            if not req["scenarios"]:
                issues.append(("WARNING",
                               "%s：requirement \"%s\" 缺场景（\"#### Scenario:\" 恰好"
                               "四个井号）" % (spec_name, req["title"])))
        for block in _extract_requirements_section(content)["body_blocks"]:
            body = _extract_requirement_body(block["raw"].split("\n")[1:])
            if not body or not _contains_shall_or_must(body):
                issues.append(("ERROR",
                               "%s：requirement \"%s\" 正文缺少 SHALL/MUST（英文大写，"
                               "且必须在头下方正文行里）" % (spec_name, block["name"])))
    except SpecEngineError as exc:
        issues.append(("ERROR", "%s：%s" % (spec_name, exc)))
    return issues


# ---------------------------------------------------------------------------
# v5 四合一 change.md —— 轻量布局的解析与骨架
#
# v5 布局的 change 目录只有一个 change.md，四个固定小节用一级标题分隔：
#   # 为什么 / # 规格条目：<域>（可多节，每域一节）/ # 方案 / # 实现清单
# 规格条目节的节体就是标准 delta spec 原格式（## ADDED Requirements、
# ### Requirement:、#### Scenario: 层级原样），因此 delta 的解析与合并
# 走完全相同的 _parse_delta_spec / _build_updated_spec 核心，只是"内容从
# 哪来"由 specs/<域>/spec.md 文件换成了 change.md 里的规格条目节。
# 布局探测：change.md 存在 → v5；否则 legacy（在途旧单照原样走完）。
# 两种布局标志并存（change.md 与 proposal.md/tasks.md/specs/ 同在）判为
# 布局混用，validate/archive 都会拒绝——静默偏向任何一边都等于丢内容。
# ---------------------------------------------------------------------------

CHANGE_DOC_NAME = "change.md"
V5_TIERS = ("full", "hotfix", "tweak")
V5_SECTION_WHY = "为什么"
V5_SECTION_SPEC = "规格条目"
V5_SECTION_DESIGN = "方案"
V5_SECTION_TASKS = "实现清单"
# v5 各档的必须节（多写不禁止；规格条目在 hotfix/tweak 档"确有规格变化才写"）。
V5_TIER_REQUIRED = {
    "full": (V5_SECTION_WHY, V5_SECTION_SPEC, V5_SECTION_DESIGN, V5_SECTION_TASKS),
    "hotfix": (V5_SECTION_WHY, V5_SECTION_TASKS),
    "tweak": (V5_SECTION_WHY, V5_SECTION_TASKS),
}
_V5_H1_RE = re.compile(r"^#\s+(.+?)\s*$")
_V5_SPEC_HEAD_RE = re.compile(r"^%s\s*[:：]\s*(.*)$" % V5_SECTION_SPEC)


def _change_doc_path(change_dir):
    return os.path.join(change_dir, CHANGE_DOC_NAME)


def _change_layout(change_dir):
    """"v5"（change.md 在）或 "legacy"。只探测，不校验混用。"""
    return "v5" if os.path.isfile(_change_doc_path(change_dir)) else "legacy"


def _legacy_markers(change_dir):
    """目录里存在的旧布局标志（用于布局混用检查与报错文案）。"""
    found = []
    for marker in ("proposal.md", "tasks.md", "design.md"):
        if os.path.isfile(os.path.join(change_dir, marker)):
            found.append(marker)
    if os.path.isdir(os.path.join(change_dir, "specs")):
        found.append("specs/")
    return found


def _require_layout_pure(change_dir):
    """v5 与旧布局标志并存时拒绝继续（validate / archive 共用）。"""
    if _change_layout(change_dir) != "v5":
        return
    markers = _legacy_markers(change_dir)
    if markers:
        raise SpecEngineError(
            "change 目录布局混用：change.md 与旧布局产物（%s）并存。"
            "四合一 change.md 与 proposal/tasks/specs 四件套只能二选一——"
            "把旧产物内容并入 change.md 对应小节后删除旧文件，或删掉 change.md "
            "继续按旧布局走完" % "、".join(markers))


def _validate_v5_domain(name):
    """规格条目节的域名做路径拼接，必须先过安全门。"""
    if not name:
        raise SpecEngineError(
            "change.md 的 \"# 规格条目：\" 节缺少域名；请写成 "
            "\"# 规格条目：<域名>\"（域名 = openspec/specs/ 下的目录名）")
    if "{" in name or "}" in name:
        raise SpecEngineError(
            "change.md 规格条目的域名含未替换占位符：%s" % name)
    if ".." in name or "/" in name or "\\" in name:
        raise SpecEngineError(
            "change.md 规格条目的域名不能包含路径分隔符或 '..'：%s" % name)
    return name


def _parse_change_doc(content):
    """把 change.md 按一级标题切成小节。

    - 边界 = 非围栏区的一级标题行（恰好一个 #）；围栏内的 "# ..."（代码注释）
      不算边界，因此方案/实现清单节里可以放代码块；
    - 已知节名：为什么 / 方案 / 实现清单（精确匹配）与 规格条目[:：]<域>；
      其他一级标题（如文档标题 "# 变更：xxx"）开启未知节，内容不归任何小节；
    - 同名节重复出现取首节并记录 duplicate；规格条目按域记录重复。
    """
    lines = _norm_newlines(content).split("\n")
    mask = _build_code_fence_mask(lines)
    boundaries = []
    for i, line in enumerate(lines):
        if mask[i]:
            continue
        match = _V5_H1_RE.match(line)
        if match:
            boundaries.append((i, match.group(1).strip()))
    sections = {}
    duplicate_sections = []
    domains = []
    domain_names = []
    duplicate_domains = []
    unknown_titles = []
    for pos, (index, title) in enumerate(boundaries):
        end = boundaries[pos + 1][0] if pos + 1 < len(boundaries) else len(lines)
        body = "\n".join(lines[index + 1:end])
        spec_head = _V5_SPEC_HEAD_RE.match(title)
        if spec_head:
            domain = spec_head.group(1).strip()
            if domain in domain_names:
                duplicate_domains.append(domain)
            else:
                domain_names.append(domain)
                domains.append({"domain": domain, "body": body,
                                "body_start_line": index + 2})
            continue
        if title in (V5_SECTION_WHY, V5_SECTION_DESIGN, V5_SECTION_TASKS):
            if title in sections:
                duplicate_sections.append(title)
            else:
                sections[title] = body
            continue
        # 首个未知一级头按文档标题惯例放行；其余未知一级头会切断前一节，
        # 记录下来供校验提示（小节内的一级头是最容易踩的书写错误）。
        if pos > 0:
            unknown_titles.append({"title": title, "line": index + 1})
    return {
        "sections": sections,
        "domains": domains,
        "duplicate_sections": duplicate_sections,
        "duplicate_domains": duplicate_domains,
        "unknown_titles": unknown_titles,
    }


def _read_change_doc(change_dir):
    # UnicodeDecodeError 不是 OSError——编码坏的 change.md 若不在这里收口,
    # 会以裸 traceback 穿透 validate/archive/done 全链(违背"流畅易用不卡死")。
    try:
        return _parse_change_doc(_read_text(_change_doc_path(change_dir)))
    except (OSError, UnicodeDecodeError) as exc:
        raise SpecEngineError(
            "change.md 读取失败（文件须为 UTF-8 编码）：%s" % exc)


def _build_change_skeleton(name, tier):
    """v5 change.md 骨架。占位统一带「（待填」前缀，流程证据据此拦残留。

    规格条目节不预置（预置就得放占位域名，占位域名会污染路径），由模型按
    ``spec instructions change`` 的格式合同在有规格变化时补写。
    """
    parts = ["# 变更：%s" % name, "", "# %s" % V5_SECTION_WHY, "",
             "（待填：背景与动机、目标/非目标）", ""]
    if tier == "full":
        # 方案节属设计阶段产出，用独立的「（待设计」前缀——open 步的占位
        # 检查不拦它，design 步的占位检查才拦。
        parts += ["# %s" % V5_SECTION_DESIGN, "",
                  "（待设计：技术方案结论，设计阶段填写）", ""]
    parts += ["# %s" % V5_SECTION_TASKS, "", "- [ ] 1. （待填：任务）", ""]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# validate —— 镜像 validateChangeDeltaSpecs（默认非 strict：仅 ERROR 定否决）
# ---------------------------------------------------------------------------

def _find_delta_spec_files(specs_dir):
    """镜像 findDeltaSpecFiles：递归收集所有名为 spec.md 的文件，绝对路径排序。"""
    results = []

    def walk(directory):
        try:
            entries = os.listdir(directory)
        except OSError:
            return
        for entry in entries:
            full = os.path.join(directory, entry)
            if os.path.isdir(full):
                walk(full)
            elif os.path.isfile(full) and entry == "spec.md":
                results.append(full)

    walk(specs_dir)
    return sorted(results)


def _shall_error_text(prefix, block_name):
    base = "%s 正文缺少 SHALL/MUST（须为英文大写词）" % prefix
    if _contains_shall_or_must(block_name):
        return (base + "；关键词只出现在 \"### Requirement:\" 头里不算，"
                "请移到头部下一行正文中")
    return base


def _iter_delta_validation_sources(change_dir):
    """delta 校验的内容源。v5 = change.md 的规格条目节（每域一条）；
    legacy = specs/ 下递归所有 spec.md（与 CLI 相同）。产出 (标签, 内容)。"""
    if _change_layout(change_dir) == "v5":
        for item in _read_change_doc(change_dir)["domains"]:
            yield "change.md 规格条目：%s" % item["domain"], item["body"]
        return
    specs_dir = os.path.join(change_dir, "specs")
    for spec_file in _find_delta_spec_files(specs_dir):
        try:
            content = _read_text_utf8(spec_file)
        except OSError:
            continue
        yield _rel_under(spec_file, specs_dir), content


def _collect_v5_structural_issues(change_dir):
    """v5 布局特有的结构问题（布局混用、域名非法/重复、小节重复）。

    返回 (issues, fatal)。fatal=True 表示布局混用——此时不应再按任何一边
    解析 delta（双源歧义），调用方需直接收尾。"""
    issues = []
    markers = _legacy_markers(change_dir)
    if markers:
        issues.append(("ERROR",
                       "change 目录布局混用：change.md 与旧布局产物（%s）并存。"
                       "把旧产物内容并入 change.md 对应小节后删除旧文件，或删掉 "
                       "change.md 继续按旧布局走完" % "、".join(markers)))
        return issues, True
    doc = _read_change_doc(change_dir)
    for title in doc["duplicate_sections"]:
        issues.append(("ERROR",
                       "change.md 小节 \"# %s\" 重复出现；每个小节只能有一个"
                       % title))
    for domain in doc["duplicate_domains"]:
        issues.append(("ERROR",
                       "change.md 规格条目域 \"%s\" 重复出现；同域的 delta 请合并"
                       "到一个 \"# 规格条目：%s\" 节里" % (domain, domain)))
    for item in doc["domains"]:
        try:
            _validate_v5_domain(item["domain"])
        except SpecEngineError as exc:
            issues.append(("ERROR", str(exc)))
    for stray in doc["unknown_titles"]:
        issues.append(("INFO",
                       "change.md 第 %d 行的一级标题 \"# %s\" 不是已知小节，"
                       "它会切断前一小节且内容不被解析；小节内的标题请用二级"
                       "及以下（规格条目节体本身就以 \"## ADDED Requirements\" "
                       "等二级标题开头）" % (stray["line"], stray["title"])))
    return issues, False


def _collect_delta_issues(change_dir):
    """对一个 change 目录执行 delta 校验，返回 (level, message) 列表。"""
    issues = []
    is_v5 = _change_layout(change_dir) == "v5"
    if is_v5:
        v5_issues, fatal = _collect_v5_structural_issues(change_dir)
        issues.extend(v5_issues)
        if fatal:
            return issues
    total_deltas = 0
    missing_header_specs = []
    empty_section_specs = []
    for entry, content in _iter_delta_validation_sources(change_dir):
        plan = _parse_delta_spec(content)
        for stray in plan["skipped"]:
            if re.match(r"^requirement:?$", stray["header"], re.I):
                message = ("%s 第 %d 行：%s 里的 \"### %s\" 缺少 requirement 名称，"
                           "已被校验忽略；请写成 \"### Requirement: <名称>\""
                           % (entry, stray["line"], stray["section"], stray["header"]))
            else:
                message = ("%s 第 %d 行：%s 里的 \"### %s\" 不是 \"### Requirement:\" 头，"
                           "已被校验忽略；若它应当是 requirement，请写成 "
                           "\"### Requirement: %s\"；若它是场景，请用四个井号 "
                           "\"#### Scenario:\""
                           % (entry, stray["line"], stray["section"],
                              stray["header"], stray["header"]))
            issues.append(("INFO", message))
        section_names = []
        if plan["presence"]["added"]:
            section_names.append("## ADDED Requirements")
        if plan["presence"]["modified"]:
            section_names.append("## MODIFIED Requirements")
        if plan["presence"]["removed"]:
            section_names.append("## REMOVED Requirements")
        if plan["presence"]["renamed"]:
            section_names.append("## RENAMED Requirements")
        has_entries = bool(plan["added"] or plan["modified"]
                           or plan["removed"] or plan["renamed"])
        if not has_entries:
            if section_names:
                empty_section_specs.append((entry, section_names))
            else:
                missing_header_specs.append(entry)
        added_names = set()
        modified_names = set()
        removed_names = set()
        renamed_from = set()
        renamed_to = set()
        for block in plan["added"]:
            total_deltas += 1
            key = block["name"]
            if key in added_names:
                issues.append(("ERROR", "%s：ADDED 段重复 requirement \"%s\""
                               % (entry, block["name"])))
            else:
                added_names.add(key)
            body = _extract_requirement_body(block["raw"].split("\n")[1:])
            if not body:
                if _contains_shall_or_must(block["name"]):
                    issues.append(("ERROR", "%s：%s" % (
                        entry, _shall_error_text("ADDED \"%s\"" % block["name"],
                                                 block["name"]))))
                else:
                    issues.append(("ERROR", "%s：ADDED \"%s\" 缺少正文"
                                   % (entry, block["name"])))
            elif not _contains_shall_or_must(body):
                issues.append(("ERROR", "%s：%s" % (
                    entry, _shall_error_text("ADDED \"%s\"" % block["name"],
                                             block["name"]))))
            if _count_scenarios(block["raw"].split("\n")[1:]) < 1:
                issues.append(("ERROR",
                               "%s：ADDED \"%s\" 至少要有一个场景（\"#### Scenario:\" "
                               "恰好四个井号）" % (entry, block["name"])))
        for block in plan["modified"]:
            total_deltas += 1
            key = block["name"]
            if key in modified_names:
                issues.append(("ERROR", "%s：MODIFIED 段重复 requirement \"%s\""
                               % (entry, block["name"])))
            else:
                modified_names.add(key)
            body = _extract_requirement_body(block["raw"].split("\n")[1:])
            if not body:
                if _contains_shall_or_must(block["name"]):
                    issues.append(("ERROR", "%s：%s" % (
                        entry, _shall_error_text("MODIFIED \"%s\"" % block["name"],
                                                 block["name"]))))
                else:
                    issues.append(("ERROR", "%s：MODIFIED \"%s\" 缺少正文"
                                   % (entry, block["name"])))
            elif not _contains_shall_or_must(body):
                issues.append(("ERROR", "%s：%s" % (
                    entry, _shall_error_text("MODIFIED \"%s\"" % block["name"],
                                             block["name"]))))
            if _count_scenarios(block["raw"].split("\n")[1:]) < 1:
                issues.append(("ERROR",
                               "%s：MODIFIED \"%s\" 至少要有一个场景（\"#### Scenario:\" "
                               "恰好四个井号）" % (entry, block["name"])))
        for name in plan["removed"]:
            total_deltas += 1
            if name in removed_names:
                issues.append(("ERROR", "%s：REMOVED 段重复 requirement \"%s\""
                               % (entry, name)))
            else:
                removed_names.add(name)
        for pair in plan["renamed"]:
            total_deltas += 1
            if pair["from"] in renamed_from:
                issues.append(("ERROR", "%s：RENAMED 段重复 FROM \"%s\""
                               % (entry, pair["from"])))
            else:
                renamed_from.add(pair["from"])
            if pair["to"] in renamed_to:
                issues.append(("ERROR", "%s：RENAMED 段重复 TO \"%s\""
                               % (entry, pair["to"])))
            else:
                renamed_to.add(pair["to"])
        for name in modified_names:
            if name in removed_names:
                issues.append(("ERROR",
                               "%s：requirement \"%s\" 同时出现在 MODIFIED 和 REMOVED"
                               % (entry, name)))
            if name in added_names:
                issues.append(("ERROR",
                               "%s：requirement \"%s\" 同时出现在 MODIFIED 和 ADDED"
                               % (entry, name)))
        for name in added_names:
            if name in removed_names:
                issues.append(("ERROR",
                               "%s：requirement \"%s\" 同时出现在 ADDED 和 REMOVED"
                               % (entry, name)))
        for pair in plan["renamed"]:
            if pair["from"] in modified_names:
                issues.append(("ERROR",
                               "%s：存在改名时 MODIFIED 必须引用新名，请用 \"%s\""
                               % (entry, pair["to"])))
            if pair["to"] in added_names:
                issues.append(("ERROR", "%s：RENAMED 的 TO \"%s\" 与 ADDED 冲突"
                               % (entry, pair["to"])))
    for entry, section_names in empty_section_specs:
        if len(section_names) == 1:
            rendered = section_names[0]
        else:
            rendered = "、".join(section_names[:-1]) + " 和 " + section_names[-1]
        issues.append(("ERROR",
                       "%s：找到了分节 %s，但没有解析出任何 requirement；每节至少要有"
                       "一个 \"### Requirement:\" 块（REMOVED 可用 \"- ### Requirement: "
                       "名\" 列表）" % (entry, rendered)))
    for entry in missing_header_specs:
        issues.append(("ERROR",
                       "%s：没有任何 delta 分节头；请添加 \"## ADDED Requirements\" 等，"
                       "或把非 delta 内容移出 specs/ 目录" % entry))
    if total_deltas == 0:
        if is_v5:
            issues.append(("ERROR",
                           "change 至少要有一个 delta：请在 change.md 里加 "
                           "\"# 规格条目：<域名>\" 节，节内用 "
                           "\"## ADDED/MODIFIED/REMOVED/RENAMED Requirements\" 分节，"
                           "且每个 requirement 至少带一个 \"#### Scenario:\" 场景"))
        else:
            issues.append(("ERROR",
                           "change 至少要有一个 delta：请在 specs/<域>/spec.md 里用 "
                           "\"## ADDED/MODIFIED/REMOVED/RENAMED Requirements\" 分节，"
                           "且每个 requirement 至少带一个 \"#### Scenario:\" 场景"))
    return issues


_LEVEL_PREFIX = {"ERROR": "[错误] ", "WARNING": "[警告] ", "INFO": "[提示] "}


def _format_issues(issues):
    return [_LEVEL_PREFIX.get(level, "") + text for level, text in issues]


def validate(root, change):
    """校验一个 change 的 delta specs；返回 ``(ok, messages)``。

    verdict 与 ``openspec validate <change>``（非 strict）一致：只有 ERROR 级
    问题才判 False；messages 里同时包含 [提示]/[警告] 级条目供人阅读。
    v5 布局对 change.md 的规格条目节执行同一套校验（外加布局混用、域名、
    重复节等 v5 结构检查）。
    change 不存在时抛 SpecEngineError（对应 CLI 的 "Unknown item"，非校验报告）。
    """
    change_dir = _require_change_dir(root, change)
    issues = _collect_delta_issues(change_dir)
    ok = not any(level == "ERROR" for level, _ in issues)
    return ok, _format_issues(issues)


def has_delta(root, change):
    """change 是否声明了规格变化（v5 看规格条目节，legacy 看 specs/ delta 头）。

    供流程侧区分"无规格变化的轻量单"（hotfix/tweak 允许）与"有规格但格式
    未过"——前者跳过 delta 校验，后者必须修到过。布局混用时这个问题没有
    可信答案，直接抛错（与 archive 的混用拒绝同一判据）。"""
    change_dir = _require_change_dir(root, change)
    _require_layout_pure(change_dir)
    return _has_delta_specs(change_dir)


def check_required_sections(root, change, tier):
    """v5 分档必须节的机器校验：返回缺失小节名列表（合规为空列表）。

    审计实锤：V5_TIER_REQUIRED 声明后一直无人消费，"full=四节"的分档合同
    在机器侧未接线——整节删除可静默过全部门禁。本函数由 ev_spec_validate
    在 done 时调用；legacy 布局或未知档位不查（返回空）。规格条目按
    "至少一个 # 规格条目：<域> 节"判定。"""
    change_dir = _require_change_dir(root, change)
    if tier not in V5_TIER_REQUIRED or _change_layout(change_dir) != "v5":
        return []
    doc = _read_change_doc(change_dir)
    missing = []
    for section in V5_TIER_REQUIRED[tier]:
        if section == V5_SECTION_SPEC:
            if not doc["domains"]:
                missing.append("%s：<域名>" % V5_SECTION_SPEC)
        elif section not in doc["sections"]:
            missing.append(section)
    return missing


def tasks_source(root, change):
    """实现清单的内容源：返回 ``(标签, 文本或 None)``。

    v5 = change.md 的 "# 实现清单" 节；legacy = tasks.md。None 表示源缺失
    （目录/文件/小节不在），报错文案由调用方组织。只统一"从哪来"——引擎
    _count_tasks 的顶层复选框语义与 gate 证据的宽松缩进语义历史上就不同，
    计数正则留在各自调用方。"""
    _validate_change_name(change)
    change_dir = _change_dir(root, change)
    # 混用（change.md 与 tasks.md 并存）时"清单从哪来"没有可信答案，
    # 与 has_delta 同一判据拒绝——静默偏向任何一边都可能读错进度。
    _require_layout_pure(change_dir)
    if _change_layout(change_dir) == "v5":
        label = ("openspec/changes/%s/change.md 的 \"# %s\" 节"
                 % (change, V5_SECTION_TASKS))
        # 坏编码传播为带 UTF-8 指引的引擎错误——吞成 None 会被调用方当
        # "实现清单缺失"报出，引导补节而不是修编码（审计实锤的错误指引）。
        doc = _read_change_doc(change_dir)
        return label, doc["sections"].get(V5_SECTION_TASKS)
    label = "openspec/changes/%s/tasks.md" % change
    try:
        return label, _read_text(os.path.join(change_dir, "tasks.md"))
    except OSError:
        return label, None
    except UnicodeDecodeError as exc:
        # 与 v5 的 _read_change_doc 对称:坏编码是"读取失败要修",不是"源缺失",
        # 收口为带指引的引擎错误,证据层转拒+可重试,不裸 traceback。
        raise SpecEngineError(
            "tasks.md 读取失败（文件须为 UTF-8 编码）：%s" % exc)


# ---------------------------------------------------------------------------
# ensure_config / new_change
# ---------------------------------------------------------------------------

def _ensure_base_dirs(root):
    os.makedirs(_main_specs_dir(root), exist_ok=True)
    os.makedirs(_archive_dir(root), exist_ok=True)


def ensure_config(root):
    """openspec/config.yaml 不存在则按 ``openspec init`` 的模板创建（幂等）。

    同时补齐 openspec/specs 与 openspec/changes/archive 目录结构。
    返回 ``{"created": bool, "path": <posix 绝对路径>}``。
    """
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise SpecEngineError("项目目录不存在：" + _posix(root))
    existing = _config_path(root)
    if existing is not None:
        _ensure_base_dirs(root)
        return {"created": False, "path": _posix(os.path.abspath(existing))}
    _ensure_base_dirs(root)
    path = os.path.join(_openspec_dir(root), "config.yaml")
    text = "\n".join(_CONFIG_TEMPLATE_LINES) % DEFAULT_SCHEMA + "\n"
    atomic_write_text(path, text)
    return {"created": True, "path": _posix(os.path.abspath(path))}


def new_change(root, name, tier=None):
    """创建 change 目录。

    ``tier=None``：旧布局（镜像 ``openspec new change`` 的产物）——
    ``openspec/changes/<name>/.openspec.yaml``（schema + created=UTC 日期）。
    保留给差分对拍与旧布局构造用，运行路径已不再产生新的旧布局单。

    ``tier`` ∈ full/hotfix/tweak：v5 四合一布局——目录里只有一个 change.md
    骨架（按档位含节），**不写 .openspec.yaml**（schema 走项目 config.yaml
    回退，日期由归档名承载）；v5 单"入库物只有 1 个文件"的关键就在这里。

    两种布局都保证 openspec/specs、openspec/changes/archive 存在；
    config.yaml 缺失时按 CLI 同款最小内容 ``schema: spec-driven`` 创建
    （注意与 ensure_config 的完整模板不同——先 ensure_config 后 new_change
    则维持完整模板不动）。
    """
    root = os.path.abspath(root)
    _validate_change_name(name)
    if tier is not None and tier not in V5_TIERS:
        raise SpecEngineError(
            "未知交付档位 '%s'；可选：%s" % (tier, ", ".join(V5_TIERS)))
    if not os.path.isdir(root):
        raise SpecEngineError("项目目录不存在：" + _posix(root))
    config = _read_project_config(root)
    schema_name = config.get("schema") or DEFAULT_SCHEMA
    if schema_name not in _list_vendored_schemas():
        raise SpecEngineError(
            "未知 schema '%s'；插件内嵌可用：%s"
            % (schema_name, ", ".join(_list_vendored_schemas()) or "(无)"))
    change_dir = _change_dir(root, name)
    if os.path.isdir(change_dir):
        raise SpecEngineError("change '%s' 已存在：%s" % (name, _posix(change_dir)))
    os.makedirs(change_dir, exist_ok=True)
    _ensure_base_dirs(root)
    if _config_path(root) is None:
        atomic_write_text(
            os.path.join(_openspec_dir(root), "config.yaml"),
            "schema: %s\n" % DEFAULT_SCHEMA)
    created = _utc_today()
    if tier is not None:
        doc_path = _change_doc_path(change_dir)
        atomic_write_text(doc_path, _build_change_skeleton(name, tier))
        return {
            "name": name,
            "path": _posix(change_dir),
            "layout": "v5",
            "tier": tier,
            "change_doc": _posix(doc_path),
            "schema": schema_name,
            "created": created,
        }
    metadata_path = os.path.join(change_dir, ".openspec.yaml")
    atomic_write_text(
        metadata_path, "schema: %s\ncreated: %s\n" % (schema_name, created))
    return {
        "name": name,
        "path": _posix(change_dir),
        "metadata_path": _posix(metadata_path),
        "schema": schema_name,
        "created": created,
    }


# ---------------------------------------------------------------------------
# instructions / status —— 制品图（依赖、完成度）与指令渲染
# ---------------------------------------------------------------------------

def _artifact_outputs(change_dir, generates):
    """镜像 resolveArtifactOutputs：非 glob 直接判文件；glob 只支持 specs/**/*.md
    这类“目录下任意 .md”形态（vendored schema 的唯一 glob）。"""
    if not any(ch in generates for ch in "*?["):
        full = os.path.join(change_dir, generates)
        return [full] if os.path.isfile(full) else []
    # 通用近似：取 glob 的首个通配段之前的目录前缀，递归收集匹配尾缀的文件。
    prefix = generates.split("*")[0].rstrip("/")
    base = os.path.join(change_dir, *prefix.split("/")) if prefix else change_dir
    suffix = generates.rsplit(".", 1)[-1] if "." in generates else ""
    matches = []
    for dirpath, _dirnames, filenames in os.walk(base):
        for filename in filenames:
            if not suffix or filename.endswith("." + suffix):
                matches.append(os.path.join(dirpath, filename))
    return sorted(matches)


def _detect_completed(schema, change_dir):
    completed = set()
    for artifact in schema["artifacts"]:
        if _artifact_outputs(change_dir, artifact["generates"]):
            completed.add(artifact["id"])
    return completed


def _build_order(schema):
    """镜像 getBuildOrder：Kahn 拓扑序，同层按字母序。"""
    in_degree = {}
    dependents = {}
    for artifact in schema["artifacts"]:
        in_degree[artifact["id"]] = len(artifact["requires"])
        dependents[artifact["id"]] = []
    for artifact in schema["artifacts"]:
        for req in artifact["requires"]:
            dependents.setdefault(req, []).append(artifact["id"])
    queue = sorted([aid for aid, deg in in_degree.items() if deg == 0])
    order = []
    while queue:
        current = queue.pop(0)
        order.append(current)
        ready = []
        for dep in dependents.get(current, []):
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                ready.append(dep)
        queue.extend(sorted(ready))
    return order


def _count_task_lines(text):
    total = 0
    completed = 0
    for line in _norm_newlines(text).split("\n"):
        if _TASK_RE.match(line):
            total += 1
            if _TASK_DONE_RE.match(line):
                completed += 1
    return {"total": total, "completed": completed}


def _count_tasks(change_dir):
    """任务进度。v5 数 change.md 的 "# 实现清单" 节；legacy 数 tasks.md
    顶层复选框（镜像 getTaskProgressForChange 的有效行为，正则语义相同）。"""
    if _change_layout(change_dir) == "v5":
        try:
            doc = _read_change_doc(change_dir)
        except SpecEngineError:
            return {"total": 0, "completed": 0}
        return _count_task_lines(doc["sections"].get(V5_SECTION_TASKS, ""))
    try:
        content = _read_text(os.path.join(change_dir, "tasks.md"))
    except (OSError, UnicodeDecodeError):
        # 展示/归档计数路径保持 CLI 同款宽容(getTaskProgress 的 try/catch 静默)。
        return {"total": 0, "completed": 0}
    return _count_task_lines(content)


def _render_change_instructions(change, change_dir, schema_name, schema, tier,
                                config):
    """v5 四合一 change.md 的创建指令。

    结构说明是 v5 自己的（上游没有这个制品）；规格条目节体的格式合同复用
    vendored schema 里 specs 制品的 instruction/template 原文——格式真源
    仍是引擎内嵌数据，不在这里手写第二份。
    """
    specs_artifact = None
    for item in schema["artifacts"]:
        if item["id"] == "specs":
            specs_artifact = item
            break
    tier_lines = {
        "full": "full（完整开发）：四节齐全——为什么 / 规格条目（至少一个域）/ 方案 / 实现清单。",
        "hotfix": "hotfix（已定位修复）：为什么 / 实现清单 必须；行为规格确有变化才补规格条目节；不写方案节。",
        "tweak": "tweak（局部修改）：为什么 / 实现清单 必须；无规格变化不写规格条目节；不写方案节。",
    }
    lines = []
    lines.append('<artifact id="change" change="%s" schema="%s">'
                 % (change, schema_name))
    lines.append("")
    lines.append("<task>")
    lines.append('Create the four-in-one change.md for change "%s".' % change)
    lines.append("四合一 change.md 是本单唯一入库产物，用固定小节取代旧四件套"
                 "（proposal/design/tasks/delta spec）。")
    lines.append("</task>")
    lines.append("")
    context_text = (config.get("context") or "").strip()
    if context_text:
        lines.append("<project_context>")
        lines.append("<!-- This is background information for you. "
                     "Do NOT include this in your output. -->")
        lines.append(context_text)
        lines.append("</project_context>")
        lines.append("")
    rules = (config.get("rules") or {}).get("change") or []
    if rules:
        lines.append("<rules>")
        lines.append("<!-- These are constraints for you to follow. "
                     "Do NOT include this in your output. -->")
        for rule in rules:
            lines.append("- %s" % rule)
        lines.append("</rules>")
        lines.append("")
    lines.append("<output>")
    lines.append("Write to: %s" % _posix(_change_doc_path(change_dir)))
    lines.append("</output>")
    lines.append("")
    lines.append("<instruction>")
    lines.append("- 小节用一级标题分隔，标题逐字使用：# 为什么 / # 规格条目：<域名> / "
                 "# 方案 / # 实现清单；其余一级标题（如文档标题）不算小节。")
    if tier in tier_lines:
        lines.append("- 本单档位 %s" % tier_lines[tier])
    else:
        for key in V5_TIERS:
            lines.append("- 档位 %s" % tier_lines[key])
    lines.append("- # 为什么：背景与动机、目标/非目标（原 proposal 的浓缩，"
                 "写决策依据不写实现细节）。")
    lines.append("- # 规格条目：<域名>：每个受影响的规格域一节，域名 = "
                 "openspec/specs/ 下的目录名（同域不得重复出节）；节体就是标准 "
                 "delta spec 原格式、层级原样（## ADDED/MODIFIED/REMOVED/RENAMED "
                 "Requirements、### Requirement:、#### Scenario: 恰好四个井号），"
                 "格式合同见下方 spec_format。小节体内禁止再出现一级标题"
                 "（会切断小节）；delta spec 文件惯用的 \"# <域> Specification\" "
                 "文档标题行在节体里不要写。")
    lines.append("- # 方案：技术方案结论（原 design 的浓缩）；讨论与勘察过程件"
                 "留在 .mae-flow-work/，不入库。")
    lines.append("- # 实现清单：\"- [ ] 编号. 任务\" 复选框，行首不缩进；"
                 "完成后勾选为 [x]；批次备注写在任务行下的缩进行。")
    lines.append("- 骨架里的「（待填…）」占位必须全部替换为实际内容。")
    lines.append("</instruction>")
    lines.append("")
    if specs_artifact is not None:
        lines.append("<spec_format>")
        lines.append("<!-- 规格条目节体的格式合同，与旧布局 delta spec 完全一致"
                     "（来自内嵌 schema，不是手写第二份）。 -->")
        instruction_text = (specs_artifact["instruction"] or "").strip()
        if instruction_text:
            lines.append(instruction_text)
            lines.append("")
        template_text = _load_template(
            schema, specs_artifact["template"]).strip()
        lines.append("<!-- 下面的模板结构直接作为 \"# 规格条目：<域名>\" 之下的"
                     "节体使用。 -->")
        lines.append(template_text)
        lines.append("</spec_format>")
        lines.append("")
    lines.append("</artifact>")
    return "\n".join(lines) + "\n"


def instructions(root, artifact, change, tier=None):
    """渲染某制品的创建指令文本（内容全部来自 vendored schema + templates）。

    输出结构镜像 ``openspec instructions <artifact> --change <name>`` 的
    ``<artifact>…</artifact>`` 文本（含 warning/task/project_context/rules/
    dependencies/output/instruction/template/success_criteria/unlocks 块），
    路径正斜杠归一。返回 str（以换行结尾）。

    v5 追加虚拟制品 ``change``：四合一 change.md 的结构说明 + 规格条目节的
    格式合同（复用 specs 制品的内嵌指令与模板）；``tier`` 只影响该制品。
    """
    root = os.path.abspath(root)
    change_dir = _require_change_dir(root, change)
    schema_name = _resolve_schema_name(root, change_dir, strict=True)
    schema = _load_schema(schema_name)
    # 布局门（审计实锤）：指令是"教模型写什么"的入口，发错布局的指令等于
    # 引擎亲口指示制造它自己随后会拒绝的混用现场。
    if artifact == "change":
        if _change_layout(change_dir) != "v5" and _legacy_markers(change_dir):
            raise SpecEngineError(
                "change '%s' 是旧布局在途单（存在 %s）；继续按旧四件套补齐走完，"
                "不要新建 change.md（用 spec instructions "
                "proposal|specs|design|tasks 取旧制品指令）"
                % (change, "、".join(_legacy_markers(change_dir))))
        return _render_change_instructions(
            change, change_dir, schema_name, schema, tier,
            _read_project_config(root))
    if _change_layout(change_dir) == "v5":
        raise SpecEngineError(
            "change '%s' 是 v5 四合一布局（change.md），不再使用旧制品 '%s'；"
            "执行 spec instructions change 取四合一结构与规格条目格式合同"
            % (change, artifact))
    valid_ids = [item["id"] for item in schema["artifacts"]]
    selected = None
    for item in schema["artifacts"]:
        if item["id"] == artifact:
            selected = item
            break
    if selected is None:
        raise SpecEngineError(
            "制品 '%s' 不在 schema '%s' 里；可选：%s"
            % (artifact, schema_name, ", ".join(valid_ids + ["change"])))
    template_text = _load_template(schema, selected["template"])
    completed = _detect_completed(schema, change_dir)
    dependencies = []
    for dep_id in selected["requires"]:
        dep = None
        for item in schema["artifacts"]:
            if item["id"] == dep_id:
                dep = item
                break
        dependencies.append({
            "id": dep_id,
            "done": dep_id in completed,
            "path": dep["generates"] if dep else dep_id,
            "description": dep["description"] if dep else "",
        })
    unlocks = sorted(item["id"] for item in schema["artifacts"]
                     if artifact in item["requires"])
    config = _read_project_config(root)
    context_text = (config.get("context") or "").strip()
    rules = (config.get("rules") or {}).get(artifact) or []

    lines = []
    lines.append('<artifact id="%s" change="%s" schema="%s">'
                 % (artifact, change, schema_name))
    lines.append("")
    missing = [dep["id"] for dep in dependencies if not dep["done"]]
    if missing:
        lines.append("<warning>")
        lines.append("This artifact has unmet dependencies. "
                     "Complete them first or proceed with caution.")
        lines.append("Missing: %s" % ", ".join(missing))
        lines.append("</warning>")
        lines.append("")
    lines.append("<task>")
    lines.append('Create the %s artifact for change "%s".' % (artifact, change))
    lines.append(selected["description"])
    lines.append("</task>")
    lines.append("")
    if context_text:
        lines.append("<project_context>")
        lines.append("<!-- This is background information for you. "
                     "Do NOT include this in your output. -->")
        lines.append(context_text)
        lines.append("</project_context>")
        lines.append("")
    if rules:
        lines.append("<rules>")
        lines.append("<!-- These are constraints for you to follow. "
                     "Do NOT include this in your output. -->")
        for rule in rules:
            lines.append("- %s" % rule)
        lines.append("</rules>")
        lines.append("")
    if dependencies:
        lines.append("<dependencies>")
        lines.append("Read these files for context before creating this artifact:")
        lines.append("")
        for dep in dependencies:
            status = "done" if dep["done"] else "missing"
            full_path = _posix(os.path.join(change_dir, dep["path"]))
            lines.append('<dependency id="%s" status="%s">' % (dep["id"], status))
            lines.append("  <path>%s</path>" % full_path)
            lines.append("  <description>%s</description>" % dep["description"])
            lines.append("</dependency>")
        lines.append("</dependencies>")
        lines.append("")
    lines.append("<output>")
    lines.append("Write to: %s"
                 % _posix(os.path.join(change_dir, selected["generates"])))
    lines.append("</output>")
    lines.append("")
    if selected["instruction"]:
        lines.append("<instruction>")
        lines.append(selected["instruction"].strip())
        lines.append("</instruction>")
        lines.append("")
    lines.append("<template>")
    lines.append("<!-- Use this as the structure for your output file. "
                 "Fill in the sections. -->")
    lines.append(template_text.strip())
    lines.append("</template>")
    lines.append("")
    lines.append("<success_criteria>")
    lines.append("<!-- To be defined in schema validation rules -->")
    lines.append("</success_criteria>")
    lines.append("")
    if unlocks:
        lines.append("<unlocks>")
        lines.append("Completing this artifact enables: %s" % ", ".join(unlocks))
        lines.append("</unlocks>")
        lines.append("")
    lines.append("</artifact>")
    return "\n".join(lines) + "\n"


def _list_main_spec_domains(root):
    specs = []
    try:
        for entry in os.listdir(_main_specs_dir(root)):
            if entry.startswith("."):
                continue
            if os.path.isfile(os.path.join(_main_specs_dir(root), entry, "spec.md")):
                specs.append(entry)
    except OSError:
        pass
    return sorted(specs)


def status(root, change):
    """返回制品存在性/就绪态 + 主 specs 域清单 + 任务进度。

    v5 布局没有四件套制品图，改报四合一小节的存在性与规格条目域清单；
    is_complete 按最低档必须节（为什么 + 实现清单）判定——档位信息属于
    流程状态层，引擎不猜。"""
    root = os.path.abspath(root)
    change_dir = _require_change_dir(root, change)
    schema_name = _resolve_schema_name(root, change_dir, strict=True)
    if _change_layout(change_dir) == "v5":
        doc = _read_change_doc(change_dir)
        sections = {
            V5_SECTION_WHY: V5_SECTION_WHY in doc["sections"],
            V5_SECTION_DESIGN: V5_SECTION_DESIGN in doc["sections"],
            V5_SECTION_TASKS: V5_SECTION_TASKS in doc["sections"],
        }
        return {
            "change": change,
            "schema": schema_name,
            "change_root": _posix(change_dir),
            "layout": "v5",
            "change_doc": _posix(_change_doc_path(change_dir)),
            "sections": sections,
            "spec_domains": [item["domain"] for item in doc["domains"]],
            "is_complete": sections[V5_SECTION_WHY] and sections[V5_SECTION_TASKS],
            "specs": _list_main_spec_domains(root),
            "tasks": _count_tasks(change_dir),
        }
    schema = _load_schema(schema_name)
    completed = _detect_completed(schema, change_dir)
    order = _build_order(schema)
    by_id = {item["id"]: item for item in schema["artifacts"]}
    artifacts = []
    for artifact_id in order:
        item = by_id[artifact_id]
        missing = sorted(dep for dep in item["requires"] if dep not in completed)
        if artifact_id in completed:
            state = "done"
        elif not missing:
            state = "ready"
        else:
            state = "blocked"
        entry = {
            "id": artifact_id,
            "exists": artifact_id in completed,
            "status": state,
            "output_path": item["generates"],
        }
        if state == "blocked":
            entry["missing_deps"] = missing
        artifacts.append(entry)
    return {
        "change": change,
        "schema": schema_name,
        "change_root": _posix(change_dir),
        "artifacts": artifacts,
        "is_complete": all(item["id"] in completed for item in schema["artifacts"]),
        "specs": _list_main_spec_domains(root),
        "tasks": _count_tasks(change_dir),
    }


# ---------------------------------------------------------------------------
# archive —— delta 合并进主 specs + 目录移动（半成功免疫）
# ---------------------------------------------------------------------------

def _build_spec_skeleton(spec_name, change_name):
    """镜像 buildSpecSkeleton（新建域时的主 spec 骨架）。"""
    return ("# %s Specification\n\n## Purpose\nTBD - created by archiving change "
            "%s. Update Purpose after archive.\n\n## Requirements\n"
            % (spec_name, change_name))


def _build_updated_spec(source_content, target_content, spec_name, change_name):
    """镜像 buildUpdatedSpec：纯内存计算重建后的主 spec 内容。

    返回 ``(rebuilt, counts, warnings)``；target_content 传 None 表示目标域
    尚不存在。所有失败点的触发条件与顺序与 CLI 相同，消息中文化。
    """
    plan = _parse_delta_spec(source_content)
    warnings = []
    # —— 段内重复检查（与 CLI 相同的先后顺序，先出现者先报错） ——
    seen = set()
    for block in plan["added"]:
        if block["name"] in seen:
            raise SpecEngineError(
                "%s 校验失败：ADDED 段重复 requirement \"### Requirement: %s\""
                % (spec_name, block["name"]))
        seen.add(block["name"])
    added_names = seen
    seen = set()
    for block in plan["modified"]:
        if block["name"] in seen:
            raise SpecEngineError(
                "%s 校验失败：MODIFIED 段重复 requirement \"### Requirement: %s\""
                % (spec_name, block["name"]))
        seen.add(block["name"])
    modified_names = seen
    seen = set()
    for name in plan["removed"]:
        if name in seen:
            raise SpecEngineError(
                "%s 校验失败：REMOVED 段重复 requirement \"### Requirement: %s\""
                % (spec_name, name))
        seen.add(name)
    removed_names = seen
    renamed_from = set()
    renamed_to = set()
    for pair in plan["renamed"]:
        if pair["from"] in renamed_from:
            raise SpecEngineError(
                "%s 校验失败：RENAMED 段重复 FROM \"### Requirement: %s\""
                % (spec_name, pair["from"]))
        if pair["to"] in renamed_to:
            raise SpecEngineError(
                "%s 校验失败：RENAMED 段重复 TO \"### Requirement: %s\""
                % (spec_name, pair["to"]))
        renamed_from.add(pair["from"])
        renamed_to.add(pair["to"])
    # —— 跨段冲突（收集后统一抛第一个；RENAMED 相关的两类先抛，与 CLI 一致） ——
    conflicts = []
    for name in modified_names:
        if name in removed_names:
            conflicts.append((name, "MODIFIED", "REMOVED"))
        if name in added_names:
            conflicts.append((name, "MODIFIED", "ADDED"))
    for name in added_names:
        if name in removed_names:
            conflicts.append((name, "ADDED", "REMOVED"))
    for pair in plan["renamed"]:
        if pair["from"] in modified_names:
            raise SpecEngineError(
                "%s 校验失败：存在改名时 MODIFIED 必须引用新名 \"### Requirement: %s\""
                % (spec_name, pair["to"]))
        if pair["to"] in added_names:
            raise SpecEngineError(
                "%s 校验失败：RENAMED 的 TO 与 ADDED 冲突 \"### Requirement: %s\""
                % (spec_name, pair["to"]))
    if conflicts:
        name, section_a, section_b = conflicts[0]
        raise SpecEngineError(
            "%s 校验失败：requirement \"### Requirement: %s\" 同时出现在 %s 和 %s"
            % (spec_name, name, section_a, section_b))
    if not (plan["added"] or plan["modified"] or plan["removed"] or plan["renamed"]):
        raise SpecEngineError(
            "%s 的 delta spec 没有解析出任何操作；请提供 ADDED/MODIFIED/REMOVED/"
            "RENAMED 分节" % spec_name)
    # —— 目标读取 / 新建域骨架 ——
    is_new_spec = False
    if target_content is None:
        if plan["modified"] or plan["renamed"]:
            raise SpecEngineError(
                "%s：目标主 spec 不存在；新建域只允许 ADDED，MODIFIED/RENAMED 需要"
                "已有 spec（openspec/specs/%s/spec.md）" % (spec_name, spec_name))
        if plan["removed"]:
            warnings.append(
                "%s：目标是新建域，%d 个 REMOVED 被忽略（没有可删对象）"
                % (spec_name, len(plan["removed"])))
        is_new_spec = True
        target_content = _build_spec_skeleton(spec_name, change_name)
    structure_issues = _find_main_spec_structure_issues(target_content)
    if structure_issues:
        details = "\n".join("第 %d 行：%s" % (item["line"], item["message"])
                            for item in structure_issues)
        raise SpecEngineError(
            "%s：目标主 spec 结构非法，修复前无法合并：\n%s" % (spec_name, details))
    parts = _extract_requirements_section(target_content)
    # dict 保插入序，等价 JS Map（改名块与新增块都追加到尾部）。
    name_to_block = {}
    for block in parts["body_blocks"]:
        name_to_block[block["name"]] = block
    for pair in plan["renamed"]:
        if pair["from"] not in name_to_block:
            raise SpecEngineError(
                "%s RENAMED 失败：\"### Requirement: %s\" 在主 spec 里找不到"
                % (spec_name, pair["from"]))
        if pair["to"] in name_to_block:
            raise SpecEngineError(
                "%s RENAMED 失败：目标名 \"### Requirement: %s\" 已存在"
                % (spec_name, pair["to"]))
        block = name_to_block.pop(pair["from"])
        raw_lines = block["raw"].split("\n")
        raw_lines[0] = "### Requirement: %s" % pair["to"]
        name_to_block[pair["to"]] = {
            "header_line": raw_lines[0],
            "name": pair["to"],
            "raw": "\n".join(raw_lines),
        }
    for name in plan["removed"]:
        if name not in name_to_block:
            if not is_new_spec:
                raise SpecEngineError(
                    "%s REMOVED 失败：\"### Requirement: %s\" 在主 spec 里找不到"
                    % (spec_name, name))
            continue
        name_to_block.pop(name)
    for block in plan["modified"]:
        current = name_to_block.get(block["name"])
        if current is None:
            raise SpecEngineError(
                "%s MODIFIED 失败：\"### Requirement: %s\" 在主 spec 里找不到；"
                "MODIFIED 必须整段替换同名 requirement" % (spec_name, block["name"]))
        head = _REQ_HEADER_RE.match(block["raw"].split("\n")[0])
        if not head or head.group(1).strip() != block["name"]:
            raise SpecEngineError(
                "%s MODIFIED 失败：\"### Requirement: %s\" 内容首行头不匹配"
                % (spec_name, block["name"]))
        current_scenarios = _parse_scenario_blocks(current["raw"])
        incoming_scenarios = set(_parse_scenario_blocks(block["raw"]))
        dropped = [name for name in current_scenarios
                   if name not in incoming_scenarios]
        if dropped:
            raise SpecEngineError(
                "%s MODIFIED 失败：\"### Requirement: %s\" 的现有场景 %s 没有出现在"
                "修改块里；MODIFIED 必须携带整段内容，否则归档会丢场景"
                % (spec_name, block["name"],
                   ", ".join('"%s"' % item for item in dropped)))
        # JS Map.set 对已有键不改变位置——dict 同语义，原位替换。
        name_to_block[block["name"]] = block
    for block in plan["added"]:
        if block["name"] in name_to_block:
            raise SpecEngineError(
                "%s ADDED 失败：\"### Requirement: %s\" 已存在；新增不能与现有"
                "requirement 重名" % (spec_name, block["name"]))
        name_to_block[block["name"]] = block
    # —— 重建（顺序：原文顺序的存留块 → 改名块 → 新增块，同 CLI） ——
    kept = []
    seen_keys = set()
    for block in parts["body_blocks"]:
        replacement = name_to_block.get(block["name"])
        if replacement is not None:
            kept.append(replacement)
            seen_keys.add(block["name"])
    for key, block in name_to_block.items():
        if key not in seen_keys:
            kept.append(block)
    pieces = []
    if parts["preamble"].strip():
        pieces.append(parts["preamble"].rstrip())
    pieces.extend(block["raw"] for block in kept)
    req_body = "\n\n".join(pieces).rstrip()
    segments = [parts["before"].rstrip(), parts["header_line"], req_body,
                parts["after"]]
    if segments[0] == "":
        segments = segments[1:]
    rebuilt = re.sub(r"\n{3,}", "\n\n", "\n".join(segments))
    counts = {
        "added": len(plan["added"]),
        "modified": len(plan["modified"]),
        "removed": len(plan["removed"]),
        "renamed": len(plan["renamed"]),
    }
    return rebuilt, counts, warnings


def _has_delta_specs(change_dir):
    """镜像 archive 的 hasDeltaSpecs 探测：一层 specs/<域>/spec.md，区分大小写。
    v5 布局改看 change.md 的规格条目节（同一条 _HAS_DELTA_RE 探测正则）。
    坏编码统一传播为带 UTF-8 指引的引擎错误（吞成 False 会让"有规格但读不了"
    伪装成"无规格轻量单"，规格被静默丢弃）。"""
    if _change_layout(change_dir) == "v5":
        doc = _read_change_doc(change_dir)
        return any(_HAS_DELTA_RE.search(item["body"]) for item in doc["domains"])
    specs_dir = os.path.join(change_dir, "specs")
    try:
        entries = os.listdir(specs_dir)
    except OSError:
        return False
    for entry in sorted(entries):
        candidate = os.path.join(specs_dir, entry, "spec.md")
        if not os.path.isdir(os.path.join(specs_dir, entry)):
            continue
        try:
            content = _read_text_utf8(candidate)
        except OSError:
            continue
        if _HAS_DELTA_RE.search(content):
            return True
    return False


def _find_spec_updates(change_dir, main_specs_dir):
    """待合并 delta 清单，每项 domain/content/target/exists。

    legacy 镜像 findSpecUpdates：只认一层 specs/<域>/spec.md（嵌套层不合并，
    与 CLI 一致）。v5 从 change.md 的规格条目节取内容；两种布局都按域名
    排序，保证 merged 顺序确定且与 legacy 语义一致。"""
    updates = []
    if _change_layout(change_dir) == "v5":
        doc = _read_change_doc(change_dir)
        if doc["duplicate_domains"]:
            raise SpecEngineError(
                "change.md 规格条目域重复：%s；同域 delta 合并到一节后重试"
                % "、".join(sorted(set(doc["duplicate_domains"]))))
        for item in sorted(doc["domains"], key=lambda it: it["domain"]):
            domain = _validate_v5_domain(item["domain"])
            target = os.path.join(main_specs_dir, domain, "spec.md")
            updates.append({
                "domain": domain,
                "content": item["body"],
                "target": target,
                "exists": os.path.isfile(target),
            })
        return updates
    specs_dir = os.path.join(change_dir, "specs")
    try:
        entries = sorted(os.listdir(specs_dir))  # 域名排序，保证 merged 顺序确定
    except OSError:
        return updates
    for entry in entries:
        if not os.path.isdir(os.path.join(specs_dir, entry)):
            continue
        source = os.path.join(specs_dir, entry, "spec.md")
        if not os.path.isfile(source):
            continue
        target = os.path.join(main_specs_dir, entry, "spec.md")
        updates.append({
            "domain": entry,
            "content": _read_text_utf8(source),
            "target": target,
            "exists": os.path.isfile(target),
        })
    return updates


def _move_directory(src, dest):
    """目录移动：优先原子 rename；跨盘/权限失败退化为 copy+delete（同 CLI）。

    Windows 杀软可能短暂锁目录，rename 带小步重试。
    """
    last_error = None
    for attempt in range(4):
        try:
            os.rename(src, dest)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.05 * (2 ** attempt))
        except OSError as exc:
            last_error = exc
            break
    try:
        shutil.copytree(src, dest)
        shutil.rmtree(src)
    except OSError as exc:
        raise SpecEngineError(
            "归档移动失败（%s → %s）：%s；rename 错误：%s"
            % (_posix(src), _posix(dest), exc, last_error))


def _sweep_main_specs_for_leak(root):
    """吸收 comet verify_main_specs_clean：主 specs 不得残留 delta 分节字样。

    引擎把它做成归档前置检查（见模块注释差异 3），返回违规文件的 posix 相对路径。
    """
    leaked = []
    specs_dir = _main_specs_dir(root)
    if not os.path.isdir(specs_dir):
        return leaked
    for entry in sorted(os.listdir(specs_dir)):
        spec_file = os.path.join(specs_dir, entry, "spec.md")
        if not os.path.isfile(spec_file):
            continue
        try:
            content = _read_text_utf8(spec_file)
        except OSError:
            continue
        if _LEAK_RE.search(_norm_newlines(content)):
            leaked.append("openspec/specs/%s/spec.md" % entry)
    return leaked


def archive(root, change, date=None):
    """归档一个 change：全量校验 → delta 合并进主 specs → 移动目录。

    等价 ``openspec archive <change> --yes``（校验开启、跳过所有交互确认），
    外加半成功免疫：目标冲突/校验失败发生在任何写盘之前；写盘后移动失败会
    回滚已写的主 specs。``date`` 仅供测试注入（YYYY-MM-DD），默认 UTC 今天。

    返回 ``{"archived_to", "archive_name", "merged", "totals", "tasks",
    "warnings"}``；失败抛 SpecEngineError 且现场保持原样、可重跑。
    """
    root = os.path.abspath(root)
    change_dir = _require_change_dir(root, change)
    if date is not None and not _DATE_RE.match(str(date)):
        raise SpecEngineError("date 必须是 YYYY-MM-DD 格式：%s" % date)
    # v5 布局混用先拒：无 delta 的混用单会跳过 delta 校验直接进移动，把
    # 未合并的旧 delta 悄悄埋进档案——必须在任何动作之前拦住。
    _require_layout_pure(change_dir)
    warnings = []
    # —— 第 1 步：delta 校验（与 CLI 相同：只有探测到 delta spec 才校验） ——
    if _has_delta_specs(change_dir):
        issues = _collect_delta_issues(change_dir)
        errors = [text for level, text in issues if level == "ERROR"]
        if errors:
            raise SpecEngineError(
                "change '%s' 的 delta 校验未通过，归档中止（未改动任何文件）：\n- %s"
                % (change, "\n- ".join(errors)))
    # —— 第 2 步：任务进度（--yes 语义：不完整只警告不阻塞） ——
    tasks = _count_tasks(change_dir)
    incomplete = max(tasks["total"] - tasks["completed"], 0)
    if incomplete > 0:
        warnings.append("有 %d 个任务未完成，按 --yes 语义继续归档" % incomplete)
    # —— 第 3 步：纯内存计算所有 spec 合并结果（零写盘） ——
    main_specs = _main_specs_dir(root)
    staged = []  # (update, rebuilt, original_or_None)
    totals = {"added": 0, "modified": 0, "removed": 0, "renamed": 0}
    for update in _find_spec_updates(change_dir, main_specs):
        source_content = update["content"]
        target_content = (_read_text_utf8(update["target"])
                          if update["exists"] else None)
        rebuilt, counts, merge_warnings = _build_updated_spec(
            source_content, target_content, update["domain"], change)
        warnings.extend(merge_warnings)
        if not update["exists"]:
            # 新建域骨架的 Purpose 是 TBD 占位(与 CLI 逐字节一致,引擎不代写)。
            # 不提醒的话 TBD 会静默入库,真相源积累空洞。
            warnings.append(
                "新建域 %s 的真相源 Purpose 是 TBD 占位:请从 change.md「为什么」"
                "节浓缩补写 openspec/specs/%s/spec.md 的 Purpose 再提交"
                % (update["domain"], update["domain"]))
        # 重建结果的 spec 级校验（镜像 validateSpecContent；ERROR 即中止）。
        spec_issues = _validate_main_spec_content(update["domain"], rebuilt)
        spec_errors = [text for level, text in spec_issues if level == "ERROR"]
        if spec_errors:
            raise SpecEngineError(
                "域 '%s' 合并后的主 spec 未通过校验，归档中止（未改动任何文件）：\n- %s"
                % (update["domain"], "\n- ".join(spec_errors)))
        for level, text in spec_issues:
            if level != "ERROR":
                warnings.append(text)
        for key in totals:
            totals[key] += counts[key]
        staged.append((update, rebuilt, target_content))
    # —— 第 4 步：写盘前的全部前置检查（半成功免疫的关键顺序） ——
    archive_name = "%s-%s" % (date or _utc_today(), change)
    archive_path = os.path.join(_archive_dir(root), archive_name)
    if os.path.exists(archive_path):
        # CLI 在写完 specs 之后才做这个检查，会留下半成功现场；引擎提前到
        # 任何写盘之前（模块注释差异 1）。
        raise SpecEngineError(
            "归档目标已存在：%s；该 change 可能已归档过（重复归档被拒绝，"
            "未改动任何文件）" % _posix(archive_path))
    leaked = _sweep_main_specs_for_leak(root)
    if leaked:
        raise SpecEngineError(
            "主 specs 残留 delta 分节字样（## ADDED/MODIFIED/... Requirements），"
            "先修复再归档（未改动任何文件）：%s" % "、".join(leaked))
    # —— 第 5 步：写主 specs（逐文件原子写），失败回滚 ——
    written = []       # (target_path, original_or_None)
    created_dirs = []  # 为新建域创建的目录（回滚时清掉空目录）
    try:
        for update, rebuilt, original in staged:
            target_dir = os.path.dirname(update["target"])
            if not os.path.isdir(target_dir):
                created_dirs.append(target_dir)
            atomic_write_text(update["target"], rebuilt)
            written.append((update["target"], original))
        os.makedirs(_archive_dir(root), exist_ok=True)
        _move_directory(change_dir, archive_path)
    except Exception as exc:
        for target, original in reversed(written):
            try:
                if original is None:
                    os.remove(target)
                else:
                    atomic_write_text(target, original)
            except OSError:
                pass
        for directory in reversed(created_dirs):
            try:
                os.rmdir(directory)
            except OSError:
                pass
        if isinstance(exc, SpecEngineError):
            raise
        raise SpecEngineError(
            "归档写盘阶段失败，已回滚主 specs：%s" % exc)
    # —— 第 6 步：写盘后复核（纯断言性质；重建内容已过校验，正常不可能触发） ——
    leaked_after = _sweep_main_specs_for_leak(root)
    if leaked_after:
        raise SpecEngineError(
            "归档已完成但主 specs 复核发现 delta 残留（请人工检查）：%s"
            % "、".join(leaked_after))
    return {
        "archived_to": _posix(archive_path),
        "archive_name": archive_name,
        "merged": ["openspec/specs/%s/spec.md" % update["domain"]
                   for update, _rebuilt, _original in staged],
        "totals": totals,
        "tasks": tasks,
        "warnings": warnings,
    }
