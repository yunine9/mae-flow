# Mae-Flow 维护者手册

读者：维护、扩展、排障本插件的人。使用者请看 [README.md](README.md)。

---

## 一、架构总览

四层栈，每层只管一件事，互为兜底：

```
mae-flow(本插件)   —— 管"路径":公司交付流程的状态机 + 实物证据 + 越界拦截
  └ comet          —— 管"工程方法":open/design/build/verify/archive 五阶段编排
      ├ openspec   —— 管 WHAT:提案、delta spec、真相源、归档
      └ superpowers—— 管 HOW:brainstorming、写计划、执行计划、收尾
公司质量 agent(env-setup/ut-generator/codecheck-fix/story-generator/compile)—— 管"质量动作"
```

职责分层的一句话版本：**状态机管路径、证据管推进、hook 管越界、comet 管方法、子 agent 管质量**。

### 设计原则（改任何代码前先读）

1. **不信口头汇报，只信磁盘**。推进流程的唯一凭据是文件系统与 git 的真实状态（`done` 的证据校验）。任何新功能如果依赖"模型说它做了"，就是错的。
2. **正确性放硬层，优雅性放软层**。硬层 = 工具拦截（证据、gate、hook exit 2）；软层 = 步骤指令措辞。无法硬拦的（如"必须用子 agent 修环境"），明文写进指令并接受其失效模式只是"不优雅"而非"不正确"。
3. **一切幂等、无进程记忆**。主流程断点靠 `.mae-flow.json`，子 agent 断点靠文件系统现状。任何组件挂了再拉起，只看磁盘就能接着干。
4. **fail-open 但可观测**。hook 自身故障不阻塞用户干活（exit 0 放行），但必须在日志留痕。静默失效是本体系最大的敌人（历史教训：GBK 解码炸 → gate 无声关闭）。
5. **路径自锚定，不赌 cwd**。插件文件锚定 `__file__`；项目文件靠 `find_project_root()` 向上定位后 chdir。
6. **Windows-only**。命令用 `python` 不用 `python3`；子进程 `text=True` 必须显式 `encoding="utf-8"`（中文 Windows 默认 GBK）；路径匹配一律 `re.I`（NTFS 不分大小写）；跨盘符禁用 `relpath`；hook 经 Git Bash 执行。
7. **用最弱的可用模型压测，用最强的模型生产**。强模型自觉守规则，会掩盖 harness 的洞；弱模型是 harness 的模糊测试器——每个洞都变成立刻可见可修的事故（2026-07-18 用 Haiku 一下午打出八类偏差，全部修复后才算"实战可信"）。改动 harness 后的回归验证同理：拿弱模型跑演习沙箱，别拿强模型的"一次通过"当证据。
8. **硬禁令必须配裁决出口**。gate 与契约拦的是"未经用户裁决的动作"，不是场景本身——工程现实里被禁动作往往有正当场景（UT 揭出源码真缺陷、既有用例被规格演进淘汰、实现揭出设计/spec 有误、AskUserQuestion 客观不可用）。每条禁令都要回答"该场景的正规出口是什么"：unlock source（UT 缺陷修复）、SUSPECTED_BUGS 呈报（agent 自查后升级）、goto --ack 回流（设计/spec 修订、验真兜底）。禁令没有出口，弱模型只剩"卡死"或"作弊绕过"两个选项，都是事故（ImpossibleBench 实证：给正规弃权通道，作弊率 54%→9%）。新加任何禁令前先写出口，出口必须带用户裁决与留痕。

### 思想图谱（三个开源思想源，各管一段、互不越界）

| 思想源 | 在流程中的位置 | 融入方式与红线 |
|---|---|---|
| **grill-me**（mattpocock/skills 的 grilling） | grill 步（open 之前） | 五铁律原文级还原（追问至共识/决策树逐支/每题带推荐/一次一题/事实自查决策问人），工程化增强：8 维备课（模板化工作表 grill-prep，hook 校验章节 + done 拦「待填」残留）、题目四要素、阻塞性排序、收敛条件。**高度红线：只问需求层（WHAT），技术分歧记入「留给设计阶段」清单，禁止下钻** |
| **superpowers**（brainstorming/writing-plans/executing-plans 等） | 经 comet 编排进 design/build | brainstorming 带着 clarifications 进场（已拍板决策禁止重问，新需求缺口回流 grill 产物）；build 四项工作方式固化标准答案；批次检查点不等用户；TDD 说教用标准回应化解；编译/测试失败按 systematic-debugging 纪律"先归因再动手"（build 主会话 + UT agent 修复循环，skill 缺失时按内联纪律执行）；评审返工轮次（review workflow）按 receiving-code-review 纪律：先查证再裁决、反驳要依据、禁"您说得对"式照单全收 |
| **EARS**（Kiro / IBM 需求句法） | grill 答案 → delta spec Scenario → UT AC_COVERAGE | 行为规格一律「WHEN <条件> THE SYSTEM SHALL <可观测行为>」，一句一测，贯穿"澄清→规格→用例"三级可追溯。**红线：只约束句式，不新增流程节点/确认点** |
| **ponytail** | build 全程 + verify 4.1 | 双用：build 写码时 full 档常驻预防（the ladder，源头压缩整条 verify 链的量）+ verify 对 diff 做 review 治疗。**两条红线：YAGNI 不得砍 delta spec 要求的行为（spec 是合同，YAGNI 只管怎么写不管写什么）；禁 ultra 档（质疑需求是 grill 的地盘）** |
| **compound-engineering**（EveryInc） | end 沉淀 → build/verify 装载 | 每单教训经用户逐条确认后沉淀进 docs/delivery-notes.md，下单 build/codecheck/UT 开工前装载。**红线：只沉淀仓库事实（构建陷阱/告警高发点/mock 策略），禁流程规则——防与插件双源打架；上限 30 条，超限删最旧** |

### 质量五维（一维一主，verify 顺序即理由：删 → 改 → 测 → 验）

| 维度 | 谁管 | 何时 | 为什么在这个位置 |
|---|---|---|---|
| 复杂度 | Ponytail | build 预防 + verify 4.1 | 先删：不给将死代码修规范/补测 |
| 规范 | CodeCheck | verify 4.2 | 再改：拆大函数等重构在此定稿；hook 三数对账+复验摘录一致性防吞告警；**done 的 codecheck_clean 现场重跑 CLI 亲数遗留（agent 报数不作数）**；只查业务代码不查测试；流水线门禁必拦 → 流程无"忽略"选项 |
| 编译 | compile-agent（全流程唯一编译执行者，隔离舱） | build 批次边界 + tw/rf 涉码时 | 主会话永不编译；路由=配置的编译方式（C++→build-fix skill/Java→mvn）；SubagentStop 硬校验 OK⇔零error + **numstat 亲算净产出不变量**（删代码换编译通过得不了分）+ BLOCKED 弃权出口 |
| 回归 | AutoUT | verify 4.3 | 后测：对定稿代码补测才不会被重构作废。TDD 已弃用（与事后补测互斥，其设计压力由 spec+design 阶段替代提供） |
| 正确性/漏洞 | comet review（standard） | build 收尾 + verify 内 | 与规范/复杂度维度不重叠，这一维只有它管 |
| 规格符合 | comet-verify | verify 4.4 | 终验对 spec；`verify_result: pass` 是硬证据 |

### 确认点预算（人工停顿的取舍原则）

保留有价值的人工关卡：配置确认、工作流选择、grill 逐题、产物确认（open/design/story）、**计划评审（plan-ready）**、build 终点 ack、REMAINING 裁决（修/正式豁免二选一）、归档确认（不可逆，ASKUSER 令牌硬校验——全流程唯一不可逆点不设软路径）。
消灭无价值的碎片等待：build 四项选择（固化）、executing-plans 批次检查点（简报后直行）、TDD 说教（标准回应）、comet 分支/commit 建议（拒绝话术前置）。

## 二、目录结构

```
skills/mae-flow/SKILL.md   触发条件 + 5 条铁律(工具管不住、靠模型自守的部分)
flow/flow.json              流程定义:步骤图、证据、权限、环境检查项
flow/steps/<step>.md        每步的执行指令(改流程行为优先改这里,无需动代码)
scripts/mae-flow.py         状态机驱动器(init/current/done/skip/gate/status/doctor/report/envcheck/goto/template)
hooks/hooks.json            5 个 hook 注册(exec form + timeout 15s)
hooks/dispatch.py           hook 分发器(防卡死 + 项目根定位 + 契约校验 + 日志)
agents/*.md                 4 个子 agent 契约(XXX_RESULT 标记 + 幂等要求)
scripts/setup.py            环境安装器:确定性流水线(A 类装东西;幂等/dry-run/离线包;日志 %TEMP%/mae-flow-setup.log)
skills/mae-flow/assets/env-profile.json  公司环境常量单一事实源(镜像/代理/包名/插件命令;换环境只改它)
commands/mae-flow.md       /mae-flow 命令的三个模式(完整/setup/story)
skills/mae-flow/assets/     模板与基线:STORY / CHAIN / GRILL-PREP / REVIEW 四份模板(hook 章节校验以此为准,
                            全插件唯一)+ settings-baseline.json 权限基线(env-setup 合并进项目 settings)
```

## 三、核心机制

### 3.1 状态机（flow.json + .mae-flow.json）

状态存项目根 `.mae-flow.json`（gitignored，`.mae-flow.json*` 模式），原子写（tmp + `os.replace`）。
终态后 `init` 先把本单摘要（耗时/goto/摩擦统计）追加进 `.mae-flow-history.jsonl`
（gitignored + gate 防篡改；`report --all` 聚合展示，团队度量数据出口），再自动备份为 `.last` 开新档；非终态 `init` 拒绝。
仓根可提交 `.mae-flow-defaults.json`（团队预设：编译方式/UT生成方式/UT运行命令等恒定项），
require_sets 步骤的 `current` 会展示预填块；它只是展示层预填，`--set` 逐项确认的硬约束不变。

flow.json 步骤字段语义：

| 字段 | 含义 |
|---|---|
| `next` | 字符串=直连；dict=按 `choice_key` 的选择分流 |
| `next_by` | 按**历史**选择分流（如 branch_create 按之前 workflow_select 的选择） |
| `choice_key` / `choices` | 本步需 `done --choice <值>`，存入 st.choices |
| `user_ack` | 本步必须 `done --ack "用户原话"`，缺失拒绝（伪造 ack 只能靠铁律，工具验不了真） |
| `require_sets` | done 前必须 `--set` 齐的配置键；含"基线分支"时自动派生分支名 |
| `evidence` | 证据数组，全部通过才推进（见 3.2） |
| `allow_source_edit` / `allow_specs_write` | 本步的写权限，gate 据此拦截 |
| `skippable` | 允许 `skip --reason`（留痕） |
| `clear_hint` | `current` 打印「建议 /clear」提示（重上下文步骤入口的会话卫生引导；状态在磁盘，/clear 零成本） |
| `tests_only` | 配合「测试路径」配置（config 逗号分隔正则 / defaults 文件数组）把本步源码写权限收窄到测试路径；未配置不生效（per-repo opt-in）；用户裁决后 `unlock source` 临时放行（仅本步实例） |
| `terminal` | 终态；打印同名 md 作收尾指令 |

### 3.2 证据系统（EVIDENCE 表）

| 类型 | 校验内容 |
|---|---|
| `glob` | 文件存在（`any` 数组任一命中；pattern 支持 `{配置键}` 占位） |
| `branch_ok` | 当前 git 分支 == 配置的分支名（实测） |
| `env_ok` | 环境检查全绿（实测，带 24h 缓存，见 3.5） |
| `tasks_checked` | 本 change 的 tasks.md 无未勾选项 |
| `commit_tagged` | 最新 commit 匹配 `[单号][feat|fix]` |
| `yaml_field` | 读本 change `.comet.yaml` 字段：`equals` 精确匹配或非空即过（**首选**——comet-guard 机器写入，不可伪造） |
| `pushed` | `git rev-parse --verify HEAD` == `@{u}`（实测已推送） |
| `agent_ran` | 本步期间发生过 harness 签发的事件令牌——SubagentStop 验完契约标记发 agent 令牌（STORY/UT/CODECHECK/ENV），PostToolUse 对 AskUserQuestion 发 **ASKUSER 令牌**（"真实问过用户"从此是 harness 记录的事实，不是模型可书写的文本）。令牌文件 gate 双拦 + 手动调 dispatch.py 被拦 + 时间戳须晚于本步进入 + **新鲜度绑定**：令牌记签发时 HEAD，签发后源码（source_patterns）有已提交/未提交变更即判证据过期（旧格式纯时间戳令牌仅验时间，兼容在途单；基点经 amend/rebase 不可解析同样判拒，重跑 agent 即恢复）。**封杀三类造假：主会话代工 agent 产出、未问用户就声称确认过、拿旧证据背新代码的书** |
| `content_free` | 文件内容不得命中禁止正则——把"标注协议"变成机器可查终态（story 在用：零"待确认"+ 禁裸"不涉及"，破解指标博弈的职责锁） |
| `clean_paths` | 指定路径 git 实测已提交且无未提交改动——硬化"产物必须 commit"义务（grill/open/design/archive 在用） |
| `codecheck_clean` | **done 现场重跑 `codecheck fullcheck -f <本单业务代码>` 亲数遗留**（解析锚点「共有 N 条告警」，全量明细读落盘报告）：0 条或每条(规则,文件)都在 `docs/codecheck-exempt-{单号}.md` 豁免清单内才放行。只查业务代码（测试路径配置/默认特征过滤）；分批防命令行超长；超时 15min。最硬形态：agent 报数不作数，harness 亲测（verify_codecheck/tw_codecheck/rf_verify 在用） |

**新增证据类型**：在 mae-flow.py 写 `ev_xxx(spec, st) -> (bool, 失败原因)`，注册进 `EVIDENCE` 字典，flow.json 里引用。失败原因要写"怎么补救"，它会原样回传给模型。

### 3.3 gate（PreToolUse 拦截）

`gate edit <路径>` / `gate bash <命令>`，exit 2 = 拦。保护清单：

- `.comet.yaml` / `.openspec.yaml`（comet-state 专属）
- `.mae-flow.json` 及其衍生（`.tokens`/`.tmp`/`.last`）与历史账本 `.mae-flow-history.jsonl`（Edit 和 Bash 写双拦）
- `dispatch.py` 禁止手动执行（伪造 agent 令牌的通道）
- 插件目录自身（防模型改规则）
- `openspec/specs/` 真相源（仅 `allow_specs_write` 步放行，Edit/Bash 双路）
- 源码 `source_patterns`（仅 `allow_source_edit` 步放行；Bash 路按 **token** 匹配——整串匹配对空格后的相对路径永远不命中，历史 bug）
- git 约定：分支名（checkout -b/-B、switch -c/-C、branch -m）、commit 格式（含不带引号的 -m）、force push（含 +refspec）、`git worktree add`（与状态机不兼容）
- `.env` 类密钥文件禁写；危险命令 denylist（管道执行远程脚本、`git clean -x`、对 `/`~`*`.`盘根 的递归删除——普通目录的 rm -r 不拦）。注：PreToolUse 硬拦在权限跳过模式下依然生效（hook 跑在 shell 里，提示词注入绕不过）
- `comet init` 会话内全禁（含子 agent、含管道喂输入变体）：交互式 TUI 被非交互执行会把二三十个 agent 平台全部初始化污染仓库（2026-07-20 实战）；拦截消息给"目录/命令/平台"三要素话术交用户手动。教训：agent 的"想尽办法装成功"哲学会压过"无法自动化"的措辞——这类禁令必须放硬层
- verify_ut 的测试路径收紧（`tests_only` × 「测试路径」配置）：配置后仅放行测试路径写入（Edit/Bash 双路），把 UT agent「禁改被测源码」从契约措辞硬化为 gate；未配置的仓行为不变。**这不是死禁**——配套 unlock 裁决通道（原则 8）
- **unlock source 裁决通道**：UT 揭出疑似源码缺陷、用户判"确为代码缺陷"后，`unlock source --reason <裁决> --ack "用户原话"`（ack 走与 done 相同的三级验真）解锁当前步的测试路径收紧；仅本步实例有效，done/goto 自动失效，历史留痕 `unlock:source`；未启用收紧的仓执行为留痕 no-op。修复提交后新鲜度绑定会强制重跑 UT agent（旧令牌 HEAD 已过期），"改完不验就 done"走不通

**已知局限（设计决定）**：Bash 写检测的 `WRITEISH` 正则是打地鼠，永远可绕过（如 `python -c`）——它的定位是**软提醒层**，真正的门槛在 done 的证据校验。不要试图把 bash 正则做"完备"。

### 3.4 hooks（dispatch.py）

5 个事件：SessionStart / UserPromptSubmit（状态注入 + 用户输入捕获进 ack 验真存储）、PreToolUse（gate）、
PostToolUse（STORY/CHAIN/GRILL-PREP 模板校验 + ASKUSER/UTRUN 令牌 + AskUserQuestion 应答捕获）、SubagentStop（契约校验 + 令牌绑 HEAD）。

**防卡死四件套**（历史上曾造成每条消息挂 10 分钟，动这里要极其小心）：
- 看门狗 12s 强制 `os._exit(0)`
- stdin 守护线程读，3s 超时按空输入（治 harness 不关 stdin）
- 调 mae-flow 的子进程 8s 超时
- 每次调用记 `%TEMP%\mae-flow-hook.log`：`start/end + rc + 耗时`；只有 start 没 end = 被看门狗击杀

SubagentStop 契约校验：最终回复**第一行**必须 `XXX_RESULT: <状态>`；CODECHECK 额外硬验三件事——
`EXECUTED_COMMAND` 含 fullcheck、三数对账 `FOUND = FIXED + REMAINING_COUNT`（吞告警最常见形态是马虎遗漏，算术不平当场打回）、
CLEAN ⇔ 遗留为 0 / REMAINING ⇔ 遗留 ≥1（FAIL 属诚实上报不苛求对账）。`stop_hook_active` 时放行（防打回死循环，代价是二次失败静默通过）。
**非正常收尾自动尸检**（2026-07-20，治"agent 奇怪退出无人知晓死因"）：无标记收尾/重答仍失败时，把轮数、临终输出、检出的报错特征落 `%TEMP%/mae-flow-agent-autopsy.log`，并把一行「尸检线索」嵌进打回消息——主 agent 重启新实例必须转告（SKILL 铁律）；配套五个 agent 契约的"带着情报死"条款（工具连败 2 次→FAIL/BLOCKED 收尾写明详情；轮次过半未完成→提前收尾出部分成果，不许干到被硬切）。

### 3.5 环境检查（env_checks）

类型：`cmd`（退出码 0）、`cmd_contains`、`node_min`、`path_any`、`file_contains`。
**缓存**：机器级慢检查全绿后 touch `~/.mae-flow-env-ok`，24h 内跳过；`FAST_TYPES`（path_any / file_contains，项目级）永远实测；`envcheck` 命令永远全量并刷新缓存。新增检查时想清楚它是机器级还是项目级。
**安装三层策略**（2026-07-20 实战定型，comet init 全平台初始化事故后重构）：A 类确定性安装 → `setup.py`（零创造力、幂等、失败带诊断线索、终验复用 envcheck）；C 类诊断 → env-setup-agent（读日志修环境参数后**重跑 setup.py**，禁止绕过它手工装——"用另一条路装上"不可复现）；B 类交互 → 人工三要素话术（comet init 会话内 gate 硬拦）。环境常量全在 env-profile.json，换代理/镜像/插件命令只改一处。教训：把智能用在确定性工作上，幺蛾子是创造力的副产品。

### 3.6 子 agent 契约

三条不可违背：**第一行标记**（SubagentStop 强制）、**无状态幂等**（先检查后动作，禁止"我下次再"话术——没有下次，是下一个实例接手）、**不能与用户对话**（决策进 PENDING_DECISIONS）。
新增 agent 时：契约文件放 agents/，且必须把 agent 名加进 dispatch.py `ev_subagentstop` 的识别正则和标记正则，否则契约校验不生效。

## 四、与 comet 的集成合同（破坏任何一条都会出鬼故事）

| 约定 | 原因 | 落点 |
|---|---|---|
| `.comet/config.yaml` 含 `auto_transition: false` | mae-flow 独占节奏，禁止 comet 自动衔接阶段 | 环境检查 + env-setup-agent 创建 |
| `review_mode: standard` | 三维分工：comet review=正确性/漏洞，CodeCheck=规范，Ponytail=复杂度，互不替代 | 同上 + build.md |
| isolation=branch、tdd=direct+direct_override、executing-plans | comet-build 四选项的公司标准答案 | build.md |
| comet verify 的分支处理选"保持分支" | 推送归 push 步，MR 人工建 | verify_comet.md |
| 依赖 `.comet.yaml` 的 `design_doc`/`verify_result` 字段 | yaml_field 证据的数据源 | flow.json |
| comet 锁 **0.3.x** | 字段名/guard 行为按 0.3 语义编写 | env-setup-agent |
| `.claude` → `.cac` 迁移 + 会话内 `/reload-skills` | codeagent 只加载 .cac | env-setup-agent step 11 |
| tweak 也走归档 | 防僵尸活跃 change 干扰 comet 阶段检测 | flow.json + archive.md |
| verify 链固定顺序 Ponytail→CodeCheck→UT→Comet | 删→改→测→验：重构定稿后 UT 才覆盖得上最终形态 | flow.json + 各 verify step md |
| ponytail 红线：YAGNI 不砍 spec、禁 ultra 档 | spec 是合同；质疑需求归 grill 阶段 | build.md + verify_ponytail.md |
| grill 高度分层：WHAT 归 grill，HOW 归 brainstorming | 三层提问不撞车；交接物 = clarifications +「留给设计阶段」清单 | grill.md + open.md + design.md |

**用户话术对照表**（用户界面层彻底封装：用户所见一律左列，右列只活在实现层与维护文档；--choice 代号、目录名、命令是 comet/openspec 的实物，不改）：

| 用户话术 | 上游/内部 |
|---|---|
| 标准交付 / 缺陷快修 / 小改快过 / 评审返工 | full / hotfix / tweak / review（--choice 代号，与 comet workflow 对齐） |
| 提案与规格、规格条目 | openspec proposal / delta spec |
| 变更目录 | change（openspec/changes/<CHANGE_NAME>） |
| 规格定稿 | archive / 归档 |
| 方案讨论 | superpowers brainstorming |
| 代码精简 | ponytail review |

话术纪律定义在 SKILL.md（面向用户不出现上游术语；doctor/排障输出保留原词，那是给维护人看的）。

**团队推广的四条运营纪律**（经验层，违反不会立刻坏，但会慢性失血）：
1. **CLAUDE.md 分工**：仓库 CLAUDE.md 只放仓库事实（构建/目录/领域约定），流程规则只活在插件里——两处都写会形成双源打架，弱模型无所适从。
2. **permissions 基线**：团队 settings 里 `deny` 密钥类文件的 Read（对模型不可见，比 hook 拦更彻底）+ `allow` 常用只读命令（每次权限弹窗打断都是弱模型的跑偏机会）。已固化为 `skills/mae-flow/assets/settings-baseline.json`，env-setup-agent 自动合并进项目 settings（追加缺失、不覆盖既有）；团队按需在该文件增删条目。
3. **会话卫生**：一单一会话为佳；改插件/agent/settings 后必须重启会话（定义在会话启动时缓存）；长会话行为漂移时 /clear（状态在磁盘，进度不丢）。重上下文步骤（build、verify 链入口）的 `current` 会主动提示 /clear 时机（`clear_hint` 标记）；重步骤 md 内置「中断恢复先读什么」清单（`current` 每次打印，恢复质量不赌模型自觉）；build 的批次 commit 后是安全 /clear 点，批次结论/调试根因假设要求写进 tasks.md 备注行（中间推理不留在会话里）。
4. **仓库预设**：`.mae-flow-defaults.json` 提交进仓（编译方式/UT生成方式/UT运行命令等恒定项），config_confirm 时 `current` 自动展示预填，新人第二单起免逐项来回；基线分支与需求文档不预设免问。另支持**机器直读键**「测试路径」（正则数组，gate 直接消费，启用 verify_ut 的测试路径收紧）——预填展示类键与机器直读键的区别要在改代码时留意。

**升级 comet 版本 checklist**：对照新版 `comet-state.sh` 核实 `design_doc`/`verify_result`/`auto_transition` 字段仍存在且语义不变 → 核实 guard `--apply` 仍是 phase 推进唯一入口 → 核实 comet init 产物目录结构 → 跑一单 tweak 冒烟 → 改 env-setup-agent 的版本号。

## 五、常见维护任务

- **改某步的行为** → 只改 `flow/steps/<step>.md`。指令是给模型的，写清楚"做什么、何时停、done 带什么参数"。
- **加一个步骤** → flow.json 加节点（接好上下游 next）+ 建同名 steps md + 若需新证据见 3.2。跑 `python -c "json.load(...)"` 和流程图连通性检查。
- **加环境检查** → flow.json `env_checks` 加项；若 agent 能修，env-setup-agent.md 加对应 Step（必须幂等）。
- **改 gate 规则** → mae-flow.py `cmd_gate`。记住 Edit/Bash 两路都要改，路径匹配带 `re.I`，改完必须跑冒烟用例（见第七节）。
- **动 dispatch.py** → 任何新增 IO 都要问：会阻塞吗？超时了吗？失败会留日志吗？
- **发版/打包前必跑 `python scripts/selftest.py`** → 语法/JSON/流程图/证据注册/占位符/agent 同步/关键文件 23 项自检，任何 ❌ 禁止发布。

## 六、Windows 军规（违反任何一条都是真实故障，不是理论）

1. 子进程 `text=True` 必须带 `encoding="utf-8", errors="replace"`（GBK 解码炸过 commit 证据和整个 gate）
2. 用户可见命令写 `python`，永远不写 `python3`（Store stub 陷阱）
3. 跨盘符场景禁 `os.path.relpath`（抛 ValueError）
4. 路径匹配一律 `re.I` / `.lower()`
5. `git rev-parse` 类命令加 `--verify`（失败时不回显参数本身）
6. 状态写盘走 tmp + `os.replace`（杀软锁文件）
7. hook 命令用 **shell form**（`python "${VAR}/dispatch.py" 事件`，Git Bash 展开变量、路径带引号）。公司 codeagent 实测**不支持 exec form 的 args 数组**——只执行 command 本体，hook payload 落进 python stdin 被当脚本解析，JSON 的 `false` 炸 NameError（2026-07-20 实战，症状：`<stdin> line 1 name 'false' is not defined`）
8. 时间戳一律显式 `%Y-%m-%d %H:%M:%S`，禁用 `%F`/`%T` 简写（依赖 UCRT 的 C99 支持，老运行时抛 ValueError；时间戳是证据比对/账本/令牌的命脉，不赌运行时）
9. 解析 git 输出中的文件路径时加 `-c core.quotepath=false`（否则非 ASCII 文件名被引号+八进制转义，pattern 匹配漏检）；且勿依赖 porcelain 输出的列偏移（`sh()` 会 strip 首行前导空格），按空白切分

## 七、排障手册

### hook 日志速读（`%TEMP%\mae-flow-hook.log`）

| 现象 | 结论 |
|---|---|
| 无此文件 | hook 没执行到 Python：查 PATH 的 python、exec form 支持、变量展开 |
| start/end 成对、几十 ms | hook 层健康 |
| start 无 end / WATCHDOG 行 | 有阻塞被看门狗击杀，看前后行定位是哪个事件 |
| `stdin read timeout` | harness 没关 stdin（已兜底，仅供了解） |
| `chdir 项目根` | hook cwd 非项目根，定位机制在工作（正常） |
| `EXC ...` | dispatch 内部异常（已 fail-open），按异常名修 |

### 故障树

- **模型说"流程未初始化"但明明有单** → `mae-flow doctor` 看第一行项目根对不对（父目录有杂散 `.mae-flow.json` 会劫持向上搜索）。
- **gate 好像全失效了** → flow.json/状态文件 JSON 坏了会让 mae-flow 崩溃（exit 1 → fail-open）。手动跑 `python mae-flow.py gate edit src/x` 看 traceback。
- **done 一直被拒但产物明明在** → 看报错里的 pattern 是否含未解析占位符（对应配置没 `--set`）；yaml_field 类型看 `.comet.yaml` 字段实际值。
- **证据实测行为**：所有证据都可手动复现——直接跑报错消息里提示的那条命令。

### 冒烟用例（改 gate/证据/hook 后必跑）

历次会话沉淀的用例集，最少覆盖：gate 的拦/放各路（状态文件+历史账本、插件目录、源码大小写、bash token、worktree、specs 双路）、证据正反例（yaml_field、pushed、非法工号）、dispatch 的 stdin 挂起（Popen 握管道不发 EOF，应 ~3s 自行退出）、子目录 init/current（应落项目根）、终态重 init（应备份重开 + 账本追加一行）、模板结构校验三路（STORY/CHAIN/GRILL-PREP）、`current` 的占位符替换与仓库预设展示、unlock 正反例（无 ack 拒/伪造 ack 拒/验真后放行 gate/推进自动失效/未配置仓 no-op）。

## 八、已知局限（均为权衡后的设计决定，改前先想清楚当初为什么）

**全流程硬度审计结论（2026-07-18，逐步过完 18 步）**：正确性级缝隙已清零。以下软点为**有意接受**，各有兜底，不要误判为疏漏：

- **verify_ponytail 零证据**——跳过无人知；兜底：复杂度维度有 build 期 ponytail 常驻 + codecheck + comet review 三重冗余。
- **codecheck REMAINING 裁决是软的**——兜底：线上流水线门禁是外部终审，敷衍的代价是 MR 被拦。
- **ack / STORY入库 / goto --ack / 需求文档确认等"用户原话"类**——不可验真（固有），价值在显式动作 + 留痕可审计。archive_confirm 已加 ASKUSER 令牌硬证据（「真实问过」可验；「用户答的是什么」仍不可验）。
- **各类"展示/告知"义务**（收尾摘要、报告展示）——纯 UX，失效不腐蚀正确性。
- verify_ut 的"测试真跑过"：UTRUN 令牌已记录（PostToolUse-Bash 检出 UT运行命令被调起，doctor 可见），**尚未设为 done 硬证据**——须公司机金丝雀确认「子 agent 的 Bash 调用会触发 PostToolUse」后再加（否则 verify_ut 永远过不去）；确认后在 flow.json verify_ut 的 evidence 加 `{"type":"agent_ran","agent":"UTRUN"}` 一行即启用。原候选方案"done 现场跑 UT运行命令"作罢（真实套件耗时超 done 容忍度）。

- **verify_ut / verify_codecheck 无文件证据**——内部 agent 无固定产物，约束靠 SubagentStop 契约 + 报告展示。
- **ack 验真已落地"三级放行"**（done 与 goto 同用）：①ack 与 harness 捕获的近期用户输入（`.mae-flow.json.usermsg`，UserPromptSubmit 的 prompt + AskUserQuestion 的应答）归一化匹配→过；②本步内有 ASKUSER 令牌→过（交互真实性已证）；③存储非空且两者皆无→拒。存储恒空（公司 harness 无 prompt/tool_response 字段）时自动降级为旧行为，永不误卡——字段有无以公司机金丝雀为准。剩余不可验：用户所答内容的语义（固有）。
- **一仓一单**——并行走 worktree；suspend/resume 未做（等真实需求）。
- **跨仓交付走"链路分解 + 各仓平等交付"两段式（v2，废除了主从概念）**——`/mae-flow chain` 由主模型做链路分解（事实自查：触点/接口/语言差异；决策问人：边界/契约/顺序——grill 哲学的跨仓同构，且必须主模型做因为子 agent 不能与用户对话），产出 CHAIN 文档；此后各仓地位平等、独立跑流程，以 CHAIN 文档为需求输入。**有意不做**跨仓联合状态机——chain 是直通模式无 done 硬校验（同 story 补生成的权衡）；痛点积累后 beads（依赖拓扑工单账本）是编排层候选。
- **review 轮次不碰规格（红线）**——行为/规格类意见在 rf_triage 分诊转 hotfix/full；rf_verify 的 UT 增量派发是软判断（纯文案类修复可不派，判断依据须向用户展示）。
- **Bash 写检测可绕过**——定位是软提醒层（见 3.3）。
- **SubagentStop 二次失败静默放行**——防死循环的代价。
