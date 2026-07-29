# Mae-Flow 彻底重构完成路线设计

## 背景

Phase 1–8 已把 Workflow 定义、推进与完成裁决，Gate 请求解析，质量任务卡，
Checkpoint/Moonlight 子状态和 CLI 分发的一部分规则抽入
`mae_flow_core`。这一轮显著增加了行为差分、架构门禁和纯规则测试，但还不能称为
“彻底重构完成”：

- `scripts/mae-flow.py` 仍有 10,408 行和 443 个函数，继续承载大量业务裁决；
- `hooks/dispatch.py` 仍有 2,812 行和 125 个函数，Agent 契约与 Hook 适配混杂；
- `specengine.py`、`lightcheck.py`、`capabilities.py` 仍是多职责大模块；
- 测试大量直接调用 `mae-flow.py` 私有函数，模块边界尚不能独立演进；
- Phase-9 黑盒差分只有 12 个场景，尚未覆盖完整模式、交付路径、并发与故障恢复矩阵；
- 当前架构基线仍允许单体文件和高复杂度函数保持原状。

因此，后续目标不是继续机械拆文件，而是在冻结行为的前提下完成职责、依赖和测试
边界的迁移，并用可执行门禁证明旧单体不能重新长回来。

## 不可变原则

1. **功能不受影响。** Phase-9 的 stdout、stderr、退出码、状态、sidecar、产物文件、
   Git 状态和关键操作顺序是不可变基线。
2. **缺陷修复与重构分离。** 重构提交不得改变 Phase-9 既有场景；发现缺陷先记录根因，
   再用独立失败测试和 `fix:` 提交处理。
3. **先 Oracle，后迁移。** 每迁移一个职责，必须先补足能观察该职责的单元、契约或
   黑盒差分场景。
4. **小步可回滚。** 一次提交只迁移一个可命名职责；出现未解释差分立即停止，不用
   更新 golden 掩盖变化。
5. **入口只做适配。** CLI 与 Hook 最终只负责解析输入、调用 use case、执行明确的
   I/O 端口和映射输出/退出码。
6. **不以行数冒充架构。** 行数是防回退指标，不是完成依据；职责内聚、依赖方向、
   独立测试和行为证据必须同时满足。
7. **只本地集成。** 各阶段在隔离分支或工作树完成；未经明确授权不推远端。

## 方案比较

### 方案 A：纵向职责绞杀（采用）

每次选取一条完整业务链，例如 Evidence、Gate、Checkpoint、CodeCheck 或 Agent
契约：先建立输入/输出 Oracle，再把纯规则、用例编排和外部适配依次迁走，最后删除
对应兼容桥。

优点：

- 每一阶段的行为面有限，差分容易定位；
- 新旧实现可以短期并存，便于小步回滚；
- 每个阶段都能真实降低入口复杂度和测试耦合；
- 适合在现有稳定功能上持续交付。

代价是阶段数较多，短期会保留少量有明确删除条件的兼容桥。

### 方案 B：先横向铺满架构层

先统一建立 models、repositories、ports、adapters，再一次性迁移所有调用者。

优点是最终形态整齐；缺点是一个接口会同时影响多个流程，差分范围巨大，旧状态兼容、
Git 副作用顺序和 Hook 退出语义更难逐项证明。对本项目的“零功能影响”约束风险过高，
不采用。

### 方案 C：按文件机械拆分

按函数分组把大文件拆成若干模块，继续共享全局状态和私有函数。

它能快速降低单文件行数，但不会改善依赖、可测试性或扩展成本，还可能把单体变成
“分布式单体”。该方案不满足目标，不采用。

## 目标架构

依赖方向固定为：

```text
CLI / Hooks
    ↓
Application Use Cases
    ↓
Domain Policies
    ↓
Foundation Ports + Immutable Values
    ↓
External Adapters
```

### Entry Adapters

- `scripts/mae-flow.py`
- `hooks/dispatch.py`
- `scripts/statusline.py`
- `scripts/comet_compat.py`

只允许：

- 参数和宿主事件解析；
- Runtime/State 上下文装配；
- 调用一个命名 use case；
- 将结果映射为输出、退出码或 Hook 响应。

禁止新增业务分支、流程边、证据裁决、Agent 报告解析或 Git 命令语义。

### Application

新增 `mae_flow_core/application/`，按业务用例分组：

- `workflow_commands/`：init/current/status/spec/action/advance/done/exit/doctor；
- `delivery/`：Checkpoint、Standalone、Moonlight 的用例编排；
- `quality/`：CodeCheck、UT、编译、任务卡和复验编排；
- `hooks/`：PreToolUse、PostToolUse、Stop、SubagentStop 用例。

Application 层可以定义副作用顺序，但只通过显式端口请求 I/O，不直接
`open`、`subprocess`、`chdir` 或访问全局变量。

### Domain Policies

- `workflow/evidence.py`：证据注册、证据结果和值对象；
- `guard/gate.py`：工具请求到放行/拒绝决策；
- `guard/permits.py`：一次性许可与绑定条件；
- `guard/ownership.py`：提交归属、源码范围和跨单边界；
- `delivery/checkpoints.py`、`delivery/moonlight.py`：只保留状态转换规则；
- `quality/agent_contracts.py`：Agent 返回、工具 transcript 与任务卡契约；
- `quality/codecheck.py`：告警解析、范围与缓存有效性规则；
- `quality/unit_tests.py`：测试范围、结果汇总和 PASS/FAIL 裁决。

纯策略输入输出使用不可变值对象，不读取磁盘、不执行 Git、不打印。

### Foundation

- `foundation/models.py`：Runtime、State、CommandResult、Decision、EvidenceResult；
- `foundation/repositories.py`：State、Flow、Artifact、TaskCard 的端口协议；
- 现有 `source_paths.py`、`fingerprints.py`、`git_intent.py` 保持纯函数边界。

Foundation 不导入 application、workflow、guard、delivery 或 quality。

### External Adapters

新增 `mae_flow_core/adapters/`：

- `git.py`：只执行已决定的 Git 操作并返回结构化结果；
- `state.py`：封装 `StateStore` 与历史状态迁移；
- `filesystem.py`：文件、目录、原子替换与编码边界；
- `processes.py`：子进程、shell、超时和平台差异。

适配器不决定“是否允许”或“下一步是什么”；它们只执行 use case 已作出的请求。

## 运行数据流

典型 CLI 请求：

1. Entry Adapter 解析参数并构造 `CommandContext`；
2. Command Router 选择一个 Application Use Case；
3. Use Case 通过 repository/adapter 读取快照；
4. Domain Policy 产生不可变 `Decision` 和有序 `EffectRequest`；
5. Use Case 依序执行 effect，并在需要时使用 StateStore CAS 保存；
6. Entry Adapter 将 `CommandResult` 原样映射为现有输出和退出码。

典型 Hook 请求使用同一数据流，只在最后映射为 Hook JSON。CLI 与 Hook 不各自复制
Gate、Ownership 或 Agent Contract 规则。

## 错误与兼容策略

- 历史状态迁移仍由 `StateStore` 负责，未知字段必须保留；
- 损坏状态下 `exit` / `doctor` 的逃生顺序保持不变；
- CAS、锁、原子替换和临时文件清理必须通过 fault-injection 测试；
- Git、文件和子进程错误不在 adapter 中吞掉，由 use case 按现有文案和退出码映射；
- Windows 的 BOM、控制台编码、PATHEXT、Git Bash 路径和大小写路径单独覆盖；
- 兼容桥只有在 AST/字符串路由无调用、固定基线差分通过、历史迁移用例通过后删除。

## 分阶段实施

### Stage 0：完成契约与行为 Oracle 扩充

- 将本文完成标准编码进架构门禁；
- 扩充差分场景清单和故障注入工具，但不改产品代码；
- 固定 Phase-9 所有旧场景值，新的 characterization 只能增加场景；
- 为后续每个领域建立迁移前覆盖清单。

### Stage 1：Evidence

- 提取证据注册、执行结果和值语义；
- 移除 CLI 中的证据业务判断；
- 保持全部证据名称、失败文案和 done 顺序。

### Stage 2：Gate、Permit 与 Ownership

- 合并 CLI/Hook 重复的 Gate 和提交归属判断；
- 提取一次性许可、路径范围和 Git 操作意图；
- 覆盖 dirty/staged/ignored/special path 和跨单状态。

### Stage 3：Delivery Use Cases

- 提取 Checkpoint、Standalone、Moonlight 编排；
- 覆盖 staged/continuous/revise、晨间 finalize/repair、push-failed 恢复。

### Stage 4：Quality Use Cases

- 提取 CodeCheck、UT、编译、Grill、任务卡和缓存复用；
- 完整覆盖分批结果、失败退出、范围缩小、源码变化、旧凭证与报告重答。

### Stage 5：Hook Agent Contracts

- 把 `dispatch.py` 的 Agent 返回契约、transcript 证据与 Hook 事件编排迁入内核；
- Hook 入口只保留协议解码和响应映射。

### Stage 6：CLI Commands

- 迁移 init/current/status/spec/action/exit/doctor/report 等剩余命令；
- 删除 tests 对 `mae-flow.py` 私有函数的直接依赖；
- CLI 只保留兼容公开入口与参数适配。

### Stage 7：Adapters 与旧桥清理

- 统一 Git、State、Filesystem、Process 适配器；
- 删除已无调用的全局变量、重复 helper 和兼容桥；
- 降低架构基线，不允许入口单体回长。

### Stage 8：大内核拆分

- 在调用者已隔离后拆分 `specengine.py`、`lightcheck.py`、`capabilities.py`；
- 以稳定公开接口保持生命周期、诊断和轻量预检行为；
- 不为追求平均文件大小引入无语义的转发层。

### Stage 9：最终证明

- 补齐全行为矩阵、故障注入、并发与平台证据；
- 删除临时迁移兼容层和废弃 golden；
- 更新维护者文档、模块地图和扩展示例；
- 完整自测、差分和架构门禁必须在干净工作区重复通过。

每个 Stage 都单独执行 spec → plan → TDD implementation → review → verification，
不得把全部 Stage 合成一次大提交。

## 测试与差分矩阵

最终矩阵至少覆盖：

- Runtime：inactive、active、direct、standalone、corrupt、terminal；
- Workflow：full、hotfix、tweak、review；
- Transition：normal、choice、return、goto、skip、risk、exit；
- Delivery：checkpoint staged/continuous/revise，完整 Moonlight on/continue/
  defer/push-failed/repair/finalize；
- Quality：compile、CodeCheck、UT、Grill、task card、缓存复用和失效；
- Git：clean、dirty、staged、ignored、combined flags、特殊字符与空格路径；
- State：旧 schema、未知字段、损坏 JSON、CAS 冲突、并发锁、原子写失败；
- Hook：所有事件、Agent 类型、合法与伪造 transcript、编码与宿主缺字段；
- Platform：Windows 路径/编码/PATHEXT/Git Bash，POSIX executable bit；
- Fault injection：文件打开/替换失败、Git 非零退出、子进程超时、半写入与清理失败。

黑盒差分必须比较 stdout、stderr、退出码、状态 JSON、sidecar、产物文件哈希和 Git
状态。时间、临时路径和随机摘要只能在归一化层做最小替换。

## 完成标准

所有条件同时满足才可宣称“彻底重构完成”：

1. `scripts/mae-flow.py` 不超过 1,500 行，`hooks/dispatch.py` 不超过 800 行；
2. 新业务模块原则上不超过 500 行，复杂度不超过 15；例外必须在架构基线中写明职责
   理由和删除条件；
3. Entry Adapter 中没有 Domain Policy，架构测试能自动阻止反向依赖和直接副作用；
4. 业务测试不再通过动态 import 直接依赖单体私有函数；仅保留少量公开兼容冒烟；
5. 本文测试矩阵有可执行覆盖清单，不以“selftest 通过”代替缺失场景；
6. Phase-9 的所有既有场景在最终实现中完全一致；每个缺陷差异都有独立问题记录和测试；
7. 完整 unittest、selftest、黑盒差分、fault-injection、架构门禁与可获得的平台检查通过；
8. `git diff --check` 通过、工作区干净、无 ResourceWarning、无未解释 skip/xfail；
9. 所有重构中发现的可复现问题已修复，或因缺少真实外部平台而明确列为未满足的发布
   条件；未满足条件存在时不得宣称全部完成；
10. 维护者可以只读模块接口和架构文档完成新增命令、证据或 Hook 规则，不必理解两个
    旧单体的内部实现。

## Stage 0 的交付边界

第一份实现计划只覆盖 Stage 0：

- completion charter 的机器可读门禁；
- 差分场景清单与 coverage manifest；
- fault-injection harness 的最小公共能力；
- Evidence、Gate、Delivery、Quality、Hook、CLI 各领域的迁移前 Oracle。

Stage 0 不迁移生产职责、不修改用户可观察行为，也不降低既有安全检查。它完成后再为
Stage 1 编写独立设计与计划，按上述顺序连续推进到 Stage 9。
