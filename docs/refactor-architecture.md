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
| `mae_flow_core/guard/gate.py` | Edit 与 Bash 写入 Gate 裁决 | sidecar、Git 和退出码 |
| `mae_flow_core/guard/bash.py` | 通用 Bash/Git 安全规则及规则顺序 | 执行命令 |
| `mae_flow_core/guard/permits.py` | block id、一次性许可和三振升级策略 | sidecar 读写 |
| `mae_flow_core/guard/ownership.py` | 检视快照、跨单归属和产物候选裁决 | Git 候选采集 |
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

## Stage 1：Evidence 完成证据

Stage 1 已将通用、Agent、Delivery 和 Quality 共 24 个历史注册名（23 个规则名及
`yaml_field` 别名）的裁决迁出 CLI。`EvidenceRegistry` 是唯一注册和有序执行源；
历史 `EVIDENCE` 名称仅暴露同一个不可变只读映射，CLI 中不存在 `def ev_*` 或第二份
字典注册。

2026-07-30 在 Stage 1 最终提交上取得的新鲜验证结果：

- 完整 `unittest discover`：308 项通过；
- 完整 `scripts/selftest.py`：全部通过；
- Phase-11 differential runner：零差分；
- State、Checkpoint 及五组 Evidence 测试在
  `error::ResourceWarning` 下全部通过；
- Evidence 业务模块均不超过 500 行，策略复杂度门禁通过；
- Phase-10 golden 与 Stage 0 通过点逐字节一致；
- `git diff --check` 通过。

Stage 1 只降低职责耦合，不调整证据名称、失败文案、执行顺序、状态字段、文件副作用
或 Git 行为。后续阶段继续以 Phase-11 为当前追加式行为基线。

## Stage 2：Gate、Permit 与 Ownership 完成证据

Stage 2 将 Edit、Bash/Git、一次性放行令和提交归属规则迁入 `mae_flow_core.guard`。
CLI 只采集 Flow/State/Git/文件事实，执行 sidecar 与历史写入，并映射纯决策到既有
stderr/退出码；Hook 继续通过同一个 Gate 入口调用这些策略。架构测试禁止已迁移规则
ID 回流到 CLI 或 Hook。

2026-07-30 在 Stage 2 最终实现上取得的新鲜验证结果：

- 完整 `unittest discover`：328 项通过；
- 完整 `scripts/selftest.py`：全部通过；
- Phase-12 differential runner：零差分，且 Phase-11 全部快照逐项保持；
- fault injection：3 项通过；
- State、Checkpoint、Gate、Permit、Ownership 和 Bash 测试在
  `error::ResourceWarning` 下全部通过；
- 四个新增 Guard 业务模块分别为 291、264、77、119 行，复杂度门禁通过；
- `git diff --check main...HEAD` 通过。

Stage 2 没有修改规则优先级、block id 算法、permit/strike sidecar schema、失败文案、
Git 候选范围或 break-glass 安全等级。后续阶段继续以 Phase-12 为追加式行为基线。

## Stage 3：Delivery Use Cases 完成证据

Stage 3 将 Checkpoint、Standalone Action 与 Moonlight 的交付编排迁入
`mae_flow_core.application.delivery`。Checkpoint plan/ready/decide/final/status 以及
commit、push、reset 和旧状态恢复由显式 ports 取得 Git、快照、时间与用户消息事实，
返回不可变 `DeliveryResult`/`DeliveryEffect`；CLI 只装配端口、按顺序执行 effect
并保持既有输出。Moonlight defer 的 build 完成边界、脏源码阻断、步内源码变化回流及
质量缓存失效也由独立用例统一裁决。

Phase-13 在 Phase-12 上追加 11 个 Delivery 场景，覆盖 staged、continuous、revise、
final review、Standalone scope/cancel，以及 Moonlight defer、push-failed、finalize
和 repair；Phase-14 逐项继承全部 Phase-13 快照。差分 runner 会从 Standalone 状态
提取动态任务卡摘要用于归一化，产品输出和任务卡内容不为测试改写。

2026-07-30 在 Stage 3 最终实现上取得的新鲜验证结果：

- 完整 `unittest discover`：373 项通过；
- 完整 `scripts/selftest.py`：全部通过；
- Phase-14 differential runner：零差分，且 Phase-12 全部快照逐项保持；
- fault injection：3 项通过；
- State、Checkpoint 与全部 Delivery application 测试在
  `error::ResourceWarning` 下 75 项通过；
- Delivery 依赖、模块大小和函数复杂度门禁全部通过；新增恢复模块分别为
  498 行和 137 行，所有新业务模块均不超过 500 行、复杂度不超过 15；
- CLI 已删除已迁移的 checkpoint 恢复函数，架构门禁阻止这些状态机回流；
- `git diff --check` 通过。

独立审查最初指出 CLI 恢复裁决残留和 Phase-13 覆盖不足；两项均在本阶段内修复并
复审。Stage 3 不改变命令参数、状态 schema、用户停点、提交/push 安全顺序、
Standalone 不自动提交的边界或 Moonlight 的失败留痕语义。后续阶段继续以 Phase-14
为追加式行为基线。

## Stage 4：Quality Use Cases 完成证据

Stage 4 将 CodeCheck 解析、分批、执行、范围分类、用户范围裁决、人工诊断记录，
以及完整流程/独立任务的质量任务卡事实、正文和指纹迁入
`mae_flow_core.quality` 与 `mae_flow_core.application.quality`。应用层通过显式
ports 获取进程、日志、文件、Git 与时间事实；CLI 保留平台装配、历史 stdout/stderr
映射和状态持久化。完整流程与独立任务共享文件分组、最近模块执行根和冻结正文模型，
但继续保留独立任务禁止提交、UT 禁改被测源码等不同安全边界。

Phase-14 在 Phase-13 上追加 CodeCheck 空范围、缺失范围扫描、质量任务卡缺失和独立
任务完成令牌缺失场景；全部历史 Phase-13 快照保持不变。架构门禁止已迁移的解析、
分批、范围和任务卡渲染私有入口回流 CLI，并将 `scripts/mae-flow.py` 的防回增长上限
从 10408 行收紧到 8620 行。

2026-07-30 在 Stage 4 最终实现上取得的新鲜验证结果：

- 完整 `unittest discover`：404 项通过；
- 完整 `scripts/selftest.py`：全部通过；
- Phase-14 differential runner：零差分；
- fault injection：3 项通过；
- Quality、CodeCheck、任务卡、日志和真实任务范围测试在
  `error::ResourceWarning` 下 56 项通过；
- Quality 依赖、模块大小和函数复杂度门禁全部通过；五个主要新模块分别为
  387、358、483、287、347 行，全部不超过 500 行、复杂度不超过 15；
- `scripts/mae-flow.py` 已降至 8620 行，已迁移的 CLI 私有策略入口全部删除；
- 严格资源测试发现并修复 MF-RF-006（测试夹具未关闭 Flow 文件句柄）；
- 独立审查覆盖执行/超时/日志、JSON 回退、范围与缓存失效、两类任务卡、
  Windows 启动和依赖方向；85 项聚焦测试通过，无 Critical/Important 发现；
- `git diff --check` 通过。

Stage 4 不改变 CodeCheck 非零退出码语义、900 秒超时、报告/JSON 新鲜度回退、
事件顺序、范围候选用户停点、月光模式保守全纳入、人工诊断的 HEAD/文件/SHA256
绑定、任务卡正文或 Standalone 的禁止提交边界。Stage 5 将继续迁移
`hooks/dispatch.py` 的 Agent transcript 与最终报告验签。

## Stage 5：Hook Contracts 与协议入口完成证据

Stage 5 将 Hook 的运行模式路由、活跃事件策略、Agent transcript 解析、任务卡与源码
范围验签、质量收据、COMPILE/CODECHECK/UT/GRILL 最终报告契约和 SubagentStop 编排迁入
`mae_flow_core.application.hooks`。平台文件、Git、进程、状态和 Hook 响应映射集中在
`mae_flow_core.adapters`；`hooks/dispatch.py` 只保留字节协议解码、stdin 超时、看门狗、
项目根定位、运行时与端口装配以及顶层 fail-open。

Phase-15 在 Phase-14 上追加 Hook Agent 契约与 Stop 安全点场景；完整 oracle 比较
stdout、stderr、退出码、状态 sidecar、文件摘要和 Git 状态。架构门禁禁止已迁移的
事件处理器与契约函数回流入口，业务测试不能动态导入 Hook 私有策略；Hook application
函数复杂度不得超过 15，新模块不得超过 500 行。入口防回增长上限从 2860 行收紧到
326 行。

2026-07-30 在 Stage 5 最终实现上取得的新鲜验证结果：

- 完整严格 `unittest discover`：485 项通过，启用
  `-W error::ResourceWarning`；
- 完整 `scripts/selftest.py`：全部通过；
- Phase-15 differential runner：零差分；
- 严格 Hook 套件：74 项通过；
- refactor completion：8 项通过，fault injection 与架构门禁通过；
- `hooks/dispatch.py` 为 326 行；新增最大适配器
  `hook_active_events.py` 为 390 行，其余新 Hook 模块均不超过 500 行；
- Hook application 全函数复杂度不超过 15，入口已无活跃事件策略和 Agent 契约实现；
- 独立复审最初发现 1 项 Critical 与 3 项 Important；修复后复审 76 项聚焦测试及
  Phase-15 通过并给出 `APPROVED`；
- `git diff --check` 通过。

本阶段额外发现并修复 MF-RF-008 至 MF-RF-011：Standalone 应答路由遗漏、UT 非 PASS
收据顺序、测试夹具文件句柄和迁移后静态检查耦合。前两项均以独立 `fix:` 提交恢复
重构前语义。Stage 5 不改变 Hook 事件 matcher、fail-open、输出文案、任务卡与收据
schema、Agent 写入边界、Stop 三次无进展保护或 Direct/Terminal/Corrupt 优先级。

## Stage 6：CLI Commands 与公共入口完成证据

Stage 6 将历史 CLI 的运行态检查、生命周期、推进、规格、Checkpoint、Standalone、
Moonlight、Gate、Agent-task、CodeCheck 与 Lightcheck 命令按语义拆入
`mae_flow_core.cli_commands`。`scripts/mae-flow.py` 只导入公共 `main`；
`cli_runtime.py` 负责组装命令模块、证据注册表和兼容测试接口。跨模块调用通过单一的
后绑定注册表解析，避免命令模块之间形成循环导入；每个命令模块均不超过 500 行。

业务测试和 Gate 探针不再动态加载私有 CLI 文件，架构门会阻止这种耦合回流。自检的
静态发布规则读取公共运行时与全部命令模块，外部 OpenSpec/Comet 透传只允许存在于
明确命名的 capability handler。

2026-07-30 在 Stage 6 实现上取得的验证结果：

- 完整严格 `unittest discover`：486 项通过，启用
  `-W error::ResourceWarning`；
- Phase-15 differential runner：零差分；
- Gate 冒烟与证据全路径探针：43 项通过；
- refactor completion：8 项通过，架构门禁 34 项通过；
- `scripts/mae-flow.py` 为 9 行，`cli_runtime.py` 为 80 行；
- 24 个语义命令模块均不超过 500 行，最大模块低于 500 行；
- CLI 私有入口动态导入违规为零，`git diff --check` 通过。

本阶段发现并修复 MF-RF-013 至 MF-RF-015：拆分后路由命名空间错误、测试替身未传播
到命令模块，以及发布探针绑定旧文件位置。Phase-15 覆盖前两类真实调用路径，自检覆盖
发布安全网。本阶段不改变命令参数、stdout/stderr、退出码、状态 schema、文件与 Git
副作用或用户停点。

## Stage 7–8：显式依赖与遗留巨型模块清零

Stage 7 将全部 CLI 命令模块对平台装配层的通配导入改为精确依赖清单，并新增架构门
阻止通配依赖回流。跨命令调用仍由组合根注册，历史测试替身兼容集中在同一处；Gate 与
Moonlight 等适配器的复杂度防回增长基线收紧到当前实际值。

Stage 8 将最后三个遗留巨型模块拆分为稳定门面与内聚实现模块：

- Capabilities：能力包渲染、宿主运行时、CodeCheck 生命周期；
- Lightcheck：源码扫描、函数匹配、变更分析、进程隔离与报告；
- SpecEngine：基础/YAML、配置、Markdown、v5 布局、校验、生命周期、合并渲染与
  原子归档。

三个原模块名继续导出拆分前的完整符号集合，并保留 `_git`、CodeCheck discovery 与
`_move_directory` 故障注入缝。逐项 API 对比确认 Capabilities 32 个、Lightcheck
70 个、SpecEngine 120 个顶层符号均无缺失。

2026-07-30 在 Stage 7–8 实现上取得的新鲜验证结果：

- 完整严格 `unittest discover`：491 项通过，启用
  `-W error::ResourceWarning`；
- 完整 `scripts/selftest.py`：全部通过；
- Phase-15 differential runner：零差分；
- Capabilities、Lightcheck、SpecEngine 聚焦测试分别为 13、19、66 项通过；
- fault injection：3 项通过，refactor completion：8 项通过；
- 架构门禁：36 项通过，超大模块豁免表为空；
- 所有生产模块均不超过 500 行，最大模块
  `specengine_lifecycle.py` 为 490 行；
- `scripts/mae-flow.py` 为 9 行，`hooks/dispatch.py` 为 326 行；
- `git diff --check` 通过。

Stage 7–8 不改变公共导入路径、命令行为、Lightcheck 结果 schema、SpecEngine 文本与
归档字节、Capabilities 宿主探测顺序，或失败时的回滚/降级语义。

## Stage 9：最终证明与独立审查

最终审查覆盖 Stage 6–8 的 CLI 组合注册、稳定门面、跨平台路径/进程、循环依赖、
资源生命周期、异常与回滚语义。审查最初复现三个进程内门面兼容回归：四个历史
Evidence 对象未导出、`FLOW` 读取停在导入快照、Evidence override 未传播到注册模块。
三项均由 MF-RF-016 的 RED/GREEN 测试修复。

修复后的独立复审结论为 `APPROVED`，无残留 Critical、Important 或 Minor 发现；复审
确认 491 项严格全量测试通过、CLI facade + architecture 39 项通过、Phase-15 零差分、
全提交范围 `git diff --check` 干净，且三个稳定门面相对拆分前无顶层绑定名或函数签名
缺失。

最终架构目标全部达到：

- CLI/Hook 入口分别为 9/326 行，低于 1500/800；
- 所有生产业务模块不超过 500 行，超大模块豁免表为空；
- Workflow、Guard、Quality、Delivery 与 Hook application 的策略复杂度均不超过 15；
- 业务测试动态导入私有单体入口为零；
- 自检、Phase-15、故障注入、完成合同、语法与两组端到端探针全部通过。
