# Mae-Flow 行为保持型重构第四阶段设计

**状态：** 按已批准的总设计和用户持续授权执行
**前置交付：** `refactor/mae-flow-phase-3` / `c50733b7042283b3bbc9c0c3536e00e479a9fcc6`
**日期：** 2026-07-29

## 1. 阶段目标

第四阶段拆分 `cmd_done()` 的完成裁决边界，使入口只负责编排以下固定阶段：

1. 建立当前完成上下文并处理兼容入口；
2. 校验配置、选择和用户确认；
3. 原子提交已验证的配置与选择；
4. 检查源码变化并按原规则回流；
5. 评估 Evidence；
6. 执行完成后的 Checkpoint、Moonlight、STORY 和推进动作。

本阶段不改变 CLI、stdout/stderr、退出码、状态字段、历史记录、Git 调用、文件操作和保存时机。
发现的产品缺陷只登记，不夹带修复。

## 2. 现状

`cmd_done()` 约 237 行，同时承担配置确认、选择验真、状态写入、分支保护、两种源码回流、
Evidence 拒绝、Checkpoint 激活、Moonlight 收尾、STORY 本地化和最终推进。任何局部修改都
需要理解全部路径，且无法单独测试其中的确定性规则。

整段迁移到新模块会把 Git、文件、进程、终端和状态仓库依赖一并搬走，只是移动单体；用十余个
回调模拟所有副作用也会让测试变成 mock 调用测试。因此采用“纯裁决 + 薄适配器阶段”的边界。

## 3. 组件边界

新增 `scripts/mae_flow_core/workflow/completion.py`，提供：

- `resolve_choice(step, state, requested)`：只处理 Moonlight 在途兼容选择；
- `choice_error(step, choice)`：生成原有选择错误；
- `choice_config(step, choice)`：返回流程定义中的配置增量；
- `evidence_failures(step, state, evaluators)`：按定义顺序执行 Evidence；
- `completion_events(step_id, step, state, choice, ack)`：规划 Evidence 成功后的动作。

完成事件包括：

- `adjust_checkpoint`
- `activate_checkpoint`
- `resolve_moonlight`
- `localize_story`
- `advance`

策略模块不修改输入，不读取 Git/文件/时间，不打印、不保存、不退出。

`scripts/mae-flow.py` 保留所有副作用，并把 `cmd_done()` 拆为命名适配器阶段。每个阶段严格保留
原控制流顺序；任何阶段返回“已处理”时，后续阶段不执行。

## 4. 时序约束

- 配置和用户确认全部通过前，不写 `st["config"]` 与 `st["choices"]`。
- STORY 兼容修复仍发生在 Evidence 前。
- 分支保护仍发生在源码回流与 Evidence 前。
- 源码回流仍会清除旧质量令牌、保存状态、输出当前步骤并立即返回。
- Evidence 失败仍先保存，再递增失败计数并构造原提示。
- Evidence 成功后才清零失败计数。
- Checkpoint 调整仍优先于 Moonlight、STORY 和 `advance()`。
- 最终动作按原顺序执行，`advance()` 始终是最后一个动作。

## 5. 测试策略

- 纯策略单元测试覆盖普通、Moonlight、非法选择、Evidence 顺序与失败、Checkpoint 两分支、
  Moonlight 收尾、STORY 本地化和最终 note。
- 适配器测试锁定 `cmd_done()` 的阶段顺序、提前返回和原始副作用调用。
- 固定基线差分增加至少一个 Evidence 失败场景和一个选择完成场景。
- 架构门禁限制 Workflow 函数复杂度不超过 15，并为 `cmd_done()` 建立显著低于现状的上限。
- 全量 unittest、selftest、固定 golden 差分和语法检查必须通过。

## 6. 非目标

- 不迁移各个 `ev_*` 的 Git/文件实现；
- 不修改 Gate、Agent task、Checkpoint、Standalone 或 Moonlight 命令；
- 不合并保存操作，不统一时间戳，不改变错误文案；
- 不修复 findings ledger 中的既有缺陷；
- 不合并到主分支、不推送远端。

## 7. 完成标准

1. `cmd_done()` 成为可读的阶段编排器，不再内联全部裁决；
2. 确定性完成规则只有一份，位于无副作用 Workflow 模块；
3. 新策略和适配器关键路径有独立测试；
4. 固定基线差分无变化；
5. 全量验证通过且工作树干净；
6. 结果冻结在独立 phase 4 分支。
