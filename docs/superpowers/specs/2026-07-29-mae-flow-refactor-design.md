# Mae-Flow 行为保持型重构设计

**状态：** 已批准
**基线提交：** `d5e7d7b2cb5d3def06d21df79fb3069efea94f16`
**日期：** 2026-07-29

## 1. 决策摘要

Mae-Flow 当前功能稳定，但核心驱动器、Hook、状态访问和测试入口高度耦合，已经无法安全、经济地持续扩展。
本次采用绞杀式重构：先把当前实现固化为行为 Oracle，再抽取共享底座，之后按完整命令和子状态机逐步迁移。

重构默认不改变任何外部行为。发现的疑似 Bug 先记录和复现，经过单独裁决后用独立测试、独立提交修复，
不得混入结构迁移。

## 2. 目标

1. 保持 CLI、Hook、状态文件、sidecar、Git 副作用、恢复语义和用户可见输出兼容。
2. 让流程、证据、Gate、质量契约和运行时适配拥有明确、单向的依赖边界。
3. 让每个模块能独立理解、独立测试、独立替换。
4. 让新增步骤、证据或命令不再要求同时修改 CLI、Hook 和多个状态分支。
5. 通过差分测试、状态机遍历和故障注入系统性发现隐藏问题。
6. 保持 Python 3.8+、Windows/Git Bash 和生产零新增依赖。

## 3. 非目标

1. 不重新设计现有交付流程、确认点、文案或用户体验。
2. 不在重构提交中修复现有行为 Bug。
3. 不更换 `flow/flow.json`、步骤 Markdown、状态 JSON 或 sidecar 的外部格式。
4. 不引入 Pydantic、Click、Hypothesis、pytest 或其他生产/测试第三方依赖。
5. 第一实施期不拆分 `specengine.py`、`lightcheck.py` 或 vendored 能力。
6. 不承诺兼容以下划线开头的 Python 私有函数和当前单体内部组织。

## 4. 兼容契约

### 4.1 必须保持兼容

| 表面 | 兼容要求 |
|---|---|
| CLI | 命令、参数、stdout、stderr、退出码和执行顺序不变 |
| Hook | 输入 JSON、输出、阻断/放行、fail-open 和超时语义不变 |
| 入口 | `scripts/mae-flow.py`、`hooks/dispatch.py`、`scripts/statusline.py` 路径不变 |
| 主状态 | `.mae-flow.json` 字段、未知字段保留、schema/revision 和迁移语义不变 |
| 辅助状态 | `.tokens`、`.usermsg`、`.agent-*`、`.gate-*`、intent、exit、last 等路径和格式不变 |
| 文件副作用 | 生成、移动、删除、归档、gitignore 和诊断文件位置不变 |
| Git | 分支、index、commit、push、工作区检查和危险命令门禁语义不变 |
| 恢复 | 旧版在途状态、Direct、Standalone、Moonlight、终态和损坏态恢复不变 |
| 平台 | Python 3.8+；Windows/Git Bash 为一等环境；编码与路径语义不变 |
| 部署 | 安装方式、插件布局、vendored 组件和生产依赖不变 |

对确定性输出执行逐字节比较。时间戳、PID、临时目录、绝对安装目录和随机收据等动态值只在测试比较器中
按明确字段归一化；生产输出本身不改变。

### 4.2 可以改变

1. 私有函数名、私有模块路径和单体内部调用关系。
2. 测试对私有函数的直接导入方式。
3. 内部类型表示，但序列化后的外部状态必须兼容。
4. 内部错误类型，但最终用户文案、退出码和 Hook 行为必须兼容。

迁移期间可以保留私有薄包装。包装只能委托新实现，不得继续承载规则；调用方迁移完成后删除。

## 5. 目标架构

稳定入口保留为适配器：

```text
scripts/mae-flow.py   -> CLI 参数、输出和退出码适配
hooks/dispatch.py     -> 宿主事件、Hook 协议和 fail-open 适配
```

核心代码按业务能力组织：

```text
scripts/mae_flow_core/
  foundation/
    models.py          # 类型化状态视图、事件、结果和效果
    paths.py           # 路径归一化、源码/测试/构建文件分类
    git_intent.py      # Git/Bash 命令意图解析
    fingerprints.py    # 内容、工作区和检视指纹
    repositories.py    # Git、状态、文件系统和时钟接口

  workflow/
    definition.py      # flow.json 加载、校验和完整流程图
    transitions.py     # 纯状态转移计划
    evidence.py        # Evidence 注册与求值
    commands/          # current、done、goto、status 等用例

  delivery/
    checkpoints.py
    moonlight.py
    standalone.py

  quality/
    task_cards.py
    agent_contracts.py
    codecheck.py
    unit_tests.py

  guard/
    gate.py
    permits.py
    ownership.py

  adapters/
    git.py             # Git 查询和受控命令执行
    state.py           # 复用 state_store 的主状态/sidecar 适配
    filesystem.py      # 文件读取、写入、移动和删除
    processes.py       # 带既有编码、超时和退出码语义的子进程适配
```

物理拆分以“哪些代码因同一业务原因一起变化”为准。上图是责任边界，不要求第一期一次创建全部文件。

依赖方向必须保持：

```text
CLI / Hook adapters
        |
        v
Application use cases
        |
        v
Workflow / Delivery / Quality / Guard policies
        |
        v
Foundation interfaces and immutable values
        ^
        |
Git / JSON / filesystem / subprocess adapters
```

禁止的反向依赖：

1. 策略层不得导入 CLI 或 Hook。
2. 策略层不得直接 `print`、`sys.exit`、`subprocess.run` 或修改当前目录。
3. Foundation 不得引用具体步骤 ID 或 Mae-Flow 业务文案。
4. CLI、Hook 不得新增流程步骤、证据和 Gate 业务规则。

## 6. 核心数据流

每次 CLI 或 Hook 调用遵循同一条管线：

```text
原始输入
  -> adapter 解析 CommandRequest / HostEvent
  -> repository 读取状态与外部事实
  -> use case 调用纯策略
  -> policy 返回 Decision
  -> application 将 Decision 转成 Effects
  -> repository 按既有顺序提交 Effects
  -> adapter 渲染 stdout/stderr/exit code
```

核心值对象使用 Python 3.8 标准库 `dataclasses` 和 `typing` 表达：

- `CommandRequest`：已解析的命令意图，不包含 argparse 对象。
- `HostEvent`：标准化后的 Hook 事件。
- `Observation`：Git、文件、时间、令牌和任务卡等已观测事实。
- `Decision`：允许、拒绝、推进、回流或旁路，以及结构化原因。
- `Effect`：保存状态、更新 sidecar、写报告或执行 Git 等明确副作用。
- `CommandResult`：输出段、退出码和待提交效果。

第一期只为新抽取的底座引入这些类型，不把全部旧状态一次转换为类层级。

## 7. 状态与事务

### 7.1 兼容视图

主状态继续以字典和原 JSON 结构持久化。类型化模型是覆盖现有字典的兼容视图：

1. 已知字段提供明确访问器和校验。
2. 未知字段原样保留。
3. 未经当前用例修改的字段不得重排、删除或重新解释。
4. 第一实施期不提升 `schema_version`。

### 7.2 Sidecar

Sidecar 的拆分具有并发和故障隔离价值，不为了“状态统一”盲目合并。每类 sidecar 通过专用 repository
访问，但继续使用原路径、原格式、原锁和原损坏隔离策略。

### 7.3 事务边界

用例先完成全部读取和纯校验，再生成效果。效果执行保持旧实现的先后顺序。任何失败路径必须与基线一致：

- 基线不写状态时，新实现也不得留下部分状态。
- 基线会先留痕再拒绝时，新实现必须保留同样留痕。
- revision/CAS、项目锁、原子替换和 Windows 重试继续由 `state_store.py` 负责。
- Hook 并发更新不得退化成完整快照覆盖。

## 8. 流程定义与转移

`flow/flow.json` 应逐步成为可验证的完整静态定义，但 JSON 不承载复杂业务代码。

1. 普通 `next`、choice、next-by 和步骤权限继续由 JSON 声明。
2. 动态回流、Moonlight 旁路和兼容迁移通过显式 policy 名称注册。
3. `definition.py` 加载时校验所有普通边、动态 policy、Evidence 类型和步骤文档。
4. `transitions.py` 输入当前状态、步骤定义和观测事实，返回转移计划，不直接保存。
5. 历史兼容桥保留独立名称、测试和删除条件，不能混入正常主路径。

最终要求：任何合法的步骤进入路径都能从流程定义和已注册 policy 中枚举出来。

## 9. 错误处理

内部使用结构化错误区分：

- 用户输入/参数错误；
- 证据不足；
- Gate 拒绝；
- 状态冲突或损坏；
- 能力缺失；
- 内部异常。

结构化错误只改善内部控制流。适配器必须把它们映射回基线的中文文案、stderr/stdout 位置和退出码。

Hook 保持现有安全原则：

1. 确定的业务拒绝返回协议退出码 2。
2. Hook 自身异常、缺失脚本、超时或非协议退出码继续 fail-open。
3. fail-open 必须保留现有日志和可观测提示。
4. exit、损坏态逃生和终态旁路属于最高优先级兼容场景。

## 10. 测试策略

### 10.1 三层安全网

**第一层：现有回归**

- 现有 162 个 `unittest` 用例继续通过。
- `scripts/selftest.py` 完整通过。
- 两个黑盒 probe 继续由 selftest 执行。

**第二层：行为特征测试**

为当前未覆盖的公开行为补测试，重点覆盖输出、退出码、状态写入和失败副作用。特征测试记录基线实际行为，
不擅自改写为维护者认为“更合理”的行为。

**第三层：新旧差分**

建立 `scripts/tests/differential/`：

```text
scenarios.py      # 场景与事件序列
runner.py         # 在隔离临时仓运行指定实现
normalize.py      # 仅归一化明确的动态字段
compare.py        # 输出、状态、文件和 Git 差异
goldens/          # 由基线提交生成并审阅的稳定结果
```

开发期 runner 可以同时接受基线 checkout 和候选 checkout，执行实时 A/B 对比。CI 不依赖 Git 历史，
使用从固定基线提交生成并入库的 golden 结果。golden 更新必须是显式维护动作，重构提交不得自动重写。

### 10.2 差分维度

每个场景比较：

1. stdout、stderr、退出码；
2. 主状态和所有 sidecar 的规范化 JSON；
3. 文件新增、修改、删除、移动和内容摘要；
4. Git HEAD、分支、index、工作区和上游关系；
5. Hook 放行、阻断和日志；
6. 重复执行后的幂等结果。

### 10.3 场景矩阵

至少覆盖：

- Inactive、Flow、Standalone、Direct、Corrupt、Terminal；
- full、hotfix、tweak、review；
- 正常推进、选择、回流、goto、skip、risk、exit；
- Checkpoint staged/continuous/revise；
- Moonlight on/defer/blocked/repair/finalize/push-failed；
- CodeCheck、UT、Compile 和 Grill 契约；
- 初始脏文件、部分暂存、特殊文件名和跨仓路径；
- 旧状态迁移、损坏 sidecar、CAS 冲突和并发 Hook；
- Windows 编码、大小写、路径分隔符和命令行形式。

### 10.4 故障注入

使用标准库测试替身模拟：

- `os.replace`、删除和锁的短暂失败；
- 子进程超时、缺失和异常退出码；
- 状态在读取后被并发更新；
- Hook stdin 不关闭、编码错误和不完整 tool transcript；
- Git 命令返回空值、未知格式或部分结果。

故障注入同时验证“不变量”和与基线的行为差分。

## 11. 架构质量门禁

使用标准库 AST 检查，不引入新依赖：

1. CLI/Hook 不得新增 Evidence、步骤转移和业务 Gate 分支。
2. 纯策略模块不得调用 `print`、`sys.exit`、`subprocess` 或 `os.chdir`。
3. Foundation 不得导入 workflow、delivery、quality、guard 或 adapters。
4. 新生产模块软上限 500 行；超过时必须在代码中说明边界理由。
5. 新普通函数圈复杂度软上限 15；解析器例外必须有集中测试。
6. 同一共享函数不得在 CLI 和 Hook 各保留一份实现。

现有大文件采用“禁止净增长、逐步下降”，不要求第一提交机械拆到阈值。

## 12. Bug 发现与处理纪律

建立 `docs/superpowers/mae-flow-refactor-findings.md`，每条记录：

- 唯一编号；
- 触发场景；
- 基线行为；
- 文档/设计期望；
- 可复现证据；
- 分类和处置状态。

分类只有：

1. 确认 Bug；
2. 有意兼容行为；
3. 死代码或不可达路径；
4. 文档与实现不一致；
5. 证据不足。

疑似 Bug 不在重构提交中修复。确认后遵循：

1. 在基线实现上写出可失败或可明确展示错误行为的测试；
2. 单独批准期望行为；
3. 使用独立 bugfix 提交修复；
4. 同时更新 golden 和兼容契约；
5. 再继续结构迁移。

当前已知候选包括未关闭文件产生的 `ResourceWarning`，以及流程图无法独立枚举全部动态进入路径。
它们在完成复现和分类前都不作为第一期修复内容。

## 13. 分期路线

### 第一期：行为 Oracle 与共享底座

1. 建立差分 runner、normalizer、golden 和代表性场景。
2. 建立兼容矩阵、状态不变量和架构 AST 门禁。
3. 抽取 CLI/Hook 重复的路径、源码分类和指纹纯函数。
4. 抽取 Git/Bash 命令意图解析，不改变 Gate 决策。
5. 旧函数变成薄包装，现有调用继续工作。

第一期不迁移步骤转移、Evidence、Checkpoint、Moonlight 或 Agent Contract。

### 第二期：类型化状态与流程定义

1. 为主状态和 sidecar 建立兼容视图及 repository。
2. 集中流程定义校验和动态 policy 注册。
3. 迁移 `current/status/steps/report` 等读取型用例。

### 第三期：转移与 Evidence

1. 将 `done/advance/goto/skip` 转成纯转移计划和效果提交。
2. 迁移 Evidence evaluator。
3. 保留并隔离旧状态兼容桥。

### 第四期：Gate

1. 分离命令解析、事实观测、策略决策和拒绝渲染。
2. CLI gate 与 Hook PreToolUse 调用同一策略。
3. 迁移 permit、strike、ownership 和危险操作出口。

### 第五期：质量契约

迁移任务卡、Compile、CodeCheck、UT、Grill、Agent token、rejection 和 transcript 契约。

### 第六期：Checkpoint、Standalone 与 Moonlight

将三个子状态机分别迁移到独立模型和用例，保留原流程状态和恢复语义。

### 第七期：收口

1. 删除已无调用的旧包装和私有测试入口。
2. 将 selftest 缩回发布组合检查。
3. 更新维护者架构文档。
4. 运行完整差分、回归和 Windows CI 后再结束迁移。

## 14. 第一期验收标准

1. 当前全部单元测试、selftest 和 probe 通过。
2. 差分场景对固定基线为零未解释差异。
3. 生产依赖和入口路径没有变化。
4. 主状态、sidecar、输出、退出码和 Git 副作用没有变化。
5. CLI/Hook 的重复路径、指纹和 Git 意图逻辑由共享模块提供。
6. 新模块满足依赖方向和复杂度门禁。
7. 发现的问题全部进入 findings ledger，没有混入行为修复。
8. 每个迁移提交可独立测试、回滚和二分定位。

## 15. 提交纪律

1. 先测试后生产代码；每个抽取点先用特征/差分测试证明基线。
2. 一个提交只包含一个可独立审阅的迁移单元。
3. 重构提交使用 `refactor:` 或 `test:`，行为修复使用独立 `fix:`。
4. 不在同一提交中修改规则、文案、状态格式和结构。
5. 每次提交前运行目标测试；每期结束运行完整 unittest 和 selftest。
6. 任何未解释差分都阻断该迁移单元。

## 16. 主要风险与控制

| 风险 | 控制 |
|---|---|
| 测试把偶然动态值当差异 | normalizer 只处理列入白名单的字段，并测试 normalizer 自身 |
| golden 掩盖回归 | golden 不自动更新；变更需要独立审阅和兼容说明 |
| 新旧规则双写后漂移 | 旧函数只能薄委托；架构测试禁止两处新增规则 |
| 类型化模型丢未知字段 | 兼容视图 round-trip 测试和旧状态 fixture |
| Hook 重构破坏 fail-open | 协议级差分、故障注入和真实子进程测试 |
| 大范围迁移难以定位 | 分期、小提交、目标测试、每步可回滚 |
| 顺手修 Bug 改变 Oracle | findings ledger 和独立 bugfix 门禁 |
