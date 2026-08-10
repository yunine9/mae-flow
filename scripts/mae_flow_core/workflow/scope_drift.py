"""规格里出现了需求原文没有的主题——这是凭空发明还是用户拍板的新增?

无人值守实战撞出来的:一次"新增短信渠道与失败重试"的交付,最终交了 25 个文件
+2076 行,里面有 alert_service.py、metrics.py、feature_flag.py、
validate-config.sh。追下去,"告警"在需求原文里出现 0 次,在 grill 出现 10 次、
decisions 11 次、spec 10 次、story 13 次——它在需求澄清那一步凭空发明了一个
告警子系统,之后每一层都忠实地把它带下去。

流程保证了从规格到代码的内部一致(验收项都实现了吗),却从没检查过反方向:
**这条验收项是从哪来的**。对弱模型来说,后者才是主要失效方式——它不是干得差,
是顺着自己的想象把活干得很漂亮。

这里只出候选清单,不判死:主题词对不上有两种可能——用户在澄清阶段确认过的
新增(正常),或者凭空发明(要删)。哪种只有人知道。
"""

import re

# 流程与文档的通用词:出现在规格里不说明任何范围问题。
_COMMON = frozenset("""
系统 需求 规格 条目 验收 场景 实现 方案 设计 代码 模块 服务 接口 参数 配置
文件 目录 路径 数据 结果 状态 类型 名称 内容 信息 记录 日志 说明 描述 备注
本次 当前 现有 既有 已有 新增 修改 删除 增加 支持 提供 使用 通过 根据 按照
必须 应当 不得 禁止 允许 需要 可以 保持 确保 校验 检查 验证 测试 用例
方式 情况 问题 原因 影响 范围 边界 前提 约束 假设 风险 遗留 建议 结论
用户 开发 交付 提交 分支 版本 时间 数量 上限 下限 默认 例如 以及 或者
决策 字符 最多 最少 错误 异常 成功 失败 触发 返回 输入 输出 字段 取值
""".split())

_TERM = re.compile(r"[一-龥]{2,6}")
_CODE_SPAN = re.compile(r"`[^`]*`|```.*?```", re.S)


def _terms(text):
    """取中文主题词;代码片段里的东西不算(那是实现细节,不是需求主题)。

    连续中文串要连同它的 2~3 字子串一起产出:整串取最长会把"失败率告警"当成
    一个词,真正该报的"告警"反而漏掉——实战里就是这么差点错过的。
    """
    plain = _CODE_SPAN.sub(" ", text or "")
    whole, inside = [], {}
    for run in _TERM.findall(plain):
        if run not in _COMMON:
            whole.append(run)
        if len(run) <= 3:
            continue
        for size in (2, 3):
            for start in range(len(run) - size + 1):
                piece = run[start:start + size]
                if piece not in _COMMON and piece != run:
                    inside.setdefault(piece, set()).add(run)
    # 子串只在"跨两种以上说法都出现"时才算主题:"告警"来自「失败率告警」
    # 与「监控与告警」两处,是真主题;"开通短"只从「按租户开通短信」切出来,
    # 是切碎的噪声。
    for piece, runs in inside.items():
        if len(runs) >= 2:
            whole += [piece] * sum(1 for r in runs for _ in (0,))
            whole += [piece] * (len(runs) - 1)
    return whole


def invented_topics(requirement, spec, floor=5, limit=5):
    """→ [(主题词, 在规格里出现次数)]，按出现次数从多到少。

    只报"在规格里反复出现(默认 ≥3 次)、而需求原文一次都没有"的词。偶尔提一句
    的不报——那多半是行文用语,不是新开的范围。
    """
    said = set(_terms(requirement))
    seen = {}
    for word in _terms(spec):
        if word in said:
            continue
        # 需求里没整词,但可能以更长的说法出现过(如"重试"vs"失败重试")
        if word in (requirement or ""):
            continue
        seen[word] = seen.get(word, 0) + 1
    # 只报 2~4 字:真正的主题词都在这个长度,更长的是短语("按租户开通短信"),
    # 拿它当"需求里没有的新范围"报出来纯属噪声。
    ranked = sorted(
        ((word, count) for word, count in seen.items()
         if count >= floor and 2 <= len(word) <= 4),
        key=lambda item: (-item[1], item[0]),
    )
    # 同一个概念的两种切法(互为子串、次数还完全相同)只留长的那个:
    # "可重"就是"可重试"切出来的碎片。但次数不同就是两个不同粒度的主题,
    # 都留——"回滚"和"回滚策略"各有各的意思,把短的去掉会丢掉真信号。
    kept = []
    for word, count in ranked:
        shadowed = any(
            word != other and word in other and count == other_count
            for other, other_count in ranked)
        if not shadowed:
            kept.append((word, count))
    return kept[:limit]


def drift_notice(topics):
    """→ 一行提示;没有漂移就返回空串。"""
    if not topics:
        return ""
    listed = "、".join("%s(%d 次)" % (word, count) for word, count in topics)
    return (
        "⚠ 规格里反复出现、而需求原文里一次都没有的主题: " + listed
        + "。两种可能:澄清阶段用户拍板的新增(正常,继续),"
        "或是凭空发明的范围(要删——实战里出现过整个告警子系统被发明出来,"
        "一路实现到交付)。逐个对一眼再确认。")
