# Mae-Flow 行为保持型重构第三阶段设计

**状态：** 按已批准的总设计和用户持续授权执行
**前置交付：** `refactor/mae-flow-phase-2` / `0a27a287410a8ffbc69871dcf4f0e8c9e10e41db`
**日期：** 2026-07-29

## 1. 阶段目标

第三阶段把 `advance()` 中“如何从当前步骤穿过兼容节点、检查点替代节点和月光旁路节点，
最终得到下一可见步骤”的规则抽成独立 Workflow 推进策略。

本阶段保持以下可观测行为不变：

- CLI 参数、stdout、stderr 和退出码；
- `.mae-flow.json` 的字段、历史记录内容和写入时机；
- Git HEAD 采集、评审快照、Moonlight 遗留关闭和报告生成；
- 旧版在途状态、Checkpoint 状态和 Moonlight 状态的兼容路由；
- `cmd_done`、`cmd_skip` 和 Moonlight defer 对 `advance()` 的调用契约。

本阶段不拆 `cmd_done()` 的证据校验，也不修正推进过程中发现的产品缺陷。疑似缺陷继续单独
登记到 findings ledger。

## 2. 现状与风险

当前 `advance()` 同时承担五类职责：

1. 进入转换前冻结 review HEAD 和 triage 文档快照；
2. 清理当前步骤实例的临时授权并追加完成历史；
3. 解析普通下一步和四组兼容/旁路路由；
4. 更新 Moonlight、`current`、`step_heads` 并持久化状态；
5. 生成 Moonlight 报告并打印下一步。

其中第 3 类是确定性策略，其余均为副作用。直接迁移整个函数会让新模块依赖 Git、文件系统、
状态仓库、报告和终端，虽然移动了代码，却没有形成可维护的边界。

推进策略还有一个容易遗漏的时序要求：一条路径可能连续产生多条审计记录，原实现是在每次
跨过节点时立即获取时间并追加。如果先一次性计算所有记录，再统一写入，极端情况下可能把
跨秒记录压成同一时间，也会改变异常发生前内存状态的顺序。

## 3. 方案比较与决策

### 方案 A：整体迁移 `advance()`，通过回调注入所有副作用

优点是单体文件缩减最多。缺点是新函数需要十余个回调，控制流仍与 I/O 混合；测试会主要
验证 mock 调用，而不是业务规则。它还扩大了 Git、文件和退出语义的迁移面，本阶段不采用。

### 方案 B：只抽取 history 和 `step_heads` 写入

风险最低，但最复杂的兼容路由仍留在单体中，无法为后续拆 `cmd_done()` 建立策略边界。
它只减少重复语句，不解决维护问题，本阶段不采用。

### 方案 C：抽取惰性的纯推进事件流

这是本阶段采用的方案。新策略按原控制流逐个产出：

- `audit`：应立即追加的一条兼容/旁路审计记录；
- `target`：最终应进入的步骤。

适配器每取得一个 `audit` 就在原位置生成时间并追加；取得 `target` 后再执行原有
Moonlight、HEAD、保存、报告和输出副作用。惰性事件流既让策略可用字典独立测试，又保持
原实现逐条推进、逐条落内存历史的顺序。

## 4. 组件边界

新增：

```text
scripts/mae_flow_core/workflow/advancement.py
scripts/tests/test_workflow_advancement.py
```

### `advancement.py`

提供：

```python
TransitionEvent(kind, step, result="", note="")
TransitionResolutionError(step_id)
transition_events(flow, state, step_id, step)
PACE_STEPS
```

职责：

1. 调用既有 `transitions.next_step()` 解析普通目标；
2. 保持旧在途状态跳过新增 pace 节点的规则；
3. 保持旧在途状态跳过 `delivery_review` 的规则；
4. 保持 Checkpoint 已接管后替代三类 legacy review 节点的规则；
5. 保持 Moonlight 连续旁路 `skip_in_moonlight` 节点及环路保护；
6. 保持 Moonlight 将 `archive_confirm` 延后到 `push` 的规则；
7. 保持 Moonlight 完成 `push` 后进入 `moonlight_review` 的规则。

该模块只读取输入字典，不修改输入，不读取时间、文件或 Git，不打印、不退出、不保存状态。

### `mae-flow.py` 适配器

`advance()` 继续负责：

1. review HEAD、review triage 等转换前快照；
2. `unlock`、`risk_acceptances` 清理和本步骤完成历史；
3. 消费 `transition_events()`，为每条 `audit` 生成原格式时间并追加；
4. 将 `TransitionResolutionError` 转成原有文案和退出码；
5. Moonlight issue 关闭、push 时间/HEAD、`current`、`step_heads`；
6. `save_state()`、Moonlight 报告、stdout 和 `print_current()`。

`PACE_STEPS` 从新模块导入，原有其他调用方继续使用同一个符号，避免形成两份常量。

## 5. 事件与错误语义

### 审计事件

事件中的 `step`、`result` 和 `note` 必须逐字保持旧实现。`at` 不进入纯策略，由适配器在
消费该事件时用原有 `time.strftime("%Y-%m-%d %H:%M:%S")` 生成。

### 最终目标

每次正常迭代恰好以一个 `target` 事件结束。目标允许为空，以保持终止边的旧语义。

### 无法解析的 Moonlight 旁路

策略抛出 `TransitionResolutionError(step_id)`。适配器继续调用：

```python
die(
    f"月光旁路步骤 {step_id} 缺少可解析的 "
    "moonlight_choice/next，拒绝卡死流程。",
    2,
)
```

异常出现前已经产出的 audit 会按旧顺序存在于当前内存状态；由于未调用 `save_state()`，
磁盘状态仍不改变。

### 环路

Moonlight `skip_in_moonlight` 旁路继续使用 `seen` 集合。遇到重复节点时停止旁路并把该
节点作为最终目标，不新增错误或审计记录。

## 6. 数据流

```text
flow + state + 当前 step
  -> workflow.advancement.transition_events
       -> audit*（纯规则）
       -> target（纯规则）
  -> mae-flow.py / advance
       -> 时间戳与 history
       -> Moonlight/Git/状态持久化
       -> 报告与终端输出
```

## 7. 测试策略

### 纯推进单元测试

使用手写 flow/state 覆盖：

- 普通目标，无 audit；
- 旧状态跳过新增 pace；
- 旧状态跳过最终 review；
- staged/continuous Checkpoint 替代 legacy review；
- Moonlight 连续旁路；
- Moonlight 旁路环路；
- Moonlight 旁路缺少可解析 next；
- Moonlight 延后 archive；
- Moonlight push 进入 morning review；
- 输入 flow/state 在成功与失败路径均不被修改。

### 适配器特征测试

动态加载 `mae-flow.py`，冻结时间和 HEAD，验证：

- audit 的字段、顺序和最终 `current`；
- `step_heads`、保存和输出仍由适配器产生；
- 非法 Moonlight 旁路仍以退出码 2 和原文案失败；
- review/Moonlight 的副作用前后顺序保持。

### 黑盒差分

在现有固定行为基线之上新增最小 `done` 场景，覆盖一次真实状态加载、推进、保存和下一步
输出。Phase 3 golden 继续与固定基线实现生成的结果比较，而不是用重构后实现自我批准。

### 架构门禁

- Workflow 策略继续禁止直接 `print`、进程、`sys.exit` 和 `os.chdir`；
- 新模块不超过 500 行、普通函数圈复杂度不超过 15；
- `advance()` 不再包含 pace、legacy review 和 `skip_in_moonlight` 的路由实现；
- `scripts/mae-flow.py` 不得超过 phase 2 行数基线。

## 8. 非目标

- 不拆 `cmd_done()` 的配置、确认、Evidence、源码回流或 Checkpoint 激活；
- 不改变 flow.json；
- 不合并 `save_state()` 调用；
- 不统一时间戳；
- 不调整历史文案；
- 不修复本阶段发现的产品 Bug；
- 不合并到主分支、不推送远端。

## 9. 完成标准

1. `advance()` 的动态路由由一个纯策略入口负责，单体中不保留第二份规则；
2. 新策略无直接副作用，成功与失败路径均不修改输入；
3. 所有原有推进分支由字面量期望测试覆盖；
4. 新增真实 `done` 黑盒场景与固定基线逐字节一致；
5. 全量 unittest、selftest、差分和架构门禁通过；
6. 工作树干净，结果冻结在独立 phase 3 分支。
