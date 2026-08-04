Story 是编码前唯一设计产物。

1. 从项目本地资源取得 `STORY-TEMPLATE.md` 精确路径。
2. 启动一次 story-generator-agent，任务卡明确给出 `.mae-flow-work/{单号}/spec.md`、`grill.md`、相关 `docs/specs/*.md`、模板和代码路径。
3. 生成 `.mae-flow-work/{单号}/story.md` 后，启动一次 craft-reviewer-agent 的 Story 设计检视；任务卡给出同一组输入和 Story 路径。
4. 主 Agent 根据检视结果修正真实问题；不得因文件时间戳、摘要、格式或修正动作自动重新派 Reviewer。
5. 展示 Story 章节摘要和全部未决项。用户修改后更新 Story，最终只确认一次进入开发节奏选择。

Story 不入库。禁止生成独立 Design、Test Blueprint、Roadmap 或详细 Build Plan；测试设计和轻量 CP 已在 Story 内。
