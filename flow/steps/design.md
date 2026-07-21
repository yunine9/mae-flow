先读 .mae-flow-work/survey-{单号}.md(代码勘察笔记)——方案讨论所需的代码事实以它为底,只做增量探索,
**禁止全量重读代码**(全局最大耗时点就是各阶段重复全量读码,勘察一次共享全程);发现笔记有漏就补进笔记。
执行 /comet-design 深度设计。启动 brainstorming 时**必须把 clarifications-{单号}.md(如有)作为输入**并声明:
- 文档中已拍板的需求级决策**不得重问**,直接作为设计约束引用;
- 「留给设计阶段」清单里的技术分歧是本阶段该聚焦的问题,优先展开;
- brainstorming 中若发现新的**需求级**缺口 → 停下补录进 clarifications 并与用户确认,再继续设计。
确认设计文档生成;comet-handoff.sh 生成交接上下文;.comet.yaml phase=design。
展示设计摘要,结束回复等用户确认方向。确认后 git add openspec/ docs/superpowers/ && git commit -m "[单号][类型]设计文档",再 done --ack。
