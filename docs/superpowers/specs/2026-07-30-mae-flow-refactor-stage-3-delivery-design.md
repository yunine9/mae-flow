# Mae-Flow Stage 3：Delivery Use Cases 设计

## 目标

将 Checkpoint、Standalone Action 与 Moonlight 的用例编排迁出 CLI，使交付状态转换、
动作顺序和恢复路径可通过显式端口独立测试；保持所有命令、输出、状态 schema、Git
行为和用户停点不变。

## 当前边界

`delivery/checkpoints.py` 和 `delivery/moonlight.py` 已包含少量纯规则，但 CLI 仍负责：

- Checkpoint plan/ready/status/final/decide 的状态分支、快照与 Git 时序；
- Standalone action start/confirm/status/critic/finish/cancel 的生命周期；
- Moonlight blocked/defer/push-failed/unlock/finalize 的报告与恢复编排。

这些函数与打印、StateStore、Git、文件和用户确认耦合，测试只能动态加载单体。

## 目标结构

- `application/delivery/checkpoints.py`：命令输入 → 有序 `DeliveryEffect` 与结果；
- `application/delivery/standalone.py`：独立任务生命周期用例；
- `application/delivery/moonlight.py`：无人值守 issue/repair/finalize 用例；
- `delivery/models.py`：不可变命令结果、事件与 effect 请求；
- 现有 `delivery/checkpoints.py`、`delivery/moonlight.py` 保持纯策略。

Application 用例只通过 ports 请求 Git、快照、State、报告和时钟；不得直接
`open`、`subprocess`、`chdir` 或 `print`。CLI 适配器依序执行 effect 并原样映射输出。

## 行为冻结

Phase-13 只追加 staged/continuous/revise、final review、Standalone scope/cancel、
Moonlight defer/push-failed/finalize/repair 场景。Phase-12 所有快照逐项不变。

特别冻结：

- Checkpoint 的 review-before-commit 与 commit-before-review 两种模式；
- receipt 与 HEAD/worktree snapshot 绑定；
- push 前状态、失败恢复和用户 revise/continue 决策；
- Standalone 不创建完整 flow State，不自动提交；
- Moonlight 质量失败留痕继续、客观阻塞停止、push 失败不伪装成功；
- sidecar/报告写入与 history 事件顺序。

## 完成条件

- CLI 不再包含 Delivery 状态转换或恢复业务判断；
- 三组用例均可用 fake ports 独立测试；
- 模块 ≤500 行、复杂度 ≤15；
- Phase-13、完整测试、fault injection、ResourceWarning 与独立审查通过。
