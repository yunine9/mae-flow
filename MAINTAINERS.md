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
8. **硬禁令必须配裁决出口**。gate 与契约拦的是"未经用户裁决的动作"，不是场景本身——工程现实里被禁动作往往有正当场景（UT 揭出源码真缺陷、既有用例被规格演进淘汰、实现揭出设计/spec 有误、AskUserQuestion 客观不可用）。每条禁令都要回答"该场景的正规出口是什么"：unlock source（UT 缺陷修复）、SUSPECTED_BUGS 呈报（agent 自查后升级）、goto --ack 回流（设计/spec 修订）、accept-risk（宿主/收尾异常导致单个 Agent 令牌无法签发）。禁令没有出口，弱模型只剩"卡死"或"作弊绕过"两个选项，都是事故（ImpossibleBench 实证：给正规弃权通道，作弊率 54%→9%）。新加任何禁令前先写出口，出口必须带用户裁决与留痕。

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

保留有价值的人工关卡：配置确认、工作流选择、grill 逐题、**规格呈审（open，ASKUSER 令牌硬校验：AI 推断/拿不准的条目逐条呈用户拍板，无脑回车机器上过不去——spec 是唯一合同，2026-07-21 治"无脑回车赖工作流"）**、产物确认（design/story）、**计划评审（plan-ready）**、build 终点 ack、REMAINING 裁决（修/正式豁免二选一）、归档确认（不可逆，ASKUSER 令牌硬校验）。
消灭无价值的碎片等待：build 四项选择（固化）、executing-plans 批次检查点（简报后直行）、TDD 说教（标准回应）、comet 分支/commit 建议（拒绝话术前置）。

## 二、目录结构

```
skills/mae-flow/SKILL.md   触发条件 + 5 条铁律(工具管不住、靠模型自守的部分)
flow/flow.json              流程定义:步骤图、证据、权限、环境检查项
flow/steps/<step>.md        每步的执行指令(改流程行为优先改这里,无需动代码)
scripts/mae-flow.py         状态机驱动器(init/current/done/skip/gate/status/doctor/report/envcheck/goto/accept-risk/template/exit)
scripts/comet_compat.py     让项目级阶段门禁识别 mae-flow 直接开发标记（setup/exit 幂等补齐）
hooks/hooks.json            6 个 hook 注册(shell form + timeout 15s)
hooks/dispatch.py           hook 分发器(防卡死 + 项目根定位 + 契约校验 + 日志)
agents/*.md                 5 个子 agent 契约(XXX_RESULT 标记 + 任务卡指纹 + 幂等要求)
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
**过程区 `.mae-flow-work/`**（gitignored，2026-07-21 治"MR 里 md 泛滥"+STORY 误提交实战）：过程性产物的家——
grill-prep 工作表、survey 代码勘察笔记、不入库 STORY——物理上不可能被卷进提交。
**提交白名单**（交付物才 commit）：openspec 全套、clarifications（拍板审计）、codecheck-exempt（门禁豁免依据）、
REVIEW（返工台账）、delivery-notes（团队沉淀）、STORY（仅用户选入库时）。
git add 一律精确路径，gate 硬拦 `-A/--all/.`（宽 add 是 STORY 误提交的凶手）。

**子 agent 任务卡**（`.mae-flow-work/agent-tasks/`）：compile/codecheck/UT 派发前必须执行
`mae-flow agent-task <kind>`。脚本把单号、本轮 diff、编译方式、UT 生成/运行方式和规格来源一次写齐并签
SHA-256；SubagentStop 要求报告回传同一指纹并复算文件内容。主模型漏传配置、旧卡复用、手改任务卡均拿不到令牌。
对配置声明为 AutoUT/java-autout/build-fix 的任务，SubagentStop 还从子会话 transcript 验真实 Skill 工具调用；
UT/直接编译命令与 `codecheck fullcheck` 同理验真实 Bash 调用，报告里写“执行过”不算证据。

**月光宝盒**是普通状态机上的显式运行策略，不是另一套流程。UserPromptSubmit 在新项目尚无状态文件时，
把十分钟内的明确授权写入一次性 `.mae-flow.json.moonlight-intent`；脚本验真并消费后才建状态，解决首次
启动的先后顺序问题。在途流程原地切换，已退出流程先恢复现场并清空旧质量证据。运行中 PreToolUse 硬拦
AskUserQuestion；编译、CodeCheck、UT、环境和最终验证仍先执行，失败只能用 `moonlight defer` 记录真实问题，
不能伪造通过。push 仍以本地 HEAD == 上游为硬证据，成功后停在 `moonlight_review`，规格定稿留给早晨。
报告位于 `.mae-flow-work/moonlight-report.md` 并受 gate 保护；`repair` 从对应质量链入口重跑，若有环境遗留则
先回 env_setup，结束后直接回质量链，不重跑需求和设计；`finalize` 才恢复普通归档流程。Stop Hook 在安全
停点前拒绝主 Agent 自行收工；真实硬阻塞须先执行 `moonlight blocked` 留痕，递归触发时 fail-open 防死循环。
完整启动原话持久化进 moonlight 状态；build defer 还会先验证 tasks_checked 与 commit_tagged_after_entry，
确保只放过编译遗留，不放过未完成实现。

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
| `tests_only` | 把本步源码写权限收窄到测试路径；优先用「测试路径」配置（config 逗号分隔正则 / defaults 数组），缺失时使用保守内置规则，不再 fail-open；用户裁决后 `unlock source` 临时放行 |
| `source_change_recheck` | tests_only 步骤经 unlock 改了被测源码后，done 不走原 next，自动回流到指定质量链入口（rf_ut→rf_compile，verify_ut→verify_recompile） |
| `source_change_next` | 可选精简步骤如果实际改了源码，done 自动改走专用编译节点；没有源码变化才走普通 next。源码必须先形成当前步骤的新提交，避免任务卡漏掉未提交文件 |
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
| `agent_ran` | 本步期间发生过 harness 签发的 `at/head/status` 令牌；证据可声明允许状态（编译只认 OK、UT 只认 PASS），FAIL/BLOCKED 是诚实报告但不再冒充通过。令牌绑定签发时 HEAD，签发后源码变化即过期。compile/codecheck/UT 还校验任务卡指纹和配置对账；AskUserQuestion 发 ASKUSER 令牌。用户可通过 `accept-risk` 只替代当前步骤的单个 Agent 令牌：ack 精确验真，绑定 step/task SHA/HEAD，代码变化或推进后失效；其他证据不受影响。**封杀主会话代工、伪确认、旧证据背新代码，同时避免宿主兼容问题形成无限重跑** |
| `content_free` | 文件内容不得命中禁止正则——把"标注协议"变成机器可查终态（story 在用：零"待确认"+ 禁裸"不涉及"，破解指标博弈的职责锁） |
| `clean_paths` | 指定路径 git 实测已提交且无未提交改动——硬化"产物必须 commit"义务（grill/open/design/archive 在用） |
| `glob_absent` | 负向存在证据:pattern 必须一个都匹配不到——"动作须留下'消失'的事实"（archive 在用:原 change 目录必须从 changes/ 消失，堵复制式假归档僵尸） |
| `codecheck_clean` | **done 现场重跑 `codecheck fullcheck -f <业务代码>` 亲数遗留**。告警数按控制台「共有 N」→报告汇总表「总计」→问题明细标题→JSON 结果→明确零告警文案多路解析，不依赖 CLI 退出码。解析失败不等于有告警：保存完整现场，让用户核对后走绑定式恢复。遗留除豁免文件外还必须有 `approve-exemption` 写入的用户审批账；手写文件不算授权（review 基点前已有的历史豁免继续承认） |
| `agent_or_no_source` | 本轮没有源码、测试或构建文件改动时自动过；只要有改动就强制指定 agent 的成功状态。适用于主流程、小改和评审返工，不再只认 C++/Java |
| `review_codecheck` | 三条流程统一先 `codecheck-scan` 冻结首检 HEAD/告警数；首检有告警才允许派 CODECHECK agent，首检 0 后源码变化会令扫描过期；最后再走 codecheck_clean 现场复核。输出格式无法解析时保存完整诊断，并允许用户核对后用 `codecheck-record` 登记数量；记录绑定步骤、HEAD、文件清单和诊断哈希，不是无条件放行 |

**新增证据类型**：在 mae-flow.py 写 `ev_xxx(spec, st) -> (bool, 失败原因)`，注册进 `EVIDENCE` 字典，flow.json 里引用。失败原因要写"怎么补救"，它会原样回传给模型。

### 3.3 gate（PreToolUse 拦截）

`gate edit <路径>` / `gate bash <命令>`，exit 2 = 拦。保护清单：

- `.comet.yaml` / `.openspec.yaml`（comet-state 专属）
- `.mae-flow.json` 及其衍生（`.tokens`/`.tmp`/`.last`）与历史账本 `.mae-flow-history.jsonl`（Edit 和 Bash 写双拦）
- `dispatch.py` 禁止手动执行（伪造 agent 令牌的通道）
- 插件目录自身（防模型改规则）
- `openspec/specs/` 真相源（仅 `allow_specs_write` 步放行，Edit/Bash 双路）
- 源码判定统一走 `_is_source_path`：常见源码扩展名和构建入口文件在任何目录都算源码，再叠加 `source_patterns` 通用目录与 defaults/config「源码路径」私有正则；Edit/Bash gate、令牌新鲜度、UT 回流共用这一口径。Bash 路按 **token** 判断，禁止退回整串 regex。
- git 约定：分支名（checkout -b/-B、switch -c/-C、branch -m）、commit 格式（含不带引号的 -m）、force push（含 +refspec）、`git worktree add`（与状态机不兼容）
- `.env` 类密钥文件禁写；危险命令 denylist（管道执行远程脚本、`git clean -x`、对 `/`~`*`.`盘根 的递归删除——普通目录的 rm -r 不拦）。注：PreToolUse 硬拦在权限跳过模式下依然生效（hook 跑在 shell 里，提示词注入绕不过）
- `comet init` 会话内全禁（含子 agent、含管道喂输入变体）：交互式 TUI 被非交互执行会把二三十个 agent 平台全部初始化污染仓库（2026-07-20 实战）；拦截消息给"目录/命令/平台"三要素话术交用户手动。教训：agent 的"想尽办法装成功"哲学会压过"无法自动化"的措辞——这类禁令必须放硬层
- `git add -A / --all / .` 全禁（宽提交会把无关文件与不入库产物卷进交付分支——STORY 误提交实战；提交必须精确到文件/明确产物目录）
- verify_ut/rf_ut 的测试路径收紧（`tests_only`）：仓库配置优先，缺失时放弃旧的 fail-open，改用内置保守测试路径规则；Edit/Bash 双路都拦非测试源码。**这不是死禁**——非标准目录补 `.mae-flow-defaults.json`，真源码缺陷走 unlock 裁决通道。
- **unlock source 裁决通道**：UT 揭出疑似源码缺陷、用户判"确为代码缺陷"后，`unlock source --reason <裁决> --ack "用户原话"`（ack 走与 done 相同的三级验真）解锁当前步骤，历史留痕 `unlock:source`。done 检测到被测源码变化后不消费旧 UT 证据，而是自动回流完整质量链：review 回 rf_compile；主流程进入 verify_recompile，再走 Ponytail/CodeCheck/UT，不重做实现计划。无 unlock 却改了被测源码则判越权，不允许通过补验证洗白。

**已知局限（设计决定）**：Bash 写检测的 `WRITEISH` 正则是打地鼠，永远可绕过（如 `python -c`）——它的定位是**软提醒层**，真正的门槛在 done 的证据校验。不要试图把 bash 正则做"完备"。

### 3.4 hooks（dispatch.py）

6 个事件：SessionStart / UserPromptSubmit（状态注入 + 用户输入捕获进 ack 验真存储）、PreToolUse（gate）、
PostToolUse（STORY/CHAIN/GRILL-PREP 模板校验 + ASKUSER/UTRUN 令牌 + AskUserQuestion 应答捕获）、
SubagentStop（契约校验 + 令牌绑 HEAD）、Stop（月光宝盒安全停点约束）。

**防卡死四件套**（历史上曾造成每条消息挂 10 分钟，动这里要极其小心）：
- 看门狗 12s 强制 `os._exit(0)`
- stdin 守护线程读，3s 超时按空输入（治 harness 不关 stdin）
- 调 mae-flow 的子进程 8s 超时
- 每次调用记 `%TEMP%\mae-flow-hook.log`：`start/end + rc + 耗时`；只有 start 没 end = 被看门狗击杀

SubagentStop 契约校验：最终回复必须有且只有一个 `XXX_RESULT: <状态>`（仍建议放第一行；模型偶尔在前面多写一句或代码围栏时兼容接受）；CODECHECK 额外硬验三件事——
`EXECUTED_COMMAND` 含 fullcheck、三数对账 `FOUND = FIXED + REMAINING_COUNT`（吞告警最常见形态是马虎遗漏，算术不平当场打回）、
CLEAN ⇔ 遗留为 0 / REMAINING ⇔ 遗留 ≥1（FAIL 属诚实上报不苛求对账）。真实编译调用会留下绑定任务卡、步骤和源码版本的临时凭证；仅因报告格式重答时，同一源码版本可复用，不重复跑长编译，源码一变立即失效。`stop_hook_active` 时仍以 0 退出防打回死循环，但拒签原因写入受保护 sidecar，`done/doctor` 会展示真实原因，不再误报成“首行没标记”。
UT 同样把真实 AutoUT/java-autout Skill 调用和 UT 命令分别记为临时凭证：报告重答可复用，源码或测试变化立即失效。
机器字段解析兼容 Markdown bullet/同行字段，真实工具调用高于 `GENERATOR_USED/EXECUTED_UT` 的文字摘要；但实际命令额外追加
filter/exclude/disable，或输出出现非零 disabled/skipped、segfault 时不得 PASS，必须走问题呈报与用户裁决。
所有 `agent_ran` 门禁都有统一人工出口 `accept-risk`，但它刻意不是“跳过步骤”：命令先确认当前步骤确实需要该 Agent，
再用 `_ack_verified(exact=True)` 核对用户当前步骤原话，拒绝脏源码，记录风险/step/task SHA/HEAD；`ev_agent_ran` 只把这一项视为通过。
CodeCheck 的现场扫描、clean_paths、提交、分支和归档等证据继续执行。新任务卡、源码变化、goto、推进和退出恢复都会废弃放行。
**非正常收尾自动尸检**（2026-07-20，治"agent 奇怪退出无人知晓死因"）：无标记收尾/重答仍失败时，把轮数、临终输出、检出的报错特征落 `%TEMP%/mae-flow-agent-autopsy.log`，并把一行「尸检线索」嵌进打回消息——主 agent 重启新实例必须转告（SKILL 铁律）；配套五个 agent 契约的"带着情报死"条款（工具连败 2 次→FAIL/BLOCKED 收尾写明详情；轮次过半未完成→提前收尾出部分成果，不许干到被硬切）。

### 3.5 环境检查（env_checks）

类型：`cmd`（退出码 0）、`cmd_contains`、`node_min`、`path_any`、`file_contains`。
**判 CLI 可用性别赌 `--help`/`--version` 的退出码**（2026-07-21 实战：`codecheck fullcheck --help` 打印帮助后 exit 1，被 `cmd` 类型误判"不可用"，白派诊断/白拦流程）。commander/Java 系 CLI 的 help 常以非零码退出——用 `cmd_contains` 看输出特征字样（如 `fullcheck`），退出码无关。同理 `ev_codecheck_clean` 不看退出码，而是解析提示行、Markdown 汇总/明细或 JSON；全都不认识时保存现场并走用户核对恢复口。
Windows 上 npm 全局 CLI 实体是 `codecheck.cmd`：执行层沿用公司实机验证过的 `shell=True` + PATHEXT 解析。
不要再手工拼 `cmd.exe /s /c`；2026-07-22 实战已证实其首尾引号规则会把原本可用的命令变成“找不到”。
**缓存**：机器级慢检查全绿后 touch `~/.mae-flow-env-ok`，24h 内跳过；`FAST_TYPES`（path_any / file_contains，项目级）永远实测；`envcheck` 命令永远全量并刷新缓存。新增检查时想清楚它是机器级还是项目级。
**安装三层策略**（2026-07-20 实战定型，comet init 全平台初始化事故后重构）：A 类确定性安装 → `setup.py`（零创造力、幂等、失败带诊断线索、终验复用 envcheck）；C 类诊断 → env-setup-agent（读日志修环境参数后**重跑 setup.py**，禁止绕过它手工装——"用另一条路装上"不可复现）；B 类交互 → 人工三要素话术（comet init 会话内 gate 硬拦）。环境常量全在 env-profile.json，换代理/镜像/插件命令只改一处。教训：把智能用在确定性工作上，幺蛾子是创造力的副产品。

### 3.6 子 agent 契约

三条不可违背：**唯一结果标记**（推荐第一行，SubagentStop 兼容小格式偏差但不接受多个冲突结果）、**无状态幂等**（先检查后动作，禁止"我下次再"话术——没有下次，是下一个实例接手）、**不能与用户对话**（决策进 PENDING_DECISIONS）。
**派发三原则**（2026-07-20 轮次经济学实战定型，生产模型 Glm-5.1 且 thinking 关闭，每轮只干一小步）：
①**喂到嘴边**——原料原文进任务提示（spec 条目/文件清单/告警明细），不给路径让它自己花轮次读；
②**分批小实例**——复杂工作切批逐实例（UT 每批 3-5 方法带收口批、codecheck >30 告警按文件分批、编译按模块），单实例马拉松 60-80 轮后被上下文裁剪拖垮，加轮次预算救不了；
③**长间隔轮询**——等待类动作单次调用内 sleep 再看结果，严禁秒级高频轮询烧预算。
maxTurns 现值：ut=200 / compile=100 / codecheck=100 / story=60 / env=40（FIELD-TEST 0.7 持续校准）。
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

**阶段互锁哨兵（2026-07-21，治"comet 与 mae-flow 双状态机冲突像随机 bug"）**：mae-flow 主导、每步核对 comet 跟队。`current`/`doctor` 内置「步骤↔comet phase 合法区间」映射（`COMET_PHASE_EXPECT`），phase 掉队（多为闪退打断 guard --apply）或活跃 change >1（僵尸）时**强预警不硬拒**（硬闸在转换点的 phase 证据/glob_absent 上，哨兵只做诊断避免制造新死锁）。三个真因固化：①僵尸放大器（comet 多活跃按字典序抽一个管全场，`_active_change_count` 检测）②双状态机无互锁（design/build 收尾自查 phase 已推进）③Bash/Write 不对称（comet hook 只拦 Write，SKILL 铁律"被 GUARD 拦禁止换工具硬绕，先 doctor"，change 目录内写用 git mv）。

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
- **codecheck REMAINING 的用户决策语义仍不可完全验真**——但 `approve-exemption` 已要求本步 ASKUSER 令牌、用户原话验真并写状态审批账；手写豁免文件不能放行。
- **ack / STORY入库 / goto --ack / 需求文档确认等"用户原话"类**——现在会与当前步骤开始后的 UserPromptSubmit / AskUserQuestion 应答原文匹配，旧步骤的“可以”不能复用。宿主拿不到选项应答正文时，让用户再发一条普通消息即可恢复；不再静默降级成模型可自填。
- **各类"展示/告知"义务**（收尾摘要、报告展示）——纯 UX，失效不腐蚀正确性。
- verify_ut 的"测试真跑过"：UTRUN 令牌已记录（PostToolUse-Bash 检出 UT运行命令被调起，doctor 可见），**尚未设为 done 硬证据**——须公司机金丝雀确认「子 agent 的 Bash 调用会触发 PostToolUse」后再加（否则 verify_ut 永远过不去）；确认后在 flow.json verify_ut 的 evidence 加 `{"type":"agent_ran","agent":"UTRUN"}` 一行即启用。原候选方案"done 现场跑 UT运行命令"作罢（真实套件耗时超 done 容忍度）。

- **verify_ut / verify_codecheck 无交付文件证据**——过程证据为受指纹保护的任务卡 + SubagentStop 状态令牌；最终报告仍需展示。
- **ack 验真按步骤绑定**（done / goto / unlock / 豁免 / CodeCheck 人工恢复共用）：只接受当前步骤进入后捕获到的用户原话；令牌与用户消息都记录 step，不能跨关复用。若公司 harness 没回传 AskUserQuestion 的选项正文，要求用户用普通消息重复确认一次。这里选择“显式多确认一次”而不是 fail-open，因为这些命令会改变流程或放宽约束。
- **一仓一单**——并行走 worktree；暂停/恢复仍未做。用户不再需要流程时走 `exit`：精确确认、现场快照、
  项目标记和 Comet Hook 兼容四件事原子化完成，代码不回滚。禁止重新引入“手删状态文件”的假逃生口。
- **跨仓交付走"链路分解 + 各仓平等交付"两段式（v2，废除了主从概念）**——`/mae-flow chain` 由主模型做链路分解（事实自查：触点/接口/语言差异；决策问人：边界/契约/顺序——grill 哲学的跨仓同构，且必须主模型做因为子 agent 不能与用户对话），产出 CHAIN 文档；此后各仓地位平等、独立跑流程，以 CHAIN 文档为需求输入。**有意不做**跨仓联合状态机——chain 是直通模式无 done 硬校验（同 story 补生成的权衡）；痛点积累后 beads（依赖拓扑工单账本）是编排层候选。
- **review 轮次不碰规格（红线）**——行为/规格类意见在 rf_triage 分诊转 hotfix/full。进入 rf_triage 前自动冻结 `review_base_head`；质量链拆为 rf_compile → rf_codecheck → rf_ut，只按本轮 diff。无业务代码机器自动跳过；有业务代码必须 COMPILE/OK 与 UT/PASS。旧 2.0.2 的 rf_verify 作为一次性迁移桥；旧版已停在 verify_ut/rf_ut 且没有 `step_heads` 时，按进入步骤的 history 时间恢复之前最后一个 commit，只允许保守多验，禁止以当前 HEAD 补位。
- **Bash 写检测可绕过**——定位是软提醒层（见 3.3）。
- **SubagentStop 二次失败对宿主返回 0**——这是防打回死循环的必要权衡；真实拒签原因已持久化并由 `done/doctor` 展示，返回 0 不再等于静默丢失诊断。
