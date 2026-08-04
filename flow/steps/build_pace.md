从 `.mae-flow-work/{单号}/story.md` 的“CP 划分与轻量实施说明”读取 1-6 个 CP，并执行：

`python "{MAEFLOW_PATH}" checkpoint plan --item "<CP1 业务边界>" [--item "<CP2 业务边界>" ...]`

向用户展示 Story 中的 CP 列表并提供三个固定选项：

- `按检查点分阶段开发、推送和检视`（Staged）：每个 CP 编码、编译和可选 CODE 检视完成后停下，等待用户检视；
- `一次完成全部代码，最终统一检视`（Continuous）：连续完成所有 CP，中间不停，最后统一检视；
- `调整检查点划分`（Adjust）：只修改 Story 的 CP 小节，再重新展示本卡。

用户选择是唯一依据。主 Agent、实现 Agent 和 Reviewer 都不得根据“效率更高”等理由改变节奏。用户确认前禁止修改源码。
