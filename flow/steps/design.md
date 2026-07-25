先读 .mae-flow-work/survey-{单号}.md(代码勘察笔记)——方案讨论所需的代码事实以它为底,只做增量探索,
**禁止全量重读代码**(全局最大耗时点就是各阶段重复全量读码,勘察一次共享全程);发现笔记有漏就补进笔记。
先执行 `python "{MAEFLOW_PATH}" capability comet-state -- check "{CHANGE_NAME}" design`，
再执行 `python "{MAEFLOW_PATH}" capability comet-handoff -- "{CHANGE_NAME}" design --write` 生成可追溯交接包。
按下方内嵌的方案讨论原文做深度设计；**必须把 clarifications-{单号}.md(如有)作为输入**并声明:
- 文档中已拍板的需求级决策**不得重问**,直接作为设计约束引用;
- 「留给设计阶段」清单里的技术分歧是本阶段该聚焦的问题,优先展开;
- brainstorming 中若发现新的**需求级**缺口 → 停下补录进 clarifications 并与用户确认,再继续设计。
设计文档确认后执行：

1. `python "{MAEFLOW_PATH}" capability comet-state -- set "{CHANGE_NAME}" design_doc "<设计文档路径>"`
2. `python "{MAEFLOW_PATH}" capability comet-handoff -- "{CHANGE_NAME}" design --write`
3. `python "{MAEFLOW_PATH}" capability comet-guard -- "{CHANGE_NAME}" design --apply`

**收尾自查(闪退/中断防线)**:done 前确认 .comet.yaml **phase 已=build**；仍卡在 design 就重跑第 3 条，
否则下一步写文档会被阶段检查拦住。
展示设计摘要后，若没有尚待用户决定的重大取舍，直接
git add openspec/ docs/superpowers/ && git commit -m "[单号][类型]设计文档"，再 done。
只有发现会改变需求边界、外部契约或存在两个明显不同且影响重大的方案时才 AskUserQuestion；
普通技术实现选择由 Agent 依据现有架构完成，不让用户为“设计阶段结束”签字。

──── 本步骤内嵌方法原文（已固定版本） ────
{{CAPABILITY_PACK:design}}
