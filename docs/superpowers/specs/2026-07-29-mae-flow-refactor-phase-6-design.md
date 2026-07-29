# Mae-Flow 行为保持型重构第六阶段设计

**前置交付：** `refactor/mae-flow-phase-5` / `b2efe5b`

## 目标

拆分 `cmd_agent_task()` 的“事实观察、质量契约渲染、任务卡持久化”职责。任务卡正文、行顺序、
SHA256、路径、状态记录、CodeCheck 日志和终端输出保持不变。

## 结构

新增 `mae_flow_core.quality.task_cards`：

- 质量种类与允许步骤常量；
- `TaskCardDocument`：只积累文本行并生成与旧实现相同的正文和摘要；
- 文件组、依据、Checkpoint、轻量检查、CodeCheck 与 UT 目标的纯渲染函数；
- `task_record()`：生成待写入 `state["agent_tasks"]` 的纯记录。

入口适配器分为：

- `_agent_task_observe`：校验步骤、Checkpoint、Git 范围、脏文件与工具事实；
- `_agent_task_render`：把已观察事实交给纯契约渲染；
- `_agent_task_store`：写任务卡、日志、状态并输出；
- `cmd_agent_task`：按上述顺序编排。

## 约束

- 不重新执行任何 Git/CodeCheck/Lightcheck 观察；
- 不改变“先检查、后生成、再保存”的时序；
- 不把未找到需求、空代码范围或旧 token 从错误变成成功；
- 不修复现有 ResourceWarning；
- 不合并、不推送。

## 验证

- 纯任务卡文档、摘要和记录测试；
- 现有 task scope、CodeCheck logging、Checkpoint 与 Agent token 测试；
- 固定旧实现生成一张最小真实任务卡 golden；
- `cmd_agent_task` 建立显著下降的复杂度门禁；
- 全量 unittest、selftest、phase 6 差分通过。
