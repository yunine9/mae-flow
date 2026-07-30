方案和实现清单已经稳定，现在只确认开发节奏，不重新讨论需求。

完整开发已经有人工确认的全局 CP 路线图和细粒度计划，执行：

`python "{MAEFLOW_PATH}" checkpoint plan --roadmap ".mae-flow-work/roadmap-{单号}.md" --plan ".mae-flow-work/plan-{单号}.md"`

命令从路线图读取 1-6 个 CP，冻结写码前 HEAD、路线图摘要、细粒度计划摘要和检查点列表。
hotfix 等没有路线图的旧入口继续使用兼容命令：

`python "{MAEFLOW_PATH}" checkpoint plan --item "<CP1 业务边界>" [--item "<CP2 业务边界>" ...]`

命令输出三个固定选项：

- `按检查点分阶段开发、推送和检视`：每批保持未提交，compile-agent 通过后先让用户在 IDE
  检视 Local Changes；确认后只提交该快照并普通 push；
- `一次完成全部代码，最终统一检视`：仍逐 CP 做 Task 分析、PLAN/CODE 独立走读和编译，
  但中途不 push、不等待用户，最终统一检视；
- `调整检查点划分`：不解锁源码，结合用户意见重新生成方案。

用户确认前禁止修改源码。月光宝盒自动旁路本步骤，保持无人值守。
