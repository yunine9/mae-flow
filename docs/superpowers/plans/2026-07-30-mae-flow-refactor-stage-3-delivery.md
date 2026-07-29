# Mae-Flow Stage 3：Delivery Use Cases 实施计划

> 每项严格 RED → GREEN → 回归 → 小提交；Phase-12 不可修改。

## Task 1：建立 Phase-13 Delivery Oracle

- 追加 Checkpoint staged/continuous/revise/final；
- 追加 Standalone confirm/cancel/finish；
- 追加 Moonlight defer/push-failed/finalize/repair；
- 固定 Phase-13 逐项保留 Phase-12；
- 提交 `test: characterize delivery use cases`。

## Task 2：建立不可变 Delivery 结果与 effect 模型

- 测试 effect 顺序、严格值类型、兼容输出；
- 新增 `delivery/models.py` 与 application ports；
- 提交 `refactor: establish delivery use case results`。

## Task 3：迁移 Checkpoint plan/ready

- 固定计划生成、源码漂移、compile receipt 与 snapshot；
- CLI 只收集事实和执行 effects；
- 提交 `refactor: extract checkpoint planning use cases`。

## Task 4：迁移 Checkpoint status/final/decide

- 固定 commit/push 前后、continue/revise、final delta；
- 保留 Git 调用和用户停点顺序；
- 提交 `refactor: extract checkpoint review use cases`。

## Task 5：迁移 Standalone Action 生命周期

- 固定 start/confirm/status/critic/finish/cancel 和过期/损坏恢复；
- 不创建完整 Flow State、不提交源码；
- 提交 `refactor: extract standalone delivery use cases`。

## Task 6：迁移 Moonlight 用例

- 固定 blocked/defer/push-failed/unlock/finalize/repair；
- 保留报告、issue ID、history 和 terminal 指针顺序；
- 提交 `refactor: extract moonlight delivery use cases`。

## Task 7：删除 CLI Delivery 业务实现

- AST 门禁阻止 Delivery 状态判断回流入口；
- 相关测试迁到公开 application API，保留装配冒烟；
- 更新架构文档；
- 提交 `refactor: remove delivery policy from cli`。

## Task 8：Stage 3 全量证明与独立审查

- 完整 unittest、自检、Phase-13、fault injection；
- State/Checkpoint/Standalone/Moonlight 严格 ResourceWarning；
- 大小、复杂度、依赖、私有单体耦合和格式检查；
- 独立审查，修复全部 Critical/Important；
- 最终提交 `docs: record delivery refactor completion`。
