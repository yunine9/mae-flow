# Mae-Flow 维护者手册

高效率、高质量；在需要人介入时聪明地让人介入。

本手册描述当前唯一生产模型。公共路径只有 Full 和 Focused，公共阶段只有 Intake → Spec → Design → Construction → Quality → Delivery。任何兼容代码都不得重新暴露额外模式、阶段或操作仪式。

## 不变量

1. **语义决定路径。** Full 与 Focused 的选择和升级只看接口、兼容性、数据、安全、共享状态、并发等语义风险，不看文件数、改动行数或目录数量。
2. **只在高价值点找人。** Full 停在 Intake、Spec、Design、每个 CP、Delivery；Focused 停在 Intake、Delivery。真实歧义、设计偏差、用户级 Reviewer 取舍、昂贵能力再次调用、不可逆动作和 manifest 变化可以增加条件停点。
3. **能力按语义 slot 一次调用。** Build、UT、CodeCheck、Grill、Story、Reviewer 是 opaque capabilities。每个 CP 使用启动时确认的 Build 路由同步编译一次；同一 slot 不后台等待、不自动重试，新 CP 的首次计划调用无需重复授权。
4. **状态是最小恢复游标。** 只保留已确认启动配置、当前路径/阶段/CP、产物路径、相关业务领域、CP 自然语言事实、风险、能力尝试、Delivery 文件和初始脏文件；不把过程报告扩成第二套工作流。
5. **写入边界单一。** 工作流命令是 capability 事实的唯一写者；Hooks 只写用户事件和 Git 副作用观察。所有读改写走项目锁和原子替换，专业 Skill/Agent 与文档渲染器不直接写活动状态。
6. **Git 精确授权。** 每次提交只使用用户审阅的逐文件 manifest，并匹配已确认的工作分支；提交总体格式是 `[ticket][feat|fix]description`，本轮 type 必须与 Intake 确认值完全一致；最终只推送一次。
7. **条件文档默认本地。** Spec、Story、决策、链路、走读、CodeCheck 和 Delivery 笔记默认保留在本地，用户明确选择后才能加入精确 manifest。
8. **安装不是授权。** 没有活动状态时 Hooks fail-open；明确退出在任何阶段生效，保留现场并释放控制。

## 领域模型

| 公共概念 | 恢复值 | 说明 |
|---|---|---|
| Full | `full` | 显式 Spec、Design 与每 CP 检视 |
| Focused | `focused` | 已定位工作；语义风险出现时升级 Full |
| Intake | `startup` | 启动选择与初始工作区归属 |
| Spec | `spec` | WHAT |
| Design | `story` | 独立的软件详细设计、测试交接、可测性与 CP |
| Construction | `construction` | 按 CP 实现 |
| Quality | `quality` | 单次 opaque capability 事实 |
| Delivery | `delivery` | 精确 manifest 与副作用授权 |

`startup`/`story` 是稳定的持久化兼容值，不是额外公共阶段。生产代码不得基于旧名称生成新的用户路径。

## 模块边界

```text
scripts/mae_flow_core/orchestration/   纯状态、转换、能力、文档和 Delivery 策略
scripts/mae_flow_core/guard/           无副作用的路径、manifest 与危险动作裁决
scripts/mae_flow_core/application/     Hook 用例与不透明返回观察
scripts/mae_flow_core/adapters/        文件、Git、Host payload 和状态存储装配
hooks/dispatch.py                      有界 stdin/stdout 生产边界
flow/phases/                           六阶段恢复说明
scripts/tests/                         发布场景、平台边界与回归套件
```

依赖方向从 adapter/application 指向纯 orchestration/guard。业务策略不得导入 CLI 或 Hook 平台实现。`hooks/dispatch.py` 只负责有界输入、装配、输出和 fail-open，不承载路径选择或阶段逻辑。

## 路径与停点

Intake 从仓库预设和用户修改中一次确认工号、单号类型、需求来源、路径、提交节奏、基线/工作分支、精确 Build 路由、UT 生成、UT 运行入口和质量组合。C++ 可选配置的 `build-fix` Skill，Java/Maven 用确认的 Maven 命令，其他语言用仓库准确 Skill/命令。确认后立即创建或切换工作分支。恢复上下文始终显示这份已确认配置；后续阶段不重新猜测。领域选择按业务能力语义完成，不按目录、类、文件数或行数划分。

Full 的常规推进：

```text
Intake 确认
  → Spec + Grill 单次返回 + 用户确认
  → Design（Story + Reviewer 单次返回）+ 用户确认
  → Construction（每个 CP 用户确认）
  → Quality
  → Delivery 用户确认
```

Focused 的常规推进：

```text
Intake 确认
  → Construction
  → Quality
  → Delivery 用户确认
```

Focused 中的普通走读修复不创建新模式，也不预声明 Spec、Story 或 UT handoff 产物。若工作仍是已定位的局部修改就继续；若发现真实语义风险，记录自然语言依据后升级到 Full/Spec，并在升级时补入 Full 产物路径。

## Capability 合同

`AttemptContext` 由 kind、相关源码 revision、环境 revision 和一次用户授权组成。支持的结果只有：

- `returned`
- `failed-to-start`
- `timed-out`
- `not-observed`

同一语义 slot 首次调用后，再次调用需要当前用户决定；新的阶段或 CP 是新的计划 slot，其首次调用正常执行。决定绑定 kind、语义 phase/CP slot 和 environment；旧 slot 的决定不能被新 slot 消费。不要从 summary 中寻找 `PASS`、`CLEAN`、数字、测试框架字段或未来工具格式。

Build 和其他 capability 必须由 Host 同步调用。每个 CP 在 Reviewer 意见逐条给出去向后调用配置的 Build 路由一次；`build-fix` 只在配置为 C++ 路由时使用。调用前，主 Agent 先读当前 slot 尝试；同一 slot 已有记录而没有当前用户重试决定时不得再次调用。这是 Agent 行为合同，不增加能力 Hook 门禁。调用真实返回后，主 Agent 立即通过 `advance capability-returned --key <kind> --decision "<简短不透明摘要>"` 记录一条轻量恢复事实；启动失败、超时或返回不可观察时使用对应的 `capability-failed-to-start`、`capability-timed-out` 或 `capability-not-observed`。这不是质量凭证，不解析专业工具输出，也不要求固定报告。若事实写入失败，不得为补写状态而重新执行昂贵能力。没有后台 worker、进度文件探测或自动再次执行。Quality 不重复仍覆盖最终源码的 CP Build；只在语义跨 CP 风险出现时做一次集成走读，并在 Delivery 前记录最终一致性自然语言结论。

## 文档模型

`DocumentPaths.for_ticket()` 把每个需求分为两组：

- 默认持久组：`docs/specs/<domain>.md` 当前行为基线，以及新领域需要的轻量 `docs/specs/index.md` 路由更新；
- 本地组：`.mae-flow-work/<safe-ticket>/` 下的 Spec、Story、决定、UT handoff、走读、CodeCheck 与 Delivery 笔记。

Spec 是工作流内确认的变更契约，Story 是按模板生成的独立软件详细设计和测试交接；两者都不是长期当前真相，也不把逐行编码计划落盘。条件文档的 durable copy 即使存在于 `docs/specs/requirements/<safe-ticket>/`，也必须有 `delivery.conditional_document` 的精确选择才能交付。未知 document kind 维持本地策略，肯定布尔值不能把拼写错误升级为提交权限。生成的 Spec、Story 和领域 Markdown 中，`<!-- generated-by: mae-flow -->` 只作来源水印，不得成为格式、Hook 或 parser 门禁。

领域行为基线按稳定业务能力划分。复杂存量领域第一次只建立本次证据覆盖的增量基线，遗漏保持未知。Delivery 对每个已选领域记录 `new`、`updated` 或 `unchanged`；只有变化文件进入 exact manifest，新领域同时更新 index，普通对账不增加用户停点。

## Git 与脏工作区

`DeliveryManifest` 使用仓库相对、逐文件、Windows-safe identity。反斜杠统一为展示用正斜杠，比较时大小写折叠；drive-relative、目录、通配、pathspec magic、仓外绝对路径和重复别名都拒绝。

启动时记录 `initial_dirty`。其中某个文件只有同时满足以下条件才能交付：

1. 用户明确采用；
2. 文件位于当前精确 manifest；
3. 采用事实仍与当前路径 identity 一致。

未采用的文件不妨碍 Construction，但会阻止自动 commit/push。Continuous 需要恰好一个提交说明；Staged 的有序 CP manifests 必须逐个获批，且它们的并集恰好等于最终 manifest。Hook 只在 Git 副作用边界核对已确认的工作分支、单号、类型和 exact manifest；失败不回退阶段，也不让 Build、UT 或 CodeCheck 失效。

## Moonlight

Moonlight 只在普通 `FlowState` 上保存四类预授权事实：enabled、business files、allow commit、allow push。文件集合使用与 Delivery 相同的 exact identity。授权重复、冲突、缺字段、包含 manifest 外文件或遗漏 manifest 文件时 fail-closed 并要求重新授权。

Moonlight 可以压缩常规等待，但 Delivery 卡始终透明地分别显示 requested/effective 权限和 block reason。风险、未拥有脏文件、capability 非正常结果、manifest 变化、推送失败或缺少真实 adapter observation 都安全停下；明确 exit 不受这些风险阻挡。

## 生产 Hook 边界

| 事件 | 当前职责 | 写入 |
|---|---|---|
| `SessionStart` | 每会话至多一次最小恢复摘要 | session marker |
| `UserPromptSubmit` | 原样记录用户事件；明确退出时原子移交状态 | 用户事件或退出 snapshot/pointer |
| `PreToolUse` | 危险动作、交互会话复用、业务源码边界和精确 Git 清单裁决 | 必要的 Git 副作用预留 |
| `PostToolUse` | 完成已预留的 Git 副作用观察 | Git observation |
| `SubagentStop` | 兼容已安装 CodeAgent 的历史事件 | 无；直接放行 |
| `Stop` | 兼容已安装 CodeAgent 的历史事件 | 无；直接放行 |

注册事件与 matcher 只按真实 CodeAgent 宿主需要调整，不能为了证明 Build/UT/CodeCheck 已执行而扩大监听。`WriteStdin` 必须经过 `PreToolUse`，防止复用交互会话绕过逐命令安全裁决。停止类事件只短路放行，不恢复任何状态机。普通 Hook payload 异常、未知工具或可选事实端口失败时 fail-open；已识别的 Git 危险副作用仍按安全内核拒绝。

## Windows 规则

- 文档、CI 和用户可见命令使用 `python`。
- 子进程使用 argv、`shell=False`、显式 UTF-8 与同步 `subprocess.run`；不依赖 POSIX signal。
- JSON 读入接受 UTF-8 BOM；Hook 字节依次尝试 UTF-8、Host locale、GB18030，无法确定时 fail-open。
- 文本资源兼容 CRLF，但生成文件固定 LF。
- 路径测试必须覆盖 drive、UNC、反斜杠、大小写和保留文件名。
- `os.replace`/`os.remove` 的 `PermissionError` 只做有界、可测试的短锁重试；达到 attempt 上限立即上抛。
- macOS/Linux 上的 `ntpath` 用例用于快速回归；真实 Windows Python 3.8/3.11 CI job 才是发布证明。

## 测试纪律

语义场景不能调用内部 Build、UT 或 CodeCheck。使用完整 fake Host payload 与 opaque outcome，断言真实状态、输出、文件或返回码。测试不能实际等待或轮询；Windows 文件锁用注入的零等待 delay 验证次数和边界，同步超时用短 subprocess timeout。

新增发布 suite 时要原子更新：

1. `scripts/tests/selftest_suites.py`
2. `scripts/tests/refactor_completion.py`
3. `scripts/tests/refactor_completion_contract.json`
4. `scripts/tests/test_refactor_completion.py`

`production_reachable_python_files` 是生产图合同。增加测试文件不改变该目标；只有生产图真实变化且另有批准时才能调整。

## 发布门

```text
python scripts/tests/test_lean_semantic_scenarios.py
python scripts/tests/test_windows_lean_runtime.py
python -m unittest discover -s scripts/tests -p 'test_*.py'
python scripts/selftest.py
git diff --check
```

本地完整 gate 只跑一轮 discover 和一轮 selftest。若失败，先用最小 targeted command 复现并修复，不重复全量碰运气。CI 必须保留真实 `windows-latest` job，且不依赖公司私有工具。
