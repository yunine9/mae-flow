这是开场配置的最后一个短选择，必须在创建分支和开发前完成。用 AskUserQuestion 单选询问：

> 是否启用独立 CODE Reviewer？

- 用户选“不启用独立 CODE Reviewer”：执行 `done --choice disabled`；
- 用户选“启用独立 CODE Reviewer”：执行 `done --choice enabled`。

简单、低风险需求推荐不启用，由用户直接检视；复杂、跨模块或高风险需求推荐启用。
拿到按钮结果后同轮直接执行 done，不要再要求用户输入确认句。

关闭只跳过每个 CP 编译后的 Craft Reviewer Agent、CODE Review 过程件和 Finding 复审环；
编码计划检视、用户 CP 代码检视、最终增量检视和后续质量链均保留。

月光宝盒自动使用 `enabled`，不增加人工停顿。旧版在途状态缺少该字段时也按 `enabled` 兼容。
