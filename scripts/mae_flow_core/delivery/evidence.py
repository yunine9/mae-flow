"""Delivery Evidence policies with explicit repository ports."""

import re
from dataclasses import dataclass

from ..foundation.models import EvidenceResult
from ..workflow.evidence import legacy_result


@dataclass(frozen=True)
class DeliveryEvidencePorts:
    moonlight: object
    development_review: object
    source_changed_since: object
    review_before_commit: object
    final_review_delta: object
    archive_delivery_paths: object
    shell_output: object
    argv_output: object
    committed_initial_carryover: object
    committed_delivery_paths: object
    trusted_harness_commit_path: object
    dirty_paths: object
    path_fingerprint: object
    repo_path_identity: object
    agent_written_paths: object
    read_text_replace: object
    agent_ran: object


def review_status_count(text, status):
    count = 0
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [
            value.strip().strip("*`")
            for value in line.strip().strip("|").split("|")
        ]
        if (len(cells) < 4 or cells[0] == "#"
                or set(cells[0]) <= {"-", ":"}):
            continue
        if cells[-1] == status:
            count += 1
    return count


def review_statuses(text):
    result = {}
    section = "未分节"
    for line in text.splitlines():
        heading = re.match(r"^\s*##\s+(.+?)\s*$", line)
        if heading:
            section = re.sub(r"\s+", " ", heading.group(1)).strip()
            continue
        if not line.lstrip().startswith("|"):
            continue
        cells = [
            value.strip().strip("*`")
            for value in line.strip().strip("|").split("|")
        ]
        if (len(cells) < 4 or cells[0] == "#"
                or set(cells[0]) <= {"-", ":"}):
            continue
        base = "%s / #%s / %s" % (
            section, cells[0], re.sub(r"\s+", " ", cells[1])[:40])
        identity, duplicate = base, 2
        while identity in result:
            identity = "%s / 重复%d" % (base, duplicate)
            duplicate += 1
        result[identity] = cells[-1]
    return result


def review_has_confirmed_fix(text):
    return review_status_count(text, "修复(已确认)") > 0


def _checkpoint_next_action(data, item):
    checkpoint = str(item.get("id", "当前 CP") or "当前 CP")
    status = str(item.get("status", "") or "")
    actions = {
        "planned": (
            "先展开本 CP 的生产代码 Task，并执行 checkpoint prepare"),
        "plan_review_pending": (
            "展示当前计划并执行 checkpoint plan-decide continue|revise"),
        "coding": (
            "完成生产代码修改和本批 compile-agent 后执行 "
            "checkpoint ready %s" % checkpoint),
        "craft_pending": (
            "执行 role-task craft-code --checkpoint %s，走读完成后执行 "
            "checkpoint craft-reviewed %s" % (checkpoint, checkpoint)),
        "craft_decision_pending": (
            "先执行 checkpoint craft-decide %s --review "
            "\"<已登记 CODE Review 路径>\"；源码已提前修改也可直接执行，"
            "命令会保留修改并安全回到 coding" % checkpoint),
        "review_pending": (
            "展示当前 CP 差异并执行 checkpoint decide "
            "continue|revise|continuous"),
        "commit_pending": (
            "执行 checkpoint status，按输出精确提交已检视快照；"
            "不要 amend 或重新 ready"),
        "commit_recovery": (
            "执行 checkpoint status，按输出让用户选择调整并安全拆回"),
        "reset_pending": (
            "执行 checkpoint status，按输出完成安全拆回"),
        "push_pending": (
            "执行 git push -u origin HEAD，成功后执行 checkpoint status"),
    }
    return actions.get(
        status,
        "执行 checkpoint status 获取当前状态的唯一恢复动作",
    )


class DeliveryEvidenceRules:
    def __init__(self, ports):
        self.ports = ports

    def checkpoint_plan(self, _spec, state):
        if self.ports.moonlight(state):
            return EvidenceResult(True, "")
        data = self.ports.development_review(state)
        if not data or data.get("status") != "plan_pending":
            return EvidenceResult(
                False,
                "尚未生成开发检查点方案。先按本步指令执行 "
                "checkpoint plan --item ...，让用户看到具体批次后再选择开发节奏",
            )
        if data.get("plan_step") != state.get("current"):
            return EvidenceResult(
                False, "检查点方案属于旧步骤，重新分析并生成本步方案")
        items = data.get("checkpoints") or []
        if not 1 <= len(items) <= 6:
            return EvidenceResult(
                False,
                "检查点数量必须为 1-6 个；小改可 1 个，常规任务建议 2-4 个",
            )
        changed, error = self.ports.source_changed_since(
            data.get("plan_head", ""), state)
        if error:
            return EvidenceResult(
                False, "检查点方案基点无法核实:" + error)
        if changed:
            return EvidenceResult(
                False,
                "检查点方案呈现后代码已经变化: "
                + "、".join(changed[:5])
                + "。必须在写码前重新生成方案，不能确认旧划分",
            )
        return EvidenceResult(True, "")

    def checkpoint_plan_complete(self, _spec, state):
        data = self.ports.development_review(state)
        if not data or self.ports.moonlight(state):
            return EvidenceResult(True, "")
        if data.get("status") != "active":
            return EvidenceResult(False, "开发节奏尚未完成用户确认")
        mode = data.get("mode")
        items = data.get("checkpoints") or []
        closed = (
            (lambda item: item.get("status") == "accepted")
            if mode == "staged"
            else (lambda item: item.get("status")
                  in ("completed", "accepted"))
        )
        pending = [
            item.get("id", "?") for item in items
            if not closed(item)
        ]
        if not pending:
            return EvidenceResult(True, "")
        index = int(data.get("current_index", 0) or 0)
        current = items[index] if 0 <= index < len(items) else None
        action = (
            _checkpoint_next_action(data, current)
            if current
            else "执行 checkpoint status 获取当前状态的唯一恢复动作"
        )
        return EvidenceResult(
            False,
            "检查点尚未闭环: %s。%s"
            % ("、".join(pending), action),
        )

    def final_review_clear(self, _spec, state):
        data = self.ports.development_review(state)
        if not data or self.ports.moonlight(state):
            return EvidenceResult(True, "")
        changed, error = self.ports.final_review_delta(state)
        if error:
            return EvidenceResult(
                False, "最终检视基点无法核实:" + error)
        if changed:
            return EvidenceResult(
                False,
                "质量链后仍有未检视代码增量: "
                + "、".join(changed[:8])
                + "。执行 checkpoint final；所有普通模式都先检视本地增量，"
                "用户确认后才进入最终 push",
            )
        return EvidenceResult(True, "")

    def archive_paths_clean(self, _spec, state):
        paths = self.ports.archive_delivery_paths(state)
        if not paths:
            return EvidenceResult(
                False,
                "缺少本次定稿的精确产物清单；重新执行 spec archive，"
                "或由维护人核对旧在途状态后再推进",
            )
        dirty = []
        for path in paths:
            output = self.ports.argv_output([
                "git", "status", "--porcelain", "--", path])
            if output:
                dirty.append(
                    "%s(%s)"
                    % (path, output.splitlines()[0][:2].strip()))
        if not dirty:
            return EvidenceResult(True, "")
        return EvidenceResult(
            False,
            "本次定稿产物尚未提交: " + "、".join(dirty)
            + "。只精确 git add 上述路径并提交；不要 git add openspec/，"
            "它可能卷入上一单遗留文件",
        )

    def commit_tagged(self, _spec, state):
        ticket = state["config"].get("单号", "")
        message = self.ports.shell_output(
            "git log -1 --pretty=%s")
        if not message:
            return EvidenceResult(False, "无法读取最新 commit")
        if re.match(
                r"^\[" + re.escape(ticket) + r"\]\[(feat|fix)\]",
                message):
            return EvidenceResult(True, "")
        return EvidenceResult(
            False,
            "最新 commit「%s」不符合 [%s][feat|fix]描述 格式。"
            "修复只需一条命令(不动已提交的改动内容):"
            "git commit --amend -m \"[%s][fix|feat]<原描述>\""
            % (message, ticket, ticket),
        )

    def commit_tagged_after_entry(self, spec, state):
        step = state.get("current", "")
        base = (
            (state.get("step_heads", {}) or {}).get(step, ""))
        if (
            not base
            or self.ports.argv_output(
                ["git", "cat-file", "-t", base]) != "commit"
        ):
            return EvidenceResult(
                False,
                "缺少 %s 的入口 HEAD，无法证明本步真的产生过提交" % step,
            )
        commits = self.ports.argv_output([
            "git", "log", "--format=%H", base + "..HEAD"]).splitlines()
        if not commits:
            return EvidenceResult(
                False,
                "当前步骤之后没有新提交，不能拿上一步的提交冒充本步产出",
            )
        return self.commit_tagged(spec, state)

    def _push_head_result(self, state):
        current = self.ports.shell_output(
            "git branch --show-current")
        wanted = state.get("config", {}).get("分支名", "")
        if wanted and current != wanted:
            return EvidenceResult(
                False,
                "当前分支 %s != 本单约定分支 %s，禁止在错误分支结束交付"
                % (current or "未知", wanted),
            )
        head = self.ports.shell_output(
            "git rev-parse --verify HEAD")
        upstream = self.ports.shell_output(
            "git rev-parse --verify @{u}")
        if not head:
            return EvidenceResult(False, "无法读取 HEAD")
        if not upstream:
            return EvidenceResult(
                False,
                "分支无上游跟踪——用 git push -u origin HEAD 推送并建立跟踪",
            )
        if head != upstream:
            return EvidenceResult(
                False,
                "本地 HEAD 与远端上游不一致(未推送/推送失败/远端有新提交):"
                "先尝试普通 git push -u origin HEAD；若远端领先，执行 git fetch "
                "后展示分叉，不要自动 rebase、reset 或 force-push"
                "（可能改写已检视检查点）",
            )
        return None

    def _push_committed_result(self, state):
        carried, error = self.ports.committed_initial_carryover(state)
        if error:
            return EvidenceResult(
                False, "无法核对是否夹带上一单遗留文件:" + error)
        if carried:
            return EvidenceResult(
                False,
                "远端提交夹带了流程启动前已存在、且本单 Agent 未实际改写的文件: "
                + "、".join(carried[:8])
                + ("…" if len(carried) > 8 else "")
                + "。这通常是上一单选择“不上传”后遗留的文件。"
                "请用普通后续提交精确移除这些文件并重新 push；"
                "不要 amend/rebase/force-push 改写已检视历史。"
                "若本单确实需要它，先让 Agent 按本单需求实际修改并重新检视",
            )
        paths, error = self.ports.committed_delivery_paths(state)
        if error:
            return EvidenceResult(
                False, "无法核对已推送 OpenSpec 的归属:" + error)
        foreign = [
            path for path in paths
            if path.startswith("openspec/")
            and not self.ports.trusted_harness_commit_path(path, state)
        ]
        if foreign:
            return EvidenceResult(
                False,
                "远端提交含不属于当前 CHANGE_NAME/本次归档的 OpenSpec 文件: "
                + "、".join(foreign[:8])
                + ("…" if len(foreign) > 8 else "")
                + "。请用普通后续提交精确移除并重新 push；"
                "STORY 不入库时应移入 .mae-flow-work/story",
            )
        return None

    def _changed_during_flow(self, state):
        current = set(self.ports.dirty_paths())
        initial = set(state.get("initial_dirty", []))
        if "initial_dirty" not in state:
            return current
        fingerprints = (
            state.get("initial_dirty_fingerprints", {}) or {})
        changed_initial = set()
        if fingerprints:
            changed_initial = {
                path for path in current & initial
                if fingerprints.get(path)
                != self.ports.path_fingerprint(path)
            }
        return (current - initial) | changed_initial

    def _push_dirty_result(self, state):
        changed = self._changed_during_flow(state)
        written = self.ports.agent_written_paths()
        dirty = {
            path for path in changed
            if (
                self.ports.repo_path_identity(path) in written
                or self.ports.trusted_harness_commit_path(path, state)
            )
        }
        story_mode = str(
            state.get("config", {}).get("STORY入库", "")).lower()
        if any(value in story_mode for value in (
                "不生成", "不入库", "不提交", "no", "false")):
            story = "docs/story/STORY-%s.md" % (
                state.get("config", {}).get("单号", ""))
            tracked = self.ports.argv_output([
                "git", "ls-tree", "-r", "--name-only",
                "HEAD", "--", story])
            if tracked:
                return EvidenceResult(
                    False,
                    "STORY 已确认不入库，但 %s 仍在当前提交中。"
                    "用 git rm --cached 精确移出索引并按单号提交修正；"
                    "本地文件可以保留。" % story,
                )
            dirty = {
                path for path in dirty
                if not path.startswith("docs/story/")
            }
        if dirty:
            return EvidenceResult(
                False,
                "仍有 Agent 实际写入或流程明确维护的交付候选未处理，"
                "远端不包含这些变化: "
                + "、".join(sorted(dirty)[:8])
                + "。逐个查看 diff：需要交付的精确提交，不需要的撤销修改；"
                "候选范围不代表必须全部提交。",
            )
        return None

    def pushed(self, _spec, state):
        for evaluator in (
            self._push_head_result,
            self._push_committed_result,
            self._push_dirty_result,
        ):
            result = evaluator(state)
            if result is not None:
                return result
        return EvidenceResult(True, "")

    def review_fix_committed(self, spec, state):
        path = "docs/review/REVIEW-%s.md" % (
            state.get("config", {}).get("单号", ""))
        try:
            text = self.ports.read_text_replace(path)
        except OSError:
            return EvidenceResult(
                False, "评审裁决文档不存在: " + path)
        baseline_rows = state.get("review_triage_statuses")
        current_rows = review_statuses(text)
        newly_transferred = []
        if isinstance(baseline_rows, dict):
            newly_transferred = [
                identity for identity, status in current_rows.items()
                if status == "转规格轮次(已确认)"
                and baseline_rows.get(identity) != "转规格轮次(已确认)"
            ]
        else:
            baseline = state.get("review_triage_transfer_count")
            transfers = review_status_count(
                text, "转规格轮次(已确认)")
            if isinstance(baseline, int) and transfers > baseline:
                newly_transferred = [
                    "旧状态新增%d条" % (transfers - baseline)]
        if newly_transferred:
            asked = legacy_result(self.ports.agent_ran(
                {"agent": "ASKUSER"}, state))
            if not asked.passed:
                return EvidenceResult(
                    False,
                    "rf_fix 把以下意见新改成了「转规格轮次(已确认)」: "
                    + "、".join(newly_transferred[:8])
                    + "；但本步没有真实 AskUserQuestion 用户裁决。"
                    "修复中改变既有裁决必须先向用户展示代码证据与行为影响，"
                    "再由用户确认；" + asked.reason,
                )
        if not review_has_confirmed_fix(text):
            return EvidenceResult(True, "")
        return self.commit_tagged_after_entry(spec, state)
