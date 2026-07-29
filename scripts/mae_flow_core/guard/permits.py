"""Pure policies for Gate strike tracking and one-shot permits."""

import copy
from dataclasses import dataclass
import hashlib

from ..foundation.source_paths import normalize_path


@dataclass(frozen=True)
class PermitCheck:
    kind: str
    signed_head: str = ""


def block_id(rule, subject):
    payload = rule + "\n" + normalize_path(subject)
    return hashlib.sha256(
        payload.encode("utf-8", errors="replace")).hexdigest()[:10]


def check_permit(permits, permit_id, step, head):
    record = (permits or {}).get(permit_id)
    if (
        not record
        or record.get("used")
        or record.get("step") != step
    ):
        return PermitCheck("missing")
    signed_head = record.get("head", "")
    if signed_head and signed_head != head:
        return PermitCheck("stale", signed_head)
    return PermitCheck("valid", signed_head)


def record_strike(data, rule, step, permit_id, subject, now):
    result = copy.deepcopy(data or {})
    counts = result.setdefault("counts", {})
    entry = counts.get(rule) or {}
    if entry.get("step") != step:
        entry = {"step": step, "count": 0}
    entry["count"] = int(entry.get("count", 0) or 0) + 1
    entry["last_at"] = now
    counts[rule] = entry
    recent = result.setdefault("recent", {})
    recent[permit_id] = {
        "rule": rule,
        "step": step,
        "sample": subject[:200],
        "at": now,
    }
    while len(recent) > 20:
        oldest = min(
            recent, key=lambda key: recent[key].get("at", ""))
        recent.pop(oldest, None)
    return result, entry["count"]


def strike_escalation(
        count, limit, moonlight, permit_id, script_path):
    if count < limit:
        return ""
    if moonlight:
        return (
            "\n⚠ 本规则已在本步骤连续拦截 %d 次,可能是误拦。月光宝盒无人值守中"
            "不可放行:这属于客观阻塞,按 current 给出的 moonlight blocked"
            "(质量步骤用 defer)留痕停止,把拦截编号 %s 写进 reason,早晨由用户裁决。"
            % (count, permit_id)
        )
    return (
        "\n⚠ 本规则已在本步骤连续拦截 %d 次,可能是误拦。停止再试写法变体;"
        "若你确认该动作正当且必要:把动作原文和拦截原因展示给用户,用户同意后执行 "
        "python \"%s\" allow %s --ack \"用户同意原话\"。"
        "放行只对这一个动作生效一次,绑定当前代码版本,用后即废;其余规则不受影响。"
        "若动作确属违规,回到 current 指引换正规路径。"
        % (count, script_path, permit_id)
    )
