# Mae-Flow 维护者手册

高效率、高质量；在需要人介入时聪明地让人介入。

本手册描述当前唯一生产模型。公共路径只有 Full 和 Focused，公共阶段只有 Intake → Spec → Design → Construction → Quality → Delivery。任何兼容代码都不得重新暴露额外模式、阶段或操作仪式。

## 不变量

1. **语义决定路径。** Full 与 Focused 的选择和升级只看接口、兼容性、数据、安全、共享状态、并发等语义风险，不看文件数、改动行数或目录数量。
2. **只在高价值点找人。** Full 停在 Intake、Spec、Design、每个 CP、Delivery；Focused 停在 Intake、Delivery。真实歧义、设计偏差、用户级 Reviewer 取舍、昂贵能力再次调用、不可逆动作和 manifest 变化可以增加条件停点。
3. **能力一次调用。** Build、UT、CodeCheck、Grill、Story、Reviewer 是一次性 opaque capabilities。Host 同步返回后记录事实，不解析私有输出，不后台等待，不自动重试。
4. **状态是最小恢复游标。** 只保留当前路径、阶段、CP、产物路径、自然语言决定、风险、能力尝试、Delivery 文件和初始脏文件；不把过程报告扩成第二套工作流。
5. **Hook 单写。** Host Hook 是唯一写者；所有读改写走项目锁和原子替换。Agent、capability 和文档渲染器不直接写活动状态。
6. **Git 精确授权。** 每次提交只使用用户审阅的逐文件 manifest；提交说明为 `[ticket][feat|fix]description`；最终只推送一次。
7. **条件文档默认本地。** Story、决策、工程笔记、链路、走读、CodeCheck 和 Delivery 笔记默认保留在本地，用户明确选择后才能加入精确 manifest。
8. **安装不是授权。** 没有活动状态时 Hooks fail-open；明确退出在任何阶段生效，保留现场并释放控制。

## 领域模型

| 公共概念 | 恢复值 | 说明 |
|---|---|---|
| Full | `full` | 显式 Spec、Design 与每 CP 检视 |
| Focused | `focused` | 已定位工作；语义风险出现时升级 Full |
| Intake | `startup` | 启动选择与初始工作区归属 |
| Spec | `spec` | WHAT |
| Design | `story` | HOW、可测性与 CP |
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

首次调用后，任何再次调用都需要当前用户决定；源码、阶段、CP 或环境变化只改变授权键，不自动授权。决定绑定 kind、语义 phase/CP slot 和 environment；旧 slot 的决定不能被新 slot 消费。不要从 summary 中寻找 `PASS`、`CLEAN`、数字、测试框架字段或未来工具格式。

Build 和其他 capability 必须由 Host 同步调用。完成信号是工具调用返回本身；没有后台 worker、进度文件探测或自动再次执行。超时由 Host 边界报告 `timed-out`，工作流保留可恢复事实并按风险决定是否找人。

## 文档模型

`DocumentPaths.for_ticket()` 把每个需求分为两组：

- 持久组：`docs/mae-flow/requirements/<safe-ticket>/spec.md` 与行为基线；
- 本地组：`.mae-flow-work/<safe-ticket>/` 下的 Story、决定、工程笔记、UT handoff、走读、CodeCheck 与 Delivery 笔记。

条件文档即使存在于持久目录，也必须有 `delivery.conditional_document` 的精确选择才能交付。未知 document kind 维持本地策略，肯定布尔值不能把拼写错误升级为提交权限。

## Git 与脏工作区

`DeliveryManifest` 使用仓库相对、逐文件、Windows-safe identity。反斜杠统一为展示用正斜杠，比较时大小写折叠；drive-relative、目录、通配、pathspec magic、仓外绝对路径和重复别名都拒绝。

启动时记录 `initial_dirty`。其中某个文件只有同时满足以下条件才能交付：

1. 用户明确采用；
2. 文件位于当前精确 manifest；
3. 采用事实仍与当前路径 identity 一致。

未采用的文件不妨碍 Construction，但会阻止自动 commit/push。Continuous 需要恰好一个提交说明；Staged 的有序 CP manifests 必须逐个获批，且它们的并集恰好等于最终 manifest。

## Moonlight

Moonlight 只在普通 `FlowState` 上保存四类预授权事实：enabled、business files、allow commit、allow push。文件集合使用与 Delivery 相同的 exact identity。授权重复、冲突、缺字段、包含 manifest 外文件或遗漏 manifest 文件时 fail-closed 并要求重新授权。

Moonlight 可以压缩常规等待，但 Delivery 卡始终透明地分别显示 requested/effective 权限和 block reason。风险、未拥有脏文件、capability 非正常结果、manifest 变化、推送失败或缺少真实 adapter observation 都安全停下；明确 exit 不受这些风险阻挡。

## 四个生产 Hooks

| 事件 | 当前职责 | 写入 |
|---|---|---|
| `SessionStart` | 每会话至多一次最小恢复摘要 | session marker |
| `UserPromptSubmit` | 原样记录用户事件；明确退出时原子移交状态 | 用户事件或退出 snapshot/pointer |
| `PreToolUse` | 安全裁决；对匹配 capability 原子预留一次 slot | pending capability + attempt |
| `PostToolUse` | 按 tool-use identity 完成已预留 slot | opaque return summary |

生产注册不得加入其他事件。旧 Host 发来的停止类事件只短路放行，不恢复任何状态机。普通 Hook payload 异常、未知工具或可选事实端口失败时 fail-open；已识别的 Git 危险副作用仍按安全内核拒绝。

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
