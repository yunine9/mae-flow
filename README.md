# Mae-Flow

高效率、高质量；在需要人介入时聪明地让人介入。

Mae-Flow 是面向 CodeAgent 的交付工作流。它把人留在真正有决策价值的位置，把可确定、可恢复、可验证的工作交给 Agent；工具结果保持不透明，不靠猜测输出推进，也不靠反复执行碰运气。

## 快速开始

在 Git 仓库中告诉 CodeAgent 单号、目标和已有材料：

```text
/mae-flow:mae-flow
交付 REQ-42：修复删除好友后会话缓存未清理的问题。
```

启动卡会一次展示工号、单号与 `feat/fix` 类型、需求来源、推荐路径、提交节奏、基线/工作分支、精确 Build 路由、UT 生成方式、UT 运行入口、质量组合和本轮已存在的工作区改动。C++ 可以配置 `build-fix` Skill，Java/Maven 配置准确 Maven 命令，其他语言使用仓库自己的 Skill 或命令；`build-fix` 不是通用 Build。用户可以直接用自然语言调整或确认；没有固定口令。确认后立即创建或切换工作分支。

恢复时直接说“继续 REQ-42”。Mae-Flow 从项目里的最小恢复游标继续，不要求旧会话仍在。要退出时明确说“退出 Mae-Flow”；退出会保存现场并释放控制，不删除业务改动。

## 只有两条路径

| 路径 | 适用情况 | 固定用户停点 |
|---|---|---|
| **Full** | 需要显式规格、设计或逐检查点检视的工作 | Intake、Spec、Design、每个 CP、Delivery |
| **Focused** | 已定位且语义边界清楚的局部工作 | Intake、Delivery |

路径由语义决定，不由文件数或行数决定。一个只改一行的兼容性修复可以选择 Full；一个涉及多个文件但边界清楚的机械落位可以选择 Focused。Focused 一旦发现接口、兼容性、数据、安全、共享状态、并发或其他真实语义风险，就升级到 Full 的 Spec，不静默扩大范围。

## 六个阶段

唯一阶段序列是：

```text
Intake → Spec → Design → Construction → Quality → Delivery
```

| 阶段 | 目标 | 典型产出 |
|---|---|---|
| **Intake** | 确认完整运行配置、相关业务领域、路径、提交节奏和初始脏文件归属 | 启动决定与恢复游标 |
| **Spec** | 固定 WHAT：可观察行为、边界、非目标和风险 | 默认本地的变更契约 |
| **Design** | 形成可独立交付的软件详细设计与测试交接 | 默认本地的 Story |
| **Construction** | 按 CP 实现、检视，并按启动配置同步 Build 一次；Full 在每个 CP 给用户检视，Focused 连续推进 | 业务改动与本批事实 |
| **Quality** | 做 CodeCheck/UT 和最终一致性对照，按语义风险决定是否做一次集成走读 | 不透明能力结果与未决风险 |
| **Delivery** | 展示精确文件清单、提交说明和推送选择 | 精确提交与一次推送 |

内部恢复游标沿用 `startup` 和 `story` 两个稳定值，分别对应面向用户的 Intake 和 Design；它们不是额外阶段。

## 人什么时候介入

默认停点之外，只有以下情况值得打断用户：

- 需求或现有行为存在真实歧义；
- 实现发现有意义的设计偏差；
- Reviewer 揭示必须由用户取舍的问题；
- 同一语义 slot 需要再次调用昂贵能力；
- 即将执行不可逆动作；
- Delivery 的精确文件清单发生变化；
- Moonlight 遇到未授权、失败或不确定事实，需要安全停下。

普通进度、工具正常返回、没有用户级取舍的走读意见和跨 CP 的已知集成工作不会制造新停点。

## 一次性能力箱

Build、UT、CodeCheck、Grill、Story、Reviewer 都是一次性、不透明的 capability，不是隐藏的子流程。

- 每个语义阶段/CP slot 默认至多调用一次。
- Host 的同步返回就是完成边界。Mae-Flow 不解析内部输出格式，不把 `PASS`、`CLEAN`、计数或任意私有字段推断成质量结论。
- 记录的结果只有 `returned`、`failed-to-start`、`timed-out` 或 `not-observed` 以及一段有界摘要。
- 没有后台轮询、等待循环或自动重试。同一语义 slot 再次调用需要当前用户决定；新的阶段/CP slot 的首次计划调用正常执行，不让用户重复授权。
- 独立调用不会创建活动工作流，不会提交或推送。输出文件默认保留在本地。

UT capability 自己负责写测试、编译测试和运行测试；弱 C++/gtest 环境无法证明执行数量时，只如实保留不透明返回。CodeCheck 输出未知时同样只记录事实，不臆造 verdict。

每个 CP 在 Lightcheck 和一次 Reviewer 意见处置后，按 Intake 确认的 Build 路由同步编译一次。Reviewer 的每条意见都有自然语言去向，但没有固定报告。Quality 不机械重复仍覆盖最终源码的最后一次 CP Build；CodeCheck 与 UT 仍各自只调用一次。只有跨 CP 耦合、共享状态、接口变化或晚期设计漂移才增加一次集成走读。Delivery 前保留一条 Spec/Story/范围与最终代码、覆盖的简短一致性结论。

## 文档与文件归属

需求过程材料按单号分组：

```text
.mae-flow-work/<ticket>/spec.md
.mae-flow-work/<ticket>/story.md
.mae-flow-work/<ticket>/decisions.md
```

领域行为基线是默认上库的当前真相源：`docs/specs/<domain>.md` 按稳定业务能力划分，`docs/specs/index.md` 只做轻量路由。复杂存量领域第一次只记录本次有证据的覆盖，未写到的行为仍是未知，不要求一次补全。

Spec 是本轮确认的 WHAT 变更契约；Story 按模板合并客户场景、业务规格、功能验收标准、软件详细设计和测试交接。二者以及决策、链路说明、走读记录、CodeCheck 记录和 Delivery 笔记默认保留在本地。只有用户明确选择 `docs/specs/requirements/<ticket>/` 下某一份 durable copy 入库后，它才会进入本轮精确 manifest；“生成了”不等于“应该提交”。工作流生成的 Spec、Story 和领域 Markdown 使用 `<!-- generated-by: mae-flow -->` 标记来源，但 Hook 和 parser 不校验该水印。

Delivery 将每个相关领域对账为 `new`、`updated` 或 `unchanged`。只有真实变化的领域文档以及新领域需要的 `index.md` 更新进入精确 manifest；不扫描、不暂存无关领域，也不物理归档历史 Spec。

Focused 启动时不声明 Spec、Story 或 UT handoff 产物；只有语义风险触发升级 Full 时，才一次补入这三条 Full 路径。

## Git 交付

Mae-Flow 只对用户已审阅的逐文件 manifest 授权：

- `git add -- <file>...` 只列精确文件，不使用宽暂存；
- Windows 反斜杠和大小写别名视为同一文件，重复或含糊路径会被拒绝；
- 启动前已有的脏文件只有被用户明确采用后才能进入 Delivery；未采用的脏文件可以留在工作区，但不能被自动交付；
- 提交只允许发生在 Intake 已确认的工作分支；总体格式仍为 `[ticket][feat|fix]description`，本轮必须使用 Intake 已确认的 exact type；
- Continuous 生成一个最终本地提交，Staged 按用户确认的 CP manifest 生成多个提交；两者最终都只推送一次；
- manifest 在确认后变化时必须重新展示，不能沿用旧授权。

## Moonlight

Moonlight 是同一工作流上的精确预授权，不是第三条路径。用户明确给出允许的业务文件以及是否允许 commit/push 后，它可以略过 Full 的常规 Intake、Spec、Design、CP 等待；歧义、真实风险、能力失败、未拥有的脏文件、manifest 变化和推送失败仍会安全停下。

Delivery 卡始终可见，并同时展示 Moonlight requested 权限、effective 权限和被撤销时的 block reason。Moonlight 可以授权卡片所描述的精确副作用，但不会把交付信息藏起来，也不会自动纳入未点名的 Story 或其他条件文档。

## 生产 Hook 边界

CodeAgent 保留六个兼容注册事件；只有前四类承担当前职责：

| Hook | 职责 |
|---|---|
| `SessionStart` | 注入一次最小恢复摘要 |
| `UserPromptSubmit` | 保留原始用户事件并识别明确退出 |
| `PreToolUse` | 在副作用发生前执行安全与精确 Git 裁决；`WriteStdin` 也必须经过该边界 |
| `PostToolUse` | 记录已预留 Git 副作用的实际结果，不解析 Agent/Skill 返回 |
| `SubagentStop` | 兼容历史 CodeAgent 事件，直接放行 |
| `Stop` | 兼容历史 CodeAgent 事件，直接放行 |

能力真实同步返回后，主 Agent 使用一次 `advance capability-<outcome> --key <kind>` 保存轻量恢复事实；工作流命令是 capability 事实的唯一写者。该记录不是质量凭证，不能触发重跑。Hook 失败时普通开发 fail-open，Git 危险动作仍由安全内核按当前事实裁决。

## 本地验证

用户可见命令统一使用 `python`：

```text
python scripts/tests/test_lean_semantic_scenarios.py
python scripts/tests/test_windows_lean_runtime.py
python -m unittest discover -s scripts/tests -p 'test_*.py'
python scripts/selftest.py
git diff --check
```

CI 在真实 `windows-latest`（Python 3.8 与 3.11）和 `ubuntu-latest`（Python 3.11）上运行同一组发布门，并对当前 push/PR 的真实 base..head 提交范围执行 diff check。CI 不调用真实内部 Build、UT 或 CodeCheck；能力场景只使用 fake Host payload 和不透明 outcome。Windows runner 负责证明真实盘符、反斜杠、大小写、文件锁、控制台编码和同步子进程语义；Linux 上的 `ntpath` 测试只是快速回归，不替代 Windows job。

维护与发布规则见 [MAINTAINERS.md](MAINTAINERS.md)，人工场景见 [FIELD-TEST.md](FIELD-TEST.md)，干净环境验收见 [CLEAN-ROOM-TEST.md](CLEAN-ROOM-TEST.md)。
