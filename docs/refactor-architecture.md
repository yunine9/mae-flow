# Mae-Flow 内核架构与扩展指南

本文描述行为保持型重构后的代码边界。用户行为、状态格式和安全规则仍以
`flow/flow.json`、步骤文档及 `MAINTAINERS.md` 为准；本文回答“规则应该放在哪里”
以及“怎样修改而不破坏既有功能”。

## 依赖方向

```text
CLI / Hooks（副作用适配层）
        │
        ├── command_dispatch（命令路由契约）
        ├── delivery（Checkpoint / Moonlight 交付子状态）
        ├── quality（质量任务卡）
        ├── guard（Git / 文件操作意图）
        ├── workflow（定义、转移、推进、完成裁决）
        ├── foundation（路径、指纹、Git 命令语义）
        ├── file_io（受管文件读写）
        ├── runtime（唯一运行模式裁决）
        └── state_store（状态迁移、锁与原子存储）
```

依赖只能由上向下。`foundation` 不得反向导入 workflow、guard、quality 或
delivery；纯规则模块不得直接 `print`、`chdir` 或启动进程。磁盘、Git、终端和退出码
仍由 `scripts/mae-flow.py` 与 `hooks/dispatch.py` 适配。

## 模块职责

| 模块 | 单一职责 | 不应包含 |
|---|---|---|
| `mae_flow_core/foundation/source_paths.py` | 源码、测试、构建文件的路径分类 | 流程步骤和状态写入 |
| `mae_flow_core/foundation/fingerprints.py` | 文件集合与检视快照指纹 | Git 命令执行 |
| `mae_flow_core/foundation/git_intent.py` | Git 命令的提交/添加意图解析 | Gate 放行裁决 |
| `mae_flow_core/file_io.py` | 确定关闭的文本、字节和 JSON 文件读写 | 状态迁移和业务裁决 |
| `mae_flow_core/workflow/definition.py` | 流程定义结构与边校验 | 当前运行状态 |
| `mae_flow_core/workflow/transitions.py` | 动态/兼容转移目标 | 保存和输出 |
| `mae_flow_core/workflow/advancement.py` | 推进事件与副作用顺序 | 直接执行副作用 |
| `mae_flow_core/workflow/completion.py` | choice、证据失败、完成事件 | 读取文件和 Git |
| `mae_flow_core/workflow/evidence.py` | Evidence 值规范化、唯一注册和有序执行 | 具体业务裁决与 I/O |
| `mae_flow_core/workflow/evidence_rules.py` | 文件、分支与规格 Evidence 纯裁决 | 直接文件或 Git 操作 |
| `mae_flow_core/workflow/agent_evidence.py` | Agent 令牌、源码新鲜度与检视快照裁决 | token 文件读取 |
| `mae_flow_core/guard/intent.py` | Edit/Bash/Git 请求的纯语义 | 用户提示与 exit code |
| `mae_flow_core/quality/task_cards.py` | 质量任务卡正文、摘要、记录 | Agent 派发和落盘 |
| `mae_flow_core/quality/evidence.py` | CodeCheck 扫描、缓存和豁免 Evidence 裁决 | 直接执行 CodeCheck |
| `mae_flow_core/delivery/checkpoints.py` | Checkpoint 导航和锁定判定 | Git push |
| `mae_flow_core/delivery/evidence.py` | Checkpoint、提交、push 和评审 Evidence 裁决 | 直接读写仓库 |
| `mae_flow_core/delivery/moonlight.py` | Moonlight issue/finalize 规则 | 报告写入和状态保存 |
| `mae_flow_core/command_dispatch.py` | Action/Flow 命令到处理器及参数的路由 | Runtime 模式门禁 |
| `mae_flow_core/runtime.py` | 唯一运行模式裁决 | 命令分发 |
| `mae_flow_core/state_store.py` | schema、锁、CAS、原子状态读写 | 业务推进规则 |

`scripts/mae-flow.py` 目前仍是兼容适配层。Evidence 的全部业务裁决和唯一注册源已经
迁入内核；CLI 只装配显式 I/O 端口，并为历史诊断保留无逻辑名称别名。其他旧处理器、
输出文案及调用顺序仍按后续阶段逐步迁移。新增业务判断应优先写成上述内核中的纯函数，
再由 CLI 处理 I/O。

## CLI 分发顺序

`main()` 的顺序是安全契约，不得交换：

1. 解析参数并定位项目根；
2. 加载 Flow、Runtime 和 State；损坏状态优先处理 `exit` / `doctor`；
3. 分发无需活跃完整流程的全局命令；
4. 应用 DIRECT、STANDALONE、CORRUPT 模式门禁；
5. 要求 State 存在并分发活跃流程命令。

处理器正常返回 `None`，所以路由适配器使用私有 sentinel 区分“已处理”与“未命中”。
Action 和活跃流程命令只在 `command_dispatch.py` 注册一次；全局命令和 Runtime
门禁因具有顺序语义，保留为命名适配器。

## 扩展方法

### 新增流程步骤

1. 在 `flow/flow.json` 声明步骤和边，并补 `flow/steps/<step>.md`；
2. 普通边用 `next`；源码变化回流用 `source_change_next` /
   `source_change_recheck`；其他运行时边在 `dynamic_next` 同步声明；
3. 只为升级前在途状态保留的入口加入顶层 `compatibility_entries`，不能把普通
   不可达步骤伪装成兼容入口；
4. `definition.py` 从 `start` 和兼容入口检查全图可达性；运行时选择策略仍放入
   `transitions.py`；
5. 新证据先写纯裁决测试，再在 `workflow/evidence.py` 的唯一构造函数注册；CLI
   只为对应规则对象装配 I/O 端口；
6. 更新 Workflow 单测和固定旧行为差分场景。

### 新增 CLI 命令

1. 在 `cli_parser.py` 定义参数；
2. 实现副作用处理器；
3. Action 或活跃 Flow 命令在 `command_dispatch.py` 增加路由和参数形状；
4. 若命令必须在 State 不存在时可用，将它放入 `_dispatch_global_command()`；
5. 若命令受运行模式影响，在 `_dispatch_runtime_mode()` 明确门禁；
6. 更新 `test_command_dispatch.py`、差分场景和 selftest。

不要同时在多个 `if` 链注册同一命令，也不要把 Runtime 文件存在性判断重新散落到
CLI 或 Hook。

### 新增状态字段

先在 `state_store.py` 定义迁移、默认值和未知字段保留策略，再写业务规则。任何
read-modify-write 必须经过 StateStore，不能用固定 `.tmp` 或裸 `json.dump` 覆盖主状态。

## 文件 I/O 边界

生产入口中的一次性读取和写入使用 `mae_flow_core.file_io`。需要流式处理或原子替换时
可以保留显式 `with open(...)`，但不得使用 `open(...).read()`、
`json.load(open(...))` 或依赖垃圾回收关闭文件。架构测试会扫描 CLI、Hook、
Comet 兼容层和状态栏入口，任何新增的未受管 `open()` 都会失败。

`file_io` 只管理文件生命周期，不吞异常、不改变 JSON 解码、不猜测编码。调用方必须
明确保留原有的 `encoding`、`errors`、`newline`、追加模式和读取上限。

## 行为安全网

验证分三层：

- 单元测试固定纯规则和适配器契约；
- `test_architecture.py` 限制依赖、文件大小及关键函数复杂度；
- `differential/runner.py` 在临时 Git 仓中比较固定重构前实现与当前实现的 stdout、
  stderr、退出码、状态、文件哈希和 Git 状态。

Phase-9 相比行为保持型 phase-8 只允许 `combined_git_add_flags` 这一项已批准缺陷修复：
`git add -fu`、`-uf`、`-Af` 必须按 Git 的组合短参数语义展开。新增差分阶段时，既有
场景值必须完全相同，只能增加经过明确分类的新场景。

Phase-10 只在 Phase-9 上增加 Stage-0 characterization 场景；测试会逐项比较所有
Phase-9 快照，旧值有任何变化都直接失败。`scripts/tests/differential/coverage.json`
必须为每个注册场景声明领域、Runtime、Workflow、Transition、Delivery 和故障类型，
同时 Phase-10 golden 必须与场景注册表一一对应。

Phase-11 只在 Phase-10 上增加 Evidence 迁移前的拒绝边界场景；测试继续逐项比较全部
Phase-10 快照。当前 golden 与场景注册表的一一对应以 Phase-11 为准，Phase-10 仍是
不可修改的 Stage-0 基线。

`scripts/tests/refactor_completion_contract.json` 保存最终入口行数、业务模块大小、复杂度
和迁移阶段。它是完成目标，不是当前代码的宽松基线：不得为了让现状通过而提高目标。
`scripts/tests/fault_injection.py` 只属于测试基础设施，生产代码不得导入；它用于在迁移
适配器前固定文件、Git、进程和状态存储的失败语义。

发版前入口仍是：

```bash
python scripts/selftest.py
```

结构重构还应额外运行完整 unittest discover，并从固定旧实现重新生成本阶段 golden。
动态时间、临时路径和任务卡摘要只能在差分归一化层处理，不能为测试修改产品输出。

## 兼容桥接

CLI 中与内核同名或相近的薄函数是有意保留的兼容桥接：旧测试、Hook 回调、证据表以及
运行时字符串路由可能仍通过这些名字调用。只有同时满足以下条件才能删除：

1. AST/全文搜索无直接调用；
2. 命令路由、证据注册表和 Hook 回调无字符串引用；
3. 固定旧实现差分与完整 selftest 均通过；
4. 删除不改变公开导入或历史状态迁移。

重构期间的问题及处置证据记录在
`docs/superpowers/mae-flow-refactor-findings.md`。缺陷修复必须使用独立测试和 `fix:`
提交，不能混入行为保持型重构。
