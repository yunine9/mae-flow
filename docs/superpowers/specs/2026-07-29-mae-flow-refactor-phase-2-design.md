# Mae-Flow 行为保持型重构第二阶段设计

**状态：** 按已批准的总设计和用户授权执行
**前置交付：** `refactor/mae-flow-phase-1` / `2bca515`
**日期：** 2026-07-29

## 1. 阶段目标

第二阶段把“流程定义如何形成下一步”从 `scripts/mae-flow.py` 抽成独立、可验证的
Workflow 策略层，同时保持 CLI、Hook、状态、输出、退出码和副作用与固定基线完全兼容。

本阶段只迁移静态流程定义和纯转移解析，不拆解 `cmd_done`、Checkpoint、Evidence
求值或 Moonlight 副作用。这样可以先建立稳定的策略边界，再在后续阶段迁移执行推进。

## 2. 方案比较与决策

### 方案 A：直接拆 `cmd_done` 和 `cmd_gate`

收益最大，但两个函数当前圈复杂度分别为 88 和 160，并混合用户确认、状态写入、Git、
Evidence、回流和输出。一次迁移的可观测面太大，不适合作为行为保持型重构的第二步。

### 方案 B：先拆 Checkpoint 子状态机

Checkpoint 的业务边界相对完整，但它同时依赖 Git HEAD、工作区、远端 push、用户收据和
历史兼容迁移。它适合在纯转移边界稳定后单独实施。

### 方案 C：拆流程定义和纯转移解析

这是本阶段采用的方案。它覆盖 `flow.json` 加载与静态校验、普通 `next`、`next_by`、
choice 分支和工作流全景链展开。所有运算都可用字典输入和字面量期望独立测试，且迁移时
旧私有函数可以保留为一行薄包装。

## 3. 组件边界

新增：

```text
scripts/mae_flow_core/workflow/
  __init__.py
  definition.py
  transitions.py
```

### `definition.py`

职责：

1. 使用 UTF-8 加载 `flow.json`，保持原有 `json.load` 异常语义。
2. 校验根结构、`start`、步骤映射、普通边、分支边和非终态步骤文档。
3. 返回结构化错误列表，不打印、不退出、不修改文件。

运行时入口只改为通过 `load_definition()` 读取 JSON；额外静态校验由 `selftest` 调用，
不在普通 CLI 启动时新增拒绝路径。

### `transitions.py`

职责：

1. `transition_targets(step)`：枚举一个步骤声明的所有静态目标。
2. `next_step(step, state, choice_override="")`：保持现有普通、`next_by` 和 choice
   解析语义，包括缺失键或坏结构时返回 `None`。
3. `resolved_next(flow, state, step_id)`：解析历史步骤的实际下一步。
4. `workflow_chain(flow, workflow)`：按既有“可选环节选择完整分支”的规则展开工作流，
   并用 visited 集合保持环路停止语义。

模块不得读取状态文件、调用 Git、打印、退出、启动进程或修改当前目录。

### 稳定入口

`scripts/mae-flow.py` 继续保留：

- `load_flow`
- `_next_from_step`
- `_resolved_next`
- `_workflow_chain`

这些私有函数在迁移期只委托新模块，不保留第二份规则。其调用方和返回值不改变。

## 4. 数据流

```text
flow/flow.json
  -> workflow.definition.load_definition
  -> 原始兼容 dict
  -> workflow.transitions 纯函数
  -> mae-flow.py 薄包装
  -> 现有 current / done / steps / 恢复逻辑
```

本阶段不引入新的数据类，也不重排 `flow.json`。原始字典仍是运行时兼容表示。

## 5. 错误与兼容策略

1. 文件不存在、编码错误和 JSON 语法错误继续由 `open/json.load` 产生原异常。
2. 运行时不新增 definition 校验，因此现有坏配置的 CLI 失败时机不改变。
3. `next_step` 继续对缺失 choice、错误映射或异常状态返回 `None`。
4. `workflow_chain` 继续对环路在首次重复时停止，不改变展示分支的选择优先级。
5. 发现静态流程与动态实现不一致时只更新 findings ledger，不在本阶段修正流程。

## 6. 测试策略

### 纯策略单元测试

用字面量 fixture 覆盖：

- 普通 `next`；
- `next_by=workflow`；
- `choice_key` 与显式 `choice_override`；
- 缺失 choice 和错误结构；
- 历史步骤解析；
- 四条工作流链；
- 环路停止；
- 无效 start、悬空边、缺失步骤文档。

每个新生产接口先观察缺失模块或缺失委托导致的 RED，再写最小实现。

### 兼容包装测试

动态加载 `scripts/mae-flow.py`，对同一 fixture 比较旧私有包装与新模块结果，防止单体内
残留或重新长出第二份规则。

### 黑盒差分

新增 `steps` 场景，从固定行为基线生成 `phase2.json`。比较完整 stdout、stderr、退出码、
文件、状态和 Git 快照，确保工作流全景输出逐字节兼容。

### 架构门禁

扩展 AST 规则：

- Workflow 策略层禁止 `print`、`sys.exit`、`subprocess.*` 和 `os.chdir`。
- 新生产模块不得超过 500 行。
- `scripts/mae-flow.py` 和 `hooks/dispatch.py` 继续禁止净增长。

## 7. 完成标准

1. 四个旧私有入口均为薄委托，调用方无需修改。
2. Workflow 模块可独立测试和理解，且没有副作用依赖。
3. `steps` 黑盒快照与固定基线一致。
4. 全量 `unittest`、`scripts/selftest.py`、架构测试和差分测试通过。
5. 疑似 Bug 只进入 findings ledger；本阶段不包含行为修复提交。
