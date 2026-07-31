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
    if moonlight:
        return (
            "\n⚠ 本规则已在本步骤拦截 %d 次。月光宝盒无人值守中"
            "不可放行:这属于客观阻塞,按 current 给出的 moonlight blocked"
            "(质量步骤用 defer)留痕停止,把拦截编号 %s 写进 reason,早晨由用户裁决。"
            % (count, permit_id)
        )
    return (
        "\n⚠ 本规则本次拦截编号 %s。不要重试写法变体；若当前步骤已捕获到用户"
        "明确授权这一个 exact 动作/path/commit 的原话，先执行 messages 取得"
        "该回答 ID，再执行 python \"%s\" allow %s --message-id <ID>。"
        "否则先把动作原文和本次全部风险展示给用户裁决。放行只对这个动作"
        "生效一次，绑定当前步骤与代码版本；Git exact 授权消费后会留下 delivery"
        " 收据，push/done 不会重复否定。若动作确属违规，回到 current 指引。"
        % (permit_id, script_path, permit_id)
    )
