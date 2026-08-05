Story 保持既有业务模板；Mae-Flow 的实施信息单独写入本地实施附录。

1. 从项目本地资源取得 `STORY-TEMPLATE.md` 和 `IMPLEMENTATION-TEMPLATE.md` 精确路径。
2. 执行 `python "{MAEFLOW_PATH}" role-task story-generate`，把输出的唯一启动话术原样交给 story-generator-agent。任务卡明确给出 `.mae-flow-work/{单号}/spec.md`、`grill.md`、相关 `docs/specs/*.md`、两个模板和代码路径。
3. 生成 `.mae-flow-work/{单号}/story.md` 与 `implementation.md` 后，执行 `python "{MAEFLOW_PATH}" role-task story-review`，把输出的唯一启动话术原样交给 craft-reviewer-agent，执行一次联合设计检视；任务卡给出同一组输入和两个输出路径。
4. 主 Agent 根据检视结果修正真实问题；不得因文件时间戳、摘要、格式或修正动作自动重新派 Reviewer。
5. 展示 Story 章节摘要、实施附录和全部未决项。用户修改后更新对应文件，最终只确认一次进入编码实现。

Story 与实施附录都不入库。禁止生成额外的编码前计划过程件。
