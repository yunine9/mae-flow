先读 .mae-flow-work/survey-{单号}.md(代码勘察笔记)——方案讨论所需的代码事实以它为底,只做增量探索,
**禁止全量重读代码**(全局最大耗时点就是各阶段重复全量读码,勘察一次共享全程);发现笔记有漏就补进笔记。
先执行 `python "{MAEFLOW_PATH}" spec show` 确认当前交付阶段与已登记产物(阶段应为 open)。
按下方内嵌的方案讨论原文做深度设计；**必须把 clarifications-{单号}.md(如有)作为输入**并声明:
- **跳过原文里的"理解问题/背景发现"提问阶段**——那是给没做过需求质询的项目准备的,
  本流程的 WHAT 层已由质询+规格覆盖,再问一遍就是 grill 的重复(用户已抱怨过这类重复);
  问题清单直接 =「留给设计阶段」清单 + 规格里标记的开放技术点;
- 文档中已拍板的需求级决策**不得重问**,直接作为设计约束引用;
- 「留给设计阶段」清单里的技术分歧是本阶段该聚焦的问题,优先展开;
- brainstorming 中若发现新的**需求级**缺口 → 停下补录进 clarifications 并与用户确认,再继续设计。
**设计文档写到 .mae-flow-work/design-{单号}.md**(完整版:背景/方案/替代方案/风险;过程件不入库,
git 本地排除已覆盖该目录);**设计结论浓缩进 change.md 的「# 方案」节**,替换「（待设计…」占位——
done 硬校验占位已消失,方案节是入库档案里设计的唯一落点,写"能让半年后的人看懂为什么这么做"的结论,
不是过程流水账。在途旧布局单(无 change.md 的):设计写进变更目录的 design.md,下条 design_doc 指它。
设计文档确认后执行(两条,顺序固定)：

1. `python "{MAEFLOW_PATH}" spec set design_doc ".mae-flow-work/design-{单号}.md"`（登记时会校验文件真实存在）
2. `python "{MAEFLOW_PATH}" spec phase build`（阶段 open→build；不可跳跃、不可回退）


**收尾自查**:done 前 `spec show` 确认 phase=build 且 design_doc 已登记（done 的证据就查这两项加占位消除）。
展示设计摘要后，若没有尚待用户决定的重大取舍，直接
git add openspec/ && git commit -m "[单号][类型]设计定稿"，再 done。
只有发现会改变需求边界、外部契约或存在两个明显不同且影响重大的方案时才 AskUserQuestion；
普通技术实现选择由 Agent 依据现有架构完成，不让用户为“设计阶段结束”签字。

──── 本步骤内嵌方法原文（已固定版本） ────
{{CAPABILITY_PACK:design}}
