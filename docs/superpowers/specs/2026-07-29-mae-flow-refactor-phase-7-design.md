# Mae-Flow 行为保持型重构第七阶段设计

**前置交付：** `refactor/mae-flow-phase-6` / `51b3938`

## 目标

统一 Checkpoint、Standalone 和 Moonlight 的交付子状态机边界。Standalone 已有独立状态仓库，
Checkpoint 已有细分命令，因此本阶段补齐 Checkpoint 纯导航策略，并拆分仍集成所有动作的
`cmd_moonlight()`。

## 结构

- `delivery/checkpoints.py`：当前检查点、期望代码步骤、锁定项、最终检视项和 pending/locked
  判定；只读 state。
- `delivery/moonlight.py`：issue id、晨间 finalize 目标和动作分类等纯规则。
- `cmd_moonlight` 保留授权启动与公共前置检查；blocked、push-failed、unlock-source、defer、
  repair、finalize 各自成为命名适配器。

所有状态字段、history 文案、issue 顺序、Git HEAD、保存与报告时机保持不变。

## 验证

- 纯 Checkpoint/Moonlight 状态测试；
- 现有 29 项 Checkpoint、Moonlight/selftest 与 Gate 测试；
- 固定旧实现的 Moonlight report/finalize 可观察基线；
- `cmd_moonlight` 与各动作建立复杂度门禁；
- 全量 unittest、selftest 和 phase 7 差分通过。

## 非目标

- 不改变夜间授权、十分钟 intent 或 ack 规则；
- 不修复既有产品缺陷；
- 不合并、不推送。
