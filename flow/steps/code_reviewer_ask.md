这是开场配置的最后一个短选择，必须在创建分支和开发前完成。用 AskUserQuestion 单选询问：

> 人工检视前，是否需要一次只读 CODE Agent 预检？

- 用户选“不需要 Agent 预检，我直接检视”：执行 `done --choice disabled`；
- 用户选“需要，人工检视前先由 Agent 预检”：执行 `done --choice enabled`。

简单、低风险需求推荐不启用，由用户直接检视；复杂、跨模块或高风险需求推荐启用。
拿到按钮结果后同轮直接执行 done，不要再要求用户输入确认句。

关闭只跳过这一次 Craft Reviewer Agent 预检；用户对完整未提交 diff 的人工检视和后续质量链均保留。

月光宝盒自动使用 `enabled`，不增加人工停顿。旧版在途状态缺少该字段时也按 `enabled` 兼容。
