# Mae-Flow 行为保持型重构第八阶段设计

**前置交付：** `refactor/mae-flow-phase-7` / `30e49ac`

## 目标

收口 CLI 命令分发与架构说明，完成本轮重构。现有 `main()` 同时承担项目根定位、
状态损坏逃生、全局命令、Action 子命令、Runtime 模式门禁和活跃流程命令分发，
使新增命令必须修改一条较长且容易破坏顺序的条件链。

## 结构

- `mae_flow_core/command_dispatch.py`：只保存 Action 与活跃流程命令到处理器名称、
  调用参数形状的不可变路由描述，不执行 I/O。
- `mae-flow.py`：保留命令处理器和副作用，增加四个命名适配器，严格按旧顺序处理：
  全局可用命令、Action、Runtime 模式、活跃流程命令。
- `main()`：只负责解析参数、定位项目、加载 Flow/Runtime/State，并串联上述适配器。
- 架构文档记录模块边界、依赖方向、兼容桥接和后续扩展入口。

路由未命中使用私有 sentinel，避免把“处理器正常返回 `None`”误判成未处理。
处理器名称与调用参数由测试校验，模式门禁仍由适配层执行。

## 行为保持

- 不改变 `load_flow()`、`resolve_runtime()`、`load_state()` 的调用顺序；
- 不改变损坏状态下 `exit` / `doctor` 的逃生优先级；
- 不改变 `envcheck`、`steps`、`init`、`moonlight on|continue` 等全局命令的可用范围；
- 不改变 DIRECT、STANDALONE、CORRUPT 的拒绝文案与退出码；
- 不改变任何命令处理器的参数、输出、状态写入或 Git 操作。

## 验证

- 先以失败测试固定完整 Action/Flow 路由表和不可变路由；
- 固定旧实现增加一个分发覆盖场景并生成 phase 8 golden；
- 对 `main()` 和新适配器建立复杂度门禁；
- 运行全量 unittest、selftest、两次 phase 8 差分与架构测试；
- 更新维护者架构说明和已知问题账本，但不修复既有问题。

## 非目标

- 不重新设计 CLI 或 Runtime 状态机；
- 不删除仍承担兼容职责的桥接函数；
- 不修复发现账本中的产品缺陷；
- 不合并、不推送。
