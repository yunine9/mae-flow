"""Pure commit-candidate ownership decisions."""

from dataclasses import dataclass

from .gate import GateDecision


@dataclass(frozen=True)
class OwnershipFacts:
    review_required: bool
    expected_snapshot: dict
    current_snapshot: dict
    candidate_paths: tuple
    inherited: tuple
    foreign_openspec: tuple
    strong_artifacts: tuple
    unproven_paths: tuple
    artifact_hints: tuple


@dataclass(frozen=True)
class OwnershipDecision:
    block: object = None
    advisories: tuple = ()


def _review_block(facts):
    if not facts.review_required:
        return None
    if facts.current_snapshot != facts.expected_snapshot:
        return GateDecision(
            "block",
            "bash-checkpoint-reviewed-snapshot",
            "检视后的未提交代码已经变化，禁止拿旧确认提交新 diff。"
            "保留现场并重新进入调整、编译和检视。",
        )
    expected = set(facts.expected_snapshot)
    actual = set(facts.candidate_paths)
    if actual == expected:
        return None
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    detail = []
    if missing:
        detail.append("漏掉 " + "、".join(missing[:8]))
    if extra:
        detail.append("夹带 " + "、".join(extra[:8]))
    return GateDecision(
        "block",
        "bash-checkpoint-reviewed-files",
        "本次 commit 必须精确等于用户刚检视的文件；"
        + "；".join(detail)
        + "。按 checkpoint status 输出的精确 git add/commit 执行。",
    )


def _candidate_block(facts):
    if facts.inherited:
        return GateDecision(
            "block",
            "bash-cross-delivery-carryover",
            "提交前检测到流程启动前已经存在、内容至今未变，且本单 Agent "
            "没有实际改写的文件: "
            + "、".join(facts.inherited[:8])
            + ("…" if len(facts.inherited) > 8 else "")
            + "。它们属于上一单/用户现场，不能因为本次暂存而变成本单交付。"
            "执行 git restore --staged -- <上述路径> 只移出暂存区；"
            "若本单确实需要某文件，让 Agent 按本单需求实际修改并检视后再提交。",
        )
    if facts.foreign_openspec:
        return GateDecision(
            "block",
            "bash-foreign-openspec",
            "提交前检测到不属于当前 CHANGE_NAME 或本次定稿产物的 OpenSpec "
            "文件: "
            + "、".join(facts.foreign_openspec[:8])
            + ("…" if len(facts.foreign_openspec) > 8 else "")
            + "。请从暂存区移除；STORY 只能写到 docs/story/STORY-<单号>.md，"
            "选择不入库后由流程移入 .mae-flow-work/story。",
        )
    if facts.strong_artifacts:
        return GateDecision(
            "block",
            "bash-build-artifacts",
            "提交前检测到既非 Agent 直接改写、又属于本次新增的高置信临时编译产物: "
            + "、".join(facts.strong_artifacts[:8])
            + ("…" if len(facts.strong_artifacts) > 8 else "")
            + "。这些文件通常不应进入 MR。若已暂存，执行 "
            "git restore --staged -- <上述路径>（只移出暂存区，不删除本地文件），"
            "并把对应规则加入项目 .gitignore 后再提交；若命令是 git add && git commit，"
            "从 git add 清单中移除这些路径。",
        )
    return None


def _advisories(facts):
    messages = []
    if facts.unproven_paths:
        messages.append(
            "[mae-flow] ⚠ 提交提示:以下文件不在 Agent 通过 Write/Edit/MultiEdit "
            "实际改写的候选范围内，可能是编译、格式化或生成命令的副作用；"
            "也可能是必要的移动/删除，因此本次不阻断。请逐个确认: "
            + "、".join(facts.unproven_paths[:8])
            + ("…" if len(facts.unproven_paths) > 8 else ""))
    if facts.artifact_hints:
        messages.append(
            "[mae-flow] ⚠ 产物提示:以下候选位于常见输出目录或具有编译产物特征；"
            "即使 Agent 直接写过，也不代表必须提交，请结合 git diff 确认: "
            + "、".join(facts.artifact_hints[:8])
            + ("…" if len(facts.artifact_hints) > 8 else ""))
    return tuple(messages)


def decide_ownership(facts):
    block = _review_block(facts) or _candidate_block(facts)
    return OwnershipDecision(
        block=block,
        advisories=() if block else _advisories(facts),
    )
