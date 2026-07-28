按 REVIEW-{单号}.md 里裁决为「修复(已确认)」的条目逐条修:
每条 修复 → 小步 commit([单号][类型]修复评审意见:<要点>)→ 在「修复对照」章记下 意见#→commit;
纪律与 build 相同:systematic-debugging(先复现读全报错定位根因再动手)、Ponytail the ladder 常驻;
**只修已裁决项,禁止顺手重构无关代码**——无关改动会污染 MR 增量,评审人还得再看一遍。
修复中发现某条意见实际涉及行为/规格变更 → 停下用 AskUserQuestion 呈用户裁决
(附代码证据、行为影响与建议),只有用户确认后才把该条改标「转规格轮次(已确认)」,本轮不修。
机器会对比裁决步收尾快照；新增「转规格轮次(已确认)」但本步没有 ASKUSER 令牌时 done 拒绝,
防止把用户已确认的「修复」单方面翻案。
中断恢复:读 REVIEW 文档「修复对照」章对照 git log,没有 commit 的条目接着修。
按编码前确认的 CP 顺序处理。每批完成后执行
`python "{MAEFLOW_PATH}" agent-task compile --checkpoint CPn --scope "<本批意见/模块>"`，
compile-agent OK 后执行 `checkpoint ready CPn`。分阶段模式按输出普通 push，并在
`checkpoint status` 验真远端后等待用户检视；一次完成模式直接进入下一批。
全部检查点闭环后 → 展示"意见 # → commit → 改动摘要"对照表 → done(机器校验最新 commit 格式)。
这是执行结果，不是新的用户决策，不再要求确认。
检查点编译只用于缩小反馈范围；done 后仍进入独立收尾编译步骤，确保最终源码有新鲜编译证据。

发生失败或评审意见本身可疑时，按下方内嵌的评审处理和系统化调试规则先查证再修改。

──── 本步骤内嵌方法原文（已固定版本） ────
{{CAPABILITY_PACK:review-fix}}
